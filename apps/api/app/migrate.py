"""CLI: ``python -m app.migrate`` runs ``alembic upgrade head`` and exits.

Equivalent to ``cd apps/api && alembic upgrade head`` (same advisory lock and
legacy ``schema_versions`` adoption, see app/migrations.py), followed by the
same ``create_all`` safety net API startup runs, so a table added to
app/models.py before its revision exists is still created.
"""
from __future__ import annotations

from .database import Base, engine
from . import models  # noqa: F401  (registers tables on Base.metadata)
from .migrations import current_revisions, run_migrations


def main() -> None:
    applied = run_migrations(engine)
    Base.metadata.create_all(bind=engine)
    print(
        f"Applied {len(applied)} revision(s): {', '.join(applied) or 'none pending'} "
        f"(database at {', '.join(current_revisions(engine)) or 'base'})"
    )


if __name__ == "__main__":
    main()
