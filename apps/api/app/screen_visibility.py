"""Per-project screen visibility: admins hide screens (e.g. for a focused demo).

Stored in ``projects.settings["hidden_screens"]`` as a list of navigation keys.
Hiding is presentation only: the screens leave the navigation and their routes
show a "hidden for this project" notice, but APIs and permissions are unchanged,
so nothing is lost and a screen comes back the moment it is unhidden.
"""
from __future__ import annotations

import re
from typing import Any

from .models import Project

# Admin stays reachable, otherwise nobody could unhide anything.
LOCKED_SCREENS = frozenset({"admin"})
# A page ("notebooks") or one tab of a page ("agents:tools", "learning:evaluations").
_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,39}(:[a-z][a-z0-9_-]{0,39})?$")
MAX_HIDDEN = 40


def hidden_screens(project: Project | None) -> list[str]:
    if project is None:
        return []
    values = (project.settings or {}).get("hidden_screens") or []
    return [value for value in values if isinstance(value, str) and _KEY.match(value) and value not in LOCKED_SCREENS]


def set_hidden_screens(project: Project, keys: list[str]) -> list[str]:
    cleaned: list[str] = []
    for key in keys:
        key = str(key).strip().lower()
        if not _KEY.match(key):
            raise ValueError(f"Invalid screen key: {key!r}")
        if key in LOCKED_SCREENS:
            raise ValueError(f"The {key} screen can't be hidden")
        if key not in cleaned:
            cleaned.append(key)
    if len(cleaned) > MAX_HIDDEN:
        raise ValueError("Too many hidden screens")
    settings: dict[str, Any] = dict(project.settings or {})
    settings["hidden_screens"] = cleaned
    project.settings = settings
    return cleaned
