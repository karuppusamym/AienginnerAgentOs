from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException

from .request_context import active_project_id

from .models import ModelProvider, ModelRoute, Project, ProjectMembership, User


def current_membership(db: Session, user: User) -> ProjectMembership | None:
    pinned = active_project_id.get()
    if pinned:
        membership = db.scalar(
            select(ProjectMembership).where(ProjectMembership.user_id == user.id, ProjectMembership.project_id == pinned)
        )
        if membership is None:
            raise HTTPException(status_code=403, detail="You are not a member of the requested project")
        return membership
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


MODEL_PURPOSES: dict[str, str] = {
    "sql_generation": "SQL generation",
    "sql_repair": "SQL repair after validation or execution errors",
    "conversation_summary": "Chat answer narrative",
    "decision_routing": "Decision router (LLM backend)",
    "agent_planning": "Agent planning",
    "agent_review": "Agent plan review",
    "tool_parameters": "Tool parameter filling",
}
_FAILED_STATUSES = {"failed", "error", "unhealthy", "configuration_required"}


class ModelProviderUnavailable(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=409, detail=detail)


def _usable(provider: ModelProvider | None) -> bool:
    return bool(provider and provider.enabled and provider.status not in _FAILED_STATUSES)


def selected_model_provider(db: Session, user: User, purpose: str | None = None) -> ModelProvider | None:
    membership = current_membership(db, user)
    project = db.get(Project, membership.project_id) if membership is not None else None
    if purpose:
        route = None
        if project is not None:
            route = db.scalar(select(ModelRoute).where(ModelRoute.purpose == purpose, ModelRoute.project_id == project.id))
        route = route or db.scalar(select(ModelRoute).where(ModelRoute.purpose == purpose, ModelRoute.project_id.is_(None)))
        if route is not None:
            routed = db.get(ModelProvider, route.provider_id)
            if _usable(routed):
                return routed
            raise ModelProviderUnavailable(
                f"The model routed for {MODEL_PURPOSES.get(purpose, purpose)} ({routed.name if routed else 'deleted provider'}) is unavailable. "
                "Test it in Admin > Model providers or change the routing."
            )
    if project is not None and project.default_model_provider_id:
        pinned = db.get(ModelProvider, project.default_model_provider_id)
        if _usable(pinned):
            return pinned
        # Pinning is a data-residency choice: never silently send this project's
        # data to a different provider because the pinned one is down.
        raise ModelProviderUnavailable(
            f"This project's pinned model provider '{pinned.name if pinned else 'deleted provider'}' is unavailable"
            f" (status: {pinned.status if pinned else 'missing'}). Test it in Admin or choose another model for this project."
        )
    return db.scalar(
        select(ModelProvider).where(
            ModelProvider.is_default.is_(True),
            ModelProvider.enabled.is_(True),
        )
    ) or db.scalar(select(ModelProvider).where(ModelProvider.enabled.is_(True)).limit(1))


def default_embedding_provider(db: Session) -> ModelProvider | None:
    """Resolve the ModelProvider whose embedding_model should be used for indexing/search.

    Embeddings are stored in a single global Qdrant collection (search_documents()
    has no per-project filter — see grounding.glossary_matches), so provider
    selection here is intentionally global rather than per-user/per-project like
    selected_model_provider(). We just want "the" active provider: prefer the
    platform default, otherwise the first enabled provider, otherwise none (the
    caller falls back to the deterministic hash embedding).
    """
    return db.scalar(
        select(ModelProvider).where(
            ModelProvider.is_default.is_(True),
            ModelProvider.enabled.is_(True),
        )
    ) or db.scalar(select(ModelProvider).where(ModelProvider.enabled.is_(True)).limit(1))
