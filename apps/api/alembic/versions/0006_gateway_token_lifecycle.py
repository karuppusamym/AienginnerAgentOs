"""External gateway hardening: token lifecycle and per-grant daily quotas.

- external_clients.expires_at / last_used_at (nullable, timezone-aware): tokens
  can expire and admins can see when a credential was last used.
- query_tool_grants.daily_quota (nullable int): cap invocations of one tool by
  one client per UTC day.
- An index on external_invocations (external_client_id, query_tool_id,
  created_at) so the daily-quota count stays an index range scan.

Fresh databases already have the columns from the baseline (it builds the
current models), so every step is guarded, on PostgreSQL and SQLite alike.

Revision ID: 0006_gateway_token_lifecycle
Revises: 0005_learning_indexes
Create Date: 2026-09-24
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_gateway_token_lifecycle"
down_revision: str | Sequence[str] | None = "0005_learning_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS: tuple[tuple[str, str, sa.types.TypeEngine], ...] = (
    ("external_clients", "expires_at", sa.DateTime(timezone=True)),
    ("external_clients", "last_used_at", sa.DateTime(timezone=True)),
    ("query_tool_grants", "daily_quota", sa.Integer()),
)
INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_external_invocations_client_tool_created", "external_invocations", "external_client_id, query_tool_id, created_at"),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table, column, column_type in COLUMNS:
        if table not in tables:
            continue
        if column not in {item["name"] for item in inspector.get_columns(table)}:
            op.add_column(table, sa.Column(column, column_type, nullable=True))
    for name, table, columns in INDEXES:
        if table in tables:
            op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})")


def downgrade() -> None:
    for name, _table, _columns in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table, column, _column_type in reversed(COLUMNS):
        if table in tables and column in {item["name"] for item in inspector.get_columns(table)}:
            with op.batch_alter_table(table) as batch:  # batch mode: SQLite cannot DROP COLUMN in older versions
                batch.drop_column(column)
