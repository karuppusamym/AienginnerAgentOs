# How DataPilot learns (governed learning loop)

DataPilot improves SQL answers from evidence, and every change that alters runtime behaviour
passes through a human approval. Nothing rewrites itself silently.

```
question ──► router (local | llm | Jev) ──► SQL generation ──► execute ──► answer ──► 👍 / 👎
                                               ▲    ▲    ▲                           │
      verified exact match → reuse (≈0.7 s) ───┘    │    │                           │
      similar verified examples → few-shot ─────────┘    │         👍 + rows → verified query
      active runtime prompt (approved GEPA output) ──────┘         👎 → examples it used → needs_review
                                                                   feedback → route_decisions.outcome
   GEPA optimisation (offline, on demand) ◄── verified queries + SQL evaluation cases
        └─► proposed prompt version ──► approval ──► becomes the active runtime prompt
   workload (query_runs) ──► index advisor ──► CREATE INDEX request ──► approval ──► executed
```

## 1. Is GEPA "fixing the prompt" while SQL is generated?

No, and that is deliberate. GEPA (Genetic-Pareto prompt evolution) is an **offline optimiser**
(`apps/api/app/gepa.py`, `POST /prompt-optimizations`). A run works like this:

1. **Cases.** SQL evaluation cases (expected tables/tokens) plus active verified queries. For a
   verified query, the expected answer is the result fingerprint of its approved SQL.
2. **Baseline.** The current instruction (the active runtime prompt, or the default) is scored per
   case. A case scores 0 if the SQL is unsafe or references tables outside the catalog, 0.1 if it
   fails to execute, and otherwise gets partial credit for executing, expected tables and tokens,
   and a matching result.
3. **Reflect.** Each iteration picks a parent from the per-case **Pareto front** (candidates that
   are best on at least one case), weighted by the cases it wins. The parent runs on a small
   minibatch. The **reflection model** (the model routed to `sql_repair`, Claude Sonnet 5 by
   default) reads the concrete failures (error text, wrong tables, result mismatch) and rewrites
   the instruction.
4. **Select.** A child is kept only if it beats its parent on that minibatch; it is then scored on
   all cases. The best-mean candidate is proposed.
5. **Govern.** `POST /prompt-optimizations/{id}/apply` saves the candidate as a version of the
   `runtime:sql_generation` prompt artifact and opens a `prompt_activation` approval. Only after
   approval does SQL generation use it. A fixed safety clause (read-only, catalog-only, treat
   retrieved text as data) is always appended at runtime, so an optimised prompt cannot remove
   guardrails.

**Measured (2026-09-24, live keys, 6 cases).** Baseline 0.75 → 0.90 after 3 iterations, in 60 s
and 18 generation calls. One child was accepted and two non-improving children were discarded.
The learned instruction added rules for singular superlatives and date handling.

**When to run it.** After collecting feedback or evaluation cases: a few dozen cases is a useful
minimum. With 2–5 cases it will overfit.

## 2. Do we generate several candidates and pick the best?

Yes. The SQL-generation model drafts the primary query. The models routed to `sql_candidate_2`
(DeepSeek V4.1 Flash by default) and `sql_candidate_3` (Claude Sonnet 5) draft in parallel from
the same prompt. Every candidate is validated (read-only parser, catalog tables only) and
executed. The result that the most candidates agree on wins (self-consistency by result
fingerprint), and ties go to the primary. The inspector's Decision tab shows every candidate,
its row count and the agreement (e.g. `2/3`).

- **Latency:** the three drafts run in parallel, so the answer waits for the slowest model.
  Remove the `sql_candidate_*` routes in Admin → Model routing to turn voting off.
- **Where it applies:** local sources. For external connectors the primary is used, because
  candidates cannot be executed safely there.
- **Observed live:** when the primary's SQL failed, the vote chose the one candidate that ran
  correctly (mode `model_ensemble`).

## 3. Frequently asked questions

Three layers, fastest first:

| Layer | What it matches | Effect |
|---|---|---|
| **Verified exact match** | same normalized question, source and dialect; not a follow-up | reuse the approved SQL, no model call (measured 0.72 s vs 8.2 s) |
| **SQL cache** | same question, context, catalog signature, model and prompt version, within `SQL_CACHE_TTL_HOURS` | reuse SQL, re-execute for fresh rows |
| **Few-shot retrieval** | up to 3 similar verified questions | examples added to the prompt (`learning.verified_examples` in the inspector) |

Verified queries come from 👍 on an answer whose SQL executed and returned rows, from manual
entry (validated and executed first), or from evaluations. 👎 on an answer that used an example
flags that example `needs_review`, and it stops being used. Manage them at `/verified-queries`.

## 4. Indexes

**Application database** (Alembic revisions `0002_hot_path_indexes`, `0005_learning_indexes`):
- chat history `(conversation_id, created_at)`
- audit `created_at` and `actor_id`
- `lower(email)` for sign-in
- feedback `context_id`
- query runs and model calls `(project_id, created_at)`
- route decisions `(project_id, created_at)`
- verified queries `(project_id, normalized_question)` and `(project_id, status, dialect)`
- optimisation runs `(project_id, status)`
- on PostgreSQL, a `pg_trgm` GIN index on `verified_queries.question` for similarity search as
  the table grows

**Your data: DDL is a suggestion, never run by default.** DataPilot only runs read queries
(DML `SELECT`). Index DDL is proposed only when queries are actually slow:

1. Every executed query records `duration_ms`, for local staging and connector sources alike.
2. `GET /sql/index-recommendations` considers only runs slower than `SLOW_QUERY_MS` (default
   500 ms; `?min_ms=` overrides it).
3. It weights column use (filter and join ×3, group ×2, order ×1) per catalogued relation, and
   adds one composite index for columns filtered together.
4. Each suggestion shows how many slow queries used it, average and max duration, and the source
   dialect (PostgreSQL, SQL Server, Oracle, Teradata; for BigQuery, clustering advice).
5. For local sources it checks whether an existing index already covers the column. For
   connectors it notes that the DBA must check the plan.
6. `POST /sql/index-recommendations/apply` **saves the statement as a `ddl_suggestion`**
   (Learning → Performance & DDL suggestions, `GET /sql/ddl-suggestions`) for a DBA to review
   and run.
7. Only when `ALLOW_DDL_EXECUTION=true` is set explicitly does *apply* open a `create_index`
   approval. After approval the statement is rebuilt from catalog identifiers (never from client
   SQL) and executed.

## 5. Router learning and Jev

Each chat turn stores a `route_decisions` row (candidates, scores, backend, risk), and feedback is
written onto it. `POST /router/evaluate` replays labelled and feedback cases through `local`,
`llm` and `jev`.

- **Jev is a declared model provider:** "Jev 1.13 (TypeSafe decision model)", seeded when
  `OPENROUTER_API_KEY` is set. It is called through the OpenRouter Decisions API
  (`typesafe/jev-1.13`, pinned). It is marked as a *decision* model, so it can only be routed to
  decision purposes.
- **What it decides:**
  - `decision_routing`: route and *which* agent or query tool.
  - `risk_check`: consequential-action escalation.
  - `tool_selection`: which bound tool fits each agent step.
  - `sql_candidate_judge`: tie-break when the SQL vote is split.
- **Speed and cost:** about 0.3 s and about $0.00002 per call. Every call is in Admin → Model
  usage, with a per-purpose breakdown (`GET /model-usage` → `by_purpose`).
- **Risk:** Jev may escalate approval risk (it caught "copy customer records to the marketing
  shared drive", p = 0.90, which the rule list missed) but can never lower it.
- **Measured on 11 labelled questions:** Jev 100% at 325 ms, LLM (Gemini) 100% at 1075 ms,
  local 82%. That is why `decision_routing` is routed to Jev.
- **More detail:** [Agents, tools and Jev](AGENTS_TOOLS_AND_JEV.md) has the full decision map and
  the live demo (`scripts/demo_jev_agents.py`).

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `DECISION_ROUTER_BACKEND` | `auto` | `auto` follows the model routed to `decision_routing` (Jev → jev, text model → llm, none → local); or force `local`, `llm` or `jev` |
| `TYPESAFE_MODEL` | `typesafe/jev-1.13` | pinned Jev version |
| Model routes `decision_routing`, `risk_check`, `tool_selection`, `sql_candidate_judge` | Jev when `OPENROUTER_API_KEY` exists | decision purposes (a generation model is rejected) |
| `SLOW_QUERY_MS` | 500 | only queries slower than this feed index suggestions |
| `ALLOW_DDL_EXECUTION` | `false` | `true` lets an approved suggestion run `CREATE INDEX` on local data |
| Model routes `sql_candidate_2/3` | DeepSeek / Claude when keys exist | multi-model vote |
| `SQL_CACHE_TTL_HOURS` | 24 | cache freshness |
