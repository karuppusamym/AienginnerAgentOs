"""Indexes for the learning loop's hot queries.

- route_decisions: recent decisions per project (router evaluation, /router/decisions)
  and lookup by message when feedback arrives.
- verified_queries: active examples per project/dialect (few-shot retrieval).
- prompt_optimization_runs: "is a run already active for this project".
- On PostgreSQL, a trigram index on verified_queries.question when pg_trgm is
  available, so similarity retrieval can move into SQL as the table grows
  (skipped silently where the extension cannot be created).

Revision ID: 0005_learning_indexes
Revises: 0004_routing_verified_queries
Create Date: 2026-09-24
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_learning_indexes"
down_revision: str | Sequence[str] | None = "0004_routing_verified_queries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_route_decisions_project_created", "route_decisions", "project_id, created_at"),
    ("ix_verified_queries_project_status_dialect", "verified_queries", "project_id, status, dialect"),
    ("ix_prompt_optimization_runs_project_status", "prompt_optimization_runs", "project_id, status"),
)


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name, table, columns in INDEXES:
        if table in tables:
            op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})")
    if bind.dialect.name == "postgresql" and "verified_queries" in tables:
        # Savepoint so a missing privilege for CREATE EXTENSION does not abort the migration.
        with bind.begin_nested() as savepoint:
            try:
                op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                op.execute("CREATE INDEX IF NOT EXISTS ix_verified_queries_question_trgm ON verified_queries USING gin (question gin_trgm_ops)")
            except Exception:
                savepoint.rollback()


def downgrade() -> None:
    for name, _table, _columns in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
    op.execute("DROP INDEX IF EXISTS ix_verified_queries_question_trgm")
