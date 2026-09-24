"""Project roles follow global roles (pre-Alembic runner's 0003).

Project roles became authoritative (no union with global roles). Preserve what
engineers could already do by promoting their plain "member" memberships to
"maintainer", and demote global viewers that were auto-enrolled as "member"
(which wrongly granted conversation:write).

This is a one-time data fix, not idempotent in effect: databases that already
ran the old runner's 0003 are stamped past this revision (app/migrations.py
LEGACY_REVISIONS), so memberships created since then are not rewritten.

Revision ID: 0003_membership_roles
Revises: 0002_hot_path_indexes
Create Date: 2026-09-23
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_membership_roles"
down_revision: str | Sequence[str] | None = "0002_hot_path_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if not {"project_memberships", "users"} <= tables:
        return
    op.execute(
        "UPDATE project_memberships SET role = 'maintainer' WHERE role = 'member' "
        "AND user_id IN (SELECT id FROM users WHERE role = 'engineer')"
    )
    op.execute(
        "UPDATE project_memberships SET role = 'viewer' WHERE role = 'member' "
        "AND user_id IN (SELECT id FROM users WHERE role = 'viewer')"
    )


def downgrade() -> None:
    pass  # data fix; the previous roles are not recoverable
