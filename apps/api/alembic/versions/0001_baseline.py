"""Baseline: build the schema from the models, then apply the legacy column upgrades.

Replaces the pre-Alembic runner's 0001 ("legacy project/feature columns") and
the ``Base.metadata.create_all`` that startup used to run first. On an empty
database this creates every table defined in app/models.py; on an older
database it only adds what is missing (both steps are idempotent).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-23
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app import models  # noqa: F401  (registers every table)
    from app.database import Base
    from app.schema_migrations import ensure_project_columns

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    ensure_project_columns(bind)


def downgrade() -> None:
    raise NotImplementedError("The baseline revision cannot be downgraded; restore the database from a backup.")
