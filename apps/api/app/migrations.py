"""Versioned, idempotent schema migrations.

Replaces "run every ALTER on every boot on every replica". Each migration runs
once, is recorded in ``schema_versions``, and on PostgreSQL the whole run holds
an advisory lock so concurrently starting replicas cannot race.

Startup runs pending migrations unless ``RUN_MIGRATIONS_ON_STARTUP=false``;
production deployments should run ``python -m app.migrate`` as a one-off job
(see infra/kubernetes/migrate-job.yaml) and disable the startup hook.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import Engine, inspect, text

from .schema_migrations import ensure_project_columns

_ADVISORY_LOCK_KEY = 7_214_430_551  # arbitrary, stable per application


def _legacy_columns(engine: Engine) -> None:
    ensure_project_columns(engine)


def _hot_path_indexes(engine: Engine) -> None:
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_conversation_messages_conv_created ON conversation_messages (conversation_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_audit_events_created_at ON audit_events (created_at)",
        "CREATE INDEX IF NOT EXISTS ix_audit_events_actor_id ON audit_events (actor_id)",
        "CREATE INDEX IF NOT EXISTS ix_users_email_lower ON users (lower(email))",
        "CREATE INDEX IF NOT EXISTS ix_user_feedback_context_id ON user_feedback (context_id)",
        "CREATE INDEX IF NOT EXISTS ix_query_runs_project_created ON query_runs (project_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_model_call_logs_project_created ON model_call_logs (project_id, created_at)",
    ]
    tables = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        for statement in statements:
            table = statement.split(" ON ", 1)[1].split(" ", 1)[0]
            if table in tables:
                connection.execute(text(statement))


def _membership_roles_follow_global_roles(engine: Engine) -> None:
    """Project roles became authoritative (no union with global roles).

    Preserve what engineers could already do by promoting their plain
    "member" memberships to "maintainer", and demote global viewers that were
    auto-enrolled as "member" (which wrongly granted conversation:write).
    """
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE project_memberships SET role = 'maintainer' WHERE role = 'member' "
            "AND user_id IN (SELECT id FROM users WHERE role = 'engineer')"
        ))
        connection.execute(text(
            "UPDATE project_memberships SET role = 'viewer' WHERE role = 'member' "
            "AND user_id IN (SELECT id FROM users WHERE role = 'viewer')"
        ))


MIGRATIONS: list[tuple[str, str, Callable[[Engine], None]]] = [
    ("0001", "legacy project/feature columns", _legacy_columns),
    ("0002", "hot-path indexes", _hot_path_indexes),
    ("0003", "membership roles follow global roles", _membership_roles_follow_global_roles),
]


def applied_versions(engine: Engine) -> set[str]:
    if "schema_versions" not in inspect(engine).get_table_names():
        return set()
    with engine.connect() as connection:
        return {row[0] for row in connection.execute(text("SELECT version FROM schema_versions"))}


def run_migrations(engine: Engine) -> list[str]:
    """Apply pending migrations in order; returns the versions applied now."""
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_versions (version VARCHAR(32) PRIMARY KEY, description VARCHAR(200) NOT NULL, applied_at VARCHAR(40) NOT NULL)"
        ))
    lock = engine.connect() if engine.dialect.name == "postgresql" else None
    try:
        if lock is not None:
            lock.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
        done = applied_versions(engine)
        applied: list[str] = []
        for version, description, migrate in MIGRATIONS:
            if version in done:
                continue
            migrate(engine)
            with engine.begin() as connection:
                connection.execute(
                    text("INSERT INTO schema_versions (version, description, applied_at) VALUES (:v, :d, :t)"),
                    {"v": version, "d": description, "t": datetime.now(timezone.utc).isoformat()},
                )
            applied.append(version)
        return applied
    finally:
        if lock is not None:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _ADVISORY_LOCK_KEY})
            lock.close()


def migrations_on_startup() -> bool:
    return os.getenv("RUN_MIGRATIONS_ON_STARTUP", "true").strip().lower() not in {"0", "false", "no", "off"}
