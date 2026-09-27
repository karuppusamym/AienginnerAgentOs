"""Admin-side view: watch external agents' tool calls land in DataPilot.

Reads GET /external-invocations (the gateway's invocation history: client, tool,
parameters, status, rows, duration) and, with --audit, the related audit events
(query_tool.published, query_tool.grant_updated, external_client.*, rate-limit /
quota events). Run it in a second terminal during the demo:

    python scripts/external_agent/watch_invocations.py --follow
    python scripts/external_agent/watch_invocations.py --limit 20 --audit
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

AUDIT_PREFIXES = ("external_", "query_tool.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--api", default=os.getenv("DATAPILOT_API", "http://localhost:8000"))
    parser.add_argument("--email", default=os.getenv("DATAPILOT_EMAIL", "admin@datapilot.local"))
    parser.add_argument("--password", default=os.getenv("DATAPILOT_PASSWORD", "ChangeMe123!"))
    parser.add_argument("--limit", type=int, default=15, help="how many recent invocations to show first")
    parser.add_argument("--follow", action="store_true", help="keep polling and print new invocations as they arrive")
    parser.add_argument("--audit", action="store_true", help="also show recent gateway-related audit events")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.api.rstrip("/"), timeout=30.0)
    login = client.post("/auth/login", json={"email": args.email, "password": args.password})
    login.raise_for_status()
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    tools = {item["id"]: item["name"] for item in client.get("/query-tools").json()}
    clients = {item["id"]: f"{item['name']} ({item['client_id']})" for item in client.get("/external-clients").json()}

    def show(item: dict) -> None:
        meta = item.get("result_metadata") or {}
        outcome = f"{meta.get('row_count', '-')} row(s)" if item["status"] == "succeeded" else (item.get("error") or "")[:80]
        print(f"{item['created_at'][:19]}  {item['status']:<9}  {tools.get(item['query_tool_id'], item['query_tool_id']):<28}  "
              f"{json.dumps(item.get('parameters') or {}):<28}  {outcome:<12}  {item.get('duration_ms') or '-'} ms  "
              f"{clients.get(item['external_client_id'], item['external_client_id'])}")

    print(f"External invocations at {args.api} (newest last)")
    print(f"{'time (UTC)':<19}  {'status':<9}  {'tool':<28}  {'parameters':<28}  {'result':<12}  duration  client")
    seen: set[str] = set()
    history = client.get("/external-invocations").json()
    for item in reversed(history[: args.limit]):
        show(item)
    seen.update(item["id"] for item in history)

    if args.audit:
        print("\nRecent gateway audit events")
        for event in reversed([e for e in client.get("/audit").json() if e["event_type"].startswith(AUDIT_PREFIXES)][:20]):
            details = event.get("details") or {}
            target = tools.get(event["entity_id"]) or clients.get(event["entity_id"]) or event["entity_id"]
            print(f"{event['created_at'][:19]}  {event['event_type']:<34}  {target}  {json.dumps(details)[:100]}")

    while args.follow:
        time.sleep(2)
        try:
            fresh = [item for item in client.get("/external-invocations").json() if item["id"] not in seen]
        except httpx.HTTPError as exc:
            print(f"(poll failed: {exc})")
            continue
        for item in reversed(fresh):
            seen.add(item["id"])
            show(item)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
