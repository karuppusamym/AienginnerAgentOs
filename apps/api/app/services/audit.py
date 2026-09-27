"""Durable audit trail and internal (system-written) artifact versioning."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..governance import record_audit_event
from ..models import Artifact, ArtifactVersion, AuditEvent, User
from ..provider_selection import current_membership
from .authz import require_current_project, require_project_resource


def audit(
    db: Session,
    actor: User | None,
    event_type: str,
    entity_type: str,
    entity_id: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    membership = current_membership(db, actor) if actor else None
    project_id = membership.project_id if membership else None
    audit_details = details or {}
    db.add(
        AuditEvent(
            project_id=project_id,
            actor_id=actor.id if actor else None,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            details=audit_details,
        )
    )
    # Every durable audit action is also exported so external governance has
    # the same activity coverage as the local audit trail.
    record_audit_event(
        event_type,
        entity_type,
        entity_id,
        project_id=project_id,
        user_id=actor.id if actor else None,
        details=audit_details,
    )


def save_internal_artifact_version(
    db: Session,
    user: User,
    name: str,
    artifact_type: str,
    content: str,
    metadata: dict[str, Any],
    artifact_id: str | None = None,
) -> tuple[Artifact, ArtifactVersion]:
    project = require_current_project(db, user)
    artifact = db.get(Artifact, artifact_id) if artifact_id else None
    if artifact is not None:
        require_project_resource(artifact, project, "Artifact")
    if artifact is None:
        artifact = Artifact(
            project_id=project.id,
            name=name,
            artifact_type=artifact_type,
            created_by=user.id,
        )
        db.add(artifact)
        db.flush()
    else:
        artifact.name = name
        artifact.updated_at = datetime.now(timezone.utc)
    current_version = db.scalar(
        select(func.max(ArtifactVersion.version)).where(ArtifactVersion.artifact_id == artifact.id)
    ) or 0
    version = ArtifactVersion(
        artifact_id=artifact.id,
        version=current_version + 1,
        content=content,
        artifact_metadata=metadata,
        created_by=user.id,
    )
    db.add(version)
    db.flush()
    return artifact, version
