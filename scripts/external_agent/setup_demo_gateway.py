"""One-time (idempotent) setup for the external-agent demo.

Logs in to DataPilot as an admin and, using only the public API:

1. ensures a small set of governed, read-only query tools exists over the demo
   data, taking each one through the real lifecycle
   draft -> test (runs the SQL, status "tested") -> publish (admin) ->
   approve any pending approval that references the tool;
2. creates (or reuses) an external client for the demo agent and grants it
   those tools, with a per-tool daily quota;
3. writes the client token to scripts/external_agent/.client.env (gitignored).

Nothing pre-existing is modified: tools are only created/updated when they carry
the ``external-agent-demo`` tag this script puts on them, and only the client
named ``External agent demo (MCP)`` is ever rotated.

    python scripts/external_agent/setup_demo_gateway.py [--api http://localhost:8000] [--rotate]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
CLIENT_ENV = HERE / ".client.env"
DEMO_TAG = "external-agent-demo"
CLIENT_NAME = "External agent demo (MCP)"
DAILY_QUOTA = 500
TOKEN_DAYS = 30

# connector: "local" = DataPilot local staging (no connector); "postgres" = the
# directly connected Postgres demo warehouse (demo.customers/orders/payments).
TOOLS: list[dict[str, Any]] = [
    {
        "connector": "local",
        "name": "banking.txn_totals_by_type",
        "description": "Count and total amount of staged banking transactions per transaction type (deposit, debit, payment, withdrawal). Amounts are signed: outflows are negative.",
        "purpose": "Answer 'how much / how many transactions of each type' questions.",
        "data_source": "DataPilot local staging",
        "line_of_business": "Retail Banking",
        "owner": "Data Platform",
        "tags": ["banking", "transactions", "aggregate"],
        "sql_template": "SELECT txn_type, COUNT(*) AS txn_count, SUM(amount) AS total_amount FROM staging.transactions GROUP BY txn_type ORDER BY txn_type",
        "parameter_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "allowed_relations": ["staging.transactions"],
        "row_limit": 50,
        "test_parameters": {},
    },
    {
        "connector": "local",
        "name": "banking.txns_by_type",
        "description": "List individual staged banking transactions of one transaction type (id, account, signed amount, posted_at, channel).",
        "purpose": "Row-level detail for one transaction type; also used by QA/QC to re-derive totals.",
        "data_source": "DataPilot local staging",
        "line_of_business": "Retail Banking",
        "owner": "Data Platform",
        "tags": ["banking", "transactions", "detail"],
        "sql_template": "SELECT transaction_id, account_id, amount, txn_type, posted_at, channel FROM staging.transactions WHERE txn_type = :txn_type ORDER BY posted_at",
        "parameter_schema": {
            "type": "object",
            "required": ["txn_type"],
            "properties": {"txn_type": {"type": "string", "enum": ["debit", "deposit", "payment", "withdrawal"], "description": "Transaction type"}},
            "additionalProperties": False,
        },
        "allowed_relations": ["staging.transactions"],
        "row_limit": 500,
        "test_parameters": {"txn_type": "deposit"},
    },
    {
        "connector": "local",
        "name": "banking.account_lookup",
        "description": "Look up one bank account by account_id: owning customer_id, account_type (checking/savings), status and opened_at.",
        "purpose": "Answer questions about a specific account's type, status or owner.",
        "data_source": "DataPilot local staging",
        "line_of_business": "Retail Banking",
        "owner": "Data Platform",
        "tags": ["banking", "accounts", "lookup"],
        "sql_template": "SELECT account_id, customer_id, account_type, status, opened_at FROM core.accounts WHERE account_id = :account_id",
        "parameter_schema": {
            "type": "object",
            "required": ["account_id"],
            "properties": {"account_id": {"type": "integer", "description": "Account number, e.g. 50101"}},
            "additionalProperties": False,
        },
        "allowed_relations": ["core.accounts"],
        "row_limit": 1,
        "test_parameters": {"account_id": 50101},
    },
    {
        "connector": "postgres",
        "name": "commerce.payments_summary",
        "description": "Payment count and total amount grouped by payment status (settled, pending, refunded) and method (credit_card, debit_card, bank_transfer).",
        "purpose": "Answer 'how many / how much in payments by status or method' questions.",
        "data_source": "Postgres demo warehouse",
        "line_of_business": "Commerce",
        "owner": "Payments Analytics",
        "tags": ["commerce", "payments", "aggregate"],
        "sql_template": "SELECT status, method, COUNT(*) AS payment_count, SUM(amount) AS total_amount FROM demo.payments GROUP BY status, method ORDER BY status, method",
        "parameter_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "allowed_relations": ["demo.payments"],
        "row_limit": 100,
        "test_parameters": {},
    },
    {
        "connector": "postgres",
        "name": "commerce.payments_by_status",
        "description": "List individual payments with one status (payment_id, order_id, payment_date, method, amount).",
        "purpose": "Row-level payment detail for one status; also used by QA/QC to re-derive payment totals.",
        "data_source": "Postgres demo warehouse",
        "line_of_business": "Commerce",
        "owner": "Payments Analytics",
        "tags": ["commerce", "payments", "detail"],
        "sql_template": "SELECT payment_id, order_id, payment_date, method, amount, status FROM demo.payments WHERE status = :status ORDER BY payment_date",
        "parameter_schema": {
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"type": "string", "enum": ["pending", "refunded", "settled"], "description": "Payment status"}},
            "additionalProperties": False,
        },
        "allowed_relations": ["demo.payments"],
        "row_limit": 500,
        "test_parameters": {"status": "settled"},
    },
    {
        "connector": "postgres",
        "name": "commerce.customer_orders",
        "description": "All orders placed by one customer (order_id, order_date, status, total_amount, currency) with the customer's segment. Customer PII is not returned.",
        "purpose": "Answer questions about a specific customer's orders and order value.",
        "data_source": "Postgres demo warehouse",
        "line_of_business": "Commerce",
        "owner": "Payments Analytics",
        "tags": ["commerce", "orders", "customers", "lookup"],
        "sql_template": "SELECT o.order_id, o.customer_id, c.segment, o.order_date, o.status, o.total_amount, o.currency FROM demo.orders o JOIN demo.customers c ON c.customer_id = o.customer_id WHERE o.customer_id = :customer_id ORDER BY o.order_date",
        "parameter_schema": {
            "type": "object",
            "required": ["customer_id"],
            "properties": {"customer_id": {"type": "integer", "description": "Customer id, e.g. 2"}},
            "additionalProperties": False,
        },
        "allowed_relations": ["demo.orders", "demo.customers"],
        "row_limit": 200,
        "test_parameters": {"customer_id": 2},
    },
]

CONTRACT_FIELDS = ["description", "purpose", "data_source", "line_of_business", "owner", "sql_template", "parameter_schema", "allowed_relations", "row_limit"]


def step(message: str) -> None:
    print(f"\n== {message}")


def info(message: str) -> None:
    print(f"   {message}")


def fail(response: httpx.Response, what: str) -> None:
    raise SystemExit(f"!! {what} failed: HTTP {response.status_code} {response.text[:400]}")


def resolve_connectors(client: httpx.Client) -> dict[str, str | None]:
    connectors = client.get("/connectors")
    if connectors.status_code != 200:
        fail(connectors, "listing connectors")
    postgres = [
        item for item in connectors.json()
        if item.get("connector_type") == "postgres" and item.get("connection_mode", "direct") == "direct" and item.get("host") == "postgres-demo"
    ]
    # Prefer the "Demo PostgreSQL — Direct" connector registered by scripts/register_demo_connectors.py.
    postgres.sort(key=lambda item: (0 if "demo postgresql" in item["name"].lower() else 1, item["name"]))
    if not postgres:
        raise SystemExit("!! No direct Postgres demo connector (host postgres-demo) found. Run scripts/register_demo_connectors.py first.")
    info(f"Postgres demo connector: {postgres[0]['name']} ({postgres[0]['id']})")
    return {"local": None, "postgres": postgres[0]["id"]}


def tool_payload(spec: dict[str, Any], connector_id: str | None) -> dict[str, Any]:
    payload = {key: value for key, value in spec.items() if key not in {"connector", "test_parameters"}}
    payload["tags"] = list(dict.fromkeys([*spec["tags"], DEMO_TAG, "read-only"]))
    payload["connector_id"] = connector_id
    payload["upstream_tool_name"] = None
    payload["result_schema"] = {"type": "object"}
    payload["timeout_seconds"] = 15
    payload["requires_approval"] = False  # external callers cannot answer an interactive approval
    return payload


def approve_pending_for(client: httpx.Client, tool: dict[str, Any]) -> int:
    """Approve any pending approval whose evidence references this tool (if the build creates one)."""
    pending = client.get("/approvals", params={"status": "pending"})
    if pending.status_code != 200:
        return 0
    approved = 0
    for approval in pending.json():
        evidence = approval.get("evidence") or {}
        if tool["id"] in {str(evidence.get("query_tool_id", "")), str(evidence.get("tool_id", ""))} or tool["name"] == evidence.get("query_tool"):
            decision = client.post(f"/approvals/{approval['id']}/decision", json={"decision": "approved", "note": "External agent demo setup: tested and reviewed."})
            if decision.status_code == 200:
                approved += 1
                info(f"approved pending approval {approval['id']} ({approval.get('action_type')})")
            else:
                info(f"could not approve {approval['id']}: HTTP {decision.status_code} {decision.text[:200]}")
    return approved


def ensure_tools(client: httpx.Client, connectors: dict[str, str | None]) -> list[dict[str, Any]]:
    step("Query tools (draft -> tested -> published)")
    listed = client.get("/query-tools")
    if listed.status_code != 200:
        fail(listed, "listing query tools")
    existing = {item["name"]: item for item in listed.json()}
    ready: list[dict[str, Any]] = []
    for spec in TOOLS:
        payload = tool_payload(spec, connectors[spec["connector"]])
        current = existing.get(spec["name"])
        if current and DEMO_TAG not in (current.get("tags") or []):
            info(f"{spec['name']}: exists but was not created by this script - left untouched")
            if current["status"] == "published":
                ready.append(current)
            continue
        if current is None:
            created = client.post("/query-tools", json=payload)
            if created.status_code != 201:
                fail(created, f"creating {spec['name']}")
            current = created.json()
            info(f"{spec['name']}: created (draft v{current['version']})")
        elif any(current.get(field) != payload[field] for field in CONTRACT_FIELDS) or current.get("connector_id") != payload["connector_id"]:
            updated = client.put(f"/query-tools/{current['id']}", json=payload)
            if updated.status_code != 200:
                fail(updated, f"updating {spec['name']}")
            current = updated.json()
            info(f"{spec['name']}: definition changed -> new draft v{current['version']}")
        if current["status"] == "published":
            info(f"{spec['name']}: already published v{current['version']} - reused")
            ready.append(current)
            continue
        tested = client.post(f"/query-tools/{current['id']}/test", json={"parameters": spec["test_parameters"]})
        if tested.status_code != 200:
            fail(tested, f"testing {spec['name']}")
        result = tested.json()
        info(f"{spec['name']}: tested with {spec['test_parameters'] or '{}'} -> {result['row_count']} row(s), columns {result['columns']}")
        published = client.post(f"/query-tools/{current['id']}/publish")
        if published.status_code != 200:
            fail(published, f"publishing {spec['name']}")
        current = published.json()
        approve_pending_for(client, current)
        info(f"{spec['name']}: published v{current['version']} (status={current['status']})")
        ready.append(current)
    return ready


def read_client_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if CLIENT_ENV.exists():
        for line in CLIENT_ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def token_works(api: str, token: str) -> bool:
    try:
        response = httpx.get(f"{api}/external/v1/query-tools", headers={"Authorization": f"Bearer {token}"}, timeout=20)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def ensure_client(client: httpx.Client, api: str, force_rotate: bool) -> tuple[dict[str, Any], str | None]:
    step(f"External client '{CLIENT_NAME}'")
    clients = client.get("/external-clients")
    if clients.status_code != 200:
        fail(clients, "listing external clients")
    current = next((item for item in clients.json() if item["name"] == CLIENT_NAME), None)
    saved = read_client_env()
    if current is None:
        created = client.post("/external-clients", json={"name": CLIENT_NAME, "scopes": ["tools:list", "tools:invoke"], "expires_in_days": TOKEN_DAYS})
        if created.status_code != 201:
            fail(created, "creating the external client")
        info(f"created client {created.json()['client_id']} (scopes tools:list, tools:invoke; expires in {TOKEN_DAYS} days)")
        return created.json(), created.json()["token"]
    info(f"found client {current['client_id']} (active={current['active']}, expires_at={current.get('expires_at')})")
    token = saved.get("DATAPILOT_CLIENT_TOKEN", "")
    if not force_rotate and token.startswith(current["client_id"] + ".") and not current.get("expired") and token_works(api, token):
        info("saved token in .client.env still works - reused (pass --rotate to issue a new one)")
        return current, None
    rotated = client.post(f"/external-clients/{current['id']}/rotate", json={"expires_in_days": TOKEN_DAYS})
    if rotated.status_code != 200:
        fail(rotated, "rotating the external client token")
    info(f"rotated token (new expiry in {TOKEN_DAYS} days)")
    return rotated.json(), rotated.json()["token"]


def ensure_grants(client: httpx.Client, external_client: dict[str, Any], tools: list[dict[str, Any]]) -> None:
    step("Grants")
    for tool in tools:
        grant = client.post(f"/query-tools/{tool['id']}/grants", json={"external_client_id": external_client["id"], "enabled": True, "daily_quota": DAILY_QUOTA})
        if grant.status_code != 201:
            fail(grant, f"granting {tool['name']}")
        info(f"{tool['name']} -> {external_client['client_id']} (daily quota {DAILY_QUOTA})")


def write_client_env(api: str, external_client: dict[str, Any], token: str) -> None:
    CLIENT_ENV.write_text(
        "# Written by setup_demo_gateway.py. Secret - gitignored, do not commit.\n"
        f"DATAPILOT_API={api}\n"
        f"DATAPILOT_CLIENT_ID={external_client['client_id']}\n"
        f"DATAPILOT_CLIENT_TOKEN={token}\n",
        encoding="utf-8",
    )
    try:
        os.chmod(CLIENT_ENV, 0o600)
    except OSError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--api", default=os.getenv("DATAPILOT_API", "http://localhost:8000"))
    parser.add_argument("--email", default=os.getenv("DATAPILOT_EMAIL", "admin@datapilot.local"))
    parser.add_argument("--password", default=os.getenv("DATAPILOT_PASSWORD", "ChangeMe123!"))
    parser.add_argument("--rotate", action="store_true", help="issue a new client token even if the saved one works")
    args = parser.parse_args()
    api = args.api.rstrip("/")

    client = httpx.Client(base_url=api, timeout=90.0)
    step(f"Admin login at {api}")
    login = client.post("/auth/login", json={"email": args.email, "password": args.password})
    if login.status_code != 200:
        fail(login, "admin login")
    user = login.json()["user"]
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    info(f"{user['email']} ({user['role']}) - project '{user.get('current_project_name')}'")
    if user.get("must_change_password"):
        info("note: this admin is flagged must_change_password; the API still accepts the session")

    connectors = resolve_connectors(client)
    tools = ensure_tools(client, connectors)
    external_client, token = ensure_client(client, api, args.rotate)
    ensure_grants(client, external_client, tools)

    step("Client credentials")
    if token:
        write_client_env(api, external_client, token)
        info(f"token written to {CLIENT_ENV.relative_to(HERE.parent.parent)} (gitignored; never printed)")
    else:
        info(f"keeping existing {CLIENT_ENV.name}")

    step("Ready")
    info(f"{len(tools)} published tools granted to {external_client['client_id']}:")
    for tool in tools:
        info(f"  - {tool['name']}")
    info("next: python scripts/external_agent/mcp_agent.py --list-tools")
    return 0


if __name__ == "__main__":
    sys.exit(main())
