"""Authorization helpers: current project, role/permission checks, project-scoped lookups.

Also authenticates external (machine) clients from their bearer token.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import verify_password
from ..models import ExternalClient, Project, User
from ..provider_selection import current_membership
from ..roles import project_permissions


def require_current_project(db: Session, user: User) -> Project:
    membership = current_membership(db, user)
    project = db.get(Project, membership.project_id) if membership else None
    if project is None or not project.active:
        raise HTTPException(status_code=409, detail="Select an active project before continuing")
    return project


def require_role(user: User, allowed: set[str], detail: str) -> User:
    if user.role not in allowed:
        raise HTTPException(status_code=403, detail=detail)
    return user


def require_permission(user: User, db: Session, permission: str, detail: str | None = None) -> User:
    """Authorize against the same granular permission map exposed by /auth/me."""
    membership = current_membership(db, user)
    membership_role = membership.role if membership else None
    if "*" not in project_permissions(user, membership_role) and permission not in project_permissions(user, membership_role):
        raise HTTPException(status_code=403, detail=detail or f"Permission required: {permission}")
    return user


def require_any_permission(user: User, db: Session, permissions: set[str], detail: str) -> User:
    """Pass when the user holds at least one of ``permissions`` (or "*") in the current project."""
    membership = current_membership(db, user)
    granted = project_permissions(user, membership.role if membership else None)
    if "*" not in granted and not granted & permissions:
        raise HTTPException(status_code=403, detail=detail)
    return user


# Running SQL, agents or tools changes cost, load or data exposure, so read-only
# roles (viewer) are excluded; analysts reach these through conversation:write.
QUERY_RUNNERS = {"query:write", "conversation:write"}
AGENT_RUNNERS = {"jobs:write", "conversation:write"}
TOOL_RUNNERS = {"jobs:write", "registry:write"}


def can_manage_shared_content(user: User, db: Session) -> bool:
    """Owners/maintainers (and admins) may edit content other members created."""
    membership = current_membership(db, user)
    granted = project_permissions(user, membership.role if membership else None)
    return "*" in granted or "registry:write" in granted


def require_data_editor(user: User, db: Session) -> User:
    return require_permission(user, db, "catalog:write", "Catalog write permission required")


def require_workspace_editor(user: User, db: Session) -> User:
    return require_permission(user, db, "conversation:write", "Workspace write permission required")


def require_project_resource(resource: Any, project: Project, label: str) -> Any:
    if resource is None or getattr(resource, "project_id", None) != project.id:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return resource


def require_semantic_maintainer(db: Session, user: User, project_id: str) -> None:
    membership = current_membership(db, user)
    if membership is None or membership.project_id != project_id or (user.role not in {"admin", "engineer"} and membership.role not in {"owner", "maintainer"}):
        raise HTTPException(status_code=403, detail="Project maintainer access required")
    require_permission(user, db, "semantic:write", "Semantic write permission required")


def _external_client_from_header(
    authorization: str | None,
    db: Session,
    required_scope: str,
) -> ExternalClient:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="External client bearer token required")
    token = authorization[7:].strip()
    if "." not in token:
        raise HTTPException(status_code=401, detail="Invalid external client token")
    client_id, secret = token.split(".", 1)
    client = db.scalar(select(ExternalClient).where(ExternalClient.client_id == client_id))
    if client is None or not client.active or not verify_password(secret, client.secret_hash):
        raise HTTPException(status_code=401, detail="Invalid external client token")
    now = datetime.now(timezone.utc)
    expires_at = client.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:  # SQLite returns naive datetimes; values are stored in UTC
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise HTTPException(status_code=401, detail="External client token has expired; rotate it to issue a new one")
    if required_scope not in client.scopes:
        raise HTTPException(status_code=403, detail=f"Missing scope: {required_scope}")
    # Cheap usage stamp: written at most once a minute and committed with the
    # caller's own transaction (invocation / audit), not by a separate write here.
    last_used = client.last_used_at
    if last_used is not None and last_used.tzinfo is None:
        last_used = last_used.replace(tzinfo=timezone.utc)
    if last_used is None or now - last_used >= timedelta(seconds=EXTERNAL_CLIENT_LAST_USED_RESOLUTION_SECONDS):
        client.last_used_at = now
    return client


EXTERNAL_CLIENT_LAST_USED_RESOLUTION_SECONDS = 60
