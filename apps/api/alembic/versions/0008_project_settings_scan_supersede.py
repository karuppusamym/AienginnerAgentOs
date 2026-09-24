"""Per-project settings and superseded metadata-scan failures.

- projects.settings (nullable JSON): per-project switches such as the
  auto-approval policy ({"auto_approval": {"enabled": true}}). Absent means
  defaults (auto-approval off).
- One-time data fix: a FAILED metadata scan followed by a SUCCEEDED scan of
  the same connector is marked SUPERSEDED so it leaves "Needs action". Old
  scan jobs carry the connector only in their title, which is what matches
  here; new scans are superseded at runtime (metadata_scan_runtime).

Fresh databases already have the column from the baseline, so the step is guarded.

Revision ID: 0008_project_settings_scan_supersede
Revises: 0007_invocation_history
Create Date: 2026-09-24
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_project_settings_scan_supersede"
down_revision: str | Sequence[str] | None = "0007_invocation_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "projects" in tables and "settings" not in {item["name"] for item in inspector.get_columns("projects")}:
        op.add_column("projects", sa.Column("settings", sa.JSON(), nullable=True))
    if "jobs" in tables:
        op.execute(
            "UPDATE jobs SET status = 'SUPERSEDED' WHERE job_type = 'metadata_scan' AND status = 'FAILED' "
            "AND EXISTS (SELECT 1 FROM jobs later WHERE later.job_type = 'metadata_scan' AND later.status = 'SUCCEEDED' "
            "AND later.title = jobs.title AND later.project_id = jobs.project_id AND later.created_at > jobs.created_at)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "jobs" in set(inspector.get_table_names()):
        op.execute("UPDATE jobs SET status = 'FAILED' WHERE job_type = 'metadata_scan' AND status = 'SUPERSEDED'")
    if "projects" in set(inspector.get_table_names()) and "settings" in {item["name"] for item in inspector.get_columns("projects")}:
        with op.batch_alter_table("projects") as batch:
            batch.drop_column("settings")
