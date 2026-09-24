"""Deterministic, catalog-grounded SQL templating.

Split out of main.py so it can be imported by both the /sql/generate route
(via main.py, which re-exports these names for backward compatibility with
every router's blanket `from ..main import ...`) and the internal tool
registry's `sql.generate` builtin handler in tool_runtime.py, without
creating a circular import (tool_runtime.py must never import from main.py,
since main.py imports from tool_runtime.py).

These functions are pure/stateless: given a dialect and (optionally) the
project's catalog, they return read-only SQL text. No DB writes, no model
calls -- the "AI-generated" SQL path (grounding + LLM) lives in
routers/sql.py and reuses grounded catalog produced here as its fallback
when no model provider is configured.
"""
from __future__ import annotations

import re

from fastapi import HTTPException

from .models import DataAsset
from .staging import safe_identifier


def generated_sql(dialect: str) -> str:
    if dialect == "bigquery":
        month_expr = "DATE_TRUNC(DATE(a.opened_at), MONTH)"
        date_filter = "DATE(a.opened_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 12 MONTH)"
        limit = "LIMIT 500"
    elif dialect == "oracle":
        month_expr = "TRUNC(a.opened_at, 'MM')"
        date_filter = "a.opened_at >= ADD_MONTHS(SYSDATE, -12)"
        limit = "FETCH FIRST 500 ROWS ONLY"
    elif dialect == "teradata":
        month_expr = "TRUNC(a.opened_at, 'MM')"
        date_filter = "a.opened_at >= ADD_MONTHS(CURRENT_DATE, -12)"
        limit = "ORDER BY month_opened DESC FETCH FIRST 500 ROWS ONLY"
    elif dialect == "postgres":
        month_expr = "DATE_TRUNC('month', a.opened_at)"
        date_filter = "a.opened_at >= CURRENT_TIMESTAMP - INTERVAL '12 months'"
        limit = "LIMIT 500"
    else:
        month_expr = "DATEFROMPARTS(YEAR(a.opened_at), MONTH(a.opened_at), 1)"
        date_filter = "a.opened_at >= DATEADD(month, -12, CURRENT_TIMESTAMP)"
        limit = "ORDER BY month_opened DESC OFFSET 0 ROWS FETCH NEXT 500 ROWS ONLY"
    return (
        "SELECT\n"
        f"  {month_expr} AS month_opened,\n"
        "  COUNT(DISTINCT a.account_id) AS new_deposit_accounts,\n"
        "  SUM(CASE WHEN a.status = 'active' THEN 1 ELSE 0 END) AS active_accounts\n"
        "FROM core.accounts AS a\n"
        "WHERE a.account_type IN ('checking', 'savings')\n"
        f"  AND {date_filter}\n"
        "GROUP BY " + month_expr + "\n"
        + limit
        + ";"
    )


_NUMERIC_TYPES = ("int", "num", "dec", "float", "double", "real", "money")
_TIME_HINTS = ("date", "time", "_at", "month", "year", "day")
_STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "is", "are", "me", "show", "list", "give",
         "what", "how", "many", "much", "by", "per", "each", "with", "from", "all", "number", "count", "total"}


def _words(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in _STOP]


def _column_words(name: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", name.lower().replace("_", " ")))
    return words | {word.rstrip("s") for word in words}


def _is_numeric(column: dict) -> bool:
    return any(token in str(column.get("type", "")).lower() for token in _NUMERIC_TYPES)


def _is_temporal(column: dict) -> bool:
    kind = str(column.get("type", "")).lower()
    return "date" in kind or "time" in kind or any(hint in str(column.get("name", "")).lower() for hint in _TIME_HINTS)


def _match_column(phrase_words: list[str], columns: list[dict], predicate=None) -> dict | None:
    best, best_score = None, 0
    for column in columns:
        if predicate and not predicate(column):
            continue
        names = _column_words(str(column.get("name", ""))) | _column_words(str(column.get("business_name", "")))
        score = sum(1 for word in phrase_words if word in names or word.rstrip("s") in names)
        if score > best_score:
            best, best_score = column, score
    return best


def _quote(name: str, dialect: str) -> str:
    cleaned = safe_identifier(name, "column")
    if dialect == "bigquery":
        return f"`{cleaned}`"
    if dialect == "sqlserver":
        return f"[{cleaned}]"
    return f'"{cleaned}"' if dialect in {"postgres", "oracle"} else cleaned


def _month(expr: str, dialect: str) -> str:
    return {
        "bigquery": f"DATE_TRUNC(DATE({expr}), MONTH)",
        "oracle": f"TRUNC({expr}, 'MM')",
        "teradata": f"TRUNC({expr}, 'MM')",
        "postgres": f"DATE_TRUNC('month', {expr})",
    }.get(dialect, f"DATEFROMPARTS(YEAR({expr}), MONTH({expr}), 1)")


def _relation(asset: DataAsset, dialect: str) -> str:
    schema_name = safe_identifier(asset.schema_name, "public")
    table_name = safe_identifier(asset.table_name, "dataset")
    # safe_identifier already restricts names to [a-z0-9_], so the relation needs no
    # quoting; columns stay quoted because names like "status" or "date" are reserved.
    return f"`{schema_name}.{table_name}`" if dialect == "bigquery" else f"{schema_name}.{table_name}"


def intent_sql(question: str, dialect: str, assets: list[DataAsset]) -> str | None:
    """Question-aware deterministic SQL for the offline model.

    Recognises counts, "by/per <column>" groupings, monthly trends, sum/avg/
    min/max of a numeric column, "top N" and an active/inactive status filter.
    Returns None when the question has no recognisable analytical intent.
    """
    if not assets:
        return None
    lowered = question.lower()
    words = _words(question)
    # Prefer the asset whose name/columns the question mentions; ties keep grounding order.
    def overlap(asset: DataAsset) -> int:
        vocabulary = _column_words(asset.table_name) | set().union(*(_column_words(str(c.get("name", ""))) for c in asset.columns or [{}]))
        return sum(1 for word in words if word in vocabulary or word.rstrip("s") in vocabulary)
    asset = max(assets, key=overlap) if any(overlap(item) for item in assets) else assets[0]
    columns = [column for column in asset.columns or [] if column.get("name")]
    if not columns:
        return None

    count_intent = bool(re.search(r"\b(how many|count|number of)\b", lowered))
    trend = bool(re.search(r"\b(monthly|per month|by month|each month|over time|trend|growth)\b", lowered))
    aggregate = next((fn for pattern, fn in ((r"\b(average|avg|mean)\b", "AVG"), (r"\b(total|sum)\b", "SUM"), (r"\b(max|maximum|highest|largest)\b", "MAX"), (r"\b(min|minimum|lowest|smallest)\b", "MIN")) if re.search(pattern, lowered)), None)
    top = re.search(r"\btop\s+(\d{1,3})\b", lowered)
    group_match = re.search(r"\b(?:by|per|for each|across|grouped by)\s+([a-z0-9_ ]{2,40})", lowered)

    select: list[str] = []
    group_by: list[str] = []
    order_by = ""
    where: list[str] = []

    if trend:
        temporal = _match_column(words, columns, _is_temporal) or next((c for c in columns if _is_temporal(c)), None)
        if temporal:
            expr = _month(_quote(temporal["name"], dialect), dialect)
            select.append(f"{expr} AS period_month")
            group_by.append(expr)
            order_by = "period_month"
    top_subject = re.search(r"\btop\s+\d{1,3}\s+([a-z0-9_ ]{2,40}?)(?:\s+(?:by|per)\b|$)", lowered)
    if top_subject and not group_by:
        group_column = _match_column(_words(top_subject.group(1)), columns, lambda c: not _is_numeric(c))
        if group_column:
            quoted = _quote(group_column["name"], dialect)
            select.append(quoted)
            group_by.append(quoted)
    if group_match and not group_by:
        group_column = _match_column(_words(group_match.group(1)), columns, lambda c: not _is_numeric(c) or not aggregate)
        if group_column:
            quoted = _quote(group_column["name"], dialect)
            select.append(quoted)
            group_by.append(quoted)

    metric = "row_count"
    metric_column = _match_column(words, columns, _is_numeric) if aggregate else None
    if aggregate and metric_column:
        metric = f"{aggregate.lower()}_{safe_identifier(metric_column['name'], 'value')}"
        select.append(f"{aggregate}({_quote(metric_column['name'], dialect)}) AS {metric}")
    elif not (count_intent or group_by):
        return None  # nothing analytical recognised: caller falls back to a column preview
    if count_intent or group_by:
        select.append("COUNT(*) AS row_count")

    status = next((c for c in columns if str(c.get("name", "")).lower() in {"status", "state"}), None)
    if status is not None:
        if re.search(r"\binactive\b", lowered):
            where.append(f"{_quote(status['name'], dialect)} = 'inactive'")
        elif re.search(r"\bactive\b", lowered):
            where.append(f"{_quote(status['name'], dialect)} = 'active'")

    limit = int(top.group(1)) if top else 500
    if top and group_by:
        order_by = f"{metric} DESC"
    sql = "SELECT\n  " + ",\n  ".join(select) + f"\nFROM {_relation(asset, dialect)}"
    if where:
        sql += "\nWHERE " + " AND ".join(where)
    if group_by:
        sql += "\nGROUP BY " + ", ".join(group_by)
    if dialect == "sqlserver":
        sql = sql.replace("SELECT\n", f"SELECT TOP ({limit})\n", 1)
        return sql + (f"\nORDER BY {order_by}" if order_by else "") + ";"
    if order_by:
        sql += f"\nORDER BY {order_by}"
    sql += f"\nFETCH FIRST {limit} ROWS ONLY" if dialect in {"oracle", "teradata"} else f"\nLIMIT {limit}"
    return sql + ";"


def generated_catalog_sql(dialect: str, assets: list[DataAsset], question: str | None = None) -> str:
    if question:
        from_intent = intent_sql(question, dialect, assets)
        if from_intent:
            return from_intent
    # Look for the well-known demo table anywhere in the catalog, not just at
    # position 0. `assets` is caller-provided ordering (grounding-prioritized
    # in routers/sql.py) -- when any other asset sorts or scores ahead of
    # core.accounts (e.g. another catalog asset whose schema_name sorts
    # alphabetically before "core", or one grounding scores higher for a
    # given question), the polished canned demo query silently disappeared
    # in favor of a generic, less useful templated query even though the
    # well-known demo table was still right there in the catalog.
    demo_accounts = next((item for item in assets if item.schema_name == "core" and item.table_name == "accounts"), None)
    if demo_accounts is not None:
        return generated_sql(dialect)
    if not assets:
        raise HTTPException(status_code=409, detail="Ingest or scan a dataset before generating SQL")
    asset = next((item for item in assets if item.asset_type in {"staged_file", "view"}), assets[0])
    columns = [safe_identifier(str(column.get("name", "")), "column") for column in asset.columns[:12]]
    projection = ",\n  ".join(columns) if columns else "*"
    schema_name = safe_identifier(asset.schema_name, "public")
    table_name = safe_identifier(asset.table_name, "dataset")
    if dialect == "bigquery":
        relation = f"`{schema_name}.{table_name}`"
        limiter = "LIMIT 500"
    elif dialect == "sqlserver":
        relation = f"[{schema_name}].[{table_name}]"
        return f"SELECT TOP (500)\n  {projection}\nFROM {relation};"
    else:
        relation = f'"{schema_name}"."{table_name}"' if dialect in {"postgres", "oracle"} else f"{schema_name}.{table_name}"
        limiter = "FETCH FIRST 500 ROWS ONLY" if dialect in {"oracle", "teradata"} else "LIMIT 500"
    return f"SELECT\n  {projection}\nFROM {relation}\n{limiter};"
