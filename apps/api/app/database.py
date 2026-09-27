from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .request_context import is_production


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./datapilot.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
is_sqlite = DATABASE_URL.startswith("sqlite")

# Explicit pool sizing, not SQLAlchemy's defaults (pool_size=5,
# max_overflow=10 -> up to 15 connections per process). That matters here
# because this API scales horizontally via Kubernetes replicas, not via
# multiple uvicorn/gunicorn workers per pod (see infra/kubernetes/api.yaml,
# HPA minReplicas=2/maxReplicas=8) — every replica opens its own pool
# against the same Postgres instance, and the Temporal worker
# (infra/kubernetes/worker.yaml, minReplicas=2/maxReplicas=10) does too.
# At default settings, worst case is (8 api + 10 worker) x 15 = 270
# connections against a Postgres default max_connections of 100 -- that
# would exhaust the database under a genuine autoscaling event. The
# defaults below (5 + 3 = 8/process) keep worst case at 18 x 8 = 144, still
# above the Postgres default, so tune DB_POOL_SIZE/DB_POOL_MAX_OVERFLOW (or
# raise Postgres max_connections, or front it with PgBouncer) to match your
# actual max replica counts before scaling this to production traffic —
# this is a real, unresolved capacity-planning item, not a solved problem.
pool_kwargs: dict[str, object] = {}
if not is_sqlite:
    pool_kwargs = {
        "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("DB_POOL_MAX_OVERFLOW", "3")),
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800")),
    }

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True, **pool_kwargs)

if is_sqlite:
    # Local-dev only: generated SQL targets PostgreSQL, so give SQLite the two
    # functions it most often calls. Syntax differences are rewritten in
    # staging.sqlite_compatible_sql before execution.
    from .sqlite_compat import register_postgres_functions

    event.listen(engine, "connect", lambda connection, _record: register_postgres_functions(connection))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# User- and model-written SQL must not run with the application's own login:
# that login can read users.password_hash, provider settings and audit data.
# STAGING_DATABASE_URL points at the same database through a role that can only
# SELECT from data schemas (staging, core, quarantine, published views).
STAGING_DATABASE_URL = os.getenv("STAGING_DATABASE_URL", "").strip()
read_only_engine = (
    create_engine(STAGING_DATABASE_URL, pool_pre_ping=True, pool_size=int(os.getenv("STAGING_POOL_SIZE", "3")), max_overflow=2)
    if STAGING_DATABASE_URL
    else None
)
_NON_DATA_SCHEMAS = {"public", "information_schema", "pg_catalog", "pg_toast"}


def grant_read_only_access(app_engine) -> None:
    """Create (when allowed) the reader role and grant SELECT on every data schema."""
    role = os.getenv("STAGING_READER_ROLE", "").strip()
    if app_engine.dialect.name != "postgresql" or not role or not role.replace("_", "").isalnum():
        return
    password = os.getenv("STAGING_READER_PASSWORD", "")
    with app_engine.begin() as connection:
        if password:
            exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar()
            if not exists:
                # Works where the app login may create roles (Compose); managed
                # databases pre-create the role and this step is skipped.
                # Utility statements cannot take bind parameters; escape the literal.
                literal = password.replace("'", "''")
                connection.exec_driver_sql(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{literal}'")
        connection.execute(text(f'ALTER ROLE "{role}" SET default_transaction_read_only = on'))
        connection.execute(text(f'GRANT CONNECT ON DATABASE "{app_engine.url.database}" TO "{role}"'))
        schemas = [
            row[0]
            for row in connection.execute(text("SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%'"))
            if row[0] not in _NON_DATA_SCHEMAS
        ]
        for schema in schemas:
            connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
            connection.execute(text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'))
            connection.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT SELECT ON TABLES TO "{role}"'))


def configure_read_only_access(app_engine) -> None:
    if app_engine.dialect.name != "postgresql":
        return  # SQLite dev path: guarded by staging.assert_no_application_relations only
    if read_only_engine is None:
        if is_production() and os.getenv("ALLOW_SHARED_QUERY_ENGINE", "false").lower() not in {"1", "true", "yes"}:
            raise RuntimeError(
                "STAGING_DATABASE_URL (a SELECT-only login for data schemas) is required when APP_ENV=production; "
                "set ALLOW_SHARED_QUERY_ENGINE=true only as a temporary, documented exception"
            )
        return
    try:
        grant_read_only_access(app_engine)
    except Exception as exc:  # pragma: no cover - depends on database privileges
        print(f"[datapilot] read-only role grants skipped: {exc}")


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
