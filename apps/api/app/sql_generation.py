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


def generated_catalog_sql(dialect: str, assets: list[DataAsset]) -> str:
    if any(asset.schema_name == "core" and asset.table_name == "accounts" for asset in assets):
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
