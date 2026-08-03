from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Column, MetaData, String, Table, and_, func, or_, select, text
from sqlalchemy.engine import Engine

from .staging import safe_identifier


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _failure_condition(table: Table, rule_type: str, column_name: str, config: dict[str, Any]):
    if column_name not in table.c:
        raise ValueError(f"Column {column_name} does not exist in the target relation")
    column = table.c[column_name]
    if rule_type == "not_null":
        return column.is_(None)
    if rule_type == "unique":
        duplicates = (
            select(column)
            .where(column.is_not(None))
            .group_by(column)
            .having(func.count() > 1)
        )
        return column.in_(duplicates)
    if rule_type == "accepted_values":
        values = config.get("values") or []
        if not values:
            raise ValueError("Accepted-values rules require at least one value")
        return and_(column.is_not(None), column.not_in(values))
    if rule_type == "range":
        bounds = []
        if config.get("min") is not None:
            bounds.append(column < config["min"])
        if config.get("max") is not None:
            bounds.append(column > config["max"])
        if not bounds:
            raise ValueError("Range rules require a minimum or maximum")
        condition = or_(*bounds)
        if config.get("allow_null", True):
            condition = and_(column.is_not(None), condition)
        else:
            condition = or_(column.is_(None), condition)
        return condition
    raise ValueError(f"Unsupported quality rule type: {rule_type}")


def execute_quality_rule(
    engine: Engine,
    schema_name: str,
    table_name: str,
    rule_name: str,
    rule_type: str,
    column_name: str,
    config: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    source_schema = schema_name if engine.dialect.name == "postgresql" else None
    source_table = Table(
        table_name,
        MetaData(),
        schema=source_schema,
        autoload_with=engine,
    )
    condition = _failure_condition(source_table, rule_type, column_name, config)
    with engine.connect() as connection:
        checked_rows = int(connection.scalar(select(func.count()).select_from(source_table)) or 0)
        failed_rows = int(
            connection.scalar(select(func.count()).select_from(source_table).where(condition)) or 0
        )
        failure_result = connection.execute(select(source_table).where(condition).limit(25))
        sample_failures = [
            {key: _json_value(value) for key, value in row._mapping.items()}
            for row in failure_result
        ]

    quarantine_relation = None
    if failed_rows:
        quarantine_schema = "quarantine" if engine.dialect.name == "postgresql" else None
        quarantine_name = safe_identifier(
            f"{table_name}_{column_name}_{run_id[:8]}",
            f"quality_{run_id[:8]}",
        )
        if quarantine_schema:
            with engine.begin() as connection:
                connection.execute(text("CREATE SCHEMA IF NOT EXISTS quarantine"))
        quarantine_table = Table(
            quarantine_name,
            MetaData(),
            *[Column(column.name, column.type, nullable=True) for column in source_table.columns],
            Column("_quality_rule", String(200), nullable=False),
            Column("_quality_run_id", String(36), nullable=False),
            schema=quarantine_schema,
        )
        quarantine_table.create(engine)
        with engine.begin() as connection:
            result = connection.execute(select(source_table).where(condition))
            while True:
                rows = result.fetchmany(1000)
                if not rows:
                    break
                connection.execute(
                    quarantine_table.insert(),
                    [
                        {
                            **dict(row._mapping),
                            "_quality_rule": rule_name,
                            "_quality_run_id": run_id,
                        }
                        for row in rows
                    ],
                )
        quarantine_relation = (
            f"{quarantine_schema}.{quarantine_name}"
            if quarantine_schema
            else quarantine_name
        )

    pass_rate = 100.0 if not checked_rows else round((checked_rows - failed_rows) * 100 / checked_rows, 2)
    return {
        "status": "passed" if failed_rows == 0 else "failed",
        "checked_rows": checked_rows,
        "failed_rows": failed_rows,
        "pass_rate": pass_rate,
        "sample_failures": sample_failures,
        "quarantine_relation": quarantine_relation,
    }
