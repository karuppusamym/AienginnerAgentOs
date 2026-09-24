# Agents, tools and Jev: how decisions are made

This page covers how DataPilot's agents and tools work, both internal and external, and where
the Jev decision model makes each choice. It also shows how to demo that live and what to
improve next. Code references are relative to `apps/api/app/`.

- **Live proof:** [`demo/`](demo/) holds the latest report from `scripts/demo_jev_agents.py`.
- **Related:** [Learning loop](LEARNING_LOOP.md), [Analytics embedding](ANALYTICS_EMBEDDING.md),
  [Architecture review](ARCHITECTURE_REVIEW_2026-09.md).

## 1. The three registries

| Registry | What it holds | Scope | Who can call it |
|---|---|---|---|
| **Agents** (`AgentDefinition`, `AgentVersion`) | Name, purpose, bound tools, bound query tools, instructions (versioned, publishable) | Platform-wide | Internal only: chat suggestions, `POST /agents/runs`, pipelines |
| **Internal tools** (`ToolDefinition`, `ToolVersion`, `ToolExecution`) | 10 built-in handlers (`catalog.search`, `dataset.profile`, `lineage.query`, `sql.generate`, `sql.preview`, `quality.run`, …) plus allow-listed HTTP tools | Platform-wide | Agents (low-risk built-ins only); users with `jobs:write` or `registry:write` |
| **Query tools** (`QueryTool`, `QueryToolGrant`) | Parameterised, read-only SQL with a business description, allowed relations, row limit and timeout | Per project | Agents; the chat router; **external clients** through `/external/v1` and MCP |

**External access** is intentionally narrow:
- An `ExternalClient` is bound to one project and authenticates with `client_id.secret`, stored
  as a password hash.
- It can only list and invoke query tools it was explicitly granted.
- Endpoints: `GET/POST /external/v1/query-tools…`, `/.well-known/mcp.json`, and `POST /mcp`
  (`initialize`, `tools/list`, `tools/call`).
- Every invocation is rate-limited (60/min per client) and audited as an `ExternalInvocation`.
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
| Which bound tool fits this plan step | `tool_selection` | **Jev** (local word overlap as fallback) | A probability for each eligible tool; top-1 plus any ≥ 25%, at most 2 | Only low-risk, published, non-approval tools are eligible |
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

## 5. Recommended improvements (not yet done)

Ordered by value. File references come from a code walk-through on 2026-09-24.

### Internal agents and tools
1. **Read the agent configuration at run time.** `AgentVersion.instructions`,
   `model_provider_id`, `input_schema` and `AgentDefinition.autonomy_level` are stored but not
   used. The provider comes from project routing and autonomy from the request.
2. **Enforce the advertised budget.** "5 agents / 12 tool calls / 5 minute budget" is only
   partly enforced:
   - Reflection retries don't count against the budget.
   - There is no wall-clock or cost limit.
   - The no-Temporal fallback runs inside the HTTP request.
   - Add a per-run deadline and a cost cap.
3. **Built-in tool timeouts and scoping.** `timeout_seconds` applies only to HTTP tools, and
   `sql.preview` doesn't scope reads to the run's project. Wrap built-ins in the same timeout, and
   pass `project_id` into the read-only guard.
4. **One audit trail.** Agent tool calls write job evidence and governance events but no
   `ToolExecution` rows, so the tool registry's usage view under-counts. Write both.
5. **Let agents use medium-risk tools after approval.** `sql.preview`, `quality.run` and
   `pipeline.stage` are bound to agents but can never run inside a loop (low-risk only). Allow
   them when the run was approved *and* the tool was in the approved plan.
6. **HTTP tool egress.** The allowlist checks only the hostname. Add private-IP and
   DNS-rebinding checks and a response-size cap.
7. **Two-person rule.** An approver can approve their own request. Block self-approval for
   `agent_execution`, `create_index` and `prompt_activation`.
8. **Publishing gates.** Agent versions can be published without an evaluation score, and query
   tools without the "tested" status. Require a passing scorecard.

### External (MCP / gateway)
9. **Client token lifecycle.** Add expiry, last-used time and scoped rotation. Tokens currently
   never expire.
10. **Rate limiting without Redis.** It fails open when Redis is down, and `tools/list` isn't
    limited. Fail closed for `tools/call`.
11. **MCP completeness.** Add `ping`, batching and correct notification handling (no body). Add
    streamable HTTP (GET/SSE) for clients that need it.
12. **Per-tool quotas and scopes** beyond `tools:list` and `tools:invoke`.
13. **Permission check on `/query-tools/{id}/test`.** Any project member can run it, and chat
    "Run tool" uses it. Route chat through the governed invoke path, and require `jobs:write` for
    `/test`.

### Jev
14. **Judge SQL candidates by default.** Use Jev for SQL candidates on every split vote (not
    only 1/3), and log the judged-vs-voted winner for evaluation.
15. **Evaluate tool choice.** Add labelled "step → expected tool" cases to Learning → Router
    evaluation so `tool_selection` accuracy is measured like routing.
16. **Data residency.** Question text goes to OpenRouter/TypeSafe. For regulated projects, route
    decision purposes to an on-prem decision model behind the same provider type, or to the local
    scorer.
