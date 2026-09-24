"""Decision-router endpoints: preview a route, inspect the active policy, and
export (decision, outcome) pairs for offline policy optimisation.

The export is the training/eval set for a GEPA- or DSPy-style optimiser: each
row carries the question, every scored candidate, the chosen route, what the
user did with it (feedback), and whether execution succeeded. The optimiser
proposes a new policy JSON, which is replayed through ``/router/decide`` and
only deployed via ``DECISION_POLICY_PATH`` after human review.
"""
from __future__ import annotations

from typing import Any

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..decision_router import active_policy, decide
from ..grounding import grounding_context
from ..models import Conversation, ConversationMessage, RouteDecision, User, UserFeedback
from ..provider_selection import selected_model_provider
from ..core import require_current_project

router = APIRouter()


class RouteRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4_000)


@router.post("/router/decide")
def preview_route(payload: RouteRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, user)
    grounding = grounding_context(db, project.id, payload.question, limit=5)
    return decide(db, project.id, payload.question, grounding)


@router.get("/router/policy")
def router_policy(_: User = Depends(get_current_user)) -> dict[str, Any]:
    return active_policy()


@router.get("/router/decisions")
def router_decisions(
    limit: int = Query(default=200, ge=1, le=2_000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = require_current_project(db, user)
    rows = db.scalars(
        select(RouteDecision).where(RouteDecision.project_id == project.id).order_by(RouteDecision.created_at.desc()).limit(limit)
    ).all()
    feedback: dict[str, str] = {}
    ids = [row.message_id for row in rows if row.message_id]
    if ids:
        for item in db.scalars(
            select(UserFeedback).where(UserFeedback.project_id == project.id, UserFeedback.context_id.in_(ids)).order_by(UserFeedback.created_at)
        ).all():
            feedback[item.context_id or ""] = item.rating
    return [
        {
            "id": row.id,
            "message_id": row.message_id,
            "conversation_id": row.conversation_id,
            "created_at": row.created_at,
            "question": row.question,
            "route": row.route,
            "confidence": row.confidence,
            "backend": row.backend,
            "policy_version": row.policy_version,
            "candidates": row.candidates,
            "risk": row.risk,
            "outcome": {**(row.outcome or {}), "feedback": feedback.get(row.message_id or "", (row.outcome or {}).get("feedback"))},
        }
        for row in rows
    ]


class LabelledCase(BaseModel):
    question: str = Field(min_length=1, max_length=4_000)
    expected_route: Literal["sql_analysis", "query_tool", "agent_run", "clarify"]


class RouterEvaluationRequest(BaseModel):
    backends: list[Literal["local", "llm", "jev"]] = Field(default_factory=lambda: ["local", "llm"])
    cases: list[LabelledCase] = Field(default_factory=list, max_length=100)
    include_feedback: bool = True
    feedback_limit: int = Field(default=50, ge=0, le=200)


@router.post("/router/evaluate")
def evaluate_router(payload: RouterEvaluationRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Replay labelled questions through each backend and report agreement.

    Labels come from explicit cases and from stored decisions whose answer got
    feedback: "helpful" means the chosen route was right; "not_helpful" means
    any other route would have been preferable. This is the gate for turning
    on the LLM or Jev backend, and the scoring function for offline policy
    optimisation (GEPA/DSPy-style) over DECISION_POLICY_PATH.
    """
    project = require_current_project(db, user)
    cases: list[dict[str, Any]] = [{"question": case.question, "expect": case.expected_route, "negative": False, "source": "labelled"} for case in payload.cases]
    if payload.include_feedback and payload.feedback_limit:
        rows = db.scalars(
            select(RouteDecision).where(RouteDecision.project_id == project.id).order_by(RouteDecision.created_at.desc()).limit(500)
        ).all()
        rated = {item.context_id: item.rating for item in db.scalars(
            select(UserFeedback).where(UserFeedback.project_id == project.id, UserFeedback.context_id.in_([row.message_id for row in rows if row.message_id]))
        ).all()} if rows else {}
        for row in rows:
            rating = rated.get(row.message_id)
            if rating and len([case for case in cases if case["source"] == "feedback"]) < payload.feedback_limit:
                cases.append({"question": row.question, "expect": row.route, "negative": rating == "not_helpful", "source": "feedback"})
    try:
        routing_model = selected_model_provider(db, user, "decision_routing")
    except HTTPException:
        routing_model = None
    groundings = {case["question"]: grounding_context(db, project.id, case["question"], limit=5) for case in cases}
    report: dict[str, Any] = {"cases": len(cases), "backends": {}}
    for backend in payload.backends:
        correct = 0
        latencies: list[float] = []
        results = []
        for case in cases:
            decision = decide(db, project.id, case["question"], groundings[case["question"]], llm_provider=routing_model, backend_override=backend)
            latencies.append(decision["latency_ms"])
            hit = (decision["route"] != case["expect"]) if case["negative"] else (decision["route"] == case["expect"])
            correct += int(hit)
            results.append({"question": case["question"][:200], "expected": ("not " if case["negative"] else "") + case["expect"], "got": decision["route"], "confidence": decision["confidence"], "backend": decision["backend"], "correct": hit})
        report["backends"][backend] = {
            "accuracy": round(correct / len(cases), 4) if cases else None,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "effective_backend": results[0]["backend"] if results else None,
            "results": results,
        }
    return report
