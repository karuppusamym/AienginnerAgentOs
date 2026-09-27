"""Agent evaluation replay (golden-trace checks without executing approval-gated actions)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import Job, Project, User
from ..temporal_activities import run_agent_plan_locally
from .agents import agent_run_requires_approval, initial_agent_plan


def run_agent_evaluation_case(
    db: Session,
    project: Project,
    user: User,
    evaluation_run_id: str,
    case: dict[str, Any],
) -> dict[str, Any]:
    """Replay an agent objective without allowing an approval-gated action to run."""
    objective = str(case["question"])
    requires_approval = agent_run_requires_approval(objective)
    job = Job(
        project_id=project.id,
        title=f"Evaluation: {case['name']}"[:200],
        job_type="agent_evaluation",
        status="SIMULATED_APPROVAL_REQUIRED" if requires_approval else "PLANNING",
        progress=100 if requires_approval else 5,
        plan=initial_agent_plan(requires_approval),
        evidence=[
            {"type": "evaluation", "label": evaluation_run_id},
            {"type": "policy", "label": "Approval simulated" if requires_approval else "Read-only local replay"},
        ],
        outputs=[],
        created_by=user.id,
    )
    db.add(job)
    db.flush()
    if requires_approval:
        job.outputs = [
            {
                "type": "policy_simulation",
                "agent": "Policy",
                "title": "Approval boundary reached",
                "summary": "The objective was not executed because it requires human approval.",
                "data": {"requires_approval": True},
                "at": datetime.now(timezone.utc).isoformat(),
            }
        ]
        db.commit()
    else:
        # The local runner uses its own session, so commit this evaluation job first.
        db.commit()
        run_agent_plan_locally(job.id, objective)
        db.expire_all()
        job = db.get(Job, job.id)
        if job is None:
            raise ValueError("Agent evaluation job disappeared during replay")

    observed_plan = [
        {"agent": str(step["agent"]), "action": re.sub(r"\s+", " ", str(step.get("action", "")).strip())}
        for step in job.plan
        if step.get("agent")
    ]
    observed_agents = [step["agent"] for step in observed_plan]
    observed_tools = sorted(
        {
            str(output.get("tool"))
            for output in job.outputs
            if output.get("type") in {"tool_result", "tool_error"} and output.get("tool")
        }
    )
    checks = [
        {"kind": "agent", "value": agent, "passed": agent in observed_agents}
        for agent in case.get("expected_agents", [])
    ] + [
        {"kind": "tool", "value": tool, "passed": tool in observed_tools}
        for tool in case.get("expected_tools", [])
    ]
    if case.get("expects_approval") is not None:
        checks.append(
            {
                "kind": "approval",
                "value": bool(case["expects_approval"]),
                "passed": requires_approval is bool(case["expects_approval"]),
            }
        )
    golden_trace = case.get("golden_trace") or {}
    actual_trace = {
        "agents": observed_agents,
        "plan_actions": [step["action"] for step in observed_plan],
        "tools": observed_tools,
        "requires_approval": requires_approval,
    }
    if golden_trace:
        if "agents" in golden_trace:
            checks.append(
                {
                    "kind": "golden_agents",
                    "value": golden_trace["agents"],
                    "passed": list(golden_trace["agents"]) == actual_trace["agents"],
                }
            )
        if "plan_actions" in golden_trace:
            expected_actions = [re.sub(r"\s+", " ", str(action).strip()) for action in golden_trace["plan_actions"]]
            checks.append(
                {
                    "kind": "golden_plan_actions",
                    "value": expected_actions,
                    "passed": expected_actions == actual_trace["plan_actions"],
                }
            )
        if "tools" in golden_trace:
            checks.append(
                {
                    "kind": "golden_tools",
                    "value": sorted(str(tool) for tool in golden_trace["tools"]),
                    "passed": sorted(str(tool) for tool in golden_trace["tools"]) == actual_trace["tools"],
                }
            )
        if "requires_approval" in golden_trace:
            checks.append(
                {
                    "kind": "golden_policy",
                    "value": bool(golden_trace["requires_approval"]),
                    "passed": bool(golden_trace["requires_approval"]) is requires_approval,
                }
            )
    score = 100.0 if not checks else 100.0 * sum(check["passed"] for check in checks) / len(checks)
    return {
        "name": case["name"],
        "case_type": "agent_run",
        "status": "passed" if score == 100 else "failed",
        "score": round(score, 2),
        "checks": checks,
        "job_id": job.id,
        "simulation": requires_approval,
        "observed_agents": observed_agents,
        "observed_tools": observed_tools,
        "observed_plan": observed_plan,
        "golden_trace": actual_trace,
        "job_status": job.status,
    }
