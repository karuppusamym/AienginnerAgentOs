"""Role → permission model.

Project membership is authoritative inside a project: a global engineer who
is only a viewer in project X gets viewer rights there. The previous model
unioned global and project roles, so global roles silently overrode
per-project restrictions. Global ``admin`` remains a superuser.
"""
from __future__ import annotations

from .models import User

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {"*"},
    "engineer": {"catalog:read", "catalog:write", "semantic:write", "query:read", "query:write", "pipeline:write", "quality:write", "registry:write", "jobs:write"},
    "analyst": {"catalog:read", "query:read", "semantic:read", "conversation:write", "feedback:write"},
    "viewer": {"catalog:read", "query:read", "semantic:read"},
    "owner": {"catalog:read", "catalog:write", "semantic:write", "query:read", "query:write", "pipeline:write", "quality:write", "registry:write", "jobs:write", "conversation:write", "feedback:write"},
    "maintainer": {"catalog:read", "catalog:write", "semantic:write", "query:read", "query:write", "pipeline:write", "quality:write", "registry:write", "jobs:write", "conversation:write", "feedback:write"},
    "member": {"catalog:read", "query:read", "semantic:read", "conversation:write", "feedback:write"},
}

# Project role a user receives when added to a project from their global role.
DEFAULT_MEMBERSHIP_ROLE = {"admin": "owner", "engineer": "maintainer", "analyst": "member", "viewer": "viewer"}


def default_membership_role(global_role: str) -> str:
    return DEFAULT_MEMBERSHIP_ROLE.get(global_role, "viewer")


def project_permissions(user: User, membership_role: str | None) -> set[str]:
    if user.role == "admin":
        return {"*"}
    if membership_role:
        return set(ROLE_PERMISSIONS.get(membership_role, set()))
    return set(ROLE_PERMISSIONS.get(user.role, set()))
