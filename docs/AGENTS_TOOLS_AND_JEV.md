# Agents, tools and Jev: how decisions are made

This page covers how DataPilot's agents and tools work, both internal and external, and where
the Jev decision model makes each choice. It also shows how to demo that live and the status of
every improvement. Code references are relative to `apps/api/app/`.

- **Live proof:** [`demo/`](demo/) holds the latest report from `scripts/demo_jev_agents.py`.
- **Related:** [Learning loop](LEARNING_LOOP.md), [Analytics embedding](ANALYTICS_EMBEDDING.md),
  [Architecture review](ARCHITECTURE_REVIEW_2026-09.md).

## 1. The three registries

| Registry | What it holds | Scope | Who can call it |
|---|---|---|---|
| **Agents** (`AgentDefinition`, `AgentVersion`) | Name, purpose, bound tools, bound query tools, instructions (versioned, publishable) | Platform-wide | Internal only: chat suggestions, `POST /agents/runs`, pipelines |
| **Internal tools** (`ToolDefinition`, `ToolVersion`, `ToolExecution`) | 10 built-in handlers (`catalog.search`, `dataset.profile`, `lineage.query`, `sql.generate`, `sql.preview`, `quality.run`, …) plus allow-listed HTTP tools | Platform-wide | Agents (low-risk built-ins; medium-risk only after a human approved the run); users with `jobs:write` or `registry:write` |
| **Query tools** (`QueryTool`, `QueryToolGrant`) | Parameterised, read-only SQL with a business description, allowed relations, row limit and timeout | Per project | Agents; the chat router; **external clients** through `/external/v1` and MCP |

**External access** is intentionally narrow:
- An `ExternalClient` is bound to one project and authenticates with `client_id.secret`, stored
  as a password hash.
- It can only list and invoke query tools it was explicitly granted.
- Endpoints: `GET/POST /external/v1/query-tools…`, `/.well-known/mcp.json`, and `POST /mcp`
  (`initialize`, `tools/list`, `tools/call`).
- Every call (list, detail, invoke, MCP `tools/list`) is rate-limited per client (60/min; an in-process window takes over without Redis), invocations can have a daily quota per grant, and each is audited as an `ExternalInvocation`.
- Client tokens can expire (`expires_in_days`) and record `last_used_at`.
- External clients cannot reach agents or internal tools.

**Seeded agents** (`seed.py`):

| Agent | Bound tools |
|---|---|
| Planner | catalog.search |
| Metadata | catalog.search, dataset.profile, file.profile, lineage.query |
| SQL Analyst | catalog.search, sql.generate, sql.preview |
| Pipeline | file.profile, pipeline.stage, schedule.run |
| Quality | catalog.search, quality.run |
| Troubleshooter | catalog.search, job.inspect, lineage.query |
| Policy | catalog.search, job.inspect |
| Analytics | catalog.search, dataset.profile, sql.generate, sql.preview, lineage.query |

## 2. The lifecycle of a request, and who decides each step

```
chat message ──► decision_routing ──► route + WHICH agent / WHICH query tool   (Jev)
                                     │
"Start <agent> agent" ──► POST /agents/runs {objective, agent_id}
                                     │
                     risk rules ──► risk_check: "is this consequential?"        (Jev, escalate only)
                                     │           └─ p ≥ 0.7 → approval hold, bound to plan hash
                     agent_planning ──► 3–6 {agent, action} steps; lead agent must own one  (LLM)
                                     │
                 for each step: tool_selection ──► which bound tool(s) fit this step  (Jev)
                                     │           tool_parameters ──► fill parameters     (heuristic, then LLM)
                                     │           execute (budget 12 calls, reflection on error)
                     agent_review ──► may append ≤2 safe steps                          (LLM)
```

| Decision | Purpose (Model routing) | Who decides | Output | Guard rails |
|---|---|---|---|---|
| Which route, which agent, which query tool | `decision_routing` | **Jev** (LLM or local scorer as fallback) | A probability for each option, e.g. `agent_run:Troubleshooter 93%` | Options come from the registry only; Jev sees only the question text |
| Does this objective change, move, publish or send data? | `risk_check` | **Jev** | P(consequential) | Can **add** an approval (p ≥ 0.7), never remove one the rules require |
| Which bound tool fits this plan step | `tool_selection` | **Jev** (local word overlap as fallback) | A probability for each eligible tool; top-1 plus any ≥ 25%, at most 2 | Only published, non-approval built-ins: low-risk, or medium-risk when a human approved the run |
| Which SQL candidate wins a split vote | `sql_candidate_judge` | **Jev** | A probability for each candidate | Used only when the multi-model vote has no majority |
| Plan steps | `agent_planning` | LLM (Claude Sonnet 5) | JSON steps | Enabled agent names only; deterministic fallback plan |
| Tool parameters | `tool_parameters` | Deterministic grounder, then LLM | JSON | Schema-validated; IDs must resolve in this project |

**Why Jev for these and an LLM for the rest.** Jev answers *typed* questions (choice, yes/no,
score) with calibrated probabilities. It cannot invent an option that isn't on the menu, and it
answers in about 0.3 s for about $0.00002. Planning and parameter filling produce free text, so
they stay with a generative model. The admin UI and the API refuse to route a decision model to
a generation purpose.

### What Jev is allowed to see
- Only trusted text: the question or objective, the step text, and registry descriptions of
  routes, agents and tools.
- For the SQL judge: SQL text and column names.
- Never result rows, tool output or retrieved documents.

Published tests show adversarial text can shift Jev's verdicts, so it is never the last line of
defence. Approvals and risk rules stay deterministic, and Jev can only make them stricter.

## 3. What changed in this pass

| Before | After | Where |
|---|---|---|
| Every bound tool ran on every step, ignoring the step text. `catalog.search` used most of the 12-call budget. | Jev picks the tool(s) for each step. The choice, probabilities, latency and cost are stored as a `tool_choice` output and evidence entry (Jobs → Run trace). | `temporal_activities._select_step_tools`, `jev_client.choose_tools` |
| The router offered one "agent" option, so Jev could not choose *which* agent. | Up to three agents are offered as separate options (a named agent isn't second-guessed). | `decision_router.local_scores` |
| "Start agent run" dropped the chosen agent. | `POST /agents/runs` accepts `agent_id`. The planner must give that lead agent a step, and it is recorded in evidence and audit. The chat button reads "Start Troubleshooter agent". | `routers/agents.py`, `schemas.AgentRunRequest`, `ConversationsView.tsx` |
| The planner's output was cut off at 800 tokens, so it silently used the fixed plan. | 1600 tokens, a "keep each action under 25 words" instruction, and tolerant array extraction. | `_plan_for_job` |
| A tool whose parameters couldn't be grounded was dropped silently. | It is logged ("skipped X: its required parameters could not be grounded"). The grounder also reads the step text, and accepts a bare table name when exactly one catalogued dataset has it. | `_parameters_for_tool` |
| `/router/decide` and `/router/evaluate` didn't commit, so their Jev calls were missing from usage. | Committed. `GET /model-usage` adds `by_purpose` (calls, failures, average latency and cost per decision type). | `routers/decisions.py`, `routers/model_providers.py` |

## 4. Demo: proof that Jev is making the decisions

```bash
docker compose --profile analytics up -d --build
python scripts/demo_jev_agents.py            # writes docs/demo/jev-proof-<timestamp>.md + .json
```

The script logs in as the demo admin and records the following:

1. **Which purposes are routed to Jev** (from `/model-routing`).
2. **Five routing cases** (SQL question, named agent, unnamed agent, vague, consequential), with
   Jev's probabilities, P(consequential), latency and cost.
3. **An objective the keyword rules miss** ("Copy all customer records to the marketing shared
   drive"). Jev escalates it and a plan-bound approval is created; nothing runs.
4. **A real agent run** with the router's lead agent. The plan comes from Claude, and each step
   shows Jev's tool choice with probabilities, plus which tools actually ran.
5. **Logged calls** per purpose from Model usage, matching the verdicts above.

Latest live result (2026-09-24, `typesafe/jev-1.13-20260917`):

| Check | Jev verdict |
|---|---|
| "Total transaction amount by type?" | sql_analysis 92% |
| "Run the Quality agent to validate null checks" | agent_run:Quality 98% |
| "Validate null checks then investigate why the nightly loads failed" (no agent named) | agent_run:Troubleshooter 93%, Planner 7% |
| "hello" | clarify 100% |
| "Copy all customer records to the marketing shared drive" | P(consequential) 90%. The keyword rules missed it; Jev escalated it to approval. |
| Metadata step "Retrieve lineage graph for staging.transactions" | lineage.query 100% |
| Analytics step "Explain how … metrics use the dataset" | dataset.profile 74%, lineage.query 24% |

- **Speed and cost:** about 310 ms per Jev call and about $0.00002 per call. 33 calls in the
  project cost $0.0006 in total.
- **Router accuracy on 11 labelled cases (earlier run):** Jev 100% at 325 ms, LLM 100% at
  1075 ms, local 82%.

**Where to show it in the UI:**
- **Analysis chat:** the inspector's *Route* section shows the Jev decision and probabilities.
- **Jobs:** the run trace shows each `Tool choice` output.
- **Approvals:** the escalated item carries an "Escalated by Jev" badge.
- **Admin → Model usage:** Jev calls with their cost.
- **Learning → Router evaluation:** run local, llm and jev side by side on your own cases.

## 5. Improvement list: status (2026-09-24 closure)

All 16 items from the earlier code walk-through have been implemented and tested. The
full backend suite passes (211 passed, 1 skipped).

### Internal agents and tools

| # | Item | Status | What changed |
|---|---|---|---|
| 1 | Agent configuration unused at run time | **Done** | Each step runs at the lower of the run's autonomy and the agent's `autonomy_level`. A published version's `model_provider_id` is used for parameter filling and reflection when it can generate text (a pin to the local deterministic model is ignored). Version `instructions` go to the planner and the parameter filler as context that cannot relax any rule. `input_schema` and `config` are still unused. |
| 2 | Advertised budget not enforced | **Done** | Reflection retries count against the 12-call budget. `AGENT_RUN_MAX_SECONDS` (default 300) is checked before each step and inside the tool loop. Unfinished steps are skipped as "run time budget exceeded" and the run ends `PARTIALLY_SUCCEEDED`. The limit label reads from the real constants. |
| 3 | Built-in tools had no timeout; `sql.preview` not project-scoped | **Done** | Built-ins run in a worker thread with the version's `timeout_seconds`, which is also the database statement timeout. Timeouts are not retried. `sql.preview` refuses tables that aren't queryable catalogued assets of the run's project. |
| 4 | Agent tool calls missing from the tool audit | **Done** | Every internal tool attempt inside an agent run writes a `ToolExecution` row (job id, status, duration, parameters, result or error). Query tools keep their governance events. |
| 5 | Medium-risk tools could never run inside agents | **Done** | They run only when a human approved the run (`agent_execution` approval). Steps added by the reviewer are excluded. The same rule applies to Jev's eligible tool set, and evidence records "ran under approval". |
| 6 | HTTP egress checked the hostname only | **Done** | Private, loopback, link-local, multicast and reserved IPs are refused unless `TOOL_HTTP_ALLOW_PRIVATE=true` (Compose: true, Kubernetes: false). The request connects to the checked IP, with SNI and Host kept, which blocks DNS rebinding. Responses are capped at `TOOL_HTTP_MAX_BYTES`, and credentials in URLs are refused. |
| 7 | Self-approval allowed | **Done** | With `APPROVAL_SEPARATION_OF_DUTIES=true` (on in Kubernetes, off for the single-admin local demo), the requester cannot approve their own agent run, index DDL, prompt activation, publication, tool execution, deploy or retention request. They can still reject it. |
| 8 | Publishing without evaluation | **Done** | Publishing an agent version returns 409 without an evaluation score of at least `AGENT_PUBLISH_MIN_SCORE` (default 0.8, i.e. the scorecard's 80%). An admin can override with `?force=true`, which is audited. |

### External (MCP / gateway)

| # | Item | Status | What changed |
|---|---|---|---|
| 9 | Client tokens never expired | **Done** | `expires_at` and `last_used_at` (Alembic `0006_gateway_token_lifecycle`). `expires_in_days` (1–365) is accepted on create and rotate. Expired tokens get 401. Admin → Gateway shows expiry and last use. |
| 10 | Rate limiting failed open without Redis | **Done** | An in-process sliding window takes over when Redis is missing or erroring. One per-client limit covers invoke, REST list and detail, and MCP `tools/list`. |
| 11 | MCP gaps | **Done** (except streamable HTTP) | `ping`, JSON-RPC batches, notifications (202, no body), and errors -32601, -32600 and -32700. GET/SSE streamable HTTP is not implemented. |
| 12 | No per-tool quotas | **Done** | `QueryToolGrant.daily_quota`. Past the quota a call gets 429 with Retry-After, and the event is audited. Set per grant in Admin → Gateway. |
| 13 | `/query-tools/{id}/test` had no permission check | **Done** | Requires the query-runner permission; viewers get 403, which is audited. The chat "Run tool" button shows a clear permission message. |

### Jev

| # | Item | Status | What changed |
|---|---|---|---|
| 14 | Judge every split vote | **Done** | With the cascade vote, a split between the first two models asks the third. Any remaining split with two or more runnable candidates goes to Jev, and the tie-break is stored in the answer's ensemble. |
| 15 | Evaluate tool choice | **Done** | `POST /router/evaluate-tools` and the Learning → Router → *Tool choice evaluation* panel score the local chooser against Jev on labelled "agent step → expected tool" cases. |
| 16 | Data residency | **Done** | Route a project's decision purposes to the local deterministic model (Admin → Model routing, "on-prem, no external call"). That project's routing, risk check, tool choice and tie-break then run locally, and no request text goes to OpenRouter. |

### Also fixed in this closure

| Item | What changed |
|---|---|
| Profiled-only files broke SQL (`relation "file_profiles.transactions" does not exist`) | `catalog_scope.py` keeps catalog entries without a table out of SQL generation and grounding. Datasets shows a "profile only" tag. |
| Sonnet 5 called on every question | Cascade vote (`SQL_VOTE_MODE=cascade`): the third model is asked only when the first two disagree. |
| Jev didn't know which table matched | Catalog evidence (for example "best staging.transactions (Ingested from transactions.csv)") is now in Jev's option text. "…in the uploaded file?" went from clarify 57% to SQL 82%. Jev scored 100% on 11 labelled routes. |
| Run budget and lead-agent evidence dropped mid-run | Kept through prepare and finalize. |

### Still open by design
- MCP streamable HTTP (GET/SSE).
- A timed-out built-in tool's thread is stopped only at the database level, then left to finish on its own.
- `AgentVersion.input_schema` and `config` are not used at run time.
