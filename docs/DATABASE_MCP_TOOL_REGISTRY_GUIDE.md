# Database MCP and external tool registry

## What is implemented

DataPilot supports two read-only database connection modes behind the same governed query-tool contract:

- `direct`: native drivers for SQL Server, Oracle, Teradata, and BigQuery.
- `mcp`: an HTTP MCP server such as Google MCP Toolbox for Databases. DataPilot performs the MCP handshake, checks `tools/list`, and calls a named pre-defined upstream tool.

In both modes, external consumers see only tools that are published and explicitly granted to their client identity. Every invocation is parameter-validated, row/time bounded, audited, and emitted to governance telemetry. An MCP-backed production query tool must name a pre-defined upstream tool; DataPilot does not forward its SQL template to a generic `execute_sql` tool.

## Configure a connector

Direct SQL Server example:

```json
{
  "name": "Retail SQL Server",
  "connector_type": "sql_server",
  "connection_mode": "direct",
  "host": "sqlserver.internal",
  "database": "Retail",
  "secret_reference": "env:RETAIL_SQLSERVER_CREDENTIALS",
  "read_only": true
}
```

Google MCP Toolbox example:

```json
{
  "name": "Retail Oracle Toolbox",
  "connector_type": "oracle",
  "connection_mode": "mcp",
  "mcp_server_url": "http://mcp-toolbox:5000/mcp",
  "secret_reference": "env:RETAIL_TOOLBOX_TOKEN",
  "read_only": true
}
```

`RETAIL_TOOLBOX_TOKEN` may be a plain bearer token, `{"token":"..."}`, or `{"headers":{"Authorization":"Bearer ..."}}`. A local unauthenticated Toolbox does not need a secret reference. Credentials in URLs are rejected.

## Google MCP Toolbox examples

Safe parameterized account-lookup examples are provided for:

- [SQL Server](../infra/mcp-toolbox/mssql.tools.yaml)
- [Oracle](../infra/mcp-toolbox/oracle.tools.yaml)
- [BigQuery](../infra/mcp-toolbox/bigquery.tools.yaml)

Set the environment variables referenced by one file, download the official Toolbox 1.8 (or compatible) binary for your OS, then run:

```powershell
.\toolbox.exe --config infra/mcp-toolbox/mssql.tools.yaml
```

Toolbox listens on port `5000` by default and exposes `http://localhost:5000/mcp`. Use only the configuration for the database needed in that deployment. The npm launcher is convenient on supported platforms but did not provide a Windows x64 binary in this verification environment, so the standalone executable is the documented Windows path. For BigQuery, use Application Default Credentials or the workload identity assigned to Toolbox.

## Register, publish, and grant a tool

Create `POST /query-tools` with metadata that agents can use for discovery:

```json
{
  "name": "accounts.get",
  "description": "Return one account by numeric account identifier.",
  "purpose": "Support customer-service account lookup.",
  "data_source": "Oracle CUSTOMER",
  "line_of_business": "Retail Banking",
  "owner": "Account Operations",
  "tags": ["accounts", "customer-service", "read-only"],
  "connector_id": "<mcp-connector-id>",
  "upstream_tool_name": "get_account",
  "sql_template": "SELECT account_id, customer_id, account_type, status FROM accounts WHERE account_id = :account_id",
  "parameter_schema": {
    "type": "object",
    "required": ["account_id"],
    "properties": {"account_id": {"type": "integer"}},
    "additionalProperties": false
  },
  "result_schema": {"type": "object"},
  "allowed_relations": ["accounts"],
  "row_limit": 10,
  "timeout_seconds": 15,
  "requires_approval": false
}
```

Then:

1. Test with `POST /query-tools/{id}/test`.
2. Publish with `POST /query-tools/{id}/publish` (admin).
3. Create a client with `POST /external-clients`; copy its one-time token.
4. Grant with `POST /query-tools/{id}/grants`.

## External discovery and invocation

Search granted tools:

```http
GET /external/v1/query-tools?q=account&line_of_business=retail&tag=read-only
Authorization: Bearer <external-client-token>
```

Get a named contract with `GET /external/v1/query-tools/{name}` and invoke it with:

```http
POST /external/v1/query-tools/accounts.get/invoke
Authorization: Bearer <external-client-token>
Content-Type: application/json

{"parameters":{"account_id":50150}}
```

MCP clients use `POST /mcp`. `tools/list` returns the input/output schemas and registry metadata under `_meta.com.datapilot.registry`; `tools/call` invokes the same audited path.

## VS Code and Google ADK

The checked-in [.vscode/mcp.json](../.vscode/mcp.json) configures VS Code to connect to DataPilot and securely prompts for the external token. Start the API, issue/grant a client token, open **MCP: List Servers**, start `datapilot-governed-data`, and enable its tools in Chat.

The [Google ADK account agent](../examples/google_adk_account_agent/agent.py) searches registry metadata before invoking a tool. Install its optional dependencies and set credentials:

```powershell
pip install -r examples/google_adk_account_agent/requirements.txt
$env:DATAPILOT_EXTERNAL_TOKEN = '<one-time-token>'
$env:GOOGLE_API_KEY = '<gemini-key>'
adk web examples
```

For a deterministic client test that does not require Gemini:

```powershell
$env:DATAPILOT_EXTERNAL_TOKEN = '<one-time-token>'
python examples/google_adk_account_agent/demo_account_lookup.py --tool accounts.count_since --parameters '{"minimum_id":50150}'
```

## Validation boundary

Automated tests cover connector contract validation, the outbound MCP handshake/session header and dispatch, registry metadata persistence/search, grant isolation, MCP discovery metadata, and invocation. All three example YAML files also pass Google MCP Toolbox 1.8.0 `migrate --dry-run` parser validation. Live SQL Server, Oracle, BigQuery, and Gemini result certification still requires reachable organization endpoints and credentials; the repository does not claim those external systems were contacted during offline validation.
