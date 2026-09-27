"""External invocation history: channel, row count and list indexes.

- external_invocations.channel (VARCHAR(16), default 'rest'): whether the call
  came over REST (/external/v1/.../invoke) or MCP (tools/call). Existing rows
  predate MCP tracking and are recorded as 'rest'.
- external_invocations.row_count (nullable int): denormalised from
  result_metadata.row_count so history summaries can SUM it in SQL; backfilled
  for existing rows.
- Indexes for the paged history (project, newest first) and the paged list
  endpoints that sort by created_at within a project.

Fresh databases already have the columns from the baseline (it builds the
current models), so every step is guarded, on PostgreSQL and SQLite alike.

Revision ID: 0007_invocation_history
Revises: 0006_gateway_token_lifecycle
Create Date: 2026-09-24
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_invocation_history"
down_revision: str | Sequence[str] | None = "0006_gateway_token_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_external_invocations_project_created", "external_invocations", "project_id, created_at"),
    ("ix_jobs_project_created", "jobs", "project_id, created_at"),
    ("ix_approvals_project_created", "approvals", "project_id, created_at"),
    ("ix_audit_events_project_created", "audit_events", "project_id, created_at"),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "external_invocations" in tables:
        columns = {item["name"] for item in inspector.get_columns("external_invocations")}
        if "channel" not in columns:
            op.add_column("external_invocations", sa.Column("channel", sa.String(16), nullable=False, server_default="rest"))
        if "row_count" not in columns:
            op.add_column("external_invocations", sa.Column("row_count", sa.Integer(), nullable=True))
        invocations = sa.table(
            "external_invocations",
            sa.column("id", sa.String),
            sa.column("result_metadata", sa.JSON),
            sa.column("row_count", sa.Integer),
        )
        pending = bind.execute(sa.select(invocations.c.id, invocations.c.result_metadata).where(invocations.c.row_count.is_(None))).all()
        for invocation_id, metadata in pending:
            count = (metadata or {}).get("row_count") if isinstance(metadata, dict) else None
            if isinstance(count, int):
                bind.execute(invocations.update().where(invocations.c.id == invocation_id).values(row_count=count))
    for name, table, columns in INDEXES:
        if table in tables:
            op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})")


def downgrade() -> None:
    for name, _table, _columns in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "external_invocations" not in set(inspector.get_table_names()):
        return
    columns = {item["name"] for item in inspector.get_columns("external_invocations")}
    for column in ("row_count", "channel"):
        if column in columns:
            with op.batch_alter_table("external_invocations") as batch:  # batch mode: SQLite cannot DROP COLUMN in older versions
                batch.drop_column(column)
