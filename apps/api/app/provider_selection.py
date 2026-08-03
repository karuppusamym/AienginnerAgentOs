from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ModelProvider, Project, ProjectMembership, User


def current_membership(db: Session, user: User) -> ProjectMembership | None:
    membership = db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.user_id == user.id,
            ProjectMembership.is_current.is_(True),
        )
    )
    if membership is not None:
        return membership
    membership = db.scalar(
        select(ProjectMembership)
        .where(ProjectMembership.user_id == user.id)
        .order_by(ProjectMembership.created_at)
        .limit(1)
    )
    if membership is not None:
        membership.is_current = True
        db.flush()
    return membership


def selected_model_provider(db: Session, user: User) -> ModelProvider | None:
    membership = current_membership(db, user)
    if membership is not None:
        project = db.get(Project, membership.project_id)
        if project and project.default_model_provider_id:
            provider = db.get(ModelProvider, project.default_model_provider_id)
            if provider and provider.enabled and provider.status == "healthy":
                return provider
    return db.scalar(
        select(ModelProvider).where(
            ModelProvider.is_default.is_(True),
            ModelProvider.enabled.is_(True),
        )
    ) or db.scalar(select(ModelProvider).where(ModelProvider.enabled.is_(True)).limit(1))
