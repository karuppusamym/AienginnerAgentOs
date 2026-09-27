"""Create model routing, verified-query and prompt-optimisation tables if missing.

model_routes, route_decisions, verified_queries and prompt_optimization_runs
were added to app/models.py after the pre-Alembic runner's last migration
(0003). Databases created before they existed (and not since touched by the
startup create_all) get them here; fresh databases already have them from the
baseline, so every step is guarded.

Revision ID: 0004_routing_verified_queries
Revises: 0003_membership_roles
Create Date: 2026-09-23
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_routing_verified_queries"
down_revision: str | Sequence[str] | None = "0003_membership_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("model_routes", "route_decisions", "verified_queries", "prompt_optimization_runs")


def upgrade() -> None:
    from app import models  # noqa: F401  (registers every table)
    from app.database import Base

    bind = op.get_bind()
    for name in TABLES:
        table = Base.metadata.tables.get(name)
        if table is None:  # model removed later; nothing to create
            continue
        table.create(bind=bind, checkfirst=True)  # also creates the table's indexes
        existing = {item["name"] for item in sa.inspect(bind).get_indexes(name)}
        for index in table.indexes:  # table predated an index (e.g. ix_verified_queries_project_norm)
            if index.name not in existing:
                index.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for name in reversed(TABLES):
        if name in existing:
            op.drop_table(name)
