# External agent demo: bring your own agent to DataPilot's tool registry

This folder shows an agent that lives **outside** DataPilot connecting to DataPilot's
governed tool registry over MCP. The agent discovers the tools it is allowed to use,
picks tools, runs them, answers, and then **checks its own answer against the data (QA/QC)**.

```
 external agent (any framework)            DataPilot
 ------------------------------            ---------------------------------------------
 plain Python  mcp_agent.py   --MCP-->  POST /mcp  initialize / tools/list / tools/call
 Google ADK    adk_agent/     --MCP-->     |  bearer client token -> scopes, expiry
 your agent    (any MCP client)            |  grants per tool, daily quota, rate limit
                                           |  arg validation (types, enums), read-only SQL
                                           |  PII masking, row limits, timeouts
                                           v
                              ExternalInvocation history + audit + governance events
```

The agents contain **no DataPilot code**. All they get is a URL and a client token.

## Files

| File | What it is |
|---|---|
| `setup_demo_gateway.py` | One-time, idempotent admin setup: 6 query tools (draft, then test, then publish), an external client, grants, and the token in `.client.env` |
| `mcp_agent.py` | Plain-Python agent. Needs only `httpx`. Calls the LLM over plain HTTP: Gemini, or OpenRouter as a fallback |
| `qc_agent.py` | QA/QC verifier (grounding, re-derivation, reproduction) and golden-set scorer |
| `qc_rules.json` | Independent re-derivation paths: aggregate tool ↔ detail tool |
| `golden_set.json` | Questions with known answers and tolerances |
| `adk_agent/agent.py`, `run_adk.py` | Google ADK agent. DataPilot is attached as an `McpToolset`; the model is Gemini |
| `watch_invocations.py` | Admin view that shows the agents' calls landing in DataPilot |
| `requirements-adk.txt` | Pinned packages for the isolated ADK venv |
| `.client.env`, `.venv/` | **Gitignored.** The client token and the ADK virtualenv |

## Prerequisites

- The stack is running: API at `http://localhost:8000`, web app at `http://localhost:3001`. The admin is `admin@datapilot.local`.
- The demo connectors are registered (`python scripts/register_demo_connectors.py`). Setup uses the **Demo PostgreSQL — Direct** connector and local staging (`staging.transactions`, `core.accounts`).
- Python 3.11+ with `httpx`.
- The repo-root `.env` holds `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, or both. The agents read these keys and never print them. Model overrides: `GEMINI_MODEL` (default `gemini-3.6-flash`), `OPENROUTER_MODEL`, `ADK_MODEL`. With no key, `mcp_agent.py --llm none` uses an offline keyword planner.

## One-time setup

```powershell
# 1. Tools, client, grants, token (safe to re-run; --rotate issues a fresh token)
python scripts/external_agent/setup_demo_gateway.py

# 2. ADK variant only: isolated venv (never installed into the API's Python)
python -m venv scripts/external_agent/.venv
scripts/external_agent/.venv/Scripts/python -m pip install -r scripts/external_agent/requirements-adk.txt
#   macOS/Linux: scripts/external_agent/.venv/bin/python -m pip install -r ...
```

Setup creates these tools, all tagged `external-agent-demo`. It never touches tools or clients it did not create.

| Tool | Source | Shape |
|---|---|---|
| `banking.txn_totals_by_type` | local `staging.transactions` | aggregate |
| `banking.txns_by_type(txn_type)` | local `staging.transactions` | detail (enum-validated) |
| `banking.account_lookup(account_id)` | local `core.accounts` | lookup |
| `commerce.payments_summary` | Postgres `demo.payments` | aggregate |
| `commerce.payments_by_status(status)` | Postgres `demo.payments` | detail (enum-validated) |
| `commerce.customer_orders(customer_id)` | Postgres `demo.orders` joined to `demo.customers` | lookup (no PII columns) |

Each tool goes through the real lifecycle: `POST /query-tools` creates a draft, `POST /query-tools/{id}/test` runs the SQL and sets the status to `tested`, and `POST /query-tools/{id}/publish` publishes it as admin. Any pending approval that references the tool is approved through `/approvals/{id}/decision`. The client `External agent demo (MCP)` gets scopes `tools:list` and `tools:invoke`, a 30-day expiry, and a grant on each tool with a daily quota of 500.

## Demo runbook

Run the commands from `scripts/external_agent/`. Keep a second terminal open for step 0.

**0. Watch the calls land.** Say: *"This is DataPilot's side. Every call an outside agent makes shows up here."*
```powershell
python watch_invocations.py --follow
```
You can show the same history in the UI: **Tools → External data tools** (registry, invocation counts, per-tool analytics). The admin API also has `GET /external-invocations` and `GET /audit`, and `python watch_invocations.py --audit` prints the publish, grant, and client events.

**1. Discovery.** Say: *"The agent only has a URL and a token. It asks DataPilot what it may use."*
```powershell
python mcp_agent.py --list-tools
```
Point out that only the six granted, published tools are visible. Each has a JSON schema with types and enums, plus registry metadata (owner, line of business, data source, version).

**2. Plan without executing.** Say: *"The LLM chooses the tool and arguments from the schemas alone."*
```powershell
python mcp_agent.py "Which orders did customer 7 place?" --dry-run
```

**3. Full run.** Say: *"Now it calls the tool. DataPilot validates the arguments, runs read-only SQL, masks PII, and records the call."*
```powershell
python mcp_agent.py "What is the total amount of settled payments, and how many are there?"
```
The output walks through numbered steps: connect, discover, plan (with why), execute (rows plus invocation id), and the answer with evidence. Each figure is tied to a tool and an invocation id. Point at the watcher: the call appears there with the same invocation id.

**4. Governance refusals.** Say: *"The agent can't reach anything it wasn't granted, and bad arguments are refused."*
```powershell
python mcp_agent.py --call customers.lookup '{"customer_id": 1}'        # published, but not granted: 404
python mcp_agent.py --call banking.txns_by_type '{"txn_type": "refund"}' # not an allowed enum value: 400
```
In Windows PowerShell 5.1, escape the inner quotes: `'{\"customer_id\": 1}'`.

**5. QA/QC on one answer.** Say: *"Before we trust the answer, a checker goes back to the data a different way."*
```powershell
python mcp_agent.py "What is the total amount of deposit transactions, and how many were there?" --qc
```

**6. Show QC catching errors.** Say: *"Here's what it looks like when the answer or the source is wrong."*
```powershell
python qc_agent.py "How many payments are still pending?" --inject-error answer   # hallucinated figure: FAIL
python qc_agent.py "List the settled payments and their total" --inject-error data  # buggy source tool: FAIL
```

**7. Golden set.** Say: *"Here's how we'd gate an agent release: known questions, known answers, and QC on each."*
```powershell
python qc_agent.py --golden            # add --verbose to see every step
```

**8. Same registry, different framework (Google ADK).** Say: *"This is a Google ADK agent. It has no tool code; DataPilot's MCP server is attached as a toolset."*
```powershell
.venv/Scripts/python run_adk.py "How many debit transactions are there and what do they add up to?"
.venv/Scripts/adk web        # optional: ADK dev UI, choose datapilot_external_agent
```
The ADK agent is told to self-check with a differently shaped tool, and it ends with a `QC: PASS/FAIL` line.

## How QA/QC works (checking the answer against the data)

`qc_agent.verify_run()` makes its own calls through the same governed gateway, so every check is audited too.

1. **Grounding.** Every key figure in the answer must trace to the rows the agent received: a cell, a column sum, a row count, or a per-group sum or count. A number with no source means the model made it up, and the check **FAILs**. Numbers in the answer text that can't be traced are reported as warnings.
2. **Re-derivation.** For each tool the agent used, `qc_rules.json` names a **differently shaped** tool:
   - *drilldown*: the agent used an aggregate tool. QC fetches the detail rows for each aggregate row and recomputes every `count` and `sum`.
   - *rollup*: the agent used a detail tool. QC fetches the aggregate tool and checks that the detail rows add up to it.

   Any disagreement **FAILs**, as does truncated evidence. This catches stale or buggy source tools, not only LLM mistakes.
3. **Reproduction.** Each key figure must also be reproducible from the independently fetched rows alone.
4. **Golden set.** End-to-end scoring against `golden_set.json` (`value` ± `tolerance`, or `text_contains`). It reports answer accuracy, tool-choice accuracy, and the QC pass rate. The exit code is non-zero unless everything passes, so it can run in CI.

To add a re-derivation path, publish a second tool with a different shape over the same data. Then add an entry to `qc_rules.json` that maps its columns (`compare: {"aggregate_col": "count" | "sum:detail_col"}`). Tools with no path (the lookups) get grounding only, and the output says so.

## Bring your own agent

Any MCP client that speaks streamable HTTP can connect:

- URL: `http://localhost:8000/mcp` (metadata at `/.well-known/mcp.json`)
- Header: `Authorization: Bearer <client_id>.<secret>`. Issue a client under Tools → External data tools, or via `POST /external-clients`, then grant it tools.
- Methods: `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, `ping`, and JSON-RPC batches.

DataPilot answers each POST with `application/json`. It issues no `Mcp-Session-Id` and has no GET/SSE stream (GET `/mcp` returns 405). The MCP spec allows this, and the official MCP Python SDK (used by ADK's `McpToolset`) works with it unchanged. The ADK variant therefore needed **no DataPilot change**.

A REST alternative for non-MCP frameworks: `GET /external/v1/query-tools`, `POST /external/v1/query-tools/{name}/invoke`, and `GET /external/v1/openapi.json` (an OpenAPI 3.1 spec of the granted tools).

## Troubleshooting

- **`Rate limit exceeded` (HTTP 429):** the per-client limit is `EXTERNAL_QUERY_TOOL_RATE_LIMIT_PER_MINUTE` (default 60), and it covers list and invoke. A golden run uses about 30 calls. The agent backs off once for 15 s.
- **`External client token has expired`, or a 401:** run `python setup_demo_gateway.py --rotate`.
- **`Published query tool not found`:** the tool isn't granted to this client, or it was retired or re-versioned back to draft. Re-run setup.
- **Golden values drift:** they were read from the demo data on 2026-09-24. Update `golden_set.json` if the demo data is re-seeded.
