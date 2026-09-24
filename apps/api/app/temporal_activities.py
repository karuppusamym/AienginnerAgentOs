from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone

from sqlalchemy import select

from .connector_runtime import ConnectorRuntimeError, execute_connector_query
from .database import SessionLocal, engine
from .decision_router import assess_risk
from .extraction_runtime import run_external_extraction_now
from .grounding import grounding_context, grounding_prompt_text, summarize_tool_result
from .governance import record_governance_event
from .model_runtime import generate_text
from .models import AgentDefinition, AgentVersion, Approval, Connector, DataAsset, IngestedFile, IngestionMapping, IngestionSchedule, Job, ModelCallLog, QueryTool, QualityRule, ToolDefinition, ToolVersion, User
from .metadata_scan_runtime import execute_metadata_scan
from .provider_selection import selected_model_provider
from .request_context import active_project_id
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

        def in_activity(self) -> bool:
            return False

        def heartbeat(self, *details) -> None:
            return None

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

# Per-run limits advertised to approvers ("5 agents / 12 tool calls").
AGENT_TOOL_CALL_BUDGET = 12
MAX_PLAN_STEPS = 12
MAX_REVIEW_ITERATIONS = 2

# Built-in handlers that only read governed metadata or draft SQL text. Used
# by autonomy level 1 ("read-only tools only"); query tools are separately
# allowed because they are read-only, row/time-bounded by construction.
READ_ONLY_BUILTIN_HANDLERS = frozenset(
    {"catalog.search", "dataset.profile", "sql.generate", "job.inspect", "lineage.query", "file.profile"}
)
_WRITE_TOOL_CATEGORIES = frozenset({"execution", "automation"})


def _is_read_only_builtin(tool: ToolDefinition, tool_version: ToolVersion) -> bool:
    return (
        tool_version.implementation_type == "builtin"
        and tool_version.handler_name in READ_ONLY_BUILTIN_HANDLERS
        and (tool.category or "").lower() not in _WRITE_TOOL_CATEGORIES
        and tool.risk_level == "low"
        and not tool.requires_approval
    )


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


def _reflect_on_tool_error(db, provider, tool_name, schema, objective, parameters, error_msg, project_id, job):
    if provider is None or provider.provider_type == "local_mock":
        return None
    schema_text = json.dumps({"required": schema.get("required", []), "properties": schema.get("properties", {})}, default=str)
    try:
        generated = generate_text(
            provider,
            "You are an agent recovering from a tool execution failure. Return strict JSON only: a single object whose keys are exactly the required parameter names. Provide corrected parameters to fix the error.",
            f"Tool: {tool_name}\nParameter schema: {schema_text}\nObjective: {objective[:500]}\nPrevious Parameters: {json.dumps(parameters, default=str)}\nError Encountered: {error_msg[:1000]}",
            300,
            governance_feature="agent_tool_reflection",
            governance_business_id=project_id,
            governance_session_id=job.id,
            governance_user_id=job.created_by,
        )
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", generated.content.strip(), flags=re.I)
        new_params = json.loads(content)
        if not isinstance(new_params, dict) or not new_params:
            return None
        validate_parameters(schema, new_params)
        for name, value in new_params.items():
            model = _ID_LOOKUP_MODELS.get(name)
            if model:
                row = db.get(model, str(value)) if isinstance(value, str) else None
                if not row or getattr(row, "project_id", None) != project_id:
                    return None
        return new_params
    except Exception:
        return None

def _review_plan_outputs(provider, objective, plan, outputs, enabled_agent_names, project_id, job):
    if provider is None or provider.provider_type == "local_mock":
        return []
    try:
        generated = generate_text(
            provider,
            f"You are the Reviewer agent for a data engineering product. Configured agents are {', '.join(sorted(enabled_agent_names))}. Review the outputs of the executed steps against the original objective. Is the objective fully met? If yes, return an empty array []. If no, propose up to 2 new steps to append to the plan to solve the objective. Return strict JSON only: an array of objects with 'agent' and 'action' string fields.",
            f"Objective: {objective}\nPlan so far:\n{json.dumps(plan, default=str)}\nOutputs from latest steps:\n{json.dumps(outputs[-3:], default=str)}",
            400,
            governance_feature="agent_plan_review",
            governance_business_id=project_id,
            governance_session_id=job.id,
            governance_user_id=job.created_by,
        )
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", generated.content.strip(), flags=re.I)
        new_steps = json.loads(content)
        if not isinstance(new_steps, list):
            return []
        valid_steps = []
        for step in new_steps:
            agent = str(step.get("agent", ""))
            action = str(step.get("action", ""))
            if agent in enabled_agent_names and action:
                valid_steps.append({"agent": agent, "action": action[:500], "status": "complete"})
        return valid_steps[:2]
    except Exception:
        return []


def _plan_requires_deterministic_approval(plan: list[dict]) -> bool:
    return any(assess_risk(str(step.get("action", "")))["requires_approval"] for step in plan)


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


def _execute_bound_tools(
    db,
    job: Job,
    plan: list[dict],
    objective: str,
    provider=None,
    *,
    autonomy_level: int = 2,
    budget: dict | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
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

    `autonomy_level` narrows (never widens) what may run: 0 executes nothing,
    1 allows only read-only built-in handlers plus published query tools, and
    2/3 allow any low-risk, non-approval built-in tool (the historical
    behaviour). `budget` is a shared {"remaining": n} counter so the per-run
    tool-call limit holds across per-step invocations; it is decremented in
    place.
    """
    evidence: list[dict] = []
    logs: list[dict] = []
    outputs: list[dict] = []
    if autonomy_level <= 0:
        return evidence, logs, outputs
    if budget is None:
        budget = {"remaining": AGENT_TOOL_CALL_BUDGET}
    calls_remaining = int(budget.get("remaining", AGENT_TOOL_CALL_BUDGET))
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
            if autonomy_level == 1 and not _is_read_only_builtin(tool, tool_version):
                logs.append({"at": datetime.now(timezone.utc).isoformat(), "level": "info", "message": f"{agent.name} skipped {tool.name}: autonomy level 1 allows read-only tools only"})
                continue
            parameter_source = "heuristic"
            parameters = _parameters_for_tool(tool_version.parameter_schema, objective, db, job.project_id)
            if parameters is None:
                parameters = _llm_parameters_for_tool(db, provider, tool_version.parameter_schema, objective, job.project_id, tool.name, job)
                parameter_source = "model"
            if parameters is None:
                continue
            calls_remaining -= 1
            for attempt_idx in range(3):
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
                    break
                except ToolRuntimeError as exc:
                    if attempt_idx < 2:
                        logs.append({"at": datetime.now(timezone.utc).isoformat(), "level": "warning", "message": f"{agent.name} encountered error with {tool.name}, attempting reflection..."})
                        outputs.append({
                            "type": "tool_reflection",
                            "agent": agent.name,
                            "tool": tool.name,
                            "title": f"Reflection triggered for {tool.name}",
                            "summary": "Repairing parameters...",
                            "data": {"error": str(exc)[:500]},
                            "at": datetime.now(timezone.utc).isoformat(),
                        })
                        new_params = _reflect_on_tool_error(db, provider, tool.name, tool_version.parameter_schema, objective, parameters, str(exc), job.project_id, job)
                        if new_params:
                            parameters = new_params
                            parameter_source = "reflection"
                            continue
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
                    break
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
            for attempt_idx in range(3):
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
                    break
                except (ToolRuntimeError, ConnectorRuntimeError, ValueError) as exc:
                    if attempt_idx < 2:
                        logs.append({"at": datetime.now(timezone.utc).isoformat(), "level": "warning", "message": f"{agent.name} encountered error with {query_tool.name}, attempting reflection..."})
                        outputs.append({
                            "type": "tool_reflection",
                            "agent": agent.name,
                            "tool": query_tool.name,
                            "title": f"Reflection triggered for {query_tool.name}",
                            "summary": "Repairing parameters...",
                            "data": {"error": str(exc)[:500]},
                            "at": datetime.now(timezone.utc).isoformat(),
                        })
                        new_params = _reflect_on_tool_error(db, provider, query_tool.name, query_tool.parameter_schema, objective, parameters, str(exc), job.project_id, job)
                        if new_params:
                            parameters = new_params
                            parameter_source = "reflection"
                            continue
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
                    break
    budget["remaining"] = calls_remaining
    return evidence, logs, outputs


# ---------------------------------------------------------------------------
# Agent run runtime: plan -> (approval hold) -> per-step execution -> review
# -> finalize.
#
# Every phase is a plain synchronous function with its own short DB session so
# the exact same code runs in the Temporal worker (one activity per phase,
# see temporal_workflows.AgentRunWorkflow) and in the local fallback
# (run_agent_plan_locally). Durable state lives on the Job row only -- no
# schema changes:
#
# * job.plan        -- the frozen plan. Each step carries step_index, origin
#                      ("planner" | "reviewer"), status ("pending" | "complete"
#                      | "skipped" | "planned") and, once finished, its
#                      idempotency_key (f"{job_id}:{step_index}").
# * job.evidence    -- the first entry flagged "agent_runtime" holds run
#                      metadata: autonomy_level, full objective, plan_hash,
#                      plan_bound, approval_id, tool_calls_used, ...
# * approval.evidence (action_type "agent_execution") -- the exact plan the
#                      human saw plus plan_hash and plan_bound.
#
# After approval the worker executes approval.evidence["plan"] verbatim after
# re-verifying its hash; it never re-plans.
# ---------------------------------------------------------------------------

FALLBACK_PLAN: tuple[dict, ...] = (
    {"agent": "Planner", "action": "Decompose objective and set limits"},
    {"agent": "Metadata", "action": "Retrieve catalog and vector context"},
    {"agent": "SQL Analyst", "action": "Draft a dialect-aware read-only query"},
    {"agent": "Analytics", "action": "Explain approved metrics and result shape"},
    {"agent": "Quality", "action": "Validate assumptions and evidence"},
    {"agent": "Policy", "action": "Confirm policy and execution limits"},
)
DEFAULT_GUARDRAILS = ["local execution only", "no destructive SQL", "full audit trace"]
_TERMINAL_JOB_STATUSES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "PARTIALLY_SUCCEEDED"})
_DONE_STEP_STATUSES = frozenset({"complete", "skipped"})
_TOOL_OUTPUT_TYPES = frozenset({"tool_result", "query_tool_result", "tool_error"})
SKIPPED_REQUIRES_APPROVAL = "skipped: requires approval"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(level: str, message: str) -> dict:
    return {"at": _now(), "level": level, "message": message}


def canonical_plan(plan: list[dict] | tuple[dict, ...]) -> list[dict]:
    """The part of a plan an approval binds to: ordered (agent, action) pairs."""
    return [{"agent": str(step.get("agent", "")), "action": str(step.get("action", ""))} for step in plan]


def compute_plan_hash(objective: str, plan: list[dict] | tuple[dict, ...]) -> str:
    """sha256 over canonical JSON of {objective, steps[(agent, action)]}."""
    payload = json.dumps(
        {"objective": str(objective or ""), "steps": canonical_plan(plan)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def step_idempotency_key(job_id: str, step_index: int) -> str:
    return f"{job_id}:{int(step_index)}"


def _freeze_plan(plan: list[dict] | tuple[dict, ...], origin: str = "planner") -> list[dict]:
    return [
        {**step, "status": "pending", "step_index": index, "origin": origin}
        for index, step in enumerate(canonical_plan(plan))
    ]


def _approved_steps(plan: list[dict]) -> list[dict]:
    """Steps covered by the plan hash (everything the planner/approver produced)."""
    return [step for step in plan if step.get("origin", "planner") != "reviewer"]


def agent_runtime_evidence(autonomy_level: int, objective: str) -> dict:
    """Evidence entry that carries run metadata the worker reads back.

    It doubles as the human-readable "Autonomy level N" policy evidence the UI
    already showed, so no schema change is required."""
    level = max(0, min(3, int(autonomy_level)))
    return {
        "type": "policy",
        "label": f"Autonomy level {level}",
        "agent_runtime": True,
        "autonomy_level": level,
        "objective": objective,
    }


def _runtime(job: Job) -> dict:
    for entry in job.evidence or []:
        if isinstance(entry, dict) and entry.get("agent_runtime"):
            return dict(entry)
    return {}


def job_autonomy_level(job: Job) -> int:
    """Autonomy level persisted on the job (default 2 = historical behaviour)."""
    runtime = _runtime(job)
    if isinstance(runtime.get("autonomy_level"), int):
        return max(0, min(3, runtime["autonomy_level"]))
    for entry in job.evidence or []:
        match = re.fullmatch(r"Autonomy level ([0-3])", str((entry or {}).get("label", "")))
        if match:
            return int(match.group(1))
    return 2


def _set_runtime(job: Job, **updates) -> dict:
    evidence = [dict(entry) if isinstance(entry, dict) else entry for entry in (job.evidence or [])]
    for index, entry in enumerate(evidence):
        if isinstance(entry, dict) and entry.get("agent_runtime"):
            entry.update(updates)
            evidence[index] = entry
            job.evidence = evidence
            return entry
    entry = {**agent_runtime_evidence(job_autonomy_level(job), updates.get("objective") or job.title), **updates}
    job.evidence = [entry, *evidence]
    return entry


def _grounding_evidence(runtime: dict) -> list[dict]:
    counts = runtime.get("grounding") or {}
    if not counts:
        return []
    return [
        {"type": "catalog", "label": f"{counts.get('catalog_matches', 0)} grounded catalog matches retrieved"},
        {"type": "vector", "label": f"{counts.get('vector_hits', 0)} vector hits retrieved"},
        {"type": "semantic", "label": f"{counts.get('semantic_matches', 0)} semantic metrics evaluated"},
    ]


def _enabled_agent_names(db) -> set[str]:
    names = set(db.scalars(select(AgentDefinition.name).where(AgentDefinition.enabled.is_(True))).all())
    names.update({"Planner", "Policy"})
    return names


def _job_provider(db, job: Job, purpose: str | None = None):
    """Resolve the model for this job's project (not the user's currently selected one)."""
    token = active_project_id.set(job.project_id)
    try:
        user = db.get(User, job.created_by)
        if purpose:
            try:
                return selected_model_provider(db, user, purpose)
            except Exception:
                pass  # routed model unavailable: fall back to the project/default chain
        return selected_model_provider(db, user)
    finally:
        active_project_id.reset(token)


def _plan_for_job(db, job: Job, objective: str) -> dict:
    """Ground the objective and produce a bounded plan (model or deterministic)."""
    plan = [dict(step) for step in FALLBACK_PLAN]
    model_log = None
    source = "deterministic"
    trace_outputs: list[dict] = []
    grounding = grounding_context(db, job.project_id, objective, limit=5)
    trace_outputs.append(
        {
            "type": "grounding",
            "agent": "Metadata",
            "title": "Retrieved grounding context",
            "summary": f"{len(grounding['catalog_matches'])} catalog matches, {len(grounding['semantic_matches'])} semantic metrics, {len(grounding['join_matches'])} approved joins",
            "data": grounding,
            "at": _now(),
        }
    )
    logs = [_log("info", f"Retrieved {len(grounding['catalog_matches'])} catalog matches and {len(grounding['semantic_matches'])} semantic metrics")]
    enabled_agent_names = _enabled_agent_names(db)
    provider = _job_provider(db, job, "agent_planning")
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
            candidate = []
            for step in parsed:
                agent = str(step.get("agent", ""))
                action = str(step.get("action", ""))
                if agent not in enabled_agent_names or not action:
                    raise ValueError("Planner output used an unsupported agent or empty action")
                candidate.append({"agent": agent, "action": action[:500]})
            plan = candidate
            source = "model"
            model_log = _log("info", f"Plan generated by {provider.name} / {provider.default_model}")
            trace_outputs.append(
                {
                    "type": "plan",
                    "agent": "Planner",
                    "title": "Generated specialist plan",
                    "summary": f"{len(plan)} steps generated by {provider.name}",
                    "data": plan,
                    "at": _now(),
                }
            )
            db.add(ModelCallLog(project_id=job.project_id, provider_id=provider.id, model=provider.default_model, purpose="agent_planning", status="healthy", latency_ms=generated.latency_ms, created_by=job.created_by))
        except Exception as exc:
            model_log = _log("warning", f"Model planning fell back to the deterministic policy plan: {str(exc)[:240]}")
            db.add(ModelCallLog(project_id=job.project_id, provider_id=provider.id, model=provider.default_model, purpose="agent_planning", status="failed", error=str(exc)[:1000], created_by=job.created_by))
    if source != "model":
        trace_outputs.append(
            {
                "type": "plan",
                "agent": "Planner",
                "title": "Deterministic specialist plan",
                "summary": f"{len(plan)} bounded steps",
                "data": plan,
                "at": _now(),
            }
        )
    if model_log:
        logs.append(model_log)
    return {
        "plan": plan,
        "trace_outputs": trace_outputs,
        "logs": logs,
        "source": source,
        "planning_fallback": bool(model_log and model_log.get("level") == "warning"),
        "grounding": {
            "catalog_matches": len(grounding["catalog_matches"]),
            "vector_hits": len(grounding["vector_hits"]),
            "semantic_matches": len(grounding["semantic_matches"]),
        },
    }


def _agent_approval(db, job_id: str, status: str) -> Approval | None:
    return db.scalar(
        select(Approval)
        .where(Approval.job_id == job_id, Approval.action_type == "agent_execution", Approval.status == status)
        .order_by(Approval.created_at.desc())
        .limit(1)
    )


def _latest_bound_approval(db, job_id: str) -> Approval | None:
    approvals = db.scalars(
        select(Approval)
        .where(Approval.job_id == job_id, Approval.action_type == "agent_execution", Approval.status == "approved")
        .order_by(Approval.created_at.desc())
    ).all()
    return next((item for item in approvals if (item.evidence or {}).get("plan_bound")), None)


def _mark_failed(db, job: Job, message: str, **governance) -> dict:
    job.status = "FAILED"
    job.progress = 100
    job.logs = [*(job.logs or []), _log("error", message[:1000])]
    db.commit()
    record_governance_event(
        "agent_run", "agent_plan", "failed",
        project_id=job.project_id, user_id=job.created_by, session_id=job.id, **governance,
    )
    return {"job_id": job.id, "status": "FAILED", "reason": message[:1000]}


def hold_agent_run_for_approval(
    job_id: str,
    objective: str,
    risk: dict | None = None,
    guardrails: list[str] | None = None,
) -> dict:
    """Objective-level hold used by POST /agents/runs.

    Generates the plan *before* the approval is created (model planner, or the
    deterministic fallback plan for local_mock/unavailable providers) so the
    approver sees -- and the approval binds to -- a concrete plan. If planning
    itself crashes, the hold is still created with plan_bound=False and the
    worker binds a plan at a plan-level hold after this approval instead.
    """
    risk = risk or assess_risk(objective)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} does not exist")
        existing = _agent_approval(db, job_id, "pending")
        if existing is not None:
            return {
                "approval_id": existing.id,
                "plan_bound": bool((existing.evidence or {}).get("plan_bound")),
                "plan_hash": (existing.evidence or {}).get("plan_hash"),
            }
        planned = None
        planning_error = None
        try:
            planned = _plan_for_job(db, job, objective)
        except Exception as exc:  # grounding/DB failure: fall back to an unbound hold
            db.rollback()
            job = db.get(Job, job_id)
            planning_error = str(exc)[:300]
        evidence = {
            "objective": objective,
            "risk_triggers": risk.get("triggers", []),
            "guardrails": guardrails or list(DEFAULT_GUARDRAILS),
            "hold": "objective",
            "autonomy_level": job_autonomy_level(job),
            "plan_bound": planned is not None,
        }
        plan_hash = None
        if planned is not None:
            frozen = _freeze_plan(planned["plan"])
            plan_hash = compute_plan_hash(objective, frozen)
            evidence.update(plan=canonical_plan(frozen), plan_hash=plan_hash, planner=planned["source"])
            job.plan = frozen
            job.outputs = planned["trace_outputs"]
            job.logs = [*(job.logs or []), *planned["logs"]]
            _set_runtime(
                job,
                objective=objective,
                plan_hash=plan_hash,
                plan_bound=True,
                grounding=planned["grounding"],
                planning_fallback=planned["planning_fallback"],
                prepared_job_id=None,
            )
        else:
            evidence["plan_binding_note"] = f"Planning failed before approval ({planning_error}); the plan will be bound at a plan-level hold after this approval."
            _set_runtime(job, objective=objective, plan_bound=False, prepared_job_id=None)
        approval = Approval(
            project_id=job.project_id,
            job_id=job.id,
            title=f"Approve controlled action: {objective[:120]}",
            action_type="agent_execution",
            risk_level=risk.get("level", "high"),
            requested_by=job.created_by,
            evidence=evidence,
        )
        db.add(approval)
        db.flush()
        _set_runtime(job, approval_id=approval.id)
        job.status = "WAITING_FOR_APPROVAL"
        job.progress = 10
        job.logs = [
            *(job.logs or []),
            _log(
                "warning",
                f"Held for human approval of plan {plan_hash[:12]} ({len(evidence.get('plan', []))} steps)"
                if plan_hash
                else "Held for human approval of the objective; plan will be bound after approval",
            ),
        ]
        db.commit()
        return {"approval_id": approval.id, "plan_bound": planned is not None, "plan_hash": plan_hash}


def _prepare_agent_run(job_id: str, objective: str) -> dict:
    """Phase 1: load the frozen approved plan, or plan (and hold if risky)."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} does not exist")
        if job.status in _TERMINAL_JOB_STATUSES:
            return {"job_id": job_id, "status": job.status}
        pending_approval = _agent_approval(db, job_id, "pending")
        if pending_approval is not None:
            job.status = "WAITING_FOR_APPROVAL"
            db.commit()
            return {"job_id": job_id, "status": "WAITING_FOR_APPROVAL", "approval_id": pending_approval.id}
        runtime = _runtime(job)
        autonomy = job_autonomy_level(job)
        bound = _latest_bound_approval(db, job_id)

        if bound is not None:
            evidence = bound.evidence or {}
            approved_plan = canonical_plan(evidence.get("plan") or [])
            expected = str(evidence.get("plan_hash") or "")
            approved_objective = str(evidence.get("objective") or "")
            problems = []
            if not approved_plan:
                problems.append("the approval carries no plan")
            if not expected or compute_plan_hash(approved_objective, approved_plan) != expected:
                problems.append("the approved plan does not match its recorded plan_hash")
            if runtime.get("plan_hash") and runtime.get("plan_hash") != expected:
                problems.append("the job's bound plan_hash differs from the approval's")
            if approved_objective != objective:
                problems.append("the requested objective differs from the approved objective")
            if problems:
                return _mark_failed(
                    db, job,
                    f"Approved plan integrity check failed ({'; '.join(problems)}). Nothing was executed; request a new approval.",
                    feature="agent_plan_binding", approval_id=bound.id,
                )
            already_prepared = (
                runtime.get("prepared_job_id") == job.id
                and runtime.get("approval_id") == bound.id
                and canonical_plan(_approved_steps(job.plan or [])) == approved_plan
            )
            if not already_prepared:
                job.plan = _freeze_plan(approved_plan)
                job.evidence = [
                    entry for entry in (job.evidence or [])
                    if isinstance(entry, dict) and (entry.get("agent_runtime") or entry.get("type") == "retry")
                ]
                job.evidence = [*(job.evidence or []), *_grounding_evidence(runtime)]
            job.status = "RUNNING"
            job.progress = max(job.progress or 0, 30)
            _set_runtime(job, objective=approved_objective, plan_hash=expected, plan_bound=True, approval_id=bound.id, prepared_job_id=job.id)
            job.logs = [
                *(job.logs or []),
                _log("info", f"Agent worker executing approved plan {expected[:12]} (approval {bound.id[:8]}) verbatim; no re-planning"),
            ]
            db.commit()
            record_governance_event("worker_job", "agent_plan", "started", project_id=job.project_id, user_id=job.created_by, session_id=job.id)
            return _ready(job, autonomy)

        # A Temporal retry of this activity after it already committed a plan
        # for this job must not call the planner (and log a model call) again.
        if runtime.get("prepared_job_id") == job.id and runtime.get("plan_hash") and job.status == "RUNNING":
            return _ready(job, autonomy)

        job.status = "RUNNING"
        job.progress = 30
        job.logs = [*(job.logs or []), _log("info", "Agent worker accepted the run")]
        db.commit()
        record_governance_event("worker_job", "agent_plan", "started", project_id=job.project_id, user_id=job.created_by, session_id=job.id)

        planned = _plan_for_job(db, job, objective)
        frozen = _freeze_plan(planned["plan"])
        plan_hash = compute_plan_hash(objective, frozen)
        job.plan = frozen
        job.outputs = planned["trace_outputs"]
        job.logs = [*(job.logs or []), *planned["logs"]]

        objective_approved = _agent_approval(db, job_id, "approved") is not None
        objective_risk = assess_risk(objective)
        needs_hold = autonomy > 0 and (
            _plan_requires_deterministic_approval(frozen)
            or (objective_risk["requires_approval"] and not objective_approved)
        )
        if needs_hold:
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
                    "reason": "The generated plan contains an approval-bound action." if _plan_requires_deterministic_approval(frozen) else "The objective requires approval.",
                    "hold": "plan",
                    "autonomy_level": autonomy,
                    "plan": canonical_plan(frozen),
                    "plan_hash": plan_hash,
                    "plan_bound": True,
                    "planner": planned["source"],
                    "risk_triggers": sorted({t for step in frozen for t in assess_risk(step["action"])["triggers"]} | set(objective_risk["triggers"])),
                },
            )
            db.add(approval)
            db.flush()
            job.evidence = [
                entry for entry in (job.evidence or [])
                if isinstance(entry, dict) and (entry.get("agent_runtime") or entry.get("type") == "retry")
            ]
            _set_runtime(
                job, objective=objective, plan_hash=plan_hash, plan_bound=True, approval_id=approval.id,
                grounding=planned["grounding"], planning_fallback=planned["planning_fallback"], prepared_job_id=None,
            )
            job.evidence = [*job.evidence, {"type": "policy", "label": "Deterministic policy approval required", "agent": "Policy"}]
            job.status = "WAITING_FOR_APPROVAL"
            job.progress = 30
            job.logs = [*job.logs, _log("warning", f"Deterministic policy held plan {plan_hash[:12]} for human approval")]
            db.commit()
            record_governance_event("agent_run", "deterministic_policy", "approval_required", project_id=job.project_id, user_id=job.created_by, session_id=job.id, feature="agent_policy")
            return {"job_id": job_id, "status": "WAITING_FOR_APPROVAL", "approval_id": approval.id, "plan_hash": plan_hash}

        job.evidence = [
            entry for entry in (job.evidence or [])
            if isinstance(entry, dict) and (entry.get("agent_runtime") or entry.get("type") == "retry")
        ]
        runtime = _set_runtime(
            job, objective=objective, plan_hash=plan_hash, plan_bound=False,
            grounding=planned["grounding"], planning_fallback=planned["planning_fallback"],
            prepared_job_id=job.id, tool_calls_used=0, review_iterations=0,
        )
        job.evidence = [*job.evidence, *_grounding_evidence(runtime)]
        db.commit()
        return _ready(job, autonomy)


def _ready(job: Job, autonomy: int) -> dict:
    runtime = _runtime(job)
    return {
        "job_id": job.id,
        "status": "READY",
        "autonomy_level": autonomy,
        "plan_hash": runtime.get("plan_hash"),
        "pending_steps": [index for index, step in enumerate(job.plan or []) if step.get("status") not in _DONE_STEP_STATUSES],
    }


def _execute_agent_step(job_id: str, step_index: int) -> dict:
    """Phase 2: execute exactly one plan step. Idempotent per job_id+step_index."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} does not exist")
        if job.status in _TERMINAL_JOB_STATUSES or job.status == "WAITING_FOR_APPROVAL":
            return {"job_id": job_id, "step_index": step_index, "status": job.status}
        plan = [dict(step) for step in (job.plan or [])]
        if not 0 <= step_index < len(plan):
            raise ValueError(f"Job {job_id} has no plan step {step_index}")
        step = plan[step_index]
        key = step_idempotency_key(job_id, step_index)
        if step.get("idempotency_key") == key and step.get("status") in _DONE_STEP_STATUSES:
            return {"job_id": job_id, "step_index": step_index, "status": "ALREADY_COMPLETED", "idempotency_key": key}
        runtime = _runtime(job)
        objective = str(runtime.get("objective") or job.title)
        expected = runtime.get("plan_hash")
        if expected and compute_plan_hash(objective, _approved_steps(plan)) != expected:
            return _mark_failed(
                db, job,
                f"Plan integrity check failed before step {step_index + 1}: the plan no longer matches hash {str(expected)[:12]}. Step not executed.",
                feature="agent_plan_binding",
            )
        autonomy = job_autonomy_level(job)
        evidence: list[dict] = []
        logs: list[dict] = []
        outputs: list[dict] = []
        tool_calls = 0
        risk = assess_risk(str(step.get("action", "")))
        if autonomy <= 0:
            step.update(status="skipped", skip_reason="autonomy level 0: plan only")
        elif step.get("origin") == "reviewer" and risk["requires_approval"]:
            step.update(status="skipped", skip_reason=SKIPPED_REQUIRES_APPROVAL, risk_triggers=risk["triggers"])
            logs.append(_log("warning", f"Skipped reviewer step {step_index + 1} ({step.get('agent')}): {SKIPPED_REQUIRES_APPROVAL}"))
            outputs.append(_skipped_output(step, step_index, risk))
        else:
            budget = {"remaining": max(0, AGENT_TOOL_CALL_BUDGET - int(runtime.get("tool_calls_used") or 0))}
            before = budget["remaining"]
            evidence, logs, outputs = _execute_bound_tools(
                db, job, [step], objective, _job_provider(db, job, "tool_parameters"), autonomy_level=autonomy, budget=budget,
            )
            tool_calls = before - budget["remaining"]
            step["status"] = "complete"
        for item in (*evidence, *outputs):
            item["step_index"] = step_index
        step.update(idempotency_key=key, completed_at=_now())
        plan[step_index] = step
        job.plan = plan
        job.outputs = [*(job.outputs or []), *outputs]
        job.logs = [*(job.logs or []), *logs]
        job.evidence = [*(job.evidence or []), *evidence]
        _set_runtime(job, tool_calls_used=int(runtime.get("tool_calls_used") or 0) + tool_calls)
        done = sum(1 for item in plan if item.get("status") in _DONE_STEP_STATUSES)
        job.progress = min(90, 30 + int(60 * done / max(1, len(plan))))
        db.commit()
        return {
            "job_id": job_id,
            "step_index": step_index,
            "status": "SKIPPED" if step["status"] == "skipped" else "COMPLETED",
            "tool_calls": tool_calls,
            "idempotency_key": key,
        }


def _skipped_output(step: dict, step_index: int, risk: dict) -> dict:
    return {
        "type": "step_skipped",
        "agent": step.get("agent"),
        "title": f"Skipped step {step_index + 1}: {str(step.get('action', ''))[:120]}",
        "summary": SKIPPED_REQUIRES_APPROVAL,
        "data": {"action": step.get("action"), "risk_triggers": risk.get("triggers", []), "origin": step.get("origin")},
        "step_index": step_index,
        "at": _now(),
    }


def _review_agent_plan(job_id: str) -> dict:
    """Phase 3: optional Reviewer pass that may append (risk-checked) steps."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} does not exist")
        if job.status in _TERMINAL_JOB_STATUSES or job.status == "WAITING_FOR_APPROVAL":
            return {"job_id": job_id, "pending_steps": []}
        plan = [dict(step) for step in (job.plan or [])]
        pending = [index for index, step in enumerate(plan) if step.get("status") not in _DONE_STEP_STATUSES]
        if pending:  # retry after a committed review: hand back what it already added
            return {"job_id": job_id, "pending_steps": pending}
        runtime = _runtime(job)
        iterations = int(runtime.get("review_iterations") or 0)
        provider = _job_provider(db, job, "agent_review")
        if (
            job_autonomy_level(job) <= 0
            or provider is None
            or provider.provider_type == "local_mock"
            or len(plan) >= MAX_PLAN_STEPS
            or iterations >= MAX_REVIEW_ITERATIONS
        ):
            return {"job_id": job_id, "pending_steps": []}
        objective = str(runtime.get("objective") or job.title)
        tool_outputs = [item for item in (job.outputs or []) if item.get("type") in _TOOL_OUTPUT_TYPES]
        new_steps = _review_plan_outputs(
            provider, objective, canonical_plan(plan), tool_outputs, _enabled_agent_names(db), job.project_id, job,
        )
        _set_runtime(job, review_iterations=iterations + 1)
        if not new_steps:
            db.commit()
            return {"job_id": job_id, "pending_steps": []}
        added: list[int] = []
        outputs: list[dict] = []
        logs = [_log("info", f"Reviewer agent proposed {len(new_steps)} new step(s).")]
        for proposed in new_steps:
            index = len(plan)
            step = {"agent": proposed["agent"], "action": proposed["action"], "origin": "reviewer", "step_index": index}
            risk = assess_risk(step["action"])
            if risk["requires_approval"]:
                # Reviewer steps were never seen by an approver: never run them.
                step.update(
                    status="skipped", skip_reason=SKIPPED_REQUIRES_APPROVAL, risk_triggers=risk["triggers"],
                    idempotency_key=step_idempotency_key(job_id, index), completed_at=_now(),
                )
                outputs.append(_skipped_output(step, index, risk))
                logs.append(_log("warning", f"Skipped reviewer step {index + 1} ({step['agent']}): {SKIPPED_REQUIRES_APPROVAL} [{', '.join(risk['triggers'])}]"))
            else:
                step["status"] = "pending"
                added.append(index)
            plan.append(step)
        outputs.insert(0, {
            "type": "plan_review",
            "agent": "Reviewer",
            "title": "Agentic Plan-and-Solve Review",
            "summary": f"Appended {len(added)} new step(s); {len(new_steps) - len(added)} skipped as requiring approval",
            "data": new_steps,
            "at": _now(),
        })
        job.plan = plan
        job.outputs = [*(job.outputs or []), *outputs]
        job.logs = [*(job.logs or []), *logs]
        db.commit()
        return {"job_id": job_id, "pending_steps": added}


def _finalize_agent_run(job_id: str) -> dict:
    """Phase 4: compose final evidence and mark the job SUCCEEDED (idempotent)."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} does not exist")
        runtime = _runtime(job)
        objective = str(runtime.get("objective") or job.title)
        if job.status in _TERMINAL_JOB_STATUSES or job.status == "WAITING_FOR_APPROVAL":
            return {"job_id": job_id, "objective": objective, "status": job.status, "plan": job.plan}
        autonomy = job_autonomy_level(job)
        plan = [dict(step) for step in (job.plan or [])]
        if autonomy <= 0:
            plan = [{**step, "status": "planned"} if step.get("status") not in _DONE_STEP_STATUSES else step for step in plan]
        skipped_for_approval = [step for step in plan if step.get("skip_reason") == SKIPPED_REQUIRES_APPROVAL]
        step_evidence = [entry for entry in (job.evidence or []) if isinstance(entry, dict) and "step_index" in entry]
        header = [
            entry for entry in (job.evidence or [])
            if isinstance(entry, dict) and (entry.get("agent_runtime") or entry.get("type") == "retry")
        ]
        policy = (
            {"type": "policy", "label": "Autonomy level 0: plan only, no tools executed"}
            if autonomy <= 0
            else {"type": "policy", "label": "Read-only and bounded-run policies passed"}
        )
        if runtime.get("plan_hash"):
            policy_binding = {
                "type": "policy",
                "label": f"Executed plan {str(runtime['plan_hash'])[:12]}" + (" as approved" if runtime.get("plan_bound") else ""),
            }
        else:
            policy_binding = None
        job.evidence = [
            *header,
            *_grounding_evidence(runtime),
            policy,
            *([policy_binding] if policy_binding else []),
            *([{"type": "planning_fallback", "label": "Model planning failed — used deterministic fallback plan"}] if runtime.get("planning_fallback") else []),
            *([{"type": "policy", "label": f"{len(skipped_for_approval)} reviewer step(s) {SKIPPED_REQUIRES_APPROVAL}"}] if skipped_for_approval else []),
            *step_evidence,
        ]
        job.plan = plan
        if autonomy <= 0:
            job.outputs = [
                *(job.outputs or []),
                {
                    "type": "plan_only",
                    "agent": "Policy",
                    "title": "Plan only (autonomy level 0)",
                    "summary": f"{len(plan)} planned step(s); no tools were executed",
                    "data": canonical_plan(plan),
                    "at": _now(),
                },
            ]
        job.logs = [
            *(job.logs or []),
            _log("info", "Plan-only run completed; no tools executed (autonomy level 0)" if autonomy <= 0 else "Specialist plan completed"),
        ]
        job.status = "SUCCEEDED"
        job.progress = 100
        db.commit()
        record_governance_event(
            "agent_run", "agent_plan", "succeeded",
            project_id=job.project_id, user_id=job.created_by, session_id=job.id,
            plan_steps=len(plan), tool_calls=len(step_evidence), autonomy_level=autonomy,
        )
        return {"job_id": job_id, "objective": objective, "status": "SUCCEEDED", "plan": job.plan}


def _fail_agent_run(job_id: str, message: str) -> dict:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return {"job_id": job_id, "status": "MISSING"}
        if job.status in _TERMINAL_JOB_STATUSES:
            return {"job_id": job_id, "status": job.status}
        return _mark_failed(db, job, str(message or "Agent run failed"))


def run_agent_plan_locally(job_id: str, objective: str) -> dict:
    """Local (no-Temporal) runner: the same phase functions, run in-process."""
    try:
        prepared = _prepare_agent_run(job_id, objective)
        if prepared.get("status") != "READY":
            return {"job_id": job_id, "objective": objective, **prepared}
        if prepared.get("autonomy_level", 2) > 0:
            pending = list(prepared.get("pending_steps") or [])
            for _ in range(MAX_REVIEW_ITERATIONS + 1):
                for step_index in pending:
                    result = _execute_agent_step(job_id, step_index)
                    if result.get("status") in {"FAILED", "CANCELLED", "WAITING_FOR_APPROVAL"}:
                        return {"job_id": job_id, "objective": objective, **result}
                pending = list(_review_agent_plan(job_id).get("pending_steps") or [])
                if not pending:
                    break
        return _finalize_agent_run(job_id)
    except Exception as exc:
        _fail_agent_run(job_id, str(exc)[:500])
        raise


# Backwards-compatible name for callers of the former monolithic runner.
_execute_agent_plan = run_agent_plan_locally


async def _in_thread_with_heartbeat(func, *args, interval: float = 10.0):
    """Run blocking work in a thread while heartbeating the Temporal activity,
    so a stuck/lost worker is detected via heartbeat_timeout instead of the
    much longer start_to_close_timeout."""
    task = asyncio.ensure_future(asyncio.to_thread(func, *args))
    while True:
        done, _ = await asyncio.wait({task}, timeout=interval)
        if done:
            return task.result()
        try:
            if activity.in_activity():
                activity.heartbeat()
        except Exception:
            pass


@activity.defn(name="prepare_agent_run")
async def prepare_agent_run_activity(job_id: str, objective: str) -> dict:
    return await _in_thread_with_heartbeat(_prepare_agent_run, job_id, objective)


@activity.defn(name="execute_agent_step")
async def execute_agent_step_activity(job_id: str, step_index: int) -> dict:
    return await _in_thread_with_heartbeat(_execute_agent_step, job_id, step_index)


@activity.defn(name="review_agent_plan")
async def review_agent_plan_activity(job_id: str) -> dict:
    return await _in_thread_with_heartbeat(_review_agent_plan, job_id)


@activity.defn(name="finalize_agent_run")
async def finalize_agent_run_activity(job_id: str) -> dict:
    return await _in_thread_with_heartbeat(_finalize_agent_run, job_id)


@activity.defn(name="fail_agent_run")
async def fail_agent_run_activity(job_id: str, message: str) -> dict:
    return await asyncio.to_thread(_fail_agent_run, job_id, message)


@activity.defn(name="execute_agent_plan")
async def execute_agent_plan(job_id: str, objective: str) -> dict:
    """Legacy whole-plan activity, kept registered only so workflows started
    before the per-step AgentRunWorkflow existed can drain. It now runs the
    same idempotent phase functions, so a retry skips completed steps."""
    return await _in_thread_with_heartbeat(run_agent_plan_locally, job_id, objective)


@activity.defn(name="execute_scheduled_ingestion")
async def execute_scheduled_ingestion(schedule_id: str, actor_id: str | None = None) -> dict:
    return await asyncio.to_thread(run_ingestion_schedule, schedule_id, actor_id)


@activity.defn(name="execute_external_extraction")
async def execute_external_extraction(extraction_id: str, actor_id: str | None = None) -> dict:
    return await asyncio.to_thread(run_external_extraction_now, extraction_id, actor_id)


@activity.defn(name="execute_metadata_scan")
async def execute_metadata_scan_activity(connector_id: str, job_id: str, actor_id: str) -> dict:
    return await asyncio.to_thread(execute_metadata_scan, connector_id, job_id, actor_id)
