"""Performance-driven DDL suggestions.

DataPilot only runs read queries against data sources. When queries are
slow, this module suggests indexes; the DDL is advice for a DBA, never run
by DataPilot unless ``ALLOW_DDL_EXECUTION=true`` is set explicitly.

How a suggestion is formed:
1. Recent query runs (local staging and connector sources) whose measured
   duration is at least ``SLOW_QUERY_MS`` (default 500 ms) are parsed.
2. Columns used to filter or join (weight 3), group (2) or sort (1) are
   counted per catalogued relation.
3. Columns that an existing index already leads with are marked (local
   sources can be inspected; for connectors the DBA must verify).
4. The DDL is written in the source's dialect from catalog identifiers only.
"""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from typing import Any

import sqlglot
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session
from sqlglot import exp

from .models import Connector, DataAsset, QueryRun

ROLE_WEIGHTS = {"filter": 3, "join": 3, "group": 2, "order": 1}
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_READ_DIALECT = {"postgres": "postgres", "sqlserver": "tsql", "oracle": "oracle", "teradata": "teradata", "bigquery": "bigquery"}


def slow_query_threshold_ms() -> float:
    return float(os.getenv("SLOW_QUERY_MS", "500"))


def ddl_execution_allowed() -> bool:
    return os.getenv("ALLOW_DDL_EXECUTION", "false").strip().lower() in {"1", "true", "yes", "on"}


def _column_uses(sql: str, dialect: str) -> list[tuple[tuple[str | None, str], str, str]]:
    try:
        tree = sqlglot.parse_one(sql, read=_READ_DIALECT.get(dialect, "postgres"))
    except Exception:
        return []
    aliases: dict[str, tuple[str | None, str]] = {}
    for table in tree.find_all(exp.Table):
        relation = (str(table.db).lower() or None, str(table.name).lower())
        aliases[str(table.alias_or_name).lower()] = relation
        aliases[str(table.name).lower()] = relation
    tables = list(set(aliases.values()))
    uses: list[tuple[tuple[str | None, str], str, str]] = []

    def collect(node: exp.Expression | None, role: str) -> None:
        if node is None:
            return
        for column in node.find_all(exp.Column):
            qualifier = str(column.table or "").lower()
            relation = aliases.get(qualifier) if qualifier else (tables[0] if len(tables) == 1 else None)
            if relation:
                uses.append((relation, str(column.name).lower(), role))

    for where in tree.find_all(exp.Where):
        collect(where, "filter")
    for join in tree.find_all(exp.Join):
        collect(join.args.get("on"), "join")
    for group in tree.find_all(exp.Group):
        collect(group, "group")
    for order in tree.find_all(exp.Order):
        collect(order, "order")
    return uses


def _existing_leading_columns(engine, schema: str | None, table: str) -> set[str]:
    try:
        inspector = inspect(engine)
        leading = {str(index["column_names"][0]).lower() for index in inspector.get_indexes(table, schema=schema) if index.get("column_names")}
        primary = inspector.get_pk_constraint(table, schema=schema).get("constrained_columns") or []
        return leading | ({str(primary[0]).lower()} if primary else set())
    except Exception:
        return set()


def index_statement(dialect: str, schema: str | None, table: str, columns: list[str], concurrent: bool = True) -> str:
    """Dialect-specific CREATE INDEX from validated identifiers only."""
    if not all(_IDENT.match(part) for part in [table, *columns, *([schema] if schema else [])]):
        raise ValueError("Unsafe identifier in index suggestion")
    name = f"ix_dp_{table}_{'_'.join(columns)}"[:63].lower()
    if dialect == "sqlserver":
        target = f"[{schema}].[{table}]" if schema else f"[{table}]"
        return f"CREATE NONCLUSTERED INDEX [{name}] ON {target} ({', '.join(f'[{c}]' for c in columns)}) WITH (ONLINE = ON);"
    if dialect in {"oracle", "teradata"}:
        target = f"{schema}.{table}" if schema else table
        return f"CREATE INDEX {name} ON {target} ({', '.join(columns)}){' ONLINE' if dialect == 'oracle' else ''};"
    if dialect == "bigquery":
        target = f"`{schema}.{table}`" if schema else f"`{table}`"
        return f"-- BigQuery has no B-tree indexes; consider clustering instead:\nALTER TABLE {target} SET OPTIONS (description = 'cluster by {', '.join(columns)}');"
    cols = ", ".join(f'"{c}"' for c in columns)
    if dialect == "sqlite":
        return f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ({cols});'
    return f'CREATE INDEX {"CONCURRENTLY " if concurrent else ""}IF NOT EXISTS "{name}" ON "{schema or "public"}"."{table}" ({cols});'


def _local_physical(engine, asset: DataAsset) -> tuple[str | None, str]:
    return (None, asset.table_name.lower()) if engine.dialect.name == "sqlite" else (asset.schema_name.lower(), asset.table_name.lower())


def _source_dialect(connector: Connector | None, engine) -> str:
    if connector is None or connector.connector_type == "local_files":
        return "sqlite" if engine.dialect.name == "sqlite" else "postgres"
    return {"sql_server": "sqlserver", "postgres": "postgres", "oracle": "oracle", "teradata": "teradata", "bigquery": "bigquery"}.get(connector.connector_type, "postgres")


def recommend_indexes(db: Session, engine, project_id: str, min_ms: float | None = None, min_occurrences: int = 1, limit: int = 20) -> list[dict[str, Any]]:
    threshold = slow_query_threshold_ms() if min_ms is None else float(min_ms)
    assets = db.scalars(select(DataAsset).where(DataAsset.project_id == project_id)).all()
    connectors = {c.id: c for c in db.scalars(select(Connector).where(Connector.project_id == project_id)).all()}
    catalog: dict[tuple[str | None, str, str], DataAsset] = {(asset.connector_id, asset.schema_name.lower(), asset.table_name.lower()): asset for asset in assets}
    runs = db.scalars(
        select(QueryRun).where(QueryRun.project_id == project_id, QueryRun.status.in_(["generated", "cache_hit"])).order_by(QueryRun.created_at.desc()).limit(500)
    ).all()
    weights: Counter = Counter()
    durations: dict[tuple, list[float]] = defaultdict(list)
    roles: dict[tuple, Counter] = defaultdict(Counter)
    pair_hits: Counter = Counter()
    for run in runs:
        execution = (run.result or {}).get("execution") or {}
        duration = execution.get("duration_ms")
        if execution.get("error") or duration is None or float(duration) < threshold:
            continue
        connector = connectors.get(run.connector_id) if run.connector_id else None
        source_id = connector.id if connector is not None and connector.connector_type != "local_files" else None
        filters: dict[tuple, set[str]] = defaultdict(set)
        for relation, column, role in _column_uses(run.sql or "", run.dialect or "postgres"):
            key = next((k for k in catalog if k[0] == source_id and k[2] == relation[1] and relation[0] in (None, k[1])), None)
            if key is None:
                continue
            weights[(key, column)] += ROLE_WEIGHTS[role]
            durations[(key, column)].append(float(duration))
            roles[(key, column)][role] += 1
            if role == "filter":
                filters[key].add(column)
        for key, columns in filters.items():
            if len(columns) >= 2:
                pair = tuple(sorted(columns))[:2]
                pair_hits[(key, pair)] += 1
                durations[(key, pair)].append(float(duration))

    def build(key: tuple, columns: list[str], reason: str, weight: float) -> dict[str, Any] | None:
        asset = catalog[key]
        valid = {str(item.get("name", "")).lower() for item in asset.columns or []}
        if any(column not in valid for column in columns):
            return None
        connector = connectors.get(key[0]) if key[0] else None
        dialect = _source_dialect(connector, engine)
        local = connector is None
        schema, table = _local_physical(engine, asset) if local else (asset.schema_name, asset.table_name)
        try:
            statement = index_statement(dialect, schema, table, columns)
        except ValueError:
            return None
        timings = durations[(key, columns[0] if len(columns) == 1 else tuple(columns))]
        return {
            "relation": f"{asset.schema_name}.{asset.table_name}".lower(),
            "columns": columns,
            "source": "local" if local else connector.name,
            "dialect": dialect,
            "slow_queries": len(timings),
            "avg_ms": round(sum(timings) / len(timings), 1) if timings else None,
            "max_ms": round(max(timings), 1) if timings else None,
            "threshold_ms": threshold,
            "occurrences": len(timings),
            "weight": weight,
            "reason": reason,
            "statement": statement,
            "exists": local and columns[0] in _existing_leading_columns(engine, schema, table),
            "verify_note": None if local else "Check existing indexes and the execution plan on the source before applying.",
        }

    suggestions = []
    for (key, column), weight in weights.most_common():
        if len(durations[(key, column)]) < min_occurrences:
            continue
        used = ", ".join(f"{role} ×{count}" for role, count in roles[(key, column)].most_common())
        item = build(key, [column], f"used in {used} in queries slower than {threshold:g} ms", weight)
        if item:
            suggestions.append(item)
    for (key, pair), hits in pair_hits.most_common(3):
        if hits >= min_occurrences:
            item = build(key, list(pair), "columns filtered together in slow queries", hits * 4)
            if item:
                suggestions.append(item)
    suggestions.sort(key=lambda item: (item["exists"], -item["weight"]))
    return suggestions[:limit]


def create_index(engine, db: Session, project_id: str, relation: str, columns: list[str]) -> str:
    """Execute a local index DDL (only reachable when ALLOW_DDL_EXECUTION=true and an approval was granted)."""
    if not ddl_execution_allowed():
        raise PermissionError("DDL execution is disabled; suggestions are saved for DBA review (ALLOW_DDL_EXECUTION=false)")
    schema_name, _, table_name = relation.lower().partition(".")
    asset = db.scalar(select(DataAsset).where(DataAsset.project_id == project_id, DataAsset.connector_id.is_(None), DataAsset.schema_name == schema_name, DataAsset.table_name == table_name))
    if asset is None:
        raise ValueError("Relation is not a local catalogued dataset")
    valid = {str(item.get("name", "")).lower() for item in asset.columns or []}
    if not columns or any(column not in valid for column in columns):
        raise ValueError("Index columns must exist on the dataset")
    schema, table = _local_physical(engine, asset)
    statement = index_statement(_source_dialect(None, engine), schema, table, columns)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql(statement.rstrip(";"))
    return statement
