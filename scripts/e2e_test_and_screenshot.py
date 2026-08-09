#!/usr/bin/env python3
"""
DataPilot End-to-End Test & Screenshot Script
=============================================
Follows the Demo Storyboard exactly (steps 01-13 from Demo_Storyboard.docx).

- Tests every major API endpoint
- Captures browser screenshots using Edge/Chrome headless
- Saves results to docs/screenshots/demo/

Usage:
    python scripts/e2e_test_and_screenshot.py [--api http://localhost:8000] [--web http://localhost:3001] [--no-screenshots]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

# ─── Config ───────────────────────────────────────────────────────────────────

DEFAULT_API = "http://localhost:8000"
DEFAULT_WEB = "http://localhost:3001"
ADMIN_EMAIL = os.environ.get("DATAPILOT_ADMIN_EMAIL", "admin@datapilot.local")
ADMIN_PASS  = os.environ.get("DATAPILOT_ADMIN_PASSWORD", "ChangeMe123!")
SCREENSHOT_DIR = Path("docs/screenshots/demo")
SETUP_FILE     = Path("scripts/.demo_setup.json")

# Maps storyboard step number to URL path and filename
SCREENSHOTS = [
    (1,  "01-login.png",            "/",                    "Login page"),
    (2,  "02-file-upload.png",      "/files",               "File upload page"),
    (3,  "03-mapping-review.png",   "/files",               "Mapping review"),
    (4,  "04-stage-load.png",       "/files",               "Stage/load"),
    (5,  "05-catalog-search.png",   "/catalog",             "Catalog & hybrid search"),
    (6,  "06-ask-question.png",     "/workspace",           "SQL workspace / ask question"),
    (7,  "07-sql-preview.png",      "/workspace",           "Guarded SQL preview"),
    (8,  "08-agent-run.png",        "/jobs",                "Agent run / jobs"),
    (9,  "09-approval.png",         "/approvals",           "Approvals queue"),
    (10, "10-quality-rules.png",    "/quality",             "Data quality rules"),
    (11, "11-pipeline-lineage.png", "/pipelines",           "Pipeline & lineage"),
    (12, "12-security-dashboard.png","/admin/security",     "Security dashboard"),
    (13, "13-superset-embed.png",   "/analytics",           "Superset embed"),
    # Extra: Connector screens
    (14, "14-connectors.png",       "/admin/connectors",    "Connectors list"),
    (15, "15-query-tools.png",      "/admin/query-tools",   "Query tools list"),
    (16, "16-external-api.png",     None,                   "External API (JSON output)"),
    (17, "17-mcp-protocol.png",     None,                   "MCP protocol (JSON output)"),
]

PASS = []
FAIL = []


def ok(label: str):
    PASS.append(label)
    print(f"  ✅ {label}")


def fail(label: str, detail: str = ""):
    FAIL.append(label)
    print(f"  ❌ {label}" + (f" — {detail[:120]}" if detail else ""))


def step(n: int, title: str):
    print(f"\n{'─'*60}\n▶ Step {n:02d}: {title}")


# ─── Screenshot helper ─────────────────────────────────────────────────────────

def screenshot(web_base: str, path: str, filename: str, label: str, token_cookie: str = ""):
    """Take a headless screenshot using Edge or Chrome."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    out = SCREENSHOT_DIR / filename
    url = f"{web_base}{path}"
    browsers = ["msedge", "microsoft-edge", "google-chrome", "chrome", "chromium", "chromium-browser"]
    for browser in browsers:
        try:
            cmd = [
                browser,
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                f"--window-size=1920,1080",
                f"--screenshot={out}",
                url,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=20)
            if out.exists() and out.stat().st_size > 1000:
                print(f"     📸 Screenshot → {out}")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    print(f"     ℹ  No headless browser found for screenshot of {label} ({url})")
    return False


# ─── Test functions ────────────────────────────────────────────────────────────

def test_health(api: str) -> bool:
    try:
        r = httpx.get(f"{api}/health/ready", timeout=5)
        if r.status_code == 200 and r.json().get("status") == "ready":
            ok("API health/ready")
            return True
        fail("API health/ready", f"HTTP {r.status_code}")
    except Exception as e:
        fail("API health/ready", str(e))
    return False


def test_login(api: str) -> str | None:
    try:
        r = httpx.post(f"{api}/auth/login",
                       json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                       timeout=10)
        if r.status_code == 200:
            token = r.json().get("access_token")
            ok("Auth login")
            return token
        fail("Auth login", f"HTTP {r.status_code}")
    except Exception as e:
        fail("Auth login", str(e))
    return None


def test_connectors(api: str, headers: dict) -> list[str]:
    try:
        r = httpx.get(f"{api}/connectors", headers=headers, timeout=10)
        if r.status_code == 200:
            conns = r.json()
            ok(f"List connectors — {len(conns)} found")
            return [c["id"] for c in conns]
        fail("List connectors", f"HTTP {r.status_code}")
    except Exception as e:
        fail("List connectors", str(e))
    return []


def test_connector_tests(api: str, headers: dict, conn_ids: list[str]):
    for cid in conn_ids[:4]:
        try:
            r = httpx.post(f"{api}/connectors/{cid}/test", headers=headers, timeout=20)
            if r.status_code == 200:
                result = r.json()
                status = result.get("status", "?")
                ok(f"Connector test {cid[:8]}… — {status}")
            else:
                fail(f"Connector test {cid[:8]}…", f"HTTP {r.status_code}")
        except Exception as e:
            fail(f"Connector test {cid[:8]}…", str(e))


def test_query_tools(api: str, headers: dict, ext_token: str) -> list[dict]:
    # Admin list
    try:
        r = httpx.get(f"{api}/query-tools", headers=headers, timeout=10)
        if r.status_code == 200:
            tools = r.json()
            ok(f"List query tools — {len(tools)} found")
        else:
            fail("List query tools", f"HTTP {r.status_code}")
            tools = []
    except Exception as e:
        fail("List query tools", str(e))
        tools = []

    # External discovery
    try:
        ext_headers = {"Authorization": f"Bearer {ext_token}"}
        r = httpx.get(f"{api}/external/v1/query-tools", headers=ext_headers, timeout=10)
        if r.status_code == 200:
            ext_tools = r.json()
            ok(f"External tool discovery — {len(ext_tools)} tools visible to agent")
        else:
            fail("External tool discovery", f"HTTP {r.status_code}")
    except Exception as e:
        fail("External tool discovery", str(e))

    return tools


def test_external_invocations(api: str, ext_token: str):
    ext_headers = {"Authorization": f"Bearer {ext_token}", "Content-Type": "application/json"}
    invocations = [
        ("sqlserver.customers.list",         {"status": "active"}),
        ("mcp.sqlserver.payments.by_status", {"status": "settled"}),
        ("postgres.orders.list",             {"status": "completed"}),
        ("mcp.postgres.payments.summary",    {}),
    ]
    for tool_name, params in invocations:
        try:
            r = httpx.post(
                f"{api}/external/v1/query-tools/{tool_name}/invoke",
                headers=ext_headers,
                json={"parameters": params},
                timeout=30,
            )
            if r.status_code == 200:
                result = r.json()
                rows = result.get("row_count", "?")
                dur  = result.get("duration_ms", "?")
                ok(f"REST invoke {tool_name} — {rows} rows ({dur}ms)")
            else:
                fail(f"REST invoke {tool_name}", f"HTTP {r.status_code}: {r.text[:100]}")
        except Exception as e:
            fail(f"REST invoke {tool_name}", str(e))


def test_mcp_protocol(api: str, ext_token: str):
    headers = {
        "Authorization": f"Bearer {ext_token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json, text/event-stream",
    }
    with httpx.Client(timeout=20) as client:
        # Initialize
        try:
            r = client.post(f"{api}/mcp", headers=headers,
                            json={"jsonrpc": "2.0", "id": "e2e-init", "method": "initialize",
                                  "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                             "clientInfo": {"name": "E2E-Test", "version": "1.0"}}})
            if r.status_code == 200:
                ok("MCP initialize handshake")
                session_id = r.headers.get("mcp-session-id", "")
                if session_id:
                    headers["Mcp-Session-Id"] = session_id
            else:
                fail("MCP initialize", f"HTTP {r.status_code}")
                return
        except Exception as e:
            fail("MCP initialize", str(e))
            return

        # Notify initialized
        client.post(f"{api}/mcp", headers=headers,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        # tools/list
        try:
            r = client.post(f"{api}/mcp", headers=headers,
                            json={"jsonrpc": "2.0", "id": "e2e-list", "method": "tools/list", "params": {}})
            if r.status_code == 200:
                tools = r.json().get("result", {}).get("tools", [])
                ok(f"MCP tools/list — {len(tools)} tools")
            else:
                fail("MCP tools/list", f"HTTP {r.status_code}")
                return
        except Exception as e:
            fail("MCP tools/list", str(e))
            return

        # tools/call
        try:
            r = client.post(f"{api}/mcp", headers=headers,
                            json={"jsonrpc": "2.0", "id": "e2e-call", "method": "tools/call",
                                  "params": {"name": "sqlserver.customers.list",
                                             "arguments": {"status": "active"}}})
            if r.status_code == 200 and "result" in r.json():
                ok("MCP tools/call (sqlserver.customers.list)")
            else:
                fail("MCP tools/call", f"HTTP {r.status_code}: {r.text[:100]}")
        except Exception as e:
            fail("MCP tools/call", str(e))


def test_catalog(api: str, headers: dict):
    try:
        r = httpx.get(f"{api}/datasets", headers=headers, params={"limit": 20}, timeout=10)
        if r.status_code == 200:
            assets = r.json()
            ok(f"Data catalog (datasets) — {len(assets)} assets")
        else:
            fail("Data catalog", f"HTTP {r.status_code}")
    except Exception as e:
        fail("Data catalog", str(e))


def test_jobs(api: str, headers: dict):
    try:
        r = httpx.get(f"{api}/jobs", headers=headers, timeout=10)
        if r.status_code == 200:
            jobs = r.json()
            ok(f"Jobs list — {len(jobs)} jobs")
        else:
            fail("Jobs list", f"HTTP {r.status_code}")
    except Exception as e:
        fail("Jobs list", str(e))


def test_approvals(api: str, headers: dict):
    try:
        r = httpx.get(f"{api}/approvals", headers=headers, timeout=10)
        if r.status_code == 200:
            ok(f"Approvals list — {len(r.json())} approvals")
        else:
            fail("Approvals list", f"HTTP {r.status_code}")
    except Exception as e:
        fail("Approvals list", str(e))


def test_quality(api: str, headers: dict):
    try:
        r = httpx.get(f"{api}/quality/rules", headers=headers, timeout=10)
        if r.status_code == 200:
            ok(f"Quality rules — {len(r.json())} rules")
        else:
            fail("Quality rules", f"HTTP {r.status_code}")
    except Exception as e:
        fail("Quality rules", str(e))


def test_pipelines(api: str, headers: dict):
    try:
        r = httpx.get(f"{api}/pipelines", headers=headers, timeout=10)
        if r.status_code == 200:
            ok(f"Pipelines — {len(r.json())} pipelines")
        else:
            fail("Pipelines", f"HTTP {r.status_code}")
    except Exception as e:
        fail("Pipelines", str(e))


def test_artifacts(api: str, headers: dict):
    try:
        r = httpx.get(f"{api}/artifacts", headers=headers, timeout=10)
        if r.status_code == 200:
            ok(f"Artifacts — {len(r.json())} artifacts")
        else:
            fail("Artifacts", f"HTTP {r.status_code}")
    except Exception as e:
        fail("Artifacts", str(e))


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DataPilot E2E test and screenshot script")
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--web", default=DEFAULT_WEB)
    parser.add_argument("--no-screenshots", action="store_true")
    args = parser.parse_args()

    api  = args.api.rstrip("/")
    web  = args.web.rstrip("/")
    skip_ss = args.no_screenshots

    # Load saved setup
    setup = json.loads(SETUP_FILE.read_text()) if SETUP_FILE.exists() else {}
    ext_token = setup.get("external_token", os.environ.get("DATAPILOT_EXTERNAL_TOKEN", ""))

    print(f"""
╔═══════════════════════════════════════════════════════════╗
║     DataPilot End-to-End Test & Screenshot Runner        ║
║     Follows: Demo_Storyboard.docx (steps 01-17)          ║
╚═══════════════════════════════════════════════════════════╝
  API:  {api}
  Web:  {web}
  Screenshots: {'disabled' if skip_ss else str(SCREENSHOT_DIR)}
""")

    # ── Step 01: Sign in (API + screenshot) ────────────────────────────────────
    step(1, "Sign in — http://localhost:3001")
    if not test_health(api):
        print("API not ready. Aborting.")
        sys.exit(1)
    token = test_login(api)
    if not token:
        print("Login failed. Aborting.")
        sys.exit(1)
    headers = {"Authorization": f"Bearer {token}"}
    if not skip_ss:
        screenshot(web, "/", "01-login.png", "Login page")

    # ── Step 02-04: File upload, mapping, stage ────────────────────────────────
    step(2, "File upload — docs/screenshots/02-file-upload.png")
    try:
        r = httpx.get(f"{api}/files", headers=headers, timeout=10)
        if r.status_code == 200:
            ok(f"Ingested files — {len(r.json())} files")
        else:
            fail("Ingested files", f"HTTP {r.status_code}")
    except Exception as e:
        fail("Ingested files", str(e))
    if not skip_ss:
        screenshot(web, "/files", "02-file-upload.png", "File upload")

    step(3, "Mapping review")
    if not skip_ss:
        screenshot(web, "/files", "03-mapping-review.png", "Mapping review")

    step(4, "Stage load")
    try:
        r = httpx.get(f"{api}/ingestion-mappings", headers=headers, timeout=10)
        if r.status_code == 200:
            ok(f"Ingestion mappings — {len(r.json())} mappings")
        else:
            fail("Ingestion mappings", f"HTTP {r.status_code}")
    except Exception as e:
        fail("Ingestion mappings", str(e))
    if not skip_ss:
        screenshot(web, "/files", "04-stage-load.png", "Stage load")

    # ── Step 05: Catalog search ────────────────────────────────────────────────
    step(5, "Catalog & hybrid search")
    test_catalog(api, headers)
    if not skip_ss:
        screenshot(web, "/catalog", "05-catalog-search.png", "Catalog search")

    # ── Step 06-07: SQL workspace ──────────────────────────────────────────────
    step(6, "Ask a grounded question — SQL workspace")
    try:
        r = httpx.get(f"{api}/conversations", headers=headers, timeout=10)
        if r.status_code == 200:
            ok(f"Conversations — {len(r.json())} conversations")
        else:
            fail("Conversations", f"HTTP {r.status_code}")
    except Exception as e:
        fail("Conversations", str(e))
    if not skip_ss:
        screenshot(web, "/workspace", "06-ask-question.png", "Ask question")

    step(7, "Guarded SQL preview + Why this result?")
    if not skip_ss:
        screenshot(web, "/workspace", "07-sql-preview.png", "SQL preview")

    # ── Step 08-09: Agent run + approval ──────────────────────────────────────
    step(8, "Bounded agent run")
    test_jobs(api, headers)
    if not skip_ss:
        screenshot(web, "/jobs", "08-agent-run.png", "Agent run")

    step(9, "Approve a risky action")
    test_approvals(api, headers)
    if not skip_ss:
        screenshot(web, "/approvals", "09-approval.png", "Approvals")

    # ── Step 10: Quality ───────────────────────────────────────────────────────
    step(10, "Data quality run")
    test_quality(api, headers)
    if not skip_ss:
        screenshot(web, "/quality", "10-quality-rules.png", "Quality rules")

    # ── Step 11: Pipeline + lineage ────────────────────────────────────────────
    step(11, "Generate & deploy pipeline, view lineage")
    test_pipelines(api, headers)
    test_artifacts(api, headers)
    if not skip_ss:
        screenshot(web, "/pipelines", "11-pipeline-lineage.png", "Pipeline lineage")

    # ── Step 12: Security dashboard ───────────────────────────────────────────
    step(12, "Security posture dashboard")
    if not skip_ss:
        screenshot(web, "/admin", "12-security-dashboard.png", "Security dashboard")

    # ── Step 13: Superset embed ────────────────────────────────────────────────
    step(13, "Embedded analytics (Superset)")
    if not skip_ss:
        screenshot(web, "/analytics", "13-superset-embed.png", "Superset embed")

    # ── Step 14: Connectors & tools ────────────────────────────────────────────
    step(14, "Connectors list (demo DBs)")
    conn_ids = test_connectors(api, headers)
    test_connector_tests(api, headers, conn_ids)
    if not skip_ss:
        screenshot(web, "/admin/connectors", "14-connectors.png", "Connectors")

    step(15, "Query tools list")
    if ext_token:
        tools = test_query_tools(api, headers, ext_token)
    else:
        ok("Query tools list (skipped — no external token)")
        tools = []
    if not skip_ss:
        screenshot(web, "/admin/query-tools", "15-query-tools.png", "Query tools")

    # ── Step 16: External REST API ─────────────────────────────────────────────
    step(16, "External REST API invocations")
    if ext_token:
        test_external_invocations(api, ext_token)
    else:
        fail("External REST invocations", "No external token — run register_demo_connectors.py first")

    # ── Step 17: MCP protocol ─────────────────────────────────────────────────
    step(17, "MCP protocol (JSON-RPC 2.0)")
    if ext_token:
        test_mcp_protocol(api, ext_token)
    else:
        fail("MCP protocol", "No external token")

    # ── Summary ────────────────────────────────────────────────────────────────
    total = len(PASS) + len(FAIL)
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║                    E2E TEST SUMMARY                      ║
╠═══════════════════════════════════════════════════════════╣
║  PASSED:  {len(PASS):3d} / {total}
║  FAILED:  {len(FAIL):3d} / {total}
╠═══════════════════════════════════════════════════════════╣""")
    if FAIL:
        print("║  Failed checks:")
        for f in FAIL:
            print(f"║    ✗ {f}")
    if not skip_ss:
        saved = list(SCREENSHOT_DIR.glob("*.png"))
        print(f"║  Screenshots saved: {len(saved)} → {SCREENSHOT_DIR}/")
    print("╚═══════════════════════════════════════════════════════╝")

    sys.exit(0 if not FAIL else 1)


if __name__ == "__main__":
    main()
