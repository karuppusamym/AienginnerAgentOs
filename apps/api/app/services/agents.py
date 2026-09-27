"""Agent-run policy helpers: approval detection and the initial multi-agent plan."""
from __future__ import annotations

from ..decision_router import RISK_TERMS, assess_risk


AGENT_APPROVAL_KEYWORDS = RISK_TERMS


def agent_run_requires_approval(objective: str) -> bool:
    # Word-boundary matching lives in decision_router so chat routing, agent
    # runs and plan review share one definition of a consequential action.
    return assess_risk(objective)["requires_approval"]


def initial_agent_plan(requires_approval: bool) -> list[dict[str, str]]:
    return [
        {"agent": "Planner", "action": "Decompose objective and set limits", "status": "waiting"},
        {"agent": "Metadata", "action": "Ground against catalog and semantic terms", "status": "waiting"},
        {"agent": "SQL Analyst", "action": "Draft dialect-aware query", "status": "waiting"},
        {"agent": "Quality", "action": "Validate assumptions and evidence", "status": "waiting"},
        {
            "agent": "Policy",
            "action": "Request human approval" if requires_approval else "Confirm read-only execution",
            "status": "waiting" if requires_approval else "complete",
        },
    ]
