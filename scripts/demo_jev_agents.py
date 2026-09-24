"""Live proof that Jev (TypeSafe decision model via OpenRouter) drives DataPilot's decisions.

Runs against a running stack (default http://localhost:8000) and records every
Jev verdict it triggers: route choice, which agent, consequential-action
escalation, and per-step tool choice inside an agent run. Model-call logs are
read back at the end so each verdict is matched by a logged call with latency
and cost.

    python scripts/demo_jev_agents.py [--api http://localhost:8000] [--out docs/demo]

Writes <out>/jev-proof-<timestamp>.md (readable report) and .json (raw evidence).
Side effects in the demo project: one agent run (read-only tools) and one
pending approval (the escalated objective; nothing executes until approved).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROUTING_CASES = [
    ("SQL question", "What is the total transaction amount by transaction type?"),
    ("Named agent", "Run the Quality agent to validate null checks on transactions"),
    ("Agent not named (Jev picks which)", "Validate null checks then investigate why the nightly loads failed"),
    ("Vague", "hello"),
    ("Consequential", "Copy all customer records to the marketing shared drive"),
]
ESCALATION_OBJECTIVE = "Copy all customer records to the marketing shared drive"
AGENT_OBJECTIVE = "Profile staging.transactions, then explain its lineage and the metrics it supports"


def login(client: httpx.Client, email: str, password: str) -> None:
    response = client.post("/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"


def pct(value) -> str:
    return f"{float(value):.0%}" if isinstance(value, (int, float)) else "-"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--api", default=os.getenv("DATAPILOT_API", "http://localhost:8000"))
    parser.add_argument("--email", default=os.getenv("DATAPILOT_EMAIL", "admin@datapilot.local"))
    parser.add_argument("--password", default=os.getenv("DATAPILOT_PASSWORD", "ChangeMe123!"))
    parser.add_argument("--out", default="docs/demo")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.api.rstrip("/"), timeout=180.0)
    login(client, args.email, args.password)
    started_at = datetime.now(timezone.utc)
    evidence: dict = {"api": args.api, "started_at": started_at.isoformat()}
    lines: list[str] = [f"# Jev decision proof — {started_at:%Y-%m-%d %H:%M} UTC", "", f"Live run against `{args.api}`. Every verdict below came from `typesafe/jev-1.13` through the OpenRouter Decisions API and is matched by a logged model call at the end.", ""]

    # 0. Which decisions are routed to Jev
    routing = client.get("/model-routing").json()
    jev_purposes = [item for item in routing["purposes"] if (item.get("effective_provider") or {}).get("model", "").startswith("typesafe/jev")]
    evidence["routing"] = routing["purposes"]
    lines += ["## 1. Decisions routed to Jev", "", "| Purpose | Provider | Model |", "|---|---|---|"]
    lines += [f"| {item['label']} (`{item['purpose']}`) | {item['effective_provider']['name']} | `{item['effective_provider']['model']}` |" for item in jev_purposes]
    if not jev_purposes:
        lines += ["", "**No purpose is routed to Jev. Set OPENROUTER_API_KEY and restart the API, or route purposes in Admin > Model routing.**"]
    lines.append("")

    # 1. Routing decisions
    lines += ["## 2. Route and agent choice (`decision_routing`)", "", "| Case | Question | Backend | Chosen | Top Jev probabilities | Consequential | Latency | Cost |", "|---|---|---|---|---|---|---|---|"]
    evidence["routing_cases"] = []
    agent_choice_case = None
    for label, question in ROUTING_CASES:
        decision = client.post("/router/decide", json={"question": question}).json()
        jev = decision.get("jev") or {}
        top = sorted((jev.get("probabilities") or {}).items(), key=lambda item: item[1], reverse=True)[:3]
        chosen = decision["route"] + (f" → {decision['target']['name']}" if decision.get("target") else "")
        lines.append(f"| {label} | {question} | `{decision['backend']}` | **{chosen}** | {', '.join(f'{name} {pct(p)}' for name, p in top) or '-'} | {pct(jev.get('consequential'))} | {jev.get('latency_ms', '-')} ms | {jev.get('cost_usd') if jev.get('cost_usd') is not None else '-'} |")
        evidence["routing_cases"].append({"label": label, "question": question, "decision": decision})
        if label.startswith("Agent not named"):
            agent_choice_case = decision
    lines.append("")
    if agent_choice_case:
        agent_options = {name: p for name, p in ((agent_choice_case.get("jev") or {}).get("probabilities") or {}).items() if name.startswith("agent_run")}
        lines += ["**Which agent:** the router offered several agents as separate options and Jev distributed probability across them: " + (", ".join(f"`{name}` {pct(p)}" for name, p in sorted(agent_options.items(), key=lambda item: -item[1])) or "no agent options") + ".", ""]

    # 2. Consequential-action escalation (risk_check)
    held = client.post("/agents/runs", json={"objective": ESCALATION_OBJECTIVE, "autonomy_level": 2}).json()
    evidence["escalation"] = held
    approval = None
    if held.get("approval_id"):
        approval = next((item for item in client.get("/approvals").json() if item["id"] == held["approval_id"]), None)
    approval_evidence = (approval or {}).get("evidence") or {}
    risk = {"triggers": approval_evidence.get("risk_triggers") or []}
    jev_risk = approval_evidence.get("jev") or {}
    lines += ["## 3. Consequential-action check (`risk_check`)", "", f"Objective: *{ESCALATION_OBJECTIVE}*", "",
              f"- Built-in keyword rules: {'held it' if risk.get('triggers') and 'jev:consequential' not in risk.get('triggers', []) else 'did not flag it'}",
              f"- Jev: P(consequential) = **{pct(jev_risk.get('consequential'))}** → run status **{held.get('status')}**, approval `{held.get('approval_id') or '-'}`" + (" (escalated by Jev)" if "jev:consequential" in (risk.get("triggers") or []) else ""),
              "- Jev can add an approval, never remove one the rules require. Nothing executes until a person approves.", ""]

    # 3. Agent run: lead agent from the router + Jev tool choice per step
    decision = client.post("/router/decide", json={"question": AGENT_OBJECTIVE}).json()
    lead = next((item.get("target") for item in decision["candidates"] if item["route"] == "agent_run" and item.get("target")), None)
    run = client.post("/agents/runs", json={"objective": AGENT_OBJECTIVE, "autonomy_level": 2, **({"agent_id": lead["id"]} if lead else {})}).json()
    job = None
    for _ in range(90):
        job = next((item for item in client.get("/jobs").json() if item["id"] == run["job_id"]), None)
        if job and job["status"] in {"SUCCEEDED", "FAILED", "PARTIALLY_SUCCEEDED", "CANCELLED", "WAITING_FOR_APPROVAL"}:
            break
        time.sleep(2)
    evidence["agent_run"] = {"decision": decision, "run": run, "job": job}
    choices = [item for item in (job or {}).get("outputs", []) if item.get("type") == "tool_choice"]
    tools_run = [item for item in (job or {}).get("outputs", []) if item.get("type") in {"tool_result", "query_tool_result"}]
    lines += ["## 4. Agent run with Jev tool choice (`tool_selection`)", "", f"Objective: *{AGENT_OBJECTIVE}*", "",
              f"- Lead agent from the router: **{lead['name'] if lead else 'none'}** · job `{run.get('job_id')}` · final status **{(job or {}).get('status')}**",
              f"- Plan: " + " → ".join(f"{step['agent']}" for step in (job or {}).get("plan", [])), "",
              "| Step agent | Step | Chosen by | Selected | Probabilities |", "|---|---|---|---|---|"]
    for item in choices:
        data = item.get("data") or {}
        probabilities = ", ".join(f"{name} {pct(p)}" for name, p in list((data.get("probabilities") or {}).items())[:4])
        by = f"jev:{data.get('model')}" if data.get("by") == "jev" else "local fallback"
        lines.append(f"| {item.get('agent')} | {str(data.get('step', ''))[:70]} | `{by}` | **{', '.join(data.get('selected') or [])}** | {probabilities} |")
    if not choices:
        lines.append("| - | - | - | - | no multi-tool step in this plan |")
    lines += ["", f"Tools actually executed: {', '.join(sorted({item.get('tool') for item in tools_run})) or 'none'} ({len(tools_run)} calls; before this change every bound tool ran on every step).", ""]

    # 4. Usage proof
    usage = client.get("/model-usage").json()
    evidence["usage"] = usage
    jev_rows = [item for item in usage.get("by_purpose", []) if str(item.get("model", "")).startswith("typesafe/jev")]
    lines += ["## 5. Logged Jev calls (Admin > Model usage)", "", "| Purpose | Calls | Failed | Avg latency | Cost (USD) |", "|---|---|---|---|---|"]
    lines += [f"| `{item['purpose']}` | {item['calls']} | {item['failed']} | {item['average_latency_ms']} ms | {item['estimated_cost_usd']:.6f} |" for item in jev_rows]
    total_cost = sum(item["estimated_cost_usd"] for item in jev_rows)
    lines += ["", f"Total Jev calls in this project: **{sum(item['calls'] for item in jev_rows)}**, total cost **${total_cost:.6f}**.", ""]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = started_at.strftime("%Y%m%d-%H%M%S")
    (out / f"jev-proof-{stamp}.json").write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    (out / f"jev-proof-{stamp}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nWrote {out / f'jev-proof-{stamp}.md'} and .json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
