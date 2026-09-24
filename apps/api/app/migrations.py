"""Schema migrations, run by Alembic (apps/api/alembic.ini, apps/api/alembic/).

``run_migrations(engine)`` is ``alembic upgrade head`` done programmatically:
it holds a PostgreSQL advisory lock for the whole run (concurrently starting
replicas wait instead of racing), adopts databases migrated by the previous
home-grown runner (its ``schema_versions`` table) by stamping the matching
Alembic revision, then applies whatever is pending and returns the revision
ids it applied.

Startup runs it unless ``RUN_MIGRATIONS_ON_STARTUP=false``; production runs
``python -m app.migrate`` as a one-off job (infra/kubernetes/migrate-job.yaml)
and disables the startup hook. The CLI also works from apps/api:
``alembic upgrade head`` / ``alembic current`` / ``alembic history``.

The baseline revision builds the schema from ``Base.metadata``, so every later
revision must be idempotent (guard with ``has_table`` / ``has_column`` /
``has_index`` below): on a fresh database the baseline already created the
current shape of every table.
"""
from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Connection, Engine, inspect, text

_ADVISORY_LOCK_KEY = 7_214_430_551  # arbitrary, stable per application (same key the old runner used)
# Alembic's ``context``/``op`` are process-global proxies, so two upgrades cannot run
# concurrently in one process; this serializes in-process callers (the advisory lock
# serializes separate processes/replicas).
_PROCESS_LOCK = threading.Lock()
API_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = API_DIR / "alembic.ini"

# The previous runner recorded "0001".."0003" in schema_versions; each maps to the
# Alembic revision that performs the same step. A database whose schema_versions
# holds 0001..N (and has no alembic_version yet) is stamped at LEGACY_REVISIONS[N].
LEGACY_REVISIONS: dict[str, str] = {
    "0001": "0001_baseline",
    "0002": "0002_hot_path_indexes",
    "0003": "0003_membership_roles",
}


# --- Helpers for idempotent revisions -------------------------------------------------


def has_table(bind: Connection, table: str) -> bool:
    return table in inspect(bind).get_table_names()


def has_column(bind: Connection, table: str, column: str) -> bool:
    return has_table(bind, table) and column in {item["name"] for item in inspect(bind).get_columns(table)}


def has_index(bind: Connection, table: str, index: str) -> bool:
    return has_table(bind, table) and index in {item["name"] for item in inspect(bind).get_indexes(table)}


# --- Locking and legacy adoption -------------------------------------------------------


@contextmanager
def advisory_lock(connection: Connection) -> Iterator[None]:
    """Session-level pg_advisory_lock around a migration run (no-op on other dialects).

    The lock statement's implicit transaction is committed straight away so the
    migration itself starts with a clean connection; session-level advisory locks
    survive commits and are released explicitly (or when the connection closes).
    """
    if connection.dialect.name != "postgresql":
        yield
        return
    connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
    connection.commit()
    try:
        yield
    finally:
        if connection.in_transaction():
            connection.rollback()
        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _ADVISORY_LOCK_KEY})
        connection.commit()


def legacy_revision(connection: Connection) -> str | None:
    """Alembic revision equivalent to what the old runner applied, if it ever ran here."""
    tables = set(inspect(connection).get_table_names())
    if "schema_versions" not in tables or "alembic_version" in tables:
        return None
    done = {row[0] for row in connection.execute(text("SELECT version FROM schema_versions"))}
    revision = None
    for version, mapped in LEGACY_REVISIONS.items():  # ordered; stop at the first gap
        if version not in done:
            break
        revision = mapped
    return revision


# --- Public API ---------------------------------------------------------------------------


def alembic_config(engine: Engine | None = None):
    from alembic.config import Config

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    config.attributes["configure_logger"] = False  # keep the application's logging config
    if engine is not None:
        config.attributes["engine"] = engine
    return config


def current_revisions(engine: Engine) -> tuple[str, ...]:
    from alembic.runtime.migration import MigrationContext

    with engine.connect() as connection:
        return tuple(MigrationContext.configure(connection).get_current_heads())


def head_revisions() -> tuple[str, ...]:
    from alembic.script import ScriptDirectory

    return tuple(ScriptDirectory.from_config(alembic_config()).get_heads())


def run_migrations(engine: Engine) -> list[str]:
    """``alembic upgrade head``; returns the revision ids applied now (oldest first).

    Locking and legacy adoption happen in alembic/env.py so the plain
    ``alembic upgrade head`` CLI behaves the same way.
    """
    from alembic import command
    from alembic.script import ScriptDirectory

    config = alembic_config(engine)
    with _PROCESS_LOCK:
        command.upgrade(config, "head")
        after = current_revisions(engine)
    # env.py records the heads it found *after* taking the advisory lock, so a replica
    # that waited for another one's upgrade correctly reports nothing applied.
    before = tuple(config.attributes.get("heads_before", after))
    if set(before) == set(after):
        return []
    # A legacy database is stamped (not run) up to its old version; don't report those.
    lower = config.attributes.get("adopted_legacy_revision") or (before[0] if before else "base")
    script = ScriptDirectory.from_config(config)
    applied = [revision.revision for revision in script.iterate_revisions(after, lower)]
    return [revision for revision in reversed(applied) if revision != lower]


def migrations_on_startup() -> bool:
    return os.getenv("RUN_MIGRATIONS_ON_STARTUP", "true").strip().lower() not in {"0", "false", "no", "off"}
