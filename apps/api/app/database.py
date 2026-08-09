from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


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
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
