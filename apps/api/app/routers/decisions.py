"""Decision-router endpoints: preview a route, inspect the active policy, and
export (decision, outcome) pairs for offline policy optimisation.

The export is the training/eval set for a GEPA- or DSPy-style optimiser: each
row carries the question, every scored candidate, the chosen route, what the
user did with it (feedback), and whether execution succeeded. The optimiser
proposes a new policy JSON, which is replayed through ``/router/decide`` and
only deployed via ``DECISION_POLICY_PATH`` after human review.
"""
from __future__ import annotations

import time
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

# Learning-loop endpoints are mounted through this router so the app shell
# (main.py) does not need to change when they grow.
from .learning import router as learning_router  # noqa: E402

router.include_router(learning_router)


class RouteRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4_000)


@router.post("/router/decide")
def preview_route(payload: RouteRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    project = require_current_project(db, user)
    grounding = grounding_context(db, project.id, payload.question, limit=5)
    try:
        routing_model = selected_model_provider(db, user, "decision_routing")
    except HTTPException:
        routing_model = None
    decision = decide(db, project.id, payload.question, grounding, llm_provider=routing_model, user_id=user.id)
    db.commit()  # keep the decision model's call log (latency, cost) in Model usage
    return decision


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
            decision = decide(db, project.id, case["question"], groundings[case["question"]], llm_provider=routing_model, backend_override=backend, user_id=user.id)
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
    db.commit()  # keep the evaluated backends' call logs in Model usage
    return report


class ToolChoiceCase(BaseModel):
    agent: str = Field(min_length=1, max_length=120)
    step: str = Field(min_length=1, max_length=1_000)
    expected_tool: str = Field(min_length=1, max_length=120)
    objective: str = Field(default="", max_length=1_000)


class ToolChoiceEvaluationRequest(BaseModel):
    backends: list[Literal["local", "jev"]] = Field(default_factory=lambda: ["local", "jev"])
    cases: list[ToolChoiceCase] = Field(min_length=1, max_length=50)


@router.post("/router/evaluate-tools")
def evaluate_tool_choice(payload: ToolChoiceEvaluationRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Labelled "agent step -> expected tool" cases replayed through the tool choosers.

    ``local`` is the word-overlap fallback; ``jev`` is the decision model routed to
    ``tool_selection``. Options are the agent's bound tools and their registry descriptions,
    the same menu an agent run offers.
    """
    from .. import jev_client
    from ..models import AgentDefinition, AgentVersion, QueryTool, ToolDefinition
    from ..provider_selection import routed_only_provider
    from ..temporal_activities import _local_tool_scores

    project = require_current_project(db, user)
    chooser = routed_only_provider(db, user, "tool_selection")
    report: dict[str, Any] = {"cases": len(payload.cases), "backends": {}, "skipped": []}
    menus: dict[str, dict[str, str]] = {}
    for case in payload.cases:
        if case.agent in menus:
            continue
        agent = db.scalar(select(AgentDefinition).where(AgentDefinition.name == case.agent))
        if agent is None:
            continue
        version = db.scalar(select(AgentVersion).where(AgentVersion.agent_id == agent.id, AgentVersion.status == "published").order_by(AgentVersion.version.desc()).limit(1))
        menu: dict[str, str] = {}
        for name in (version.tool_names if version else agent.tool_names) or []:
            tool = db.scalar(select(ToolDefinition).where(ToolDefinition.name == name))
            if tool is not None:
                menu[name] = tool.description or name
        for name in (version.query_tool_names if version else agent.query_tool_names) or []:
            query_tool = db.scalar(select(QueryTool).where(QueryTool.project_id == project.id, QueryTool.name == name))
            if query_tool is not None:
                menu[name] = f"{query_tool.description} {query_tool.purpose}".strip() or name
        menus[case.agent] = menu
    usable = []
    for case in payload.cases:
        menu = menus.get(case.agent) or {}
        if case.expected_tool not in menu or len(menu) < 2:
            report["skipped"].append({"agent": case.agent, "step": case.step[:200], "reason": "unknown agent, expected tool not bound to it, or nothing to choose between"})
        else:
            usable.append((case, menu))
    for backend in payload.backends:
        results, latencies = [], []
        for case, menu in usable:
            started = time.perf_counter()
            if backend == "jev":
                verdict = jev_client.choose_tools(db, chooser, case.step, case.objective or case.step, menu, project.id, user.id) if chooser is not None else None
                probabilities = (verdict or {}).get("probabilities") or {}
                effective = f"jev:{verdict['model']}" if verdict else ("jev (not routed)" if chooser is None else "jev (unavailable)")
            else:
                probabilities = _local_tool_scores(f"{case.step} {case.objective}", menu)
                effective = "local"
            latencies.append((time.perf_counter() - started) * 1000)
            got = max(probabilities, key=probabilities.get) if probabilities else None
            results.append({"agent": case.agent, "step": case.step[:200], "expected": case.expected_tool, "got": got, "probability": round(probabilities.get(got, 0.0), 4) if got else None, "backend": effective, "correct": got == case.expected_tool})
        report["backends"][backend] = {
            "accuracy": round(sum(item["correct"] for item in results) / len(results), 4) if results else None,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "effective_backend": results[0]["backend"] if results else None,
            "results": results,
        }
    db.commit()  # keep Jev call logs in Model usage
    return report
