from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone

from sqlalchemy import select

from .connector_runtime import ConnectorRuntimeError, execute_connector_query
from .database import SessionLocal, engine
from .extraction_runtime import run_external_extraction_now
from .grounding import grounding_context, grounding_prompt_text, summarize_tool_result
from .governance import record_governance_event
from .model_runtime import generate_text
from .models import AgentDefinition, AgentVersion, Approval, Connector, DataAsset, IngestedFile, IngestionMapping, IngestionSchedule, Job, ModelCallLog, QueryTool, QualityRule, ToolDefinition, ToolVersion, User
from .metadata_scan_runtime import execute_metadata_scan
from .provider_selection import selected_model_provider
from .schedule_runtime import run_ingestion_schedule
from .staging import execute_parameterized_read_only
from .tool_runtime import ToolRuntimeError, execute_tool, validate_parameters

try:
    from temporalio import activity
except ModuleNotFoundError:
    class _ActivityFallback:
        def defn(self, name: str | None = None):
            def decorator(func):
                return func

            return decorator

    activity = _ActivityFallback()


# Foreign-key-shaped parameter names the bounded loop is willing to resolve
# to a real database row, keyed by the model that owns that ID space. Shared
# by both the deterministic heuristic below and the guarded LLM fallback --
# any identifier either path proposes for these names must resolve to a real
# row scoped to the run's project, or it is discarded, never trusted as-is.
_ID_LOOKUP_MODELS: dict[str, type] = {
    "asset_id": DataAsset,
    "file_id": IngestedFile,
    "mapping_id": IngestionMapping,
    "rule_id": QualityRule,
    "schedule_id": IngestionSchedule,
    "job_id": Job,
}


def _parameters_for_tool(schema: dict, objective: str, db=None, project_id: str | None = None) -> dict | None:
    """Build only schema-valid parameters that can be grounded in the objective.

    Defaults are limited to bounded, non-identity values. Resource identifiers
    are resolved only from an exact UUID/name/relation match in the current
    project; the agent never guesses an asset, file, rule, mapping, or schedule.
    """
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    parameters: dict = {}
    objective_lower = objective.lower()
    assets = db.scalars(select(DataAsset).where(DataAsset.project_id == project_id)).all() if db is not None and project_id else []
    relations = {f"{asset.schema_name}.{asset.table_name}": asset for asset in assets}
    matched_asset = next((asset for relation, asset in relations.items() if relation.lower() in objective_lower), None)
    uuid_candidates = set(re.findall(r"\b[0-9a-f]{8}-[0-9a-f-]{27,36}\b", objective_lower))
    for name, declaration in properties.items():
        if name in {"query", "objective"} and declaration.get("type") == "string":
            parameters[name] = objective[:300]
        elif name == "sql" and declaration.get("type") == "string":
            candidate = re.search(r"\b(?:select|with)\b[\s\S]*", objective, re.IGNORECASE)
            if candidate:
                parameters[name] = candidate.group(0).split("```", 1)[0].strip()[:100_000]
        elif name == "dialect" and declaration.get("type") == "string":
            allowed = declaration.get("enum") or ["postgres"]
            if "postgres" in allowed:
                parameters[name] = "postgres"
        elif name == "relation" and declaration.get("type") == "string" and matched_asset:
            parameters[name] = f"{matched_asset.schema_name}.{matched_asset.table_name}"
        elif name == "asset_id" and matched_asset:
            parameters[name] = matched_asset.id
        elif name.endswith("_id") and declaration.get("type") == "string" and db is not None and project_id:
            model = _ID_LOOKUP_MODELS.get(name)
            if model:
                candidates = db.scalars(select(model).where(getattr(model, "project_id") == project_id)).all()
                exact = next((item for item in candidates if str(item.id).lower() in uuid_candidates), None)
                if exact:
                    parameters[name] = exact.id
        elif name == "limit" and declaration.get("type") == "integer":
            parameters[name] = max(int(declaration.get("minimum", 1)), min(10, int(declaration.get("maximum", 10))))
        elif "default" in declaration:
            parameters[name] = declaration["default"]
    return parameters if required.issubset(parameters) else None


def _llm_parameters_for_tool(
    db, provider, schema: dict, objective: str, project_id: str, tool_label: str, job: Job,
) -> dict | None:
    """Guarded fallback for _parameters_for_tool: only reached once the
    deterministic heuristic above has already failed to ground every
    required parameter. A model gets one narrow shot at filling the gap --
    its output is never trusted directly:

    1. It must be strict JSON, an object, and non-empty.
    2. It must pass the exact same JSON-Schema `validate_parameters()` every
       other tool call is checked against (required/type/enum/bounds).
    3. Any field named like a foreign key (see `_ID_LOOKUP_MODELS`) must
       resolve to a real row scoped to *this* project, or the whole fill is
       discarded -- a schema-valid-looking but hallucinated ID is rejected
       exactly like a missing one, never partially applied.

    If any check fails, this returns None and the tool is skipped for this
    run, same outcome as the heuristic returning None. This never runs for
    approval-gated or non-low-risk tools -- callers only reach this point
    after the same risk_level/requires_approval gate the heuristic path
    already passed through.
    """
    if provider is None or provider.provider_type == "local_mock":
        return None
    schema_text = json.dumps(
        {"required": schema.get("required", []), "properties": schema.get("properties", {})}, default=str
    )[:4000]
    started = datetime.now(timezone.utc)
    try:
        generated = generate_text(
            provider,
            "You fill in parameters for one governed, read-only tool call inside a bounded automated run. "
            "Return strict JSON only: a single object whose keys are exactly the required parameter names. "
            "If you are not fully confident of a correct value for every required parameter, return {} instead "
            "of guessing -- a partial or uncertain answer is treated as a refusal, not a best effort. "
            "Never invent an identifier: only use one that is explicitly present, verbatim, in the objective text.",
            f"Tool: {tool_label}\nParameter schema (required + properties): {schema_text}\nObjective: {objective[:500]}",
            300,
            governance_feature="agent_tool_parameter_fill",
            governance_business_id=project_id,
            governance_session_id=job.id,
            governance_user_id=job.created_by,
        )
    except Exception:
        return None
    latency_ms = generated.latency_ms if hasattr(generated, "latency_ms") else round((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    try:
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", generated.content.strip(), flags=re.I)
        parameters = json.loads(content)
        if not isinstance(parameters, dict) or not parameters:
            raise ValueError("Model returned no usable parameters")
        validate_parameters(schema, parameters)
        for name, value in parameters.items():
            model = _ID_LOOKUP_MODELS.get(name)
            if model is None:
                continue
            row = db.get(model, str(value)) if isinstance(value, str) else None
            if row is None or getattr(row, "project_id", None) != project_id:
                raise ValueError(f"Model-proposed '{name}' does not resolve to a real row in this project")
    except Exception as exc:
        db.add(
            ModelCallLog(
                project_id=project_id, provider_id=provider.id, model=provider.default_model,
                purpose="agent_tool_parameter_fill", status="failed", error=str(exc)[:1000],
                latency_ms=latency_ms, created_by=job.created_by,
            )
        )
        return None
    db.add(
        ModelCallLog(
            project_id=project_id, provider_id=provider.id, model=provider.default_model,
            purpose="agent_tool_parameter_fill", status="healthy", latency_ms=latency_ms, created_by=job.created_by,
        )
    )
    return parameters


DETERMINISTIC_POLICY_KEYWORDS = (
    "schedule", "write", "create table", "publish", "deploy", "execute", "delete",
    "drop", "alter", "truncate", "grant", "revoke", "export", "send", "email",
)


def _plan_requires_deterministic_approval(plan: list[dict]) -> bool:
    """The configurable Policy agent can explain this result, but cannot weaken it."""
    return any(
        any(keyword in str(step.get("action", "")).lower() for keyword in DETERMINISTIC_POLICY_KEYWORDS)
        for step in plan
    )


def _execute_bound_query_tool(db, job: Job, query_tool: QueryTool, parameters: dict) -> dict:
    """Run one governed SQL query tool the same way the external gateway does
    (connector or local staging engine, read-only, row/time bounded), so a
    bound agent gets identical PII masking and governance logging to an
    external accessor invoking the same published tool."""
    if query_tool.connector_id:
        connector = db.get(Connector, query_tool.connector_id)
        if connector is None or connector.project_id != query_tool.project_id:
            raise ToolRuntimeError("The configured connector is unavailable")
        return execute_connector_query(
            connector,
            query_tool.sql_template,
            parameters,
            query_tool.row_limit,
            query_tool.timeout_seconds,
            upstream_tool_name=query_tool.upstream_tool_name,
            user_id=job.created_by,
            session_id=job.id,
            feature="agent_bound_query_tool",
        )
    return execute_parameterized_read_only(
        engine, query_tool.sql_template, parameters, query_tool.row_limit, query_tool.timeout_seconds
    )


def _execute_bound_tools(db, job: Job, plan: list[dict], objective: str, provider=None) -> tuple[list[dict], list[dict], list[dict]]:
    """Run a small, registry-bound, read-only tool loop with durable evidence.

    Two registries feed this loop: the internal ToolDefinition registry
    (built-in handlers / allowlisted HTTP) and the governed QueryTool
    registry (published, business-described SQL tools -- the same ones
    exposed to external accessors over /external/v1 and /mcp). An agent
    binds to either or both by name; both share the same bounded call
    budget and are skipped, never guessed, when a contract can't be
    satisfied safely.

    Parameter filling is two-tier: the deterministic, DB-grounded heuristic
    in _parameters_for_tool() runs first; only if that can't satisfy every
    required field does the guarded LLM fallback in _llm_parameters_for_tool()
    get a turn (and only when `provider` is a real, non-local_mock provider).
    Both tiers apply the same "never guess, discard on any doubt" outcome --
    the LLM tier just widens what counts as "grounded" for cases the fixed
    heuristic can't reach (a fill it accepts still has to be schema-valid and
    every ID in it still has to resolve to a real row in this project).
    """
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
            parameter_source = "heuristic"
            parameters = _parameters_for_tool(tool_version.parameter_schema, objective, db, job.project_id)
            if parameters is None:
                parameters = _llm_parameters_for_tool(db, provider, tool_version.parameter_schema, objective, job.project_id, tool.name, job)
                parameter_source = "model"
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
                evidence.append({"type": "tool", "label": f"{agent.name} used {tool.name}: {count}", "tool": tool.name, "parameters": parameters, "parameter_source": parameter_source})
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
        query_tool_names = (version.query_tool_names if version else agent.query_tool_names) or []
        for query_tool_name in query_tool_names:
            if calls_remaining <= 0:
                break
            query_tool = db.scalar(
                select(QueryTool).where(
                    QueryTool.project_id == job.project_id,
                    QueryTool.name == query_tool_name,
                    QueryTool.status == "published",
                )
            )
            if query_tool is None or query_tool.requires_approval:
                continue
            parameter_source = "heuristic"
            parameters = _parameters_for_tool(query_tool.parameter_schema, objective, db, job.project_id)
            if parameters is None:
                parameters = _llm_parameters_for_tool(db, provider, query_tool.parameter_schema, objective, job.project_id, query_tool.name, job)
                parameter_source = "model"
            if parameters is None:
                continue
            try:
                validate_parameters(query_tool.parameter_schema, parameters)
            except ToolRuntimeError:
                continue
            calls_remaining -= 1
            started = datetime.now(timezone.utc)
            try:
                result = _execute_bound_query_tool(db, job, query_tool, parameters)
                duration_ms = round((datetime.now(timezone.utc) - started).total_seconds() * 1000)
                record_governance_event(
                    "agent_bound_query_tool",
                    query_tool.name,
                    "succeeded",
                    project_id=job.project_id,
                    user_id=job.created_by,
                    session_id=job.id,
                    feature="agent_bound_query_tool",
                    query_tool_id=query_tool.id,
                    row_count=result.get("row_count") if isinstance(result, dict) else None,
                    duration_ms=duration_ms,
                )
                evidence.append({"type": "query_tool", "label": f"{agent.name} used {query_tool.name}: {result.get('row_count', 'completed') if isinstance(result, dict) else 'completed'}", "tool": query_tool.name, "parameters": parameters, "parameter_source": parameter_source})
                logs.append({"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": f"{agent.name} completed SQL query tool {query_tool.name} in {duration_ms} ms"})
                outputs.append(
                    {
                        "type": "query_tool_result",
                        "agent": agent.name,
                        "tool": query_tool.name,
                        "title": f"{agent.name} -> {query_tool.name}",
                        "summary": f"{query_tool.name} completed in {duration_ms} ms",
                        "data": summarize_tool_result(result),
                        "at": datetime.now(timezone.utc).isoformat(),
                    }
                )
            except (ToolRuntimeError, ConnectorRuntimeError, ValueError) as exc:
                record_governance_event(
                    "agent_bound_query_tool",
                    query_tool.name,
                    "failed",
                    project_id=job.project_id,
                    user_id=job.created_by,
                    session_id=job.id,
                    feature="agent_bound_query_tool",
                    query_tool_id=query_tool.id,
                    error_type=type(exc).__name__,
                )
                logs.append({"at": datetime.now(timezone.utc).isoformat(), "level": "warning", "message": f"{agent.name} skipped {query_tool.name}: {str(exc)[:300]}"})
                outputs.append(
                    {
                        "type": "tool_error",
                        "agent": agent.name,
                        "tool": query_tool.name,
                        "title": f"{agent.name} -> {query_tool.name}",
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
        {"agent": "Analytics", "action": "Explain approved metrics and result shape", "status": "complete"},
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
            enabled_agent_names = set(db.scalars(select(AgentDefinition.name).where(AgentDefinition.enabled.is_(True))).all())
            enabled_agent_names.update({"Planner", "Policy"})
            provider = selected_model_provider(db, db.get(User, job.created_by))
            if provider and provider.provider_type != "local_mock":
                try:
                    generated = generate_text(
                        provider,
                        f"You are the governed planner for a local data engineering product. Return JSON only: an array of 3 to 6 objects with agent and action string fields. Configured agents are {', '.join(sorted(enabled_agent_names))}. Deterministic policy enforcement remains authoritative even when the Policy agent is configured. Every action must be read-only unless it explicitly says approval is required.",
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
                    allowed_agents = enabled_agent_names
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
            if _plan_requires_deterministic_approval(plan):
                approval = Approval(
                    project_id=job.project_id,
                    job_id=job.id,
                    title=f"Approve deterministic policy boundary: {job.title[:120]}",
                    action_type="agent_execution",
                    risk_level="high",
                    requested_by=job.created_by,
                    evidence={
                        "objective": objective,
                        "policy_agent": "Policy",
                        "deterministic_authority": True,
                        "reason": "The generated plan contains an approval-bound action.",
                    },
                )
                db.add(approval)
                job.status = "WAITING_FOR_APPROVAL"
                job.progress = 30
                job.logs = [*job.logs, {"at": datetime.now(timezone.utc).isoformat(), "level": "warning", "message": "Deterministic policy held the generated plan for human approval"}]
                job.evidence = [{"type": "policy", "label": "Deterministic policy approval required", "agent": "Policy"}]
                db.commit()
                record_governance_event("agent_run", "deterministic_policy", "approval_required", project_id=job.project_id, user_id=job.created_by, session_id=job.id, feature="agent_policy")
                return {"status": "WAITING_FOR_APPROVAL", "job_id": job.id}
            tool_evidence, tool_logs, tool_outputs = _execute_bound_tools(db, job, plan, objective, provider)
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


@activity.defn(name="execute_external_extraction")
async def execute_external_extraction(extraction_id: str, actor_id: str | None = None) -> dict:
    return await asyncio.to_thread(run_external_extraction_now, extraction_id, actor_id)


@activity.defn(name="execute_metadata_scan")
async def execute_metadata_scan_activity(connector_id: str, job_id: str, actor_id: str) -> dict:
    return await asyncio.to_thread(execute_metadata_scan, connector_id, job_id, actor_id)
