"""CLI: ``python -m app.migrate`` applies pending schema migrations and exits."""
from __future__ import annotations

from .database import Base, engine
from . import models  # noqa: F401  (registers tables on Base.metadata)
from .migrations import MIGRATIONS, run_migrations


def main() -> None:
    Base.metadata.create_all(bind=engine)
    applied = run_migrations(engine)
    print(f"Applied {len(applied)} migration(s): {', '.join(applied) or 'none pending'} (known: {len(MIGRATIONS)})")


if __name__ == "__main__":
    main()
