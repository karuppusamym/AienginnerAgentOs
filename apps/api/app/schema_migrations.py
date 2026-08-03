from __future__ import annotations

from sqlalchemy import Engine, inspect, text


PROJECT_SCOPED_TABLES = (
    "model_call_logs",
    "user_feedback",
    "connectors",
    "data_assets",
    "ingested_files",
    "ingestion_mappings",
    "external_extractions",
    "quality_rules",
    "quality_runs",
    "jobs",
    "approvals",
    "audit_events",
    "artifacts",
    "ingestion_schedules",
    "evaluation_sets",
    "semantic_join_policies",
)


def ensure_project_columns(engine: Engine) -> None:
    """Upgrade databases created before project isolation was introduced."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table_name in PROJECT_SCOPED_TABLES:
            if table_name not in existing_tables:
                continue
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            if "project_id" not in columns:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN project_id VARCHAR(36)"))
            index_name = f"ix_{table_name}_project_id"
            if engine.dialect.name == "postgresql":
                connection.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} (project_id)")
                )
        if "model_call_logs" in existing_tables:
            model_columns = {column["name"] for column in inspector.get_columns("model_call_logs")}
            for column_name, definition in (
                ("input_tokens", "INTEGER NOT NULL DEFAULT 0"),
                ("output_tokens", "INTEGER NOT NULL DEFAULT 0"),
                ("estimated_cost_usd", "FLOAT NOT NULL DEFAULT 0"),
            ):
                if column_name not in model_columns:
                    connection.execute(text(f"ALTER TABLE model_call_logs ADD COLUMN {column_name} {definition}"))
        if "conversations" in existing_tables:
            conversation_columns = {column["name"] for column in inspector.get_columns("conversations")}
            if "summary" not in conversation_columns:
                connection.execute(text("ALTER TABLE conversations ADD COLUMN summary TEXT NOT NULL DEFAULT ''"))
        if "jobs" in existing_tables:
            job_columns = {column["name"] for column in inspector.get_columns("jobs")}
            if "outputs" not in job_columns:
                connection.execute(text("ALTER TABLE jobs ADD COLUMN outputs JSON"))
        if "connectors" in existing_tables:
            connector_columns = {column["name"] for column in inspector.get_columns("connectors")}
            if "description" not in connector_columns:
                connection.execute(text("ALTER TABLE connectors ADD COLUMN description TEXT"))
            if "connection_mode" not in connector_columns:
                connection.execute(text("ALTER TABLE connectors ADD COLUMN connection_mode VARCHAR(24) NOT NULL DEFAULT 'direct'"))
            if "mcp_server_url" not in connector_columns:
                connection.execute(text("ALTER TABLE connectors ADD COLUMN mcp_server_url TEXT"))
        if "query_tools" in existing_tables:
            query_tool_columns = {column["name"] for column in inspector.get_columns("query_tools")}
            for column_name, definition in (
                ("purpose", "TEXT NOT NULL DEFAULT ''"),
                ("data_source", "VARCHAR(160) NOT NULL DEFAULT ''"),
                ("line_of_business", "VARCHAR(160) NOT NULL DEFAULT ''"),
                ("owner", "VARCHAR(160) NOT NULL DEFAULT ''"),
                ("tags", "JSON"),
                ("upstream_tool_name", "VARCHAR(160)"),
            ):
                if column_name not in query_tool_columns:
                    connection.execute(text(f"ALTER TABLE query_tools ADD COLUMN {column_name} {definition}"))


def backfill_project_columns(engine: Engine, project_id: str) -> None:
    with engine.begin() as connection:
        for table_name in PROJECT_SCOPED_TABLES:
            connection.execute(
                text(f"UPDATE {table_name} SET project_id = :project_id WHERE project_id IS NULL"),
                {"project_id": project_id},
            )
