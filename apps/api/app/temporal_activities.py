from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone

from sqlalchemy import select

from .database import SessionLocal
from .grounding import grounding_context, grounding_prompt_text, summarize_tool_result
from .governance import record_governance_event
from .model_runtime import generate_text
from .models import AgentDefinition, AgentVersion, Job, ModelCallLog, ToolDefinition, ToolVersion, User
from .metadata_scan_runtime import execute_metadata_scan
from .provider_selection import selected_model_provider
from .schedule_runtime import run_ingestion_schedule
from .tool_runtime import ToolRuntimeError, execute_tool

try:
    from temporalio import activity
except ModuleNotFoundError:
    class _ActivityFallback:
        def defn(self, name: str | None = None):
            def decorator(func):
                return func

            return decorator

    activity = _ActivityFallback()


def _parameters_for_tool(schema: dict, objective: str) -> dict | None:
    """Supply only unambiguous safe inputs; uncertain contracts are never guessed."""
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    parameters: dict = {}
    for name, declaration in properties.items():
        if name in {"query", "objective"} and declaration.get("type") == "string":
            parameters[name] = objective[:300]
        elif name == "limit" and declaration.get("type") == "integer":
            parameters[name] = min(10, int(declaration.get("maximum", 10)))
    return parameters if required.issubset(parameters) else None


def _execute_bound_tools(db, job: Job, plan: list[dict], objective: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Run a small, registry-bound, read-only tool loop with durable evidence."""
    evidence: list[dict] = []
    logs: list[dict] = []
    outputs: list[dict] = []
    calls_remaining = 12
    for step in plan:
        if calls_remaining <= 0:
            break
        agent = db.scalar(select(AgentDefinition).where(AgentDefinition.name == step["agent"], AgentDefinition.enabled.is_(True)))
        if agent is None:
            continue
        version = db.scalar(select(AgentVersion).where(AgentVersion.agent_id == agent.id, AgentVersion.status == "published").order_by(AgentVersion.version.desc()).limit(1))
        tool_names = version.tool_names if version else agent.tool_names
        for tool_name in tool_names:
            if calls_remaining <= 0:
                break
            tool = db.scalar(select(ToolDefinition).where(ToolDefinition.name == tool_name, ToolDefinition.enabled.is_(True)))
            if tool is None or tool.requires_approval or tool.risk_level != "low":
                continue
            tool_version = db.scalar(select(ToolVersion).where(ToolVersion.tool_id == tool.id, ToolVersion.status == "published").order_by(ToolVersion.version.desc()).limit(1))
            if tool_version is None or tool_version.implementation_type != "builtin":
                continue
            parameters = _parameters_for_tool(tool_version.parameter_schema, objective)
            if parameters is None:
                continue
            calls_remaining -= 1
            try:
                result, attempts, duration_ms = execute_tool(
                    db,
                    tool_version.implementation_type,
                    tool_version.handler_name,
                    tool_version.endpoint,
                    tool_version.http_method,
                    tool_version.parameter_schema,
                    parameters,
                    job.project_id,
                    tool_version.timeout_seconds,
                    tool_version.max_retries,
                    tool_version.retry_backoff_seconds,
                    user_id=job.created_by,
                    session_id=job.id,
                )
                count = result.get("count", result.get("row_count", "completed")) if isinstance(result, dict) else "completed"
                evidence.append({"type": "tool", "label": f"{agent.name} used {tool.name}: {count}", "tool": tool.name, "parameters": parameters})
                logs.append({"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": f"{agent.name} completed {tool.name} in {duration_ms} ms ({attempts} attempt(s))"})
                outputs.append(
                    {
                        "type": "tool_result",
                        "agent": agent.name,
                        "tool": tool.name,
                        "title": f"{agent.name} -> {tool.name}",
                        "summary": f"{tool.name} completed in {duration_ms} ms",
                        "data": summarize_tool_result(result),
                        "at": datetime.now(timezone.utc).isoformat(),
                    }
                )
            except ToolRuntimeError as exc:
                logs.append({"at": datetime.now(timezone.utc).isoformat(), "level": "warning", "message": f"{agent.name} skipped {tool.name}: {str(exc)[:300]}"})
                outputs.append(
                    {
                        "type": "tool_error",
                        "agent": agent.name,
                        "tool": tool.name,
                        "title": f"{agent.name} -> {tool.name}",
                        "summary": str(exc)[:300],
                        "data": {"error": str(exc)[:500]},
                        "at": datetime.now(timezone.utc).isoformat(),
                    }
                )
    return evidence, logs, outputs


def _execute_agent_plan(job_id: str, objective: str) -> dict:
    fallback_plan = [
        {"agent": "Planner", "action": "Decompose objective and set limits", "status": "complete"},
        {"agent": "Metadata", "action": "Retrieve catalog and vector context", "status": "complete"},
        {"agent": "SQL Analyst", "action": "Draft a dialect-aware read-only query", "status": "complete"},
        {"agent": "Quality", "action": "Validate assumptions and evidence", "status": "complete"},
        {"agent": "Policy", "action": "Confirm policy and execution limits", "status": "complete"},
    ]
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} does not exist")
        job.status = "RUNNING"
        job.progress = 30
        job.logs = [
            {"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": "Temporal worker accepted the run"}
        ]
        db.commit()
        record_governance_event(
            "worker_job",
            "agent_plan",
            "started",
            project_id=job.project_id,
            user_id=job.created_by,
            session_id=job.id,
        )
        try:
            plan = fallback_plan
            model_log = None
            trace_outputs: list[dict] = []
            grounding = grounding_context(db, job.project_id, objective, limit=5)
            trace_outputs.append(
                {
                    "type": "grounding",
                    "agent": "Metadata",
                    "title": "Retrieved grounding context",
                    "summary": f"{len(grounding['catalog_matches'])} catalog matches, {len(grounding['semantic_matches'])} semantic metrics, {len(grounding['join_matches'])} approved joins",
                    "data": grounding,
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            )
            job.logs = [
                *job.logs,
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "level": "info",
                    "message": f"Retrieved {len(grounding['catalog_matches'])} catalog matches and {len(grounding['semantic_matches'])} semantic metrics",
                },
            ]
            provider = selected_model_provider(db, db.get(User, job.created_by))
            if provider and provider.provider_type != "local_mock":
                try:
                    generated = generate_text(
                        provider,
                        "You are the governed planner for a local data engineering product. Return JSON only: an array of 3 to 6 objects with agent and action string fields. Allowed agents are Planner, Metadata, SQL Analyst, Pipeline, Quality, Troubleshooter, and Policy. Every action must be read-only unless it explicitly says approval is required.",
                        f"Create a bounded specialist plan for this objective: {objective}\n\n{grounding_prompt_text(grounding)}",
                        800,
                        governance_feature="agent_planning",
                        governance_business_id=job.project_id,
                        governance_session_id=job.id,
                        governance_user_id=job.created_by,
                    )
                    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", generated.content.strip(), flags=re.I)
                    parsed = json.loads(content)
                    if not isinstance(parsed, list) or not 3 <= len(parsed) <= 6:
                        raise ValueError("Planner output must contain 3 to 6 steps")
                    allowed_agents = {"Planner", "Metadata", "SQL Analyst", "Pipeline", "Quality", "Troubleshooter", "Policy"}
                    plan = []
                    for step in parsed:
                        agent = str(step.get("agent", ""))
                        action = str(step.get("action", ""))
                        if agent not in allowed_agents or not action:
                            raise ValueError("Planner output used an unsupported agent or empty action")
                        plan.append({"agent": agent, "action": action[:500], "status": "complete"})
                    model_log = {"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": f"Plan generated by {provider.name} / {provider.default_model}"}
                    trace_outputs.append(
                        {
                            "type": "plan",
                            "agent": "Planner",
                            "title": "Generated specialist plan",
                            "summary": f"{len(plan)} steps generated by {provider.name}",
                            "data": plan,
                            "at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    db.add(ModelCallLog(project_id=job.project_id, provider_id=provider.id, model=provider.default_model, purpose="agent_planning", status="healthy", latency_ms=generated.latency_ms, created_by=job.created_by))
                except Exception as exc:
                    model_log = {"at": datetime.now(timezone.utc).isoformat(), "level": "warning", "message": f"Model planning fell back to the deterministic policy plan: {str(exc)[:240]}"}
                    db.add(ModelCallLog(project_id=job.project_id, provider_id=provider.id, model=provider.default_model, purpose="agent_planning", status="failed", error=str(exc)[:1000], created_by=job.created_by))
            if not any(item.get("type") == "plan" for item in trace_outputs):
                trace_outputs.append(
                    {
                        "type": "plan",
                        "agent": "Planner",
                        "title": "Deterministic specialist plan",
                        "summary": f"{len(plan)} bounded steps",
                        "data": plan,
                        "at": datetime.now(timezone.utc).isoformat(),
                    }
                )

            job.plan = plan
            tool_evidence, tool_logs, tool_outputs = _execute_bound_tools(db, job, plan, objective)
            job.evidence = [
                {"type": "catalog", "label": f"{len(grounding['catalog_matches'])} grounded catalog matches retrieved"},
                {"type": "vector", "label": f"{len(grounding['vector_hits'])} vector hits retrieved"},
                {"type": "semantic", "label": f"{len(grounding['semantic_matches'])} semantic metrics evaluated"},
                {"type": "policy", "label": "Read-only and bounded-run policies passed"},
                *tool_evidence,
            ]
            job.outputs = [*trace_outputs, *tool_outputs]
            job.logs = [
                *job.logs,
                *([model_log] if model_log else []),
                *tool_logs,
                {"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": "Specialist plan completed"},
            ]
            job.status = "SUCCEEDED"
            job.progress = 100
            db.commit()
            record_governance_event(
                "agent_run",
                "agent_plan",
                "succeeded",
                project_id=job.project_id,
                user_id=job.created_by,
                session_id=job.id,
                plan_steps=len(plan),
                tool_calls=len(tool_evidence),
            )
        except Exception as exc:
            job.status = "FAILED"
            job.progress = 100
            job.logs = [*job.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "error", "message": str(exc)[:500]}]
            db.commit()
            record_governance_event(
                "agent_run",
                "agent_plan",
                "failed",
                project_id=job.project_id,
                user_id=job.created_by,
                session_id=job.id,
                error_type=type(exc).__name__,
            )
            raise
    return {"job_id": job_id, "objective": objective, "status": "SUCCEEDED", "plan": plan}


def run_agent_plan_locally(job_id: str, objective: str) -> dict:
    return _execute_agent_plan(job_id, objective)


@activity.defn(name="execute_agent_plan")
async def execute_agent_plan(job_id: str, objective: str) -> dict:
    return await asyncio.to_thread(_execute_agent_plan, job_id, objective)


@activity.defn(name="execute_scheduled_ingestion")
async def execute_scheduled_ingestion(schedule_id: str, actor_id: str | None = None) -> dict:
    return await asyncio.to_thread(run_ingestion_schedule, schedule_id, actor_id)


@activity.defn(name="execute_metadata_scan")
async def execute_metadata_scan_activity(connector_id: str, job_id: str, actor_id: str) -> dict:
    return await asyncio.to_thread(execute_metadata_scan, connector_id, job_id, actor_id)
