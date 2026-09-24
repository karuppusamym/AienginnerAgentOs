"""SQL analysis services: dialects, generation cache, safety checks, catalog context,
conversation memory, answer text and chart suggestions."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import engine
from ..model_runtime import generate_text
from ..models import (
    Connector,
    Conversation,
    ConversationMessage,
    DataAsset,
    ModelProvider,
    SQLQueryCache,
)
from ..sql_guard import is_read_only
from ..staging import execute_read_only, safe_identifier


def connector_dialect(connector: Connector | None, requested_dialect: str) -> str:
    """Use the registered system type as the source of truth for analysis SQL."""
    if connector is None:
        return requested_dialect
    return {
        "postgres": "postgres",
        "sql_server": "sqlserver",
        "local_files": "postgres",
        "oracle": "oracle",
        "teradata": "teradata",
        "bigquery": "bigquery",
    }.get(connector.connector_type, requested_dialect)


def analysis_source_output(connector: Connector | None, dialect: str) -> dict[str, Any]:
    if connector is None:
        return {
            "id": None,
            "name": "DataPilot local workspace",
            "database": "PostgreSQL staging",
            "connector_type": "local_files",
            "dialect": dialect,
            "connection_mode": "direct",
        }
    return {
        "id": connector.id,
        "name": connector.name,
        "database": connector.database or connector.host or connector.name,
        "connector_type": connector.connector_type,
        "dialect": dialect,
        # Lets clients (e.g. the semantic graph / join-policy UI) tell an
        # MCP-backed connector apart from a direct-driver one: MCP execution
        # invokes exactly one named tool per call, so unlike a direct
        # connector, assets sharing this connector_id are NOT automatically
        # joinable -- see group_key() in routers/semantic.py.
        "connection_mode": connector.connection_mode,
    }


def refresh_conversation_summary(conversation: Conversation, messages: list[ConversationMessage]) -> str:
    """Maintain a deterministic long-horizon memory without storing a hidden model transcript."""
    meaningful = [message for message in messages if message.role in {"user", "assistant"}]
    if len(meaningful) <= 12:
        conversation.summary = ""
        return ""
    highlights = [
        f"{message.role}: {message.content.replace(chr(10), ' ').strip()[:360]}"
        for message in meaningful[-12:]
    ]
    conversation.summary = "Earlier conversation summary:\n" + "\n".join(highlights)
    return conversation.summary


def compact_conversation_context(messages: list[ConversationMessage], summary: str = "") -> list[dict[str, str]]:
    """Persist full messages, but send only bounded recent context plus durable summary to the model."""
    context = ([{"role": "system", "content": summary[:4_000]}] if summary else [])
    context.extend([
        {"role": message.role, "content": message.content[:2_000]}
        for message in messages[-16:]
        if message.role in {"user", "assistant"}
    ])
    return context


# Bump whenever SQL generation changes, so cached statements from an older
# generator are regenerated instead of replayed.
SQL_GENERATOR_VERSION = "2026-09-intent-v1"
SQL_CACHE_TTL_HOURS = float(os.getenv("SQL_CACHE_TTL_HOURS", "24"))


def _cacheable_sql_result(result: dict[str, Any]) -> bool:
    """Only successful, non-fallback generations are worth replaying."""
    execution = result.get("execution") or {}
    mode = str((result.get("provider") or {}).get("mode", ""))
    return not execution.get("error") and "fallback" not in mode


def _sql_cache_key(
    project_id: str,
    connector_id: str | None,
    dialect: str,
    normalized_question: str,
    context_hash: str,
    grounding_signature: str,
    provider_key: str = "",
) -> str:
    payload = {
        "provider": provider_key,
        "project_id": project_id,
        "connector_id": connector_id,
        "dialect": dialect,
        "question": normalized_question,
        "context_hash": context_hash,
        "grounding_signature": grounding_signature,
        "generator": SQL_GENERATOR_VERSION,
    }
    return hashlib.sha1(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _cached_sql_response(
    db: Session,
    *,
    project_id: str,
    cache_key: str,
) -> dict[str, Any] | None:
    cached = db.scalar(
        select(SQLQueryCache).where(
            SQLQueryCache.project_id == project_id,
            SQLQueryCache.cache_key == cache_key,
        )
    )
    if cached is None or not cached.result or not _cacheable_sql_result(cached.result):
        return None
    freshest = cached.updated_at or cached.created_at
    if freshest is not None:
        if freshest.tzinfo is None:
            freshest = freshest.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - freshest > timedelta(hours=SQL_CACHE_TTL_HOURS):
            return None
    cached.hit_count += 1
    cached.last_used_at = datetime.now(timezone.utc)
    payload = json.loads(json.dumps(cached.result, default=str))
    provider = payload.get("provider") or {}
    payload["provider"] = {
        **provider,
        "mode": "cache_reuse",
        "latency_ms": 0,
    }
    payload["cache"] = {
        "hit": True,
        "cache_key": cached.cache_key,
        "normalized_question": cached.normalized_question,
        "created_at": cached.created_at.isoformat(),
        "updated_at": cached.updated_at.isoformat() if cached.updated_at else cached.created_at.isoformat(),
        "last_used_at": cached.last_used_at.isoformat(),
        "hit_count": cached.hit_count,
    }
    return payload


def _store_sql_query_cache(
    db: Session,
    *,
    project_id: str,
    connector_id: str | None,
    dialect: str,
    normalized_question: str,
    context_hash: str,
    grounding_signature: str,
    cache_key: str,
    result: dict[str, Any],
    created_by: str | None,
) -> None:
    if not _cacheable_sql_result(result):
        return
    payload = json.loads(json.dumps(result, default=str))
    # Store the statement, not the data: rows go stale and would be duplicated
    # across the cache, QueryRun and the conversation message.
    payload["execution"] = None
    payload["preview"] = []
    payload["cache"] = {
        "hit": False,
        "cache_key": cache_key,
        "normalized_question": normalized_question,
    }
    cached = db.scalar(
        select(SQLQueryCache).where(
            SQLQueryCache.project_id == project_id,
            SQLQueryCache.cache_key == cache_key,
        )
    )
    if cached is None:
        db.add(
            SQLQueryCache(
                project_id=project_id,
                connector_id=connector_id,
                dialect=dialect,
                normalized_question=normalized_question,
                context_signature=context_hash,
                grounding_signature=grounding_signature,
                cache_key=cache_key,
                result=payload,
                hit_count=0,
                created_by=created_by,
            )
        )
        return
    cached.connector_id = connector_id
    cached.dialect = dialect
    cached.normalized_question = normalized_question
    cached.context_signature = context_hash
    cached.grounding_signature = grounding_signature
    cached.result = payload
    cached.updated_at = datetime.now(timezone.utc)


def conversational_analysis_answer(
    provider: ModelProvider,
    question: str,
    analysis: dict[str, Any],
    prior_message_count: int,
    project_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> str:
    execution = analysis.get("execution") or {}
    source = analysis.get("source") or {}
    if execution.get("error"):
        # Driver errors embed the full statement and a docs URL; the inspector
        # shows the complete error, the chat line only needs the cause.
        cause = str(execution["error"]).split("\n[SQL:", 1)[0].splitlines()[0][:240]
        summary = f"I prepared a safe {analysis['dialect']} query, but its preview could not run: {cause}"
    elif execution:
        summary = f"I found {execution.get('row_count', 0)} row{'s' if execution.get('row_count', 0) != 1 else ''} in the preview."
    else:
        summary = f"I prepared a safe {analysis['dialect']} query for the selected source."
    memory_note = " I used the earlier discussion in this topic to interpret this follow-up." if prior_message_count else ""
    deterministic = (
        f"{summary}{memory_note} "
        f"The governed SQL, validation checks, and source context for {source.get('name', 'the selected source')} are attached below."
    )
    if os.getenv("CONVERSATION_MODEL_SUMMARY_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        return deterministic
    if provider.provider_type == "local_mock":
        return f"{summary}{memory_note} The SQL and validation details are attached below; ask a follow-up in this same topic and I will retain the context."
    try:
        response = generate_text(
            provider,
            "You are a concise data analyst in a continuing chat. Explain the result naturally in 2-4 sentences. Respect the provided evidence, do not invent findings, and do not include SQL or markdown tables.",
            json.dumps({"question": question, "analysis": analysis, "prior_message_count": prior_message_count}, default=str)[:18_000],
            900,
            governance_feature="conversation_summary",
            governance_business_id=project_id,
            governance_session_id=session_id,
            governance_user_id=user_id,
        )
        return response.content.strip()[:4_000] or deterministic
    except Exception:
        return deterministic


def _extract_sql(value: str) -> str:
    fenced = re.search(r"```(?:sql)?\s*(.*?)(?:```|$)", value, re.IGNORECASE | re.DOTALL)
    candidate = (fenced.group(1) if fenced else value).strip()
    start = re.search(r"\b(select|with)\b", candidate, re.IGNORECASE)
    if start:
        candidate = candidate[start.start():]
    return candidate.split("```")[0].strip()


def _safe_read_only_sql(sql: str, dialect: str | None = None) -> bool:
    """Cheap completeness checks first, then the sqlglot parser guard (sql_guard.py)."""
    normalized = sql.strip()
    destructive = bool(re.search(r"\b(drop|delete|truncate|alter|update|insert|merge|grant|revoke)\b", normalized, re.I))
    multiple_statements = ";" in normalized.rstrip().rstrip(";")
    balanced = normalized.count("(") == normalized.count(")") and normalized.replace("''", "").count("'") % 2 == 0
    complete = not re.search(r"(?:\b(and|or|where|from|join|on|as|in)|[,.(=])\s*;?$", normalized, re.I)
    shape_ok = bool(re.match(r"^\s*(select|with)\b", normalized, re.I)) and not destructive and not multiple_statements and balanced and complete
    return shape_ok and is_read_only(normalized.rstrip(";"), dialect)


def _column_sql_context_entry(column: dict[str, Any]) -> str:
    business_name = column.get("business_name")
    business_suffix = f" ({business_name})" if business_name else ""
    required_suffix = "" if column.get("nullable", True) else ", required"
    return f"{column.get('name', '')}{business_suffix} ({column.get('type', 'unknown')}{required_suffix})"


def _catalog_sql_context(assets: list[DataAsset]) -> str:
    """Format catalog metadata so SQL generation can respect actual data types."""
    entries: list[str] = []
    for asset in assets[:40]:
        columns = ", ".join(
            _column_sql_context_entry(column) for column in asset.columns if column.get("name")
        )
        entries.append(
            f"- {asset.schema_name}.{asset.table_name}: {columns or 'No column metadata'}. {asset.description or ''}"
        )
    return "\n".join(entries)


def _local_execution_error(sql: str) -> dict[str, Any] | None:
    try:
        return execute_read_only(engine, sql, 500)
    except Exception as exc:
        return {
            "error": str(exc),
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "limit": 500,
        }


def _identifier_quote(value: str, dialect: str) -> str:
    identifier = safe_identifier(value, "value")
    if dialect == "bigquery":
        return f"`{identifier}`"
    if dialect == "sqlserver":
        return f"[{identifier}]"
    return f'"{identifier}"' if dialect in {"postgres", "oracle"} else identifier


def _asset_relation_sql(asset: DataAsset, connector: Connector | None) -> tuple[str, str]:
    dialect = connector_dialect(connector, "postgres")
    schema_name = safe_identifier(asset.schema_name, "public")
    table_name = safe_identifier(asset.table_name, "dataset")
    relation = f"{schema_name}.{table_name}"
    if dialect == "bigquery":
        return relation, f"`{relation}`"
    if dialect == "sqlserver":
        return relation, f"[{schema_name}].[{table_name}]"
    if dialect in {"postgres", "oracle"}:
        return relation, f'"{schema_name}"."{table_name}"'
    return relation, relation


def _json_schema_type(column: dict[str, Any]) -> str:
    column_type = str(column.get("type", "")).lower()
    if any(token in column_type for token in ("int", "serial")):
        return "integer"
    if any(token in column_type for token in ("decimal", "numeric", "float", "double", "real")):
        return "number"
    if any(token in column_type for token in ("bool", "bit")):
        return "boolean"
    return "string"


def _chart_from_result(question: str, execution: dict[str, Any] | None) -> dict[str, Any]:
    """Chart spec fitted to the result's shape (see app/charts.py)."""
    from ..charts import infer_chart

    return infer_chart(question, execution)
