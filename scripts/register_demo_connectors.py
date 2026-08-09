#!/usr/bin/env python3
"""
DataPilot Demo — Connector & Tool Registration Script
======================================================
Automates the complete setup of demo connectors, query tools,
external client, and grants through the DataPilot API.

Usage:
    python register_demo_connectors.py [--api http://localhost:8000] [--verbose]

Output:
    scripts/.demo_setup.json  — saved IDs and external token for use by demo_agent.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

# ─── Configuration ────────────────────────────────────────────────────────────

DEFAULT_API = "http://localhost:8000"
ADMIN_EMAIL = os.environ.get("DATAPILOT_ADMIN_EMAIL", "admin@datapilot.local")
ADMIN_PASS  = os.environ.get("DATAPILOT_ADMIN_PASSWORD", "ChangeMe123!")

CONNECTORS = [
    {
        "name":             "Demo SQL Server — Direct",
        "connector_type":   "sql_server",
        "connection_mode":  "direct",
        "description":      "Direct SQL Server connection to the DemoDB container. "
                            "Tables: demo.customers, demo.orders, demo.payments.",
        "host":             "sqlserver-demo",
        "database":         "DemoDB",
        "secret_reference": "env:SQLSERVER_DEMO_CREDENTIALS",
        "read_only":        True,
    },
    {
        "name":             "Demo SQL Server — MCP",
        "connector_type":   "sql_server",
        "connection_mode":  "mcp",
        "description":      "MCP Toolbox connection to the SQL Server DemoDB container. "
                            "Exposes: sqlserver.customers.list, sqlserver.orders.by_customer, "
                            "sqlserver.payments.by_status.",
        "mcp_server_url":   "http://mcp-toolbox:5000/mcp",
        "read_only":        True,
    },
    {
        "name":             "Demo PostgreSQL — Direct",
        "connector_type":   "postgres",
        "connection_mode":  "direct",
        "description":      "Direct PostgreSQL connection to the demodb container. "
                            "Tables: demo.customers, demo.orders, demo.payments.",
        "host":             "postgres-demo",
        "database":         "demodb",
        "secret_reference": "env:POSTGRES_DEMO_CREDENTIALS",
        "read_only":        True,
    },
    {
        "name":             "Demo PostgreSQL — MCP",
        "connector_type":   "postgres",
        "connection_mode":  "mcp",
        "description":      "MCP Toolbox connection to the PostgreSQL demo container. "
                            "Exposes: postgres.customers.lookup, postgres.orders.recent, "
                            "postgres.payments.summary.",
        "mcp_server_url":   "http://mcp-toolbox:5000/mcp",
        "read_only":        True,
    },
]

QUERY_TOOLS = [
    {
        "_connector_index": 0,   # Demo SQL Server — Direct
        "name":             "sqlserver.customers.list",
        "description":      "Return a bounded list of customers from the SQL Server demo database.",
        "purpose":          "Customer service — look up customer accounts by status.",
        "data_source":      "SQL Server DemoDB",
        "line_of_business": "Retail Banking",
        "owner":            "Customer Operations",
        "tags":             ["customers", "sql-server", "read-only", "demo"],
        "sql_template":     "SELECT TOP 50 customer_id, first_name, last_name, email, phone, status, segment FROM demo.customers WHERE (:status IS NULL OR status = :status) ORDER BY customer_id",
        "parameter_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status: active, inactive, suspended. Leave empty for all."}
            },
            "additionalProperties": False,
        },
        "result_schema":    {"type": "array"},
        "allowed_relations":["demo.customers"],
        "row_limit":        50,
        "timeout_seconds":  15,
        "requires_approval":False,
    },
    {
        "_connector_index": 1,   # Demo SQL Server — MCP
        "name":             "mcp.sqlserver.payments.by_status",
        "description":      "Return payments by status via MCP Toolbox from SQL Server.",
        "purpose":          "Payment operations — review payments by settlement status.",
        "data_source":      "SQL Server DemoDB via MCP Toolbox",
        "line_of_business": "Payments",
        "owner":            "Payment Operations",
        "tags":             ["payments", "sql-server", "mcp", "read-only", "demo"],
        "upstream_tool_name": "sqlserver.payments.by_status",
        "sql_template":     "SELECT TOP 50 payment_id, order_id, payment_date, method, amount, status, reference FROM demo.payments WHERE status = :status ORDER BY payment_date DESC",
        "parameter_schema": {
            "type": "object",
            "required": ["status"],
            "properties": {
                "status": {"type": "string", "description": "Payment status: settled, pending, or refunded"}
            },
            "additionalProperties": False,
        },
        "result_schema":    {"type": "array"},
        "allowed_relations":["demo.payments"],
        "row_limit":        50,
        "timeout_seconds":  15,
        "requires_approval":False,
    },
    {
        "_connector_index": 2,   # Demo PostgreSQL — Direct
        "name":             "postgres.orders.list",
        "description":      "Return recent orders from the PostgreSQL demo database. Optionally filter by status.",
        "purpose":          "Order management — review recent order activity.",
        "data_source":      "PostgreSQL DemoDB",
        "line_of_business": "Order Management",
        "owner":            "Operations",
        "tags":             ["orders", "postgres", "read-only", "demo"],
        "sql_template":     "SELECT o.order_id, o.customer_id, c.first_name || ' ' || c.last_name AS customer_name, o.order_date, o.status, o.total_amount, o.currency FROM demo.orders o JOIN demo.customers c ON c.customer_id = o.customer_id WHERE (COALESCE(:status,'') = '' OR o.status = :status) ORDER BY o.order_date DESC LIMIT 50",
        "parameter_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status: completed, pending, processing, cancelled. Leave empty for all."}
            },
            "additionalProperties": False,
        },
        "result_schema":    {"type": "array"},
        "allowed_relations":["demo.orders", "demo.customers"],
        "row_limit":        50,
        "timeout_seconds":  15,
        "requires_approval":False,
    },
    {
        "_connector_index": 3,   # Demo PostgreSQL — MCP
        "name":             "mcp.postgres.payments.summary",
        "description":      "Return a payment summary grouped by status and method via MCP Toolbox.",
        "purpose":          "Finance analytics — summarise payment volumes by method and status.",
        "data_source":      "PostgreSQL DemoDB via MCP Toolbox",
        "line_of_business": "Finance",
        "owner":            "Finance Analytics",
        "tags":             ["payments", "postgres", "mcp", "analytics", "read-only", "demo"],
        "upstream_tool_name": "postgres.payments.summary",
        "sql_template":     "SELECT status, method, COUNT(*) AS payment_count, SUM(amount) AS total_amount FROM demo.payments GROUP BY status, method ORDER BY total_amount DESC",
        "parameter_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "result_schema":    {"type": "array"},
        "allowed_relations":["demo.payments"],
        "row_limit":        50,
        "timeout_seconds":  15,
        "requires_approval":False,
    },
]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ok(r: httpx.Response, label: str) -> dict:
    if r.status_code >= 400:
        print(f"  [FAIL] {label} — HTTP {r.status_code}: {r.text[:300]}")
        sys.exit(1)
    return r.json()


def step(msg: str):
    print(f"\n{'─'*60}\n▶  {msg}")


def info(msg: str):
    print(f"   {msg}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    api = args.api.rstrip("/")

    # ── 0. Wait for API ────────────────────────────────────────────────────────
    step("Waiting for DataPilot API to be healthy")
    for attempt in range(30):
        try:
            r = httpx.get(f"{api}/health/ready", timeout=5)
            if r.status_code == 200:
                info(f"API is ready: {r.json()}")
                break
        except Exception:
            pass
        print(f"  attempt {attempt+1}/30 — not ready, waiting 3s...")
        time.sleep(3)
    else:
        print("API did not become ready in time.")
        sys.exit(1)

    # ── 1. Login ───────────────────────────────────────────────────────────────
    step(f"Signing in as {ADMIN_EMAIL}")
    r = httpx.post(f"{api}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=10)
    token_data = _ok(r, "login")
    token = token_data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    info("Login successful")

    # ── 2. Get or create a project ─────────────────────────────────────────────
    step("Getting default project")
    r = httpx.get(f"{api}/projects", headers=headers, timeout=10)
    projects = _ok(r, "list projects")
    project_id = None
    if projects:
        project_id = projects[0]["id"]
        info(f"Using existing project: {projects[0]['name']} ({project_id})")
    else:
        info("No projects found, creating 'Demo Project'")
        r = httpx.post(f"{api}/projects",
                       headers=headers,
                       json={"name": "Demo Project", "description": "Auto-created for demo setup"},
                       timeout=10)
        proj = _ok(r, "create project")
        project_id = proj["id"]
        info(f"Created project: {proj['name']} ({project_id})")

    # Switch to this project
    httpx.post(f"{api}/projects/{project_id}/switch", headers=headers, timeout=10)

    # ── 3. Register connectors ─────────────────────────────────────────────────
    step("Registering connectors")
    connector_ids = []
    for conn_def in CONNECTORS:
        payload = {k: v for k, v in conn_def.items()}
        payload["project_id"] = project_id
        # Check if already exists
        r = httpx.get(f"{api}/connectors", headers=headers, params={"project_id": project_id}, timeout=10)
        existing = _ok(r, "list connectors")
        found = next((c for c in existing if c["name"] == payload["name"]), None)
        if found:
            conn_id = found["id"]
            info(f"  ✓ Already exists: {payload['name']} ({conn_id})")
        else:
            r = httpx.post(f"{api}/connectors", headers=headers, json=payload, timeout=15)
            conn = _ok(r, f"create connector {payload['name']}")
            conn_id = conn["id"]
            info(f"  ✓ Created: {payload['name']} ({conn_id})")
        connector_ids.append(conn_id)

    # ── 4. Test connectors ─────────────────────────────────────────────────────
    step("Testing connectors")
    for i, conn_id in enumerate(connector_ids):
        name = CONNECTORS[i]["name"]
        r = httpx.post(f"{api}/connectors/{conn_id}/test", headers=headers, timeout=30)
        if r.status_code == 200:
            result = r.json()
            status = result.get("status", "?")
            msg    = result.get("message", "")
            latency= result.get("latency_ms", "?")
            icon = "✅" if status == "healthy" else "⚠️"
            info(f"  {icon} {name}: {status} — {msg} ({latency}ms)")
        else:
            info(f"  ⚠️  {name}: HTTP {r.status_code} — {r.text[:200]}")

    # ── 5. Scan metadata ───────────────────────────────────────────────────────
    step("Scanning metadata (direct connectors)")
    for i, conn_id in enumerate(connector_ids):
        name = CONNECTORS[i]["name"]
        mode = CONNECTORS[i].get("connection_mode", "direct")
        r = httpx.post(f"{api}/connectors/{conn_id}/scan", headers=headers, timeout=60)
        if r.status_code in (200, 202):
            result = r.json()
            summary = result.get("summary", {})
            info(f"  ✅ {name} [{mode}]: {summary.get('tables',0)} tables, {summary.get('columns',0)} columns")
        else:
            info(f"  ⚠️  {name}: scan HTTP {r.status_code} — {r.text[:200]}")

    # ── 6. Create query tools ──────────────────────────────────────────────────
    step("Creating query tools")
    tool_ids = []
    for i, tool_def in enumerate(QUERY_TOOLS):
        conn_idx = tool_def.pop("_connector_index")
        payload = dict(tool_def)
        payload["connector_id"] = connector_ids[conn_idx]
        payload["project_id"]   = project_id

        # Check if already exists
        r = httpx.get(f"{api}/query-tools", headers=headers, params={"project_id": project_id}, timeout=10)
        existing_tools = _ok(r, "list query-tools")
        found_tool = next((t for t in existing_tools if t["name"] == payload["name"]), None)
        if found_tool:
            tool_id = found_tool["id"]
            info(f"  ✓ Already exists: {payload['name']} ({tool_id})")
        else:
            r = httpx.post(f"{api}/query-tools", headers=headers, json=payload, timeout=15)
            tool = _ok(r, f"create tool {payload['name']}")
            tool_id = tool["id"]
            info(f"  ✓ Created: {payload['name']} ({tool_id})")
        tool_ids.append(tool_id)

    # ── 7. Test query tools ────────────────────────────────────────────────────
    step("Testing query tools")
    test_params = [
        {"status": "active"},   # customers.list
        {"status": "settled"},  # mcp.sqlserver.payments.by_status
        {"status": None},       # postgres.orders.recent
        {},                     # mcp.postgres.payments.summary
    ]
    for i, tool_id in enumerate(tool_ids):
        name = QUERY_TOOLS[i]["name"] if "_connector_index" not in QUERY_TOOLS[i] else QUERY_TOOLS[i].get("name","?")
        # Re-read name from list (already popped _connector_index)
        params = test_params[i] if i < len(test_params) else {}
        clean_params = {k: v for k, v in params.items() if v is not None}
        r = httpx.post(f"{api}/query-tools/{tool_id}/test",
                       headers=headers,
                       json={"parameters": clean_params},
                       timeout=30)
        if r.status_code == 200:
            result = r.json()
            rows = result.get("row_count", "?")
            info(f"  ✅ Tool test OK — {rows} rows returned")
        else:
            info(f"  ⚠️  Tool test HTTP {r.status_code}: {r.text[:200]}")

    # ── 8. Publish query tools ─────────────────────────────────────────────────
    step("Publishing query tools")
    for tool_id in tool_ids:
        r = httpx.post(f"{api}/query-tools/{tool_id}/publish", headers=headers, timeout=15)
        if r.status_code in (200, 204):
            info(f"  ✅ Published tool {tool_id}")
        else:
            info(f"  ⚠️  Publish HTTP {r.status_code}: {r.text[:200]}")

    # ── 9. Create external client ──────────────────────────────────────────────
    step("Creating external demo agent client")
    r = httpx.get(f"{api}/external-clients", headers=headers, timeout=10)
    existing_clients = r.json() if r.status_code == 200 else []
    found_client = next((c for c in existing_clients if c.get("name") == "Demo Agent Client"), None)
    if found_client:
        client_id_field = found_client["id"]
        # Cannot recover the one-time token, create a new one
        info(f"  ⚠️  Client already exists ({client_id_field}). Creating a fresh one for a new token.")
        # Deactivate old and create new
        httpx.delete(f"{api}/external-clients/{client_id_field}", headers=headers, timeout=10)

    r = httpx.post(f"{api}/external-clients",
                   headers=headers,
                   json={"name": "Demo Agent Client",
                         "scopes": ["tools:list", "tools:invoke"],
                         "default_project_id": project_id},
                   timeout=15)
    client_data = _ok(r, "create external client")
    client_id   = client_data["id"]
    ext_token   = client_data.get("token") or client_data.get("secret") or client_data.get("api_key", "")
    info(f"  ✅ External client created: {client_id}")
    info(f"  🔑 One-time token: {ext_token[:30]}...  (saved to scripts/.demo_setup.json)")

    # ── 10. Grant all tools to the client ─────────────────────────────────────
    step("Granting all tools to demo agent client")
    for tool_id in tool_ids:
        r = httpx.post(f"{api}/query-tools/{tool_id}/grants",
                       headers=headers,
                       json={"external_client_id": client_id, "enabled": True},
                       timeout=15)
        if r.status_code in (200, 201):
            info(f"  ✅ Granted tool {tool_id}")
        else:
            info(f"  ⚠️  Grant HTTP {r.status_code}: {r.text[:200]}")

    # ── 11. Save setup state ───────────────────────────────────────────────────
    step("Saving setup state")
    setup = {
        "api_url":        api,
        "project_id":     project_id,
        "connector_ids":  connector_ids,
        "tool_ids":       tool_ids,
        "client_id":      client_id,
        "external_token": ext_token,
        "tool_names": [t["name"] for t in QUERY_TOOLS],
    }
    out_path = Path(__file__).parent / ".demo_setup.json"
    out_path.write_text(json.dumps(setup, indent=2))
    info(f"  Saved → {out_path}")

    # ── Done ───────────────────────────────────────────────────────────────────
    print(f"""
{'═'*60}
✅  DEMO SETUP COMPLETE
{'═'*60}
  Project:          {project_id}
  Connectors:       {len(connector_ids)} registered and tested
  Query Tools:      {len(tool_ids)} created and published
  External client:  {client_id}
  Token saved to:   scripts/.demo_setup.json

Next steps:
  python examples/demo_agent/agent.py
  powershell scripts/e2e_test_and_screenshot.ps1
{'═'*60}
""")


if __name__ == "__main__":
    main()
