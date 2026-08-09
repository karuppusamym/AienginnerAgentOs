#!/usr/bin/env python3
"""
DataPilot Demo Agent
====================
An external agent that discovers and invokes DataPilot governed query tools
using BOTH the REST external API (/external/v1/) and the MCP protocol (/mcp).

This demonstrates the "External AI Developer" sequence diagram from the deck:
  tools/list → grant filter → invoke with typed params → audit → typed result

Usage:
    # After running register_demo_connectors.py:
    python agent.py

    # Or with explicit token:
    python agent.py --token <your-token> --api http://localhost:8000

    # Run a specific tool:
    python agent.py --tool sqlserver.customers.list --params '{"status":"active"}'
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

DEFAULT_API = "http://localhost:8000"
SETUP_FILE  = Path(__file__).parent.parent / "scripts" / ".demo_setup.json"

DEMO_INVOCATIONS = [
    {
        "label":  "SQL Server — Active Customers (direct connector, REST)",
        "tool":   "sqlserver.customers.list",
        "params": {"status": "active"},
        "mode":   "rest",
    },
    {
        "label":  "SQL Server — Settled Payments (MCP connector, REST)",
        "tool":   "mcp.sqlserver.payments.by_status",
        "params": {"status": "settled"},
        "mode":   "rest",
    },
    {
        "label":  "PostgreSQL — Recent Orders (direct connector, REST)",
        "tool":   "postgres.orders.list",
        "params": {"status": "completed"},
        "mode":   "rest",
    },
    {
        "label":  "PostgreSQL — Payment Summary (MCP connector, REST)",
        "tool":   "mcp.postgres.payments.summary",
        "params": {},
        "mode":   "rest",
    },
    {
        "label":  "MCP Protocol — tools/list discovery",
        "tool":   None,
        "params": {},
        "mode":   "mcp_list",
    },
    {
        "label":  "MCP Protocol — invoke sqlserver.customers.list",
        "tool":   "sqlserver.customers.list",
        "params": {"status": "active"},
        "mode":   "mcp_call",
    },
]


def load_setup() -> dict:
    if SETUP_FILE.exists():
        return json.loads(SETUP_FILE.read_text())
    return {}


def rest_discover(api: str, token: str) -> list[dict]:
    """Discover all granted tools via the external REST API."""
    r = httpx.get(
        f"{api}/external/v1/query-tools",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def rest_invoke(api: str, token: str, tool_name: str, params: dict) -> dict:
    """Invoke a specific tool via the external REST API."""
    r = httpx.post(
        f"{api}/external/v1/query-tools/{tool_name}/invoke",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"parameters": params},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def mcp_list_tools(api: str, token: str) -> list[dict]:
    """Discover tools via the MCP JSON-RPC protocol."""
    headers = {
        "Authorization":  f"Bearer {token}",
        "Content-Type":   "application/json",
        "Accept":         "application/json, text/event-stream",
    }
    with httpx.Client(timeout=20) as client:
        # Initialize
        init_resp = client.post(
            f"{api}/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": "agent-init", "method": "initialize",
                  "params": {"protocolVersion": "2025-03-26",
                             "capabilities": {},
                             "clientInfo": {"name": "DataPilot-Demo-Agent", "version": "1.0"}}},
        )
        init_resp.raise_for_status()
        session_id = init_resp.headers.get("mcp-session-id", "")
        if session_id:
            headers["Mcp-Session-Id"] = session_id

        # Notify initialized
        client.post(f"{api}/mcp", headers=headers,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        # List tools
        list_resp = client.post(
            f"{api}/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": "agent-list", "method": "tools/list", "params": {}},
        )
        list_resp.raise_for_status()
        payload = list_resp.json()
        return payload.get("result", {}).get("tools", [])


def mcp_call_tool(api: str, token: str, tool_name: str, params: dict) -> dict:
    """Call a tool via the MCP JSON-RPC protocol."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json, text/event-stream",
    }
    with httpx.Client(timeout=30) as client:
        init_resp = client.post(
            f"{api}/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": "agent-init", "method": "initialize",
                  "params": {"protocolVersion": "2025-03-26",
                             "capabilities": {},
                             "clientInfo": {"name": "DataPilot-Demo-Agent", "version": "1.0"}}},
        )
        init_resp.raise_for_status()
        session_id = init_resp.headers.get("mcp-session-id", "")
        if session_id:
            headers["Mcp-Session-Id"] = session_id

        client.post(f"{api}/mcp", headers=headers,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        call_resp = client.post(
            f"{api}/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": "agent-call", "method": "tools/call",
                  "params": {"name": tool_name, "arguments": params}},
        )
        call_resp.raise_for_status()
        payload = call_resp.json()
        if "error" in payload:
            raise RuntimeError(f"MCP error: {payload['error']}")
        return payload.get("result", {})


def print_rows(result: dict, title: str):
    """Pretty-print query result rows in a table."""
    columns = result.get("columns", [])
    rows    = result.get("rows", [])
    count   = result.get("row_count", len(rows))
    duration = result.get("duration_ms", "?")

    if not columns and not rows:
        console.print(f"  [dim]No rows returned[/dim]")
        return

    table = Table(box=box.ROUNDED, title=f"{title} — {count} rows ({duration}ms)",
                  show_header=True, header_style="bold cyan")
    for col in columns[:8]:   # cap visible columns for terminal width
        table.add_column(str(col), overflow="ellipsis", max_width=25)

    for row in rows[:10]:     # cap display rows
        if isinstance(row, dict):
            table.add_row(*[str(row.get(c, ""))[:24] for c in columns[:8]])
        elif isinstance(row, list):
            table.add_row(*[str(v)[:24] for v in row[:8]])
    console.print(table)


def run_demo(api: str, token: str, single_tool: str | None, single_params: dict | None):
    console.print(Panel.fit(
        "[bold green]DataPilot External Demo Agent[/bold green]\n"
        f"[dim]API: {api}[/dim]\n"
        "[dim]Demonstrates REST /external/v1/ and MCP /mcp protocol paths[/dim]",
        border_style="green",
    ))

    # ── Discover available tools ───────────────────────────────────────────────
    console.print("\n[bold]Step 1 — Discover granted tools via REST[/bold]")
    try:
        tools = rest_discover(api, token)
        disc_table = Table(box=box.SIMPLE, show_header=True, header_style="bold magenta")
        disc_table.add_column("Tool Name", style="cyan")
        disc_table.add_column("Data Source")
        disc_table.add_column("LOB")
        disc_table.add_column("Owner")
        for t in tools:
            disc_table.add_row(
                t.get("name",""),
                t.get("data_source",""),
                t.get("line_of_business",""),
                t.get("owner",""),
            )
        console.print(disc_table)
        console.print(f"  [green]✅ {len(tools)} tools discovered[/green]")
    except Exception as e:
        console.print(f"  [red]⚠ REST discover failed: {e}[/red]")

    if single_tool:
        invocations = [{
            "label": f"User-specified: {single_tool}",
            "tool": single_tool,
            "params": single_params or {},
            "mode": "rest",
        }]
    else:
        invocations = DEMO_INVOCATIONS

    console.print("\n[bold]Step 2 — Invoke tools[/bold]")
    for idx, inv in enumerate(invocations):
        console.print(f"\n  [bold yellow]{idx+1}. {inv['label']}[/bold yellow]")
        start = time.perf_counter()
        try:
            mode = inv["mode"]
            tool = inv["tool"]
            params = inv["params"]

            if mode == "rest" and tool:
                result = rest_invoke(api, token, tool, params)
                elapsed = round((time.perf_counter() - start) * 1000)
                print_rows(result, tool)

            elif mode == "mcp_list":
                mcp_tools = mcp_list_tools(api, token)
                elapsed = round((time.perf_counter() - start) * 1000)
                mt = Table(box=box.SIMPLE, show_header=True, header_style="bold magenta")
                mt.add_column("MCP Tool Name", style="cyan")
                mt.add_column("Description", overflow="ellipsis", max_width=60)
                for t in mcp_tools:
                    mt.add_row(t.get("name",""), t.get("description","")[:58])
                console.print(mt)
                console.print(f"  [green]✅ {len(mcp_tools)} tools via MCP ({elapsed}ms)[/green]")

            elif mode == "mcp_call" and tool:
                result = mcp_call_tool(api, token, tool, params)
                elapsed = round((time.perf_counter() - start) * 1000)
                # MCP result has content array
                content = result.get("content", [])
                text_parts = [c.get("text","") for c in content if c.get("type")=="text"]
                if text_parts:
                    try:
                        data = json.loads(text_parts[0])
                        if isinstance(data, dict) and "columns" in data:
                            print_rows(data, f"MCP {tool}")
                        else:
                            console.print(f"  [cyan]{str(data)[:300]}[/cyan]")
                    except Exception:
                        console.print(f"  [cyan]{text_parts[0][:300]}[/cyan]")
                console.print(f"  [green]✅ MCP call succeeded ({elapsed}ms)[/green]")

        except Exception as e:
            elapsed = round((time.perf_counter() - start) * 1000)
            console.print(f"  [red]⚠ Failed ({elapsed}ms): {e}[/red]")

    console.print(Panel.fit(
        "[bold green]Demo agent run complete![/bold green]\n"
        "Every invocation above went through DataPilot's governed gateway:\n"
        "  • Parameter schema validation\n"
        "  • Grant / scope check\n"
        "  • Row limit enforcement\n"
        "  • PII masking\n"
        "  • Audit log written\n"
        "  • Governance telemetry emitted",
        border_style="green",
    ))


def main():
    parser = argparse.ArgumentParser(description="DataPilot external demo agent")
    parser.add_argument("--api",    default=DEFAULT_API, help="DataPilot API base URL")
    parser.add_argument("--token",  default="",          help="External client bearer token")
    parser.add_argument("--tool",   default="",          help="Run a single named tool")
    parser.add_argument("--params", default="{}",        help='JSON parameters, e.g. \'{"status":"active"}\'')
    args = parser.parse_args()

    token = args.token
    if not token:
        setup = load_setup()
        token = setup.get("external_token", "")
    if not token:
        token = os.environ.get("DATAPILOT_EXTERNAL_TOKEN", "")
    if not token:
        console.print("[red]No external token found. Run register_demo_connectors.py first "
                      "or set DATAPILOT_EXTERNAL_TOKEN.[/red]")
        sys.exit(1)

    single_params = json.loads(args.params) if args.params else {}
    run_demo(args.api, token, args.tool or None, single_params)


import os
if __name__ == "__main__":
    main()
