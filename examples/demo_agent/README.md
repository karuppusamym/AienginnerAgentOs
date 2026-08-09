# DataPilot Demo Agent

An external Python agent that demonstrates the **External AI Developer** flow
from the DataPilot architecture deck — connecting to a live DataPilot instance
through the governed external API and MCP protocol.

---

## What it does

1. **REST discovery** — `GET /external/v1/query-tools` returns all tools granted to this client
2. **REST invocation** — `POST /external/v1/query-tools/{name}/invoke` with typed parameters
3. **MCP discovery** — `POST /mcp` → `tools/list` via JSON-RPC 2.0
4. **MCP invocation** — `POST /mcp` → `tools/call` with structured arguments

Every call goes through DataPilot's governance layer:
- Bearer token → grant lookup → scope check
- Parameter schema validation
- Row limit enforcement  
- PII masking (email, phone, etc.)
- Audit log entry written to PostgreSQL
- Governance telemetry emitted (AgentGuard / OTLP / webhook)

---

## Prerequisites

```powershell
# 1. Start the full stack (including new DB containers)
docker compose up -d

# 2. Register connectors, tools, and get a token
python scripts/register_demo_connectors.py

# 3. Install agent dependencies
pip install -r examples/demo_agent/requirements.txt
```

---

## Run the full demo

```powershell
# Uses the token auto-saved by register_demo_connectors.py
python examples/demo_agent/agent.py
```

Expected output: rich terminal tables showing results from all 4 tools
via both REST and MCP paths, with governance summary at the end.

---

## Run a single tool

```powershell
python examples/demo_agent/agent.py `
    --tool sqlserver.customers.list `
    --params '{"status":"active"}'
```

```powershell
python examples/demo_agent/agent.py `
    --tool postgres.orders.recent `
    --params '{"status":"completed"}'
```

---

## Use a custom token

```powershell
$env:DATAPILOT_EXTERNAL_TOKEN = "<your-token>"
python examples/demo_agent/agent.py
```

Or pass it directly:

```powershell
python examples/demo_agent/agent.py --token "<your-token>"
```

---

## Available tools (after registration)

| Tool name | Connector | Mode | Description |
|-----------|-----------|------|-------------|
| `sqlserver.customers.list` | Demo SQL Server | Direct | Filter customers by status |
| `mcp.sqlserver.payments.by_status` | Demo SQL Server | MCP | Payments by settlement status |
| `postgres.orders.recent` | Demo PostgreSQL | Direct | Recent orders, optional status filter |
| `mcp.postgres.payments.summary` | Demo PostgreSQL | MCP | Payment totals grouped by method/status |

---

## Sequence diagram mapping

```
Demo Agent                      DataPilot API (/external/v1/ or /mcp)
   │                                      │
   │── GET /external/v1/query-tools ─────►│  discover granted tools
   │◄─ [{name, description, metadata}] ───│
   │                                      │
   │── POST …/invoke {parameters} ───────►│  validate params → check grant
   │                                      │── connector/MCP call
   │                                      │── PII masking
   │                                      │── audit log
   │◄─ {columns, rows, row_count} ────────│
```
