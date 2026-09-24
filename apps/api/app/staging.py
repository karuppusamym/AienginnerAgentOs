from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Column, Float, Integer, MetaData, Table, Text, and_, delete, func, inspect, or_, select, text
from sqlalchemy.engine import Engine
from .pii import protect_rows
from .sql_guard import check_read_only
import time


IDENTIFIER = re.compile(r"[^a-zA-Z0-9_]+")
FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|truncate|create|grant|revoke|copy|call|execute|vacuum|analyze)\b",
    re.IGNORECASE,
)


SYSTEM_RELATIONS = {"pg_authid", "pg_shadow", "pg_user_mapping", "pg_user_mappings", "sqlite_master", "sqlite_schema", "sqlite_temp_master"}
_SQL_TOKEN = re.compile(r'"[^"]*"|[A-Za-z_][A-Za-z0-9_$]*|[.,()]')
_SQL_NOISE = re.compile(r"'(?:[^']|'')*'|--[^\n]*|/\*.*?\*/", re.DOTALL)
_CLAUSE_END = {"where", "group", "order", "having", "limit", "union", "intersect", "except", "on", "using", "join",
               "inner", "left", "right", "full", "cross", "natural", "window", "fetch", "offset", "qualify", "lateral"}


def application_relations() -> set[str]:
    """Table names owned by DataPilot's own metadata schema (users, providers, audit...)."""
    from .database import Base  # late import: staging is imported while models load

    return {table.name.lower() for table in Base.metadata.tables.values()}


def referenced_relations(sql: str) -> list[tuple[str | None, str]]:
    """Best-effort (schema, table) references that follow FROM / JOIN, including comma lists."""
    tokens = [t.strip('"').lower() if t.startswith('"') else t.lower() for t in _SQL_TOKEN.findall(_SQL_NOISE.sub(" ", sql))]
    found: list[tuple[str | None, str]] = []
    index = 0
    while index < len(tokens):
        if tokens[index] not in {"from", "join"}:
            index += 1
            continue
        index += 1
        while index < len(tokens):
            if tokens[index] == "(":
                break  # subquery or table function; its own FROM is scanned later
            parts = [tokens[index]]
            index += 1
            while index + 1 < len(tokens) and tokens[index] == ".":
                parts.append(tokens[index + 1])
                index += 2
            found.append((parts[-2] if len(parts) > 1 else None, parts[-1]))
            if index < len(tokens) and tokens[index] == "as":
                index += 2
            elif index < len(tokens) and tokens[index] not in _CLAUSE_END and tokens[index] not in {",", ")", "("}:
                index += 1  # bare alias
            if index < len(tokens) and tokens[index] == ",":
                index += 1
                continue
            break
    return found


def assert_no_application_relations(sql: str) -> None:
    """Defence in depth until staging queries use a dedicated least-privilege login.

    The local execution paths share the application's engine, so without this
    check ``SELECT password_hash FROM users`` is a valid "read-only" query.
    """
    protected = application_relations()
    for schema, table in referenced_relations(sql):
        if table in SYSTEM_RELATIONS or (schema in {None, "public", "main"} and table in protected):
            raise ValueError(f"Relation {table} is part of DataPilot's internal metadata and cannot be queried")


def safe_identifier(value: str, fallback: str) -> str:
    cleaned = IDENTIFIER.sub("_", value).strip("_").lower()
    if not cleaned:
        cleaned = fallback
    if cleaned[0].isdigit():
        cleaned = f"t_{cleaned}"
    return cleaned[:55]


def _sql_type(inferred_type: str):
    return {
        "integer": Integer,
        "number": Float,
        "boolean": Boolean,
    }.get(inferred_type, Text)


def _coerce(value: Any, inferred_type: str) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        value = float(value)
    try:
        if inferred_type == "integer":
            return int(value)
        if inferred_type == "number":
            return float(value)
        if inferred_type == "boolean":
            return str(value).lower() in {"true", "yes", "1"}
    except (TypeError, ValueError):
        return None
    return str(value)


def stage_rows(
    engine: Engine,
    requested_name: str,
    file_id: str,
    profile_columns: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    load_mode: str = "versioned",
    key_columns: list[str] | None = None,
) -> dict[str, Any]:
    if load_mode not in {"versioned", "replace", "append", "upsert"}:
        raise ValueError(f"Unsupported load mode: {load_mode}")
    is_postgres = engine.dialect.name == "postgresql"
    schema = "staging" if is_postgres else None
    base_name = safe_identifier(requested_name, f"file_{file_id[:8]}")
    if schema is None and base_name in application_relations():
        # SQLite has no staging schema: never let an upload named "users" replace or append to an app table.
        base_name = f"stg_{base_name}"[:55]
    inspector = inspect(engine)
    existing = set(inspector.get_table_names(schema=schema))
    table_name = base_name
    if load_mode == "versioned" and table_name in existing:
        table_name = f"{base_name}_{file_id[:8]}"
    sequence = 2
    while load_mode == "versioned" and table_name in existing:
        table_name = f"{base_name}_{file_id[:8]}_{sequence}"
        sequence += 1

    metadata = MetaData()
    column_specs: list[tuple[str, str, str, bool]] = []
    used_names: set[str] = set()
    for index, column in enumerate(profile_columns):
        original = str(column.get("source_name") or column["name"])
        requested = str(column.get("target_name") or column.get("name") or original)
        inferred_type = str(column.get("target_type") or column.get("inferred_type", "string"))
        name = safe_identifier(requested, f"column_{index + 1}")
        if name in used_names:
            name = f"{name}_{index + 1}"
        used_names.add(name)
        column_specs.append((original, name, inferred_type, bool(column.get("nullable", True))))

    normalized_keys = [safe_identifier(key, "key") for key in (key_columns or [])]
    target_names = {name for _, name, _, _ in column_specs}
    if load_mode == "upsert":
        if not normalized_keys:
            raise ValueError("Merge mode requires at least one key column")
        missing_keys = [key for key in normalized_keys if key not in target_names]
        if missing_keys:
            raise ValueError(f"Merge key columns do not exist in the mapping: {', '.join(missing_keys)}")

    if is_postgres:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS staging"))

    if table_name in existing:
        table = Table(table_name, metadata, autoload_with=engine, schema=schema)
        if set(table.c.keys()) != target_names:
            raise ValueError("The stable target table columns do not match the confirmed mapping")
    else:
        table = Table(
            table_name,
            metadata,
            *[
                Column(name, _sql_type(inferred_type), nullable=nullable)
                for _, name, inferred_type, nullable in column_specs
            ],
            schema=schema,
        )
        metadata.create_all(engine, tables=[table])
    prepared = [
        {
            name: _coerce(row.get(original), inferred_type)
            for original, name, inferred_type, _ in column_specs
        }
        for row in rows
    ]

    if load_mode == "upsert":
        deduplicated: dict[tuple[Any, ...], dict[str, Any]] = {}
        for row in prepared:
            key = tuple(row[column] for column in normalized_keys)
            if any(value is None for value in key):
                raise ValueError("Merge key values cannot be null")
            deduplicated[key] = row
        prepared = list(deduplicated.values())

    deleted_rows = 0
    with engine.begin() as connection:
        if load_mode == "replace":
            result = connection.execute(delete(table))
            deleted_rows = max(result.rowcount or 0, 0)
        elif load_mode == "upsert" and prepared:
            for offset in range(0, len(prepared), 100):
                predicates = [
                    and_(*[table.c[key] == row[key] for key in normalized_keys])
                    for row in prepared[offset : offset + 100]
                ]
                result = connection.execute(delete(table).where(or_(*predicates)))
                deleted_rows += max(result.rowcount or 0, 0)
        if prepared:
            for offset in range(0, len(prepared), 1000):
                connection.execute(table.insert(), prepared[offset : offset + 1000])
        final_row_count = int(connection.scalar(select(func.count()).select_from(table)) or 0)

    return {
        "schema_name": schema or "main",
        "table_name": table_name,
        "relation": f"{schema}.{table_name}" if schema else table_name,
        "row_count": final_row_count,
        "loaded_rows": len(prepared),
        "replaced_rows": deleted_rows,
        "load_mode": load_mode,
        "key_columns": normalized_keys,
        "columns": [
            {"source_name": original, "name": name, "type": inferred_type}
            for original, name, inferred_type, _ in column_specs
        ],
    }


def _json_safe_value(value: Any) -> Any:
    """Convert a raw DB-driver value into something JSON/JSONB-serializable.

    Query results are stored verbatim into JSONB columns (QueryRun.result,
    SqlQueryCache.result) after this function runs. Raw driver values for
    date/time/decimal columns (e.g. a `timestamp` column, or a `numeric`
    column) come back as native Python `datetime`/`date`/`Decimal` objects,
    which psycopg's JSON adapter cannot serialize — every SQL-generate or
    ask-a-question call that executed a query touching such a column failed
    with `TypeError: Object of type datetime is not JSON serializable` on
    commit. Normalize those two type families before they reach the ORM.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def execute_parameterized_read_only(
    engine: Engine,
    sql: str,
    parameters: dict[str, Any] | None = None,
    limit: int = 500,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    normalized = sql.strip().rstrip(";").strip()
    if not normalized or ";" in normalized:
        raise ValueError("Exactly one SQL statement is allowed")
    if not re.match(r"^(select|with)\b", normalized, re.IGNORECASE):
        raise ValueError("Only SELECT statements and read-only CTEs are allowed")
    if FORBIDDEN_SQL.search(normalized):
        raise ValueError("The statement contains a prohibited write or administrative operation")
    verdict = check_read_only(normalized, "postgres")
    if not verdict.ok:
        raise ValueError(verdict.reason)
    assert_no_application_relations(normalized)
    if engine.dialect.name == "sqlite":
        from .sqlite_compat import sqlite_compatible_sql

        normalized = sqlite_compatible_sql(normalized, set(inspect(engine).get_table_names()))
        # Unqualifying "core.users" would otherwise reach the app's own users table.
        assert_no_application_relations(normalized)

    from .database import engine as app_engine, grant_read_only_access, read_only_engine

    target = read_only_engine if engine is app_engine and read_only_engine is not None else engine
    try:
        rows, columns = _run_read_only(target, normalized, parameters, limit, timeout_seconds)
    except Exception as exc:
        if target is engine or "permission denied" not in str(exc).lower():
            raise
        # A schema created after startup (e.g. a newly published pipeline view)
        # has no grant for the reader role yet: refresh grants once and retry.
        grant_read_only_access(app_engine)
        rows, columns = _run_read_only(target, normalized, parameters, limit, timeout_seconds)
    truncated = len(rows) > limit
    protected_rows, pii_columns = protect_rows(
        columns,
        [{key: _json_safe_value(value) for key, value in zip(columns, row, strict=False)} for row in rows[:limit]],
    )
    return {
        "columns": columns,
        "rows": protected_rows,
        "row_count": min(len(rows), limit),
        "truncated": truncated,
        "limit": limit,
        "protected_columns": pii_columns,
    }


def _run_read_only(engine: Engine, sql: str, parameters: dict[str, Any] | None, limit: int, timeout_seconds: int) -> tuple[list[Any], list[str]]:
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            if engine.dialect.name == "postgresql":
                connection.execute(
                    text("SELECT set_config('statement_timeout', :timeout, true)"),
                    {"timeout": f"{timeout_seconds}s"},
                )
                connection.execute(text("SET TRANSACTION READ ONLY"))
            elif engine.dialect.name == "sqlite":
                # SQLite has no statement_timeout; abort runaway queries (e.g. recursive CTEs).
                deadline = time.monotonic() + timeout_seconds
                connection.connection.driver_connection.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
            result = connection.execute(text(sql), parameters or {})
            rows = result.fetchmany(limit + 1)
            columns = list(result.keys())
            transaction.rollback()
        except Exception:
            transaction.rollback()
            raise
        finally:
            if engine.dialect.name == "sqlite":
                connection.connection.driver_connection.set_progress_handler(None, 0)
    return rows, columns


def execute_read_only(engine: Engine, sql: str, limit: int = 500) -> dict[str, Any]:
    return execute_parameterized_read_only(engine, sql, {}, limit)
