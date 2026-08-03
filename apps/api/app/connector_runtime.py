from __future__ import annotations

import json
import os
import time
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .models import Connector
from .governance import record_governance_event


class ConnectorRuntimeError(RuntimeError):
    pass


@dataclass
class ConnectionTest:
    status: str
    message: str
    latency_ms: int


@dataclass
class MetadataDiscovery:
    assets: list[dict[str, Any]]
    summary: dict[str, int]


def resolve_credentials(secret_reference: str | None) -> dict[str, Any]:
    if not secret_reference or not secret_reference.startswith("env:"):
        raise ConnectorRuntimeError("An env: secret reference is required")
    variable = secret_reference[4:].strip()
    raw = os.getenv(variable, "")
    if not variable or not raw:
        raise ConnectorRuntimeError(f"Environment variable {variable or '<empty>'} is not configured")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    prefix = variable
    for suffix in ("_PASSWORD", "_CREDENTIALS", "_SECRET"):
        if prefix.endswith(suffix):
            prefix = prefix[: -len(suffix)]
            break
    username = os.getenv(f"{prefix}_USERNAME", "")
    if not username:
        raise ConnectorRuntimeError(
            f"{variable} contains a password, but {prefix}_USERNAME is not configured"
        )
    return {"username": username, "password": raw}


def _mcp_headers(secret_reference: str | None) -> dict[str, str]:
    """Resolve optional upstream MCP authentication without storing a token."""
    if not secret_reference:
        return {}
    if not secret_reference.startswith("env:"):
        raise ConnectorRuntimeError("An env: secret reference is required for MCP authentication")
    variable = secret_reference[4:].strip()
    raw = os.getenv(variable, "")
    if not variable or not raw:
        raise ConnectorRuntimeError(f"Environment variable {variable or '<empty>'} is not configured")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        configured = parsed.get("headers")
        if configured is not None:
            if not isinstance(configured, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in configured.items()
            ):
                raise ConnectorRuntimeError("MCP credential headers must be a string-to-string object")
            return dict(configured)
        token = parsed.get("token") or parsed.get("access_token")
        if token:
            return {"Authorization": f"Bearer {token}"}
        raise ConnectorRuntimeError("MCP credentials require headers, token, or access_token")
    return {"Authorization": f"Bearer {raw}"}


def _mcp_endpoint(connector: Connector) -> str:
    endpoint = str(connector.mcp_server_url or "").strip()
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConnectorRuntimeError("MCP connection mode requires an http(s) MCP server URL")
    if parsed.username or parsed.password:
        raise ConnectorRuntimeError("MCP server credentials must not be embedded in the URL")
    return endpoint


def _mcp_json(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if "text/event-stream" in content_type:
        for line in response.text.splitlines():
            if line.startswith("data:"):
                candidate = line[5:].strip()
                if candidate and candidate != "[DONE]":
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        return parsed
        raise ConnectorRuntimeError("The MCP server returned no JSON event")
    parsed = response.json()
    if not isinstance(parsed, dict):
        raise ConnectorRuntimeError("The MCP server returned an invalid JSON-RPC response")
    return parsed


def _mcp_request(
    connector: Connector,
    method: str,
    params: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    endpoint = _mcp_endpoint(connector)
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        **_mcp_headers(connector.secret_reference),
    }
    with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
        initialize_response = client.post(
            endpoint,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": "datapilot-initialize",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "DataPilot", "version": "1.0.0"},
                },
            },
        )
        initialized = _mcp_json(initialize_response)
        if "error" in initialized:
            raise ConnectorRuntimeError(f"MCP initialize failed: {initialized['error']}")
        session_id = initialize_response.headers.get("mcp-session-id")
        session_headers = {**headers, **({"Mcp-Session-Id": session_id} if session_id else {})}
        notification = client.post(
            endpoint,
            headers=session_headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        if notification.status_code >= 400:
            notification.raise_for_status()
        response = client.post(
            endpoint,
            headers=session_headers,
            json={"jsonrpc": "2.0", "id": "datapilot-call", "method": method, "params": params},
        )
        payload = _mcp_json(response)
    if "error" in payload:
        raise ConnectorRuntimeError(f"MCP {method} failed: {payload['error']}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ConnectorRuntimeError(f"MCP {method} returned no result object")
    return result


def list_mcp_tools(connector: Connector, timeout_seconds: int = 15) -> list[dict[str, Any]]:
    result = _mcp_request(connector, "tools/list", {}, timeout_seconds)
    tools = result.get("tools", [])
    if not isinstance(tools, list):
        raise ConnectorRuntimeError("MCP tools/list returned an invalid tool list")
    return [item for item in tools if isinstance(item, dict)]


def _normalize_mcp_result(result: dict[str, Any], limit: int, started: float) -> dict[str, Any]:
    if result.get("isError"):
        raise ConnectorRuntimeError("The upstream MCP tool reported an execution error")
    value: Any = result.get("structuredContent")
    if value is None:
        text_parts = [
            item.get("text", "")
            for item in result.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        text_value = "\n".join(part for part in text_parts if part)
        try:
            value = json.loads(text_value) if text_value else []
        except json.JSONDecodeError:
            value = {"result": text_value}
    if isinstance(value, dict) and isinstance(value.get("rows"), list):
        rows = value["rows"]
        columns = value.get("columns") or (
            list(rows[0]) if rows and isinstance(rows[0], dict) else []
        )
    elif isinstance(value, list):
        rows = value
        columns = list(rows[0]) if rows and isinstance(rows[0], dict) else ["result"]
    elif isinstance(value, dict):
        rows = [value]
        columns = list(value)
    else:
        rows = [{"result": value}]
        columns = ["result"]
    normalized_rows = [row if isinstance(row, dict) else {"result": row} for row in rows]
    truncated = len(normalized_rows) > limit
    return {
        "columns": [str(column) for column in columns],
        "rows": normalized_rows[:limit],
        "row_count": min(len(normalized_rows), limit),
        "truncated": truncated,
        "limit": limit,
        "duration_ms": round((time.perf_counter() - started) * 1000),
    }


def execute_mcp_tool(
    connector: Connector,
    tool_name: str | None,
    parameters: dict[str, Any],
    limit: int,
    timeout_seconds: int,
    started: float,
) -> dict[str, Any]:
    if not tool_name:
        raise ConnectorRuntimeError("An upstream MCP tool name is required")
    available = {str(item.get("name", "")) for item in list_mcp_tools(connector, timeout_seconds)}
    if tool_name not in available:
        raise ConnectorRuntimeError(f"Upstream MCP tool is not available: {tool_name}")
    result = _mcp_request(
        connector,
        "tools/call",
        {"name": tool_name, "arguments": parameters},
        timeout_seconds,
    )
    return _normalize_mcp_result(result, limit, started)


def _required(credentials: dict[str, Any], key: str, alternative: str | None = None) -> str:
    value = credentials.get(key) or (credentials.get(alternative) if alternative else None)
    if value is None or str(value).strip() == "":
        raise ConnectorRuntimeError(f"Connector credentials are missing {key}")
    return str(value)


def _group_columns(rows: list[tuple[Any, ...]]) -> MetadataDiscovery:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for schema_name, table_name, column_name, data_type, nullable, *_ in rows:
        grouped[(str(schema_name), str(table_name))].append(
            {
                "name": str(column_name),
                "type": str(data_type),
                "nullable": str(nullable).upper() in {"YES", "Y", "TRUE", "1"},
            }
        )
    assets = [
        {
            "schema_name": schema,
            "table_name": table,
            "columns": columns,
            "tags": _classify_columns(columns),
        }
        for (schema, table), columns in grouped.items()
    ]
    return MetadataDiscovery(
        assets=assets,
        summary={
            "schemas": len({asset["schema_name"] for asset in assets}),
            "tables": len(assets),
            "columns": sum(len(asset["columns"]) for asset in assets),
        },
    )


def _classify_columns(columns: list[dict[str, Any]]) -> list[str]:
    sensitive_tokens = {
        "address",
        "birth",
        "dob",
        "email",
        "first_name",
        "last_name",
        "phone",
        "social_security",
        "ssn",
    }
    names = {str(column["name"]).lower() for column in columns}
    return ["PII-candidate"] if any(token in name for name in names for token in sensitive_tokens) else []


def _sql_server(connector: Connector, credentials: dict[str, Any], scan: bool) -> MetadataDiscovery | None:
    try:
        import pymssql
    except ImportError as exc:
        raise ConnectorRuntimeError("The SQL Server driver is not installed") from exc
    connection = pymssql.connect(
        server=_required({"host": connector.host}, "host"),
        user=_required(credentials, "username", "user"),
        password=_required(credentials, "password"),
        database=_required({"database": connector.database}, "database"),
        login_timeout=10,
        timeout=30,
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            if not scan:
                cursor.execute("SELECT 1")
                cursor.fetchone()
                return None
            cursor.execute(
                """
                SELECT TOP 5000 TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE,
                       IS_NULLABLE, ORDINAL_POSITION
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA NOT IN ('sys', 'INFORMATION_SCHEMA')
                ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
                """
            )
            return _group_columns(list(cursor.fetchall()))
    finally:
        connection.close()


def _postgres(connector: Connector, credentials: dict[str, Any], scan: bool) -> MetadataDiscovery | None:
    """Connect with the project's existing psycopg driver using a read-only probe."""
    try:
        import psycopg
    except ImportError as exc:
        raise ConnectorRuntimeError("The PostgreSQL driver is not installed") from exc
    connection = psycopg.connect(
        host=_required({"host": connector.host}, "host"),
        port=int(credentials.get("port", 5432)),
        user=_required(credentials, "username", "user"),
        password=_required(credentials, "password"),
        dbname=_required({"database": connector.database}, "database"),
        connect_timeout=10,
        options="-c default_transaction_read_only=on",
    )
    try:
        with connection.cursor() as cursor:
            if not scan:
                cursor.execute("SELECT 1")
                cursor.fetchone()
                return None
            cursor.execute(
                """
                SELECT table_schema, table_name, column_name, data_type,
                       is_nullable, ordinal_position
                FROM information_schema.columns
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_schema, table_name, ordinal_position
                LIMIT 5000
                """
            )
            return _group_columns(list(cursor.fetchall()))
    finally:
        connection.close()


def _oracle(connector: Connector, credentials: dict[str, Any], scan: bool) -> MetadataDiscovery | None:
    try:
        import oracledb
    except ImportError as exc:
        raise ConnectorRuntimeError("The Oracle driver is not installed") from exc
    dsn = credentials.get("dsn") or (
        f"{_required({'host': connector.host}, 'host')}/{_required({'service': connector.database}, 'service')}"
    )
    connection = oracledb.connect(
        user=_required(credentials, "username", "user"),
        password=_required(credentials, "password"),
        dsn=str(dsn),
    )
    try:
        with connection.cursor() as cursor:
            if not scan:
                cursor.execute("SELECT 1 FROM dual")
                cursor.fetchone()
                return None
            cursor.execute(
                """
                SELECT OWNER, TABLE_NAME, COLUMN_NAME, DATA_TYPE, NULLABLE, COLUMN_ID
                FROM ALL_TAB_COLUMNS
                WHERE OWNER NOT IN ('SYS', 'SYSTEM', 'XDB', 'MDSYS', 'CTXSYS')
                  AND ROWNUM <= 5000
                ORDER BY OWNER, TABLE_NAME, COLUMN_ID
                """
            )
            return _group_columns(list(cursor.fetchall()))
    finally:
        connection.close()


def _teradata(connector: Connector, credentials: dict[str, Any], scan: bool) -> MetadataDiscovery | None:
    try:
        import teradatasql
    except ImportError as exc:
        raise ConnectorRuntimeError("The Teradata driver is not installed") from exc
    connection = teradatasql.connect(
        host=_required({"host": connector.host}, "host"),
        user=_required(credentials, "username", "user"),
        password=_required(credentials, "password"),
        database=connector.database or "",
        logmech=str(credentials.get("logmech", "TD2")),
    )
    try:
        with connection.cursor() as cursor:
            if not scan:
                cursor.execute("SELECT 1")
                cursor.fetchone()
                return None
            database_name = _required({"database": connector.database}, "database")
            cursor.execute(
                """
                SELECT TOP 5000 DatabaseName, TableName, ColumnName, ColumnType,
                       Nullable, ColumnId
                FROM DBC.ColumnsV
                WHERE DatabaseName = ?
                ORDER BY DatabaseName, TableName, ColumnId
                """,
                [database_name],
            )
            return _group_columns(list(cursor.fetchall()))
    finally:
        connection.close()


def _bigquery(connector: Connector, credentials: dict[str, Any], scan: bool) -> MetadataDiscovery | None:
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError as exc:
        raise ConnectorRuntimeError("The BigQuery driver is not installed") from exc

    project = connector.host or credentials.get("project_id")
    if not project:
        raise ConnectorRuntimeError("BigQuery requires a project in Host / project")
    service_account_value = credentials.get("service_account") or credentials
    if isinstance(service_account_value, str):
        path = Path(service_account_value)
        if not path.is_file():
            raise ConnectorRuntimeError("The BigQuery service-account file does not exist")
        auth = service_account.Credentials.from_service_account_file(path)
    else:
        auth = service_account.Credentials.from_service_account_info(service_account_value)
    client = bigquery.Client(project=project, credentials=auth)
    if not scan:
        list(client.query("SELECT 1").result(timeout=30))
        return None

    dataset_ids = [connector.database] if connector.database else [item.dataset_id for item in client.list_datasets(max_results=50)]
    assets: list[dict[str, Any]] = []
    for dataset_id in dataset_ids:
        for table_item in client.list_tables(f"{project}.{dataset_id}", max_results=500):
            table = client.get_table(table_item.reference)
            columns = [
                {"name": field.name, "type": field.field_type, "nullable": field.mode != "REQUIRED"}
                for field in table.schema
            ]
            assets.append(
                {
                    "schema_name": str(dataset_id),
                    "table_name": table.table_id,
                    "columns": columns,
                    "tags": _classify_columns(columns),
                    "row_count": table.num_rows,
                }
            )
    return MetadataDiscovery(
        assets=assets,
        summary={
            "schemas": len({asset["schema_name"] for asset in assets}),
            "tables": len(assets),
            "columns": sum(len(asset["columns"]) for asset in assets),
        },
    )


ADAPTERS = {
    "postgres": _postgres,
    "sql_server": _sql_server,
    "oracle": _oracle,
    "teradata": _teradata,
    "bigquery": _bigquery,
}


FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|truncate|create|grant|revoke|call|exec(?:ute)?|copy|unload)\b",
    re.IGNORECASE,
)


def _validate_read_only_query(sql: str) -> str:
    normalized = sql.strip().rstrip(";").strip()
    if not normalized or ";" in normalized or not re.match(r"^(select|with)\b", normalized, re.I):
        raise ConnectorRuntimeError("Exactly one read-only SELECT statement is required")
    if FORBIDDEN_SQL.search(normalized):
        raise ConnectorRuntimeError("The query contains a prohibited operation")
    return normalized


def _ordered_parameters(sql: str, parameters: dict[str, Any], marker: str) -> tuple[str, list[Any]]:
    values: list[Any] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in parameters:
            raise ConnectorRuntimeError(f"Missing query parameter: {name}")
        values.append(parameters[name])
        return marker

    return re.sub(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", replace, sql), values


def execute_connector_query(
    connector: Connector,
    sql: str,
    parameters: dict[str, Any],
    limit: int,
    timeout_seconds: int,
    upstream_tool_name: str | None = None,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    tenant_id: str | None = None,
    feature: str = "connector_query",
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        normalized = _validate_read_only_query(sql)
        if getattr(connector, "connection_mode", "direct") == "mcp":
            result_payload = execute_mcp_tool(
                connector,
                upstream_tool_name,
                parameters,
                limit,
                timeout_seconds,
                started,
            )
            record_governance_event(
                "connector_query",
                connector.connector_type,
                "succeeded",
                project_id=connector.project_id,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                feature=feature,
                connector_id=connector.id,
                row_count=result_payload["row_count"],
                duration_ms=result_payload["duration_ms"],
                read_only=True,
                connection_mode="mcp",
            )
            return result_payload
        credentials = resolve_credentials(connector.secret_reference)
        rows: list[Any]
        columns: list[str]

        if connector.connector_type == "sql_server":
            import pymssql

            statement, values = _ordered_parameters(normalized, parameters, "%s")
            connection = pymssql.connect(
                server=_required({"host": connector.host}, "host"),
                user=_required(credentials, "username", "user"),
                password=_required(credentials, "password"),
                database=_required({"database": connector.database}, "database"),
                login_timeout=10,
                timeout=timeout_seconds,
                autocommit=True,
            )
            try:
                with connection.cursor() as cursor:
                    cursor.execute(statement, tuple(values))
                    columns = [str(item[0]) for item in cursor.description]
                    rows = list(cursor.fetchmany(limit + 1))
            finally:
                connection.close()
        elif connector.connector_type == "postgres":
            import psycopg

            statement, values = _ordered_parameters(normalized, parameters, "%s")
            connection = psycopg.connect(
                host=_required({"host": connector.host}, "host"),
                port=int(credentials.get("port", 5432)),
                user=_required(credentials, "username", "user"),
                password=_required(credentials, "password"),
                dbname=_required({"database": connector.database}, "database"),
                connect_timeout=10,
                options="-c default_transaction_read_only=on",
            )
            try:
                with connection.cursor() as cursor:
                    cursor.execute(f"SET LOCAL statement_timeout = {int(timeout_seconds * 1000)}")
                    cursor.execute(statement, tuple(values))
                    columns = [str(item.name) for item in cursor.description]
                    rows = list(cursor.fetchmany(limit + 1))
            finally:
                connection.close()
        elif connector.connector_type == "oracle":
            import oracledb

            dsn = credentials.get("dsn") or f"{connector.host}/{connector.database}"
            connection = oracledb.connect(
                user=_required(credentials, "username", "user"),
                password=_required(credentials, "password"),
                dsn=str(dsn),
            )
            try:
                with connection.cursor() as cursor:
                    cursor.call_timeout = timeout_seconds * 1000
                    cursor.execute(normalized, parameters)
                    columns = [str(item[0]).lower() for item in cursor.description]
                    rows = list(cursor.fetchmany(limit + 1))
            finally:
                connection.close()
        elif connector.connector_type == "teradata":
            import teradatasql

            statement, values = _ordered_parameters(normalized, parameters, "?")
            connection = teradatasql.connect(
                host=_required({"host": connector.host}, "host"),
                user=_required(credentials, "username", "user"),
                password=_required(credentials, "password"),
                database=connector.database or "",
                logmech=str(credentials.get("logmech", "TD2")),
            )
            try:
                with connection.cursor() as cursor:
                    cursor.execute(statement, values)
                    columns = [str(item[0]) for item in cursor.description]
                    rows = list(cursor.fetchmany(limit + 1))
            finally:
                connection.close()
        elif connector.connector_type == "bigquery":
            from google.cloud import bigquery
            from google.oauth2 import service_account

            project = connector.host or credentials.get("project_id")
            service_account_value = credentials.get("service_account") or credentials
            auth = (
                service_account.Credentials.from_service_account_file(service_account_value)
                if isinstance(service_account_value, str)
                else service_account.Credentials.from_service_account_info(service_account_value)
            )
            client = bigquery.Client(project=project, credentials=auth)
            query_parameters = []
            for name, value in parameters.items():
                parameter_type = "BOOL" if isinstance(value, bool) else "INT64" if isinstance(value, int) else "FLOAT64" if isinstance(value, float) else "STRING"
                query_parameters.append(bigquery.ScalarQueryParameter(name, parameter_type, value))
            query_job = client.query(normalized, job_config=bigquery.QueryJobConfig(query_parameters=query_parameters))
            result = query_job.result(timeout=timeout_seconds, max_results=limit + 1)
            columns = [field.name for field in result.schema]
            rows = [tuple(row[column] for column in columns) for row in result]
        else:
            raise ConnectorRuntimeError(f"Query execution is not supported for {connector.connector_type}")

        truncated = len(rows) > limit
        result_payload = {
            "columns": columns,
            "rows": [dict(zip(columns, row, strict=False)) for row in rows[:limit]],
            "row_count": min(len(rows), limit),
            "truncated": truncated,
            "limit": limit,
            "duration_ms": round((time.perf_counter() - started) * 1000),
        }
        record_governance_event(
            "connector_query",
            connector.connector_type,
            "succeeded",
            project_id=connector.project_id,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            feature=feature,
            connector_id=connector.id,
            row_count=result_payload["row_count"],
            duration_ms=result_payload["duration_ms"],
            read_only=True,
        )
        return result_payload
    except Exception as exc:
        record_governance_event(
            "connector_query",
            connector.connector_type,
            "failed",
            project_id=connector.project_id,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            feature=feature,
            connector_id=connector.id,
            duration_ms=round((time.perf_counter() - started) * 1000),
            read_only=True,
            error_type=type(exc).__name__,
        )
        raise


def test_connection(connector: Connector) -> ConnectionTest:
    if connector.connector_type == "local_files":
        return ConnectionTest("healthy", "Local file storage is available", 0)
    if connector.host == "mock-sqlserver":
        return ConnectionTest("healthy", "Offline demonstration catalog is available", 0)
    if getattr(connector, "connection_mode", "direct") == "mcp":
        started = time.perf_counter()
        tools = list_mcp_tools(connector)
        return ConnectionTest(
            "healthy",
            f"Upstream MCP handshake passed; {len(tools)} tools available",
            round((time.perf_counter() - started) * 1000),
        )
    adapter = ADAPTERS.get(connector.connector_type)
    if adapter is None:
        raise ConnectorRuntimeError(f"Unsupported connector type: {connector.connector_type}")
    credentials = resolve_credentials(connector.secret_reference)
    started = time.perf_counter()
    try:
        adapter(connector, credentials, False)
    except ConnectorRuntimeError:
        raise
    except Exception as exc:
        raise ConnectorRuntimeError(f"Connection failed: {type(exc).__name__}: {exc}") from exc
    return ConnectionTest(
        "healthy",
        "Read-only connection and query probe passed",
        round((time.perf_counter() - started) * 1000),
    )


def discover_metadata(connector: Connector) -> MetadataDiscovery:
    if connector.host == "mock-sqlserver":
        raise ConnectorRuntimeError("The demonstration connector uses its seeded offline catalog")
    if getattr(connector, "connection_mode", "direct") == "mcp":
        raise ConnectorRuntimeError(
            "Metadata scanning through MCP is not configured; use a direct connector or publish a dedicated metadata tool"
        )
    adapter = ADAPTERS.get(connector.connector_type)
    if adapter is None:
        raise ConnectorRuntimeError(f"Metadata discovery is not available for {connector.connector_type}")
    credentials = resolve_credentials(connector.secret_reference)
    try:
        discovery = adapter(connector, credentials, True)
    except ConnectorRuntimeError:
        raise
    except Exception as exc:
        raise ConnectorRuntimeError(f"Metadata discovery failed: {type(exc).__name__}: {exc}") from exc
    if discovery is None:
        raise ConnectorRuntimeError("The connector returned no metadata result")
    return discovery
