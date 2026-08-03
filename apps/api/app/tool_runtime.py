from __future__ import annotations

import os
import time
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import engine
from .grounding import project_asset_search, semantic_matches
from .governance import record_governance_event
from .models import DataAsset, Job, LineageEdge
from .staging import execute_read_only


class ToolRuntimeError(RuntimeError):
    pass


def validate_parameters(schema: dict[str, Any], parameters: dict[str, Any]) -> None:
    if schema.get("type", "object") != "object":
        raise ToolRuntimeError("Tool parameter schema must describe an object")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ToolRuntimeError("Tool parameter properties must be an object")
    missing = [name for name in schema.get("required", []) if name not in parameters]
    if missing:
        raise ToolRuntimeError(f"Missing required parameters: {', '.join(missing)}")
    extra = set(parameters) - set(properties)
    if extra and schema.get("additionalProperties", False) is not True:
        raise ToolRuntimeError(f"Unsupported parameters: {', '.join(sorted(extra))}")
    expected_types = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    for name, value in parameters.items():
        definition = properties.get(name, {})
        expected = expected_types.get(definition.get("type"))
        if expected and (not isinstance(value, expected) or isinstance(value, bool) and expected != bool):
            raise ToolRuntimeError(f"Parameter '{name}' must be {definition['type']}")
        if isinstance(value, str) and len(value) > int(definition.get("maxLength", 100_000)):
            raise ToolRuntimeError(f"Parameter '{name}' exceeds its maximum length")
        if isinstance(value, (int, float)):
            if "minimum" in definition and value < definition["minimum"]:
                raise ToolRuntimeError(f"Parameter '{name}' is below its minimum")
            if "maximum" in definition and value > definition["maximum"]:
                raise ToolRuntimeError(f"Parameter '{name}' exceeds its maximum")


def _catalog_search(db: Session, parameters: dict[str, Any], project_id: str) -> dict[str, Any]:
    query = str(parameters["query"]).strip()
    limit = int(parameters.get("limit", 10))
    matches = project_asset_search(db, project_id, query, limit=limit)
    semantic = semantic_matches(db, project_id, query, limit=min(limit, 5))
    return {
        "query": parameters["query"],
        "matches": matches,
        "semantic_matches": semantic["metrics"],
        "approved_joins": semantic["joins"],
        "count": len(matches),
    }


def _dataset_profile(db: Session, parameters: dict[str, Any], project_id: str) -> dict[str, Any]:
    asset = db.get(DataAsset, str(parameters["asset_id"]))
    if asset is None or asset.project_id != project_id:
        raise ToolRuntimeError("Dataset was not found")
    return {
        "id": asset.id,
        "relation": f"{asset.schema_name}.{asset.table_name}",
        "row_count": asset.row_count,
        "columns": asset.columns,
        "tags": asset.tags,
        "description": asset.description,
    }


def _sql_preview(db: Session, parameters: dict[str, Any], project_id: str) -> dict[str, Any]:
    return execute_read_only(engine, str(parameters["sql"]), int(parameters.get("limit", 100)))


def _job_inspect(db: Session, parameters: dict[str, Any], project_id: str) -> dict[str, Any]:
    job = db.get(Job, str(parameters["job_id"]))
    if job is None or job.project_id != project_id:
        raise ToolRuntimeError("Job was not found")
    return {
        "id": job.id,
        "title": job.title,
        "status": job.status,
        "progress": job.progress,
        "plan": job.plan,
        "evidence": job.evidence,
        "logs": job.logs,
        "outputs": job.outputs,
    }


def _lineage_query(db: Session, parameters: dict[str, Any], project_id: str) -> dict[str, Any]:
    relation = str(parameters["relation"]).lower()
    edges = db.scalars(
        select(LineageEdge).where(LineageEdge.project_id == project_id)
    ).all()
    matches = [
        {
            "id": edge.id,
            "source_relation": edge.source_relation,
            "target_relation": edge.target_relation,
            "transformation": edge.transformation,
            "column_mapping": edge.column_mapping,
        }
        for edge in edges
        if relation in edge.source_relation.lower() or relation in edge.target_relation.lower()
    ]
    return {"relation": parameters["relation"], "edges": matches}


BUILTIN_HANDLERS: dict[str, Callable[[Session, dict[str, Any], str], dict[str, Any]]] = {
    "catalog.search": _catalog_search,
    "dataset.profile": _dataset_profile,
    "sql.preview": _sql_preview,
    "job.inspect": _job_inspect,
    "lineage.query": _lineage_query,
}


def _execute_http(
    endpoint: str | None,
    method: str,
    parameters: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    if not endpoint:
        raise ToolRuntimeError("HTTP tools require an endpoint")
    parsed = urlparse(endpoint)
    allowlist = {
        host.strip().lower()
        for host in os.getenv("TOOL_HTTP_ALLOWLIST", "localhost,127.0.0.1").split(",")
        if host.strip()
    }
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in allowlist:
        raise ToolRuntimeError("Tool endpoint host is not in TOOL_HTTP_ALLOWLIST")
    with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
        response = client.request(method.upper(), endpoint, json=parameters)
        response.raise_for_status()
        if "application/json" in response.headers.get("content-type", ""):
            content: Any = response.json()
        else:
            content = response.text[:100_000]
    return {"status_code": response.status_code, "content": content}


def execute_tool(
    db: Session,
    implementation_type: str,
    handler_name: str,
    endpoint: str | None,
    http_method: str,
    parameter_schema: dict[str, Any],
    parameters: dict[str, Any],
    project_id: str,
    timeout_seconds: int,
    max_retries: int,
    retry_backoff_seconds: int,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    tenant_id: str | None = None,
    feature: str = "tool_execution",
) -> tuple[dict[str, Any], int, int]:
    started = time.perf_counter()
    attempts = 0
    last_error: Exception | None = None
    try:
        validate_parameters(parameter_schema, parameters)
        for attempt in range(max_retries + 1):
            attempts = attempt + 1
            try:
                if implementation_type == "builtin":
                    handler = BUILTIN_HANDLERS.get(handler_name)
                    if handler is None:
                        raise ToolRuntimeError(f"Unknown built-in handler: {handler_name}")
                    result = handler(db, parameters, project_id)
                elif implementation_type == "http":
                    result = _execute_http(endpoint, http_method, parameters, timeout_seconds)
                else:
                    raise ToolRuntimeError("Only built-in and allowlisted HTTP tools can execute")
                duration_ms = round((time.perf_counter() - started) * 1000)
                record_governance_event(
                    "tool_execution",
                    handler_name,
                    "succeeded",
                    project_id=project_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    session_id=session_id,
                    feature=feature,
                    implementation_type=implementation_type,
                    attempts=attempts,
                    duration_ms=duration_ms,
                )
                return result, attempts, duration_ms
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    time.sleep(min(retry_backoff_seconds * (2**attempt), 10))
        raise ToolRuntimeError(str(last_error or "Tool execution failed"))
    except Exception:
        record_governance_event(
            "tool_execution",
            handler_name,
            "failed",
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            feature=feature,
            implementation_type=implementation_type,
            attempts=attempts,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        raise
