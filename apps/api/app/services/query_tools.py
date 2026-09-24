"""Query-tool registry and external gateway: contract validation, discovery filters,
parameter checks, grants, rate-limited invocation and usage summaries."""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..connection_guard import ConnectionLimitExceeded
from ..connector_runtime import ConnectorRuntimeError, execute_connector_query
from ..database import engine
from ..governance import record_governance_event
from ..models import Connector, ExternalClient, ExternalInvocation, Project, QueryTool, QueryToolGrant
from ..rate_limit import check_rate_limit
from ..schemas import QueryToolCreate
from ..staging import execute_parameterized_read_only
from .audit import audit
from .authz import require_project_resource
from .sql_service import _safe_read_only_sql


def _validate_query_tool_contract(payload: QueryToolCreate, db: Session, project: Project) -> None:
    schema = payload.parameter_schema
    if schema.get("type") != "object" or not isinstance(schema.get("properties", {}), dict):
        raise HTTPException(status_code=400, detail="Parameter schema must be a JSON Schema object")
    placeholders = set(re.findall(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", payload.sql_template))
    properties = set(schema.get("properties", {}))
    if not placeholders.issubset(properties):
        raise HTTPException(status_code=400, detail="Every SQL parameter must be declared in parameter_schema")
    probe = re.sub(r"(?<!:):[A-Za-z_][A-Za-z0-9_]*", "NULL", payload.sql_template)
    if not _safe_read_only_sql(probe):
        raise HTTPException(status_code=400, detail="Query tools require one complete read-only SELECT statement")
    normalized_sql = re.sub(r'["`\[\]\s]', "", payload.sql_template.lower())
    normalized_relations = [re.sub(r'["`\[\]\s]', "", relation.lower()) for relation in payload.allowed_relations]
    if any(relation not in normalized_sql for relation in normalized_relations):
        raise HTTPException(status_code=400, detail="Every allowed relation must be referenced by the SQL template")
    if payload.connector_id:
        connector = require_project_resource(db.get(Connector, payload.connector_id), project, "Connector")
        if connector.connection_mode == "mcp" and not payload.upstream_tool_name:
            raise HTTPException(status_code=400, detail="MCP-backed query tools require upstream_tool_name")
        if connector.connection_mode != "mcp" and payload.upstream_tool_name:
            raise HTTPException(status_code=400, detail="upstream_tool_name is only valid for an MCP-backed connector")
    elif payload.upstream_tool_name:
        raise HTTPException(status_code=400, detail="upstream_tool_name requires an MCP-backed connector")


def _registry_metadata(tool: QueryTool) -> dict[str, Any]:
    return {
        "purpose": tool.purpose,
        "data_source": tool.data_source,
        "line_of_business": tool.line_of_business,
        "owner": tool.owner,
        "tags": tool.tags or [],
        "version": tool.version,
    }


def _external_query_tool_output(tool: QueryTool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        **_registry_metadata(tool),
        "input_schema": tool.parameter_schema,
        "result_schema": tool.result_schema,
        "annotations": {
            "read_only": True,
            "destructive": False,
            "row_limit": tool.row_limit,
            "timeout_seconds": tool.timeout_seconds,
        },
    }


def _filter_registry_tools(
    tools: list[QueryTool],
    q: str = "",
    data_source: str = "",
    line_of_business: str = "",
    tag: str = "",
) -> list[QueryTool]:
    query = q.strip().lower()
    source = data_source.strip().lower()
    lob = line_of_business.strip().lower()
    wanted_tag = tag.strip().lower()
    filtered: list[QueryTool] = []
    for tool in tools:
        searchable = " ".join(
            [tool.name, tool.description, tool.purpose, tool.data_source, tool.line_of_business, tool.owner]
            + list(tool.tags or [])
        ).lower()
        if query and query not in searchable:
            continue
        if source and source not in tool.data_source.lower():
            continue
        if lob and lob not in tool.line_of_business.lower():
            continue
        if wanted_tag and wanted_tag not in {item.lower() for item in tool.tags or []}:
            continue
        filtered.append(tool)
    return filtered


def _validate_tool_parameters(schema: dict[str, Any], parameters: dict[str, Any]) -> None:
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    missing = sorted(required - set(parameters))
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required parameters: {', '.join(missing)}")
    if schema.get("additionalProperties", True) is False:
        unknown = sorted(set(parameters) - set(properties))
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown parameters: {', '.join(unknown)}")
    expected_types = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    for name, value in parameters.items():
        declaration = properties.get(name, {})
        expected = expected_types.get(declaration.get("type"))
        if expected and (not isinstance(value, expected) or declaration.get("type") in {"integer", "number"} and isinstance(value, bool)):
            raise HTTPException(status_code=400, detail=f"Parameter {name} has the wrong type")
        if "enum" in declaration and value not in declaration["enum"]:
            raise HTTPException(status_code=400, detail=f"Parameter {name} is not an allowed value")


def _granted_query_tools(db: Session, client: ExternalClient) -> list[QueryTool]:
    return db.scalars(
        select(QueryTool)
        .join(QueryToolGrant, QueryToolGrant.query_tool_id == QueryTool.id)
        .where(
            QueryTool.project_id == client.default_project_id,
            QueryTool.status == "published",
            QueryToolGrant.external_client_id == client.id,
            QueryToolGrant.enabled.is_(True),
        )
        .order_by(QueryTool.name)
    ).all()


EXTERNAL_QUERY_TOOL_RATE_LIMIT_PER_MINUTE = int(os.getenv("EXTERNAL_QUERY_TOOL_RATE_LIMIT_PER_MINUTE", "60"))


def enforce_external_rate_limit(db: Session, client: ExternalClient, action: str, tool_name: str | None = None) -> None:
    """Per-client limit shared by discovery (list) and invocation.

    Without Redis the limiter uses an in-process sliding window (see
    app/rate_limit.py), so this never fails open.
    """
    rate = check_rate_limit(f"external_client:{client.id}", EXTERNAL_QUERY_TOOL_RATE_LIMIT_PER_MINUTE, 60)
    if rate.allowed:
        return
    details: dict[str, Any] = {"limit_per_minute": rate.limit, "action": action, "project_id": client.default_project_id}
    if tool_name:
        details["query_tool"] = tool_name
    audit(db, None, "external_query_tool.rate_limited", "external_client", client.id, details)
    db.commit()
    raise HTTPException(
        status_code=429,
        detail=f"Rate limit exceeded: {rate.limit} requests/minute for this client",
        headers={"Retry-After": str(rate.retry_after_seconds)},
    )


def _utc_day_start(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _enforce_daily_quota(db: Session, client: ExternalClient, tool: QueryTool, grant: QueryToolGrant) -> None:
    if grant.daily_quota is None:
        return
    day_start = _utc_day_start()
    used = db.scalar(
        select(func.count(ExternalInvocation.id)).where(
            ExternalInvocation.external_client_id == client.id,
            ExternalInvocation.query_tool_id == tool.id,
            ExternalInvocation.created_at >= day_start,
        )
    ) or 0
    if used < grant.daily_quota:
        return
    audit(
        db, None, "external_query_tool.quota_exceeded", "external_client", client.id,
        {"daily_quota": grant.daily_quota, "used": used, "query_tool": tool.name, "project_id": tool.project_id},
    )
    db.commit()
    seconds_to_midnight = max(1, int(86_400 - (datetime.now(timezone.utc) - day_start).total_seconds()))
    raise HTTPException(
        status_code=429,
        detail=f"Daily quota exceeded: {grant.daily_quota} invocations/day of {tool.name} for this client",
        headers={"Retry-After": str(seconds_to_midnight)},
    )


def _invoke_external_query_tool(
    db: Session,
    client: ExternalClient,
    tool: QueryTool,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    enforce_external_rate_limit(db, client, "invoke", tool.name)
    grant = db.scalar(
        select(QueryToolGrant).where(
            QueryToolGrant.query_tool_id == tool.id,
            QueryToolGrant.external_client_id == client.id,
            QueryToolGrant.enabled.is_(True),
        )
    )
    if tool.project_id != client.default_project_id or tool.status != "published" or grant is None:
        raise HTTPException(status_code=404, detail="Published query tool not found")
    if tool.requires_approval:
        raise HTTPException(status_code=409, detail="This tool requires an interactive portal approval")
    _validate_tool_parameters(tool.parameter_schema, parameters)
    _enforce_daily_quota(db, client, tool, grant)
    invocation = ExternalInvocation(
        project_id=tool.project_id,
        external_client_id=client.id,
        query_tool_id=tool.id,
        parameters=parameters,
    )
    db.add(invocation)
    db.flush()
    record_governance_event(
        "external_query_tool",
        tool.name,
        "started",
        project_id=tool.project_id,
        user_id=client.client_id,
        session_id=invocation.id,
        feature="external_query_tool",
        external_client_id=client.id,
        query_tool_id=tool.id,
        connector_id=tool.connector_id or "",
        row_limit=tool.row_limit,
    )
    started = time.perf_counter()
    try:
        if tool.connector_id:
            connector = db.get(Connector, tool.connector_id)
            if connector is None or connector.project_id != tool.project_id:
                raise ConnectorRuntimeError("The configured connector is unavailable")
            result = execute_connector_query(
                connector, tool.sql_template, parameters, tool.row_limit, tool.timeout_seconds,
                upstream_tool_name=tool.upstream_tool_name,
                user_id=client.client_id,
                session_id=invocation.id,
                feature="external_query_tool",
            )
        else:
            result = execute_parameterized_read_only(
                engine, tool.sql_template, parameters, tool.row_limit, tool.timeout_seconds
            )
        serializable = json.loads(json.dumps(result, default=str))
        invocation.status = "succeeded"
        invocation.duration_ms = round((time.perf_counter() - started) * 1000)
        invocation.result_metadata = {
            "columns": serializable["columns"],
            "row_count": serializable["row_count"],
            "truncated": serializable["truncated"],
        }
        db.commit()
        record_governance_event(
            "external_query_tool",
            tool.name,
            "succeeded",
            project_id=tool.project_id,
            user_id=client.client_id,
            session_id=invocation.id,
            feature="external_query_tool",
            external_client_id=client.id,
            query_tool_id=tool.id,
            duration_ms=invocation.duration_ms,
            row_count=serializable["row_count"],
            truncated=serializable["truncated"],
        )
        return {"invocation_id": invocation.id, "tool": tool.name, **serializable}
    except HTTPException as exc:
        invocation.status = "failed"
        invocation.duration_ms = round((time.perf_counter() - started) * 1000)
        invocation.error = str(exc.detail)[:2000]
        db.commit()
        record_governance_event(
            "external_query_tool",
            tool.name,
            "failed",
            project_id=tool.project_id,
            user_id=client.client_id,
            session_id=invocation.id,
            feature="external_query_tool",
            external_client_id=client.id,
            query_tool_id=tool.id,
            duration_ms=invocation.duration_ms,
            error_type=type(exc).__name__,
        )
        raise
    except ConnectionLimitExceeded as exc:
        invocation.status = "failed"
        invocation.duration_ms = round((time.perf_counter() - started) * 1000)
        invocation.error = str(exc)[:2000]
        db.commit()
        record_governance_event(
            "external_query_tool",
            tool.name,
            "failed",
            project_id=tool.project_id,
            user_id=client.client_id,
            session_id=invocation.id,
            feature="external_query_tool",
            external_client_id=client.id,
            query_tool_id=tool.id,
            duration_ms=invocation.duration_ms,
            error_type=type(exc).__name__,
        )
        # 503, not the generic 422 below: this is a transient capacity signal
        # (too many simultaneous connections to the source system right now),
        # not a malformed request -- a well-behaved client should retry.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        invocation.status = "failed"
        invocation.duration_ms = round((time.perf_counter() - started) * 1000)
        invocation.error = str(exc)[:2000]
        db.commit()
        record_governance_event(
            "external_query_tool",
            tool.name,
            "failed",
            project_id=tool.project_id,
            user_id=client.client_id,
            session_id=invocation.id,
            feature="external_query_tool",
            external_client_id=client.id,
            query_tool_id=tool.id,
            duration_ms=invocation.duration_ms,
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=422, detail=f"Query tool execution failed: {exc}") from exc


def query_tool_usage_summary(db: Session, tool: QueryTool) -> dict[str, Any]:
    invocations = db.scalars(
        select(ExternalInvocation)
        .where(ExternalInvocation.project_id == tool.project_id, ExternalInvocation.query_tool_id == tool.id)
        .order_by(ExternalInvocation.created_at.desc())
    ).all()
    succeeded = [item for item in invocations if item.status == "succeeded"]
    failed = [item for item in invocations if item.status == "failed"]
    durations = sorted(item.duration_ms for item in invocations if item.duration_ms is not None)
    midpoint = len(durations) // 2
    median_latency_ms = (
        round(sum(durations[midpoint - 1 : midpoint + 1]) / len(durations[midpoint - 1 : midpoint + 1]), 2)
        if durations
        else None
    )
    parameter_key_counts: dict[str, int] = {}
    client_counts: dict[str, int] = {}
    client_ids = {item.external_client_id for item in invocations}
    clients = {
        client.id: client.name
        for client in db.scalars(select(ExternalClient).where(ExternalClient.id.in_(client_ids))).all()
    } if client_ids else {}
    for invocation in invocations:
        client_name = clients.get(invocation.external_client_id, "Unknown client")
        client_counts[client_name] = client_counts.get(client_name, 0) + 1
        for key in (invocation.parameters or {}).keys():
            parameter_key_counts[str(key)] = parameter_key_counts.get(str(key), 0) + 1
    return {
        "invocation_count": len(invocations),
        "success_count": len(succeeded),
        "failure_count": len(failed),
        "success_rate": round(100 * len(succeeded) / len(invocations), 2) if invocations else None,
        "median_latency_ms": median_latency_ms,
        "rows_returned": sum(int((item.result_metadata or {}).get("row_count", 0) or 0) for item in succeeded),
        "last_invoked_at": invocations[0].created_at if invocations else None,
        "client_usage": [
            {"client": name, "invocations": count}
            for name, count in sorted(client_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "parameter_key_usage": [
            {"parameter": key, "invocations": count}
            for key, count in sorted(parameter_key_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "recent_errors": [
            {"at": item.created_at, "error": (item.error or "Execution failed")[:500]}
            for item in failed[:5]
        ],
    }
