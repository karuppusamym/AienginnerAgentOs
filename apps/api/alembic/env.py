"""Alembic environment for the DataPilot API.

Uses app.database (DATABASE_URL) and ``Base.metadata`` with every model
registered. Online runs hold a PostgreSQL advisory lock for the whole upgrade
and adopt databases migrated by the pre-Alembic runner (``schema_versions``
0001-0003) by stamping the equivalent revision instead of re-running it.
See app/migrations.py.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from alembic.script import ScriptDirectory

from app import models  # noqa: F401  (registers every table on Base.metadata)
from app.database import DATABASE_URL, Base, engine as app_engine
from app.migrations import advisory_lock, legacy_revision

config = context.config
if config.config_file_name and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Keep ``--autogenerate`` additive: never propose dropping what the models don't declare.

    Staged/demo data tables share this database (SQLite dev), as do the legacy
    ``schema_versions`` table and the hand-written indexes from 0002.
    """
    if reflected and compare_to is None and type_ in {"table", "index", "unique_constraint"}:
        return False
    return True


def run_migrations_offline() -> None:
    """Emit SQL to stdout (``alembic upgrade head --sql``) without a database connection."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=DATABASE_URL.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = config.attributes.get("engine") or app_engine
    with engine.connect() as connection:
        with advisory_lock(connection):
            adopted = legacy_revision(connection)
            if connection.in_transaction():
                connection.commit()  # end the inspection's implicit transaction
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                # SQLite cannot ALTER most constraints; batch mode recreates the table.
                render_as_batch=connection.dialect.name == "sqlite",
                compare_type=True,
                include_object=include_object,
            )
            with context.begin_transaction():
                # Read under the lock: what this run actually starts from (app.migrations
                # reports the revisions applied relative to it).
                config.attributes["heads_before"] = tuple(context.get_context().get_current_heads())
                if adopted:
                    context.get_context().stamp(ScriptDirectory.from_config(config), adopted)
                    config.attributes["adopted_legacy_revision"] = adopted
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
