"""Hot-path indexes (pre-Alembic runner's 0002).

Revision ID: 0002_hot_path_indexes
Revises: 0001_baseline
Create Date: 2026-09-23
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_hot_path_indexes"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (index name, table, column expression). CREATE INDEX IF NOT EXISTS works on
# PostgreSQL and SQLite, so re-running (or running after the old runner) is a no-op.
INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_conversation_messages_conv_created", "conversation_messages", "conversation_id, created_at"),
    ("ix_audit_events_created_at", "audit_events", "created_at"),
    ("ix_audit_events_actor_id", "audit_events", "actor_id"),
    ("ix_users_email_lower", "users", "lower(email)"),
    ("ix_user_feedback_context_id", "user_feedback", "context_id"),
    ("ix_query_runs_project_created", "query_runs", "project_id, created_at"),
    ("ix_model_call_logs_project_created", "model_call_logs", "project_id, created_at"),
)


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name, table, columns in INDEXES:
        if table in tables:
            op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})")


def downgrade() -> None:
    for name, _table, _columns in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
