from __future__ import annotations

import contextvars
import ipaddress
import json
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import engine
from .file_profiles import read_structured_rows
from .grounding import grounding_context, project_asset_search, semantic_matches
from .governance import record_governance_event
from .models import DataAsset, IngestedFile, IngestionMapping, IngestionSchedule, Job, LineageEdge, QualityRule, QualityRun
from .quality import execute_quality_rule
from .catalog_scope import queryable_asset_ids
from .schedule_runtime import run_ingestion_schedule
from .sql_guard import unknown_relations
from .sql_generation import generated_catalog_sql
from .staging import execute_parameterized_read_only, safe_identifier, stage_rows


class ToolRuntimeError(RuntimeError):
    pass


class ToolTimeoutError(ToolRuntimeError):
    """A built-in handler ran past its tool version's timeout_seconds (never retried)."""


# The running tool version's timeout, visible to handlers that can pass it down
# to the database (sql.preview sets it as the statement timeout).
_TOOL_TIMEOUT_SECONDS: contextvars.ContextVar[int | None] = contextvars.ContextVar("tool_timeout_seconds", default=None)
# After a timeout the worker is interrupted; give it this long to unwind before returning.
_TIMEOUT_GRACE_SECONDS = 2.0


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
        if "enum" in definition and value not in definition["enum"]:
            raise ToolRuntimeError(f"Parameter '{name}' must be one of: {', '.join(map(str, definition['enum']))}")
        if definition.get("type") == "array" and isinstance(value, list) and isinstance(definition.get("items"), dict):
            item_type = definition["items"].get("type")
            if item_type == "string" and any(not isinstance(item, str) for item in value):
                raise ToolRuntimeError(f"Parameter '{name}' must contain only strings")


def _catalog_search(db: Session, parameters: dict[str, Any], project_id: str, user_id: str | None = None) -> dict[str, Any]:
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


def _dataset_profile(db: Session, parameters: dict[str, Any], project_id: str, user_id: str | None = None) -> dict[str, Any]:
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


def _project_relations(db: Session, project_id: str) -> set[str]:
    """Lower-case "schema.table" names of the project's queryable catalogued assets."""
    assets = db.scalars(select(DataAsset).where(DataAsset.project_id == project_id)).all()
    allowed_ids = queryable_asset_ids(db, project_id, list(assets))
    return {f"{asset.schema_name}.{asset.table_name}".lower() for asset in assets if asset.id in allowed_ids}


def _sql_preview(db: Session, parameters: dict[str, Any], project_id: str, user_id: str | None = None) -> dict[str, Any]:
    sql = str(parameters["sql"])
    # Scope reads to the run's project: every relation must be a queryable
    # catalogued asset of this project (the same rule /sql/generate applies).
    # The read-only guards in execute_parameterized_read_only still run after.
    outside = unknown_relations(sql, "postgres", _project_relations(db, project_id))
    if outside:
        raise ToolRuntimeError(f"sql.preview can only read this project's catalogued datasets; not allowed: {', '.join(sorted(set(outside)))}")
    timeout = _TOOL_TIMEOUT_SECONDS.get() or 15
    try:
        return execute_parameterized_read_only(engine, sql, {}, int(parameters.get("limit", 100)), max(1, int(timeout)))
    except ValueError as exc:
        raise ToolRuntimeError(str(exc)) from exc


def _job_inspect(db: Session, parameters: dict[str, Any], project_id: str, user_id: str | None = None) -> dict[str, Any]:
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


def _lineage_query(db: Session, parameters: dict[str, Any], project_id: str, user_id: str | None = None) -> dict[str, Any]:
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


def _sql_generate(db: Session, parameters: dict[str, Any], project_id: str, user_id: str | None = None) -> dict[str, Any]:
    """Catalog-grounded, dialect-aware SQL drafting -- the same deterministic
    templating routers/sql.py falls back to when no model provider is
    configured, exposed as a bounded tool so the SQL Analyst agent can
    actually generate SQL instead of only searching/previewing it. Real
    (model-backed) generation still lives behind /sql/generate, which does
    caching, conversation context, and full audit trail that a bounded
    12-call agent step has no room for; this handler covers the grounded,
    deterministic case so the agent has a genuine draft to hand back."""
    question = str(parameters["query"]).strip()
    if not question:
        raise ToolRuntimeError("A non-empty question is required")
    dialect = str(parameters.get("dialect") or "postgres")
    assets = db.scalars(
        select(DataAsset).where(DataAsset.project_id == project_id).order_by(DataAsset.schema_name, DataAsset.table_name)
    ).all()
    grounding = grounding_context(db, project_id, question, limit=5)
    prioritized_ids = {item["asset_id"] for item in grounding["catalog_matches"] if item.get("asset_id")}
    prioritized = [
        *[asset for asset in assets if asset.id in prioritized_ids],
        *[asset for asset in assets if asset.id not in prioritized_ids],
    ]
    try:
        sql = generated_catalog_sql(dialect, prioritized)
    except HTTPException as exc:
        raise ToolRuntimeError(str(exc.detail)) from exc
    return {
        "question": question,
        "dialect": dialect,
        "sql": sql,
        "catalog_matches": len(grounding["catalog_matches"]),
        "grounded_asset_ids": [asset.id for asset in prioritized[:5]],
    }


def _file_profile(db: Session, parameters: dict[str, Any], project_id: str, user_id: str | None = None) -> dict[str, Any]:
    """Read-only lookup of an already-ingested file's persisted profile --
    the IngestedFile.profile column populated at upload time. This never
    re-reads the source file from disk; it is intentionally a pure catalog
    read, same risk class as dataset.profile."""
    item = db.get(IngestedFile, str(parameters["file_id"]))
    if item is None or item.project_id != project_id:
        raise ToolRuntimeError("Ingested file was not found")
    return {
        "id": item.id,
        "filename": item.filename,
        "status": item.status,
        "row_count": item.row_count,
        "size_bytes": item.size_bytes,
        "profile": item.profile,
    }


def _quality_run(db: Session, parameters: dict[str, Any], project_id: str, user_id: str | None = None) -> dict[str, Any]:
    """Execute one persisted data-quality rule against its bound dataset and
    record a QualityRun -- the same execution routers/quality.py's
    POST /quality/rules/{id}/run performs, reusable as a bounded tool."""
    rule = db.get(QualityRule, str(parameters["rule_id"]))
    if rule is None or rule.project_id != project_id:
        raise ToolRuntimeError("Quality rule was not found")
    asset = db.get(DataAsset, rule.asset_id)
    if asset is None:
        raise ToolRuntimeError("The quality rule's dataset no longer exists")
    # QualityRun.created_by is NOT NULL; a bounded tool call may run without
    # an interactive user (e.g. a scheduled agent run), so fall back to
    # whoever authored the rule rather than leaving attribution blank.
    run = QualityRun(project_id=project_id, rule_id=rule.id, status="running", created_by=user_id or rule.created_by)
    db.add(run)
    db.flush()
    try:
        result = execute_quality_rule(
            engine, asset.schema_name, asset.table_name, rule.name, rule.rule_type, rule.column_name, rule.config, run.id,
        )
        for key, value in result.items():
            setattr(run, key, value)
    except Exception as exc:
        run.status = "error"
        run.error = str(exc)[:2000]
        raise ToolRuntimeError(f"Quality rule execution failed: {exc}") from exc
    return {
        "quality_run_id": run.id,
        "rule_id": rule.id,
        "rule_name": rule.name,
        "dataset": f"{asset.schema_name}.{asset.table_name}",
        "status": run.status,
        "checked_rows": run.checked_rows,
        "failed_rows": run.failed_rows,
        "pass_rate": run.pass_rate,
    }


def _pipeline_stage(db: Session, parameters: dict[str, Any], project_id: str, user_id: str | None = None) -> dict[str, Any]:
    """Stage an ingested file through a confirmed mapping into a governed
    local staging relation -- the same write routers/files.py's
    POST /files/{id}/stage performs. Registered risk_level=high /
    requires_approval=True (see seed.py), so this never fires inside the
    autonomous bounded orchestration loop (which only ever auto-selects
    risk_level=low tools); it only runs through the explicit
    POST /tools/{id}/execute -> approval -> execute path."""
    item = db.get(IngestedFile, str(parameters["file_id"]))
    if item is None or item.project_id != project_id:
        raise ToolRuntimeError("Ingested file was not found")
    mapping = db.get(IngestionMapping, str(parameters["mapping_id"]))
    if mapping is None or mapping.project_id != project_id or mapping.file_id != item.id:
        raise ToolRuntimeError("Ingestion mapping was not found for this file")
    suffix = Path(item.filename).suffix.lower()
    rows = read_structured_rows(Path(item.storage_path), suffix)
    if rows is None:
        raise ToolRuntimeError("The file is no longer available as structured data")
    load_mode = str(parameters.get("load_mode") or "append")
    key_columns = parameters.get("key_columns") or []
    try:
        staged = stage_rows(engine, mapping.target_table, item.id, mapping.columns, rows, load_mode=load_mode, key_columns=key_columns)
    except ValueError as exc:
        raise ToolRuntimeError(str(exc)) from exc
    item.status = "staged"
    item.profile = {
        **item.profile,
        "staged_table": staged,
        "confirmed_mapping": {"id": mapping.id, "name": mapping.name, "target_table": mapping.target_table, "columns": mapping.columns, "load_mode": load_mode, "key_columns": key_columns},
    }
    mapping.latest_relation = staged["relation"]
    mapping.run_count += 1
    # Mirror routers/files.py's /files/{id}/stage: register the same catalog
    # asset so a run through this tool is exactly as catalog-visible as one
    # through the REST endpoint -- an agent-driven stage should not produce a
    # relation the catalog and downstream SQL generation can't see.
    asset = db.scalar(
        select(DataAsset).where(
            DataAsset.project_id == project_id,
            DataAsset.source_name == "Local files",
            DataAsset.schema_name == staged["schema_name"],
            DataAsset.table_name == staged["table_name"],
        )
    )
    if asset is None:
        asset = DataAsset(project_id=project_id, source_name="Local files", schema_name=staged["schema_name"], table_name=staged["table_name"], asset_type="staged_file")
        db.add(asset)
    asset.row_count = staged["row_count"]
    asset.columns = [
        {
            "name": column["name"],
            "type": column["type"],
            "nullable": next((mapped["nullable"] for mapped in mapping.columns if mapped["source_name"] == column["source_name"]), True),
        }
        for column in staged["columns"]
    ]
    asset.tags = ["local-file", "mapped", "staged", load_mode, "agent-staged"]
    asset.description = f"Mapped {load_mode} ingestion from {item.filename} (staged by an agent-bound tool)"
    db.flush()
    return {"file_id": item.id, "mapping_id": mapping.id, "asset_id": asset.id, **staged}


def _schedule_run(db: Session, parameters: dict[str, Any], project_id: str, user_id: str | None = None) -> dict[str, Any]:
    """Run one approved ingestion schedule now (out of band from its cron) --
    the same execution schedule_runtime.run_ingestion_schedule performs for
    the Temporal-driven poller. Registered risk_level=high /
    requires_approval=True (see seed.py) for the same reason as
    pipeline.stage: never auto-fires in the bounded orchestration loop."""
    schedule_id = str(parameters["schedule_id"])
    schedule = db.get(IngestionSchedule, schedule_id)
    if schedule is None or schedule.project_id != project_id:
        raise ToolRuntimeError("Ingestion schedule was not found")
    if not schedule.enabled:
        raise ToolRuntimeError("Approve the schedule before running it")
    try:
        return run_ingestion_schedule(schedule_id, actor_id=user_id)
    except ValueError as exc:
        raise ToolRuntimeError(str(exc)) from exc


BUILTIN_HANDLERS: dict[str, Callable[[Session, dict[str, Any], str, str | None], dict[str, Any]]] = {
    "catalog.search": _catalog_search,
    "dataset.profile": _dataset_profile,
    "sql.preview": _sql_preview,
    "job.inspect": _job_inspect,
    "lineage.query": _lineage_query,
    "sql.generate": _sql_generate,
    "file.profile": _file_profile,
    "quality.run": _quality_run,
    "pipeline.stage": _pipeline_stage,
    "schedule.run": _schedule_run,
}


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _blocked_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _resolve_endpoint(hostname: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise ToolRuntimeError(f"Tool endpoint host could not be resolved: {hostname}") from exc
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        try:
            address = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
        except ValueError:
            continue
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise ToolRuntimeError(f"Tool endpoint host could not be resolved: {hostname}")
    return addresses


def _http_client(timeout_seconds: int) -> httpx.Client:
    """One place to build the outbound client (tests swap in a MockTransport)."""
    return httpx.Client(timeout=timeout_seconds, follow_redirects=False, trust_env=False)


def _execute_http(
    endpoint: str | None,
    method: str,
    parameters: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    """Call an allowlisted HTTP tool with SSRF and response-size guards.

    1. The hostname must be in TOOL_HTTP_ALLOWLIST (unchanged).
    2. The host is resolved once; private, loopback, link-local, multicast,
       reserved and unspecified addresses are refused unless
       TOOL_HTTP_ALLOW_PRIVATE=true (the host is necessarily allowlisted too).
    3. The request connects to the vetted IP itself (Host header and TLS SNI /
       certificate check keep the original hostname), so a second DNS answer
       cannot swap in an internal address (DNS rebinding).
    4. The body is streamed and aborted past TOOL_HTTP_MAX_BYTES.
    """
    if not endpoint:
        raise ToolRuntimeError("HTTP tools require an endpoint")
    parsed = urlparse(endpoint)
    allowlist = {
        host.strip().lower()
        for host in os.getenv("TOOL_HTTP_ALLOWLIST", "localhost,127.0.0.1").split(",")
        if host.strip()
    }
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or hostname not in allowlist:
        raise ToolRuntimeError("Tool endpoint host is not in TOOL_HTTP_ALLOWLIST")
    if parsed.username or parsed.password:
        raise ToolRuntimeError("Tool endpoints must not embed credentials in the URL")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ToolRuntimeError("Tool endpoint has an invalid port") from exc
    allow_private = _env_flag("TOOL_HTTP_ALLOW_PRIVATE")
    addresses = _resolve_endpoint(hostname, port)
    blocked = [str(address) for address in addresses if _blocked_address(address)]
    if blocked and not allow_private:
        raise ToolRuntimeError(
            f"Tool endpoint {hostname} resolves to a private or reserved address ({', '.join(blocked)}); "
            "set TOOL_HTTP_ALLOW_PRIVATE=true to allow allowlisted internal hosts"
        )
    target = addresses[0]
    ip_host = f"[{target}]" if isinstance(target, ipaddress.IPv6Address) else str(target)
    pinned_url = parsed._replace(netloc=f"{ip_host}:{port}").geturl()
    default_port = port == (443 if parsed.scheme == "https" else 80)
    headers = {"Host": hostname if default_port else f"{hostname}:{port}"}
    extensions = {"sni_hostname": hostname} if parsed.scheme == "https" else {}
    max_bytes = max(1, int(os.getenv("TOOL_HTTP_MAX_BYTES", "1000000")))
    with _http_client(timeout_seconds) as client:
        with client.stream(method.upper(), pinned_url, json=parameters, headers=headers, extensions=extensions) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise ToolRuntimeError(f"Tool response exceeds TOOL_HTTP_MAX_BYTES ({max_bytes} bytes)")
            chunks: list[bytes] = []
            received = 0
            for chunk in response.iter_bytes():
                received += len(chunk)
                if received > max_bytes:
                    raise ToolRuntimeError(f"Tool response exceeds TOOL_HTTP_MAX_BYTES ({max_bytes} bytes)")
                chunks.append(chunk)
            body = b"".join(chunks)
            status_code = response.status_code
            content_type = response.headers.get("content-type", "")
            encoding = response.encoding or "utf-8"
    if "application/json" in content_type:
        try:
            content: Any = json.loads(body.decode(encoding, errors="replace") or "null")
        except ValueError as exc:
            raise ToolRuntimeError("Tool endpoint returned invalid JSON") from exc
    else:
        content = body.decode(encoding, errors="replace")[:100_000]
    return {"status_code": status_code, "content": content}


def _interrupt_session(db: Session) -> None:
    """Best effort: abort the statement a timed-out handler is running on db's connection."""
    try:
        if not db.in_transaction():
            return
        raw = db.connection().connection.dbapi_connection
        if hasattr(raw, "interrupt"):  # sqlite3
            raw.interrupt()
        elif hasattr(raw, "cancel"):  # psycopg / psycopg2
            raw.cancel()
    except Exception:
        pass


def _run_builtin(
    handler: Callable[[Session, dict[str, Any], str, str | None], dict[str, Any]],
    handler_name: str,
    db: Session,
    parameters: dict[str, Any],
    project_id: str,
    user_id: str | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Run a built-in handler under the tool version's timeout.

    The handler runs in a worker thread while this thread waits; the session is
    never used by both at once. On timeout the session's in-flight statement is
    interrupted, the worker gets a short grace period to unwind, and a
    ToolTimeoutError is raised. SQL-running handlers also receive the timeout
    as a database statement timeout, so the query itself stops too.
    """
    if not timeout_seconds or timeout_seconds <= 0:
        return handler(db, parameters, project_id, user_id)
    token = _TOOL_TIMEOUT_SECONDS.set(int(timeout_seconds))
    try:
        context = contextvars.copy_context()
    finally:
        _TOOL_TIMEOUT_SECONDS.reset(token)
    outcome: dict[str, Any] = {}
    done = threading.Event()

    def target() -> None:
        try:
            outcome["result"] = context.run(handler, db, parameters, project_id, user_id)
        except BaseException as exc:  # re-raised in the calling thread
            outcome["error"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=target, name=f"tool-{handler_name}", daemon=True)
    worker.start()
    if not done.wait(timeout_seconds):
        _interrupt_session(db)
        done.wait(_TIMEOUT_GRACE_SECONDS)
        raise ToolTimeoutError(f"Built-in tool {handler_name} timed out after {timeout_seconds}s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["result"]


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
                    result = _run_builtin(handler, handler_name, db, parameters, project_id, user_id, timeout_seconds)
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
            except ToolTimeoutError as exc:
                last_error = exc
                break  # the timed-out worker may still be unwinding: never retry on the same session
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    time.sleep(min(retry_backoff_seconds * (2**attempt), 10))
        if isinstance(last_error, ToolTimeoutError):
            raise last_error
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
