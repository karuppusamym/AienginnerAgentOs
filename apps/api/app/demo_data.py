from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, inspect, text
from sqlalchemy.engine import Engine


def ensure_demo_tables(engine: Engine) -> None:
    is_postgres = engine.dialect.name == "postgresql"
    schema = "core" if is_postgres else None
    if is_postgres:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
    inspector = inspect(engine)
    if "accounts" in inspector.get_table_names(schema=schema):
        return

    metadata = MetaData()
    accounts = Table(
        "accounts",
        metadata,
        Column("account_id", Integer, primary_key=True),
        Column("customer_id", Integer, nullable=False),
        Column("account_type", String(30), nullable=False),
        Column("status", String(30), nullable=False),
        Column("opened_at", DateTime, nullable=False),
        schema=schema,
    )
    metadata.create_all(engine, tables=[accounts])
    rows = [
        {"account_id": 50101, "customer_id": 1001, "account_type": "checking", "status": "active", "opened_at": datetime(2026, 4, 3, 9)},
        {"account_id": 50122, "customer_id": 1002, "account_type": "savings", "status": "active", "opened_at": datetime(2026, 4, 19, 9)},
        {"account_id": 50137, "customer_id": 1003, "account_type": "checking", "status": "active", "opened_at": datetime(2026, 5, 7, 9)},
        {"account_id": 50148, "customer_id": 1004, "account_type": "savings", "status": "inactive", "opened_at": datetime(2026, 5, 22, 9)},
        {"account_id": 50155, "customer_id": 1005, "account_type": "checking", "status": "active", "opened_at": datetime(2026, 6, 2, 9)},
        {"account_id": 50161, "customer_id": 1006, "account_type": "savings", "status": "active", "opened_at": datetime(2026, 6, 18, 9)},
        {"account_id": 50170, "customer_id": 1007, "account_type": "checking", "status": "active", "opened_at": datetime(2026, 7, 9, 9)},
        {"account_id": 50188, "customer_id": 1008, "account_type": "savings", "status": "active", "opened_at": datetime(2026, 7, 21, 9)},
    ]
    with engine.begin() as connection:
        connection.execute(accounts.insert(), rows)
