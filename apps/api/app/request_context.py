"""Per-request context shared by middleware and project resolution.

The UI used to rely only on the server-side "current project" flag, so
switching project in one tab silently re-scoped every other tab and any
in-flight request. Clients now send ``X-Project-Id`` and the request is
pinned to that project for its whole lifetime.
"""
from __future__ import annotations

import os
from contextvars import ContextVar

active_project_id: ContextVar[str | None] = ContextVar("active_project_id", default=None)


def is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() in {"production", "prod"}
