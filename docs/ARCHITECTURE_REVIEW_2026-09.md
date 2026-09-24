# DataPilot architecture review — devil's-advocate pass (2026-09-23)

Scope: full API and web UI review, the 3-panel Analysis chat, a decision layer for picking
routes/tools/agents (Jev, GEPA/DSPy), and Open Knowledge Foundation (Frictionless) interchange.
Findings cite `file:line` as of this review. "Done" items shipped in the same change set.

## 1. The uncomfortable summary

1. **The most important problems are not routing or UX. They are security and request design.**
   Local SQL runs on the application's own database engine, so any "read-only" query could read
   `users.password_hash`. High-risk endpoints check project membership, not permission. The ask
   path holds a write transaction open across up to four LLM calls. Fix these before adding more
   intelligence.
2. **"Agentic" today is mostly deterministic plumbing.** Chat always generates SQL. Tools bound to
   an agent are all attempted in order, whatever the step says. Approval was a substring keyword
   match (`"rewrite"` matched `write`, `"Update prices"` did not match). There was no single place
   that decided *what should handle a request*.
3. **The data needed for a learned router mostly exists** (QueryRun, UserFeedback, EvaluationRun,
   Approval decisions, ModelCallLog). It isn't linked to decisions, so nothing can learn from it
   yet.

## 2. What shipped in this change set

| Area | Change | Files |
|---|---|---|
| Decision router | Scored, explainable routing for every chat turn (`sql_analysis`, `query_tool`, `agent_run`, `clarify`). Each candidate carries a score and reasons, plus calibrated confidence, a versioned policy, and a pluggable backend (`local` or `jev`). Tool and agent routes are surfaced as suggested actions, not auto-executed. | `apps/api/app/decision_router.py`, `routers/conversations.py` |
| Router API | `POST /router/decide` (preview), `GET /router/policy`, `GET /router/decisions` (decision + outcome export: the training/eval set for offline optimisation). | `routers/decisions.py` |
| Approval risk | One shared `assess_risk()` with word-boundary and inflection matching; adds update/insert/modify/remove/merge. Replaces three divergent keyword copies (`main.py`, `temporal_activities.py`). Agent approvals now record the real risk level and which terms triggered it. | `decision_router.py`, `main.py`, `routers/agents.py`, `temporal_activities.py` |
| SQL guard (stopgap for C1) | Rejects FROM/JOIN references to DataPilot metadata tables and `pg_authid`/`sqlite_master` in every governed read-only path. SQLite uploads named like an app table get a `stg_` prefix instead of replacing it. | `apps/api/app/staging.py` |
| Chat API | `list_conversations` uses aggregate queries instead of loading every message (the N+1). Answers carry `route`, `follow_ups`, `question`. The chat line no longer embeds raw driver errors with full SQL. | `routers/conversations.py`, `main.py` |
| Frictionless (OKF) | `GET /datapackage` (project catalog), `GET /datasets/{id}/datapackage[?include_data]` (inline rows go through the PII-masked read-only path), `POST /datapackage/validate`, `POST /datasets/{id}/datapackage` (imports **descriptive** metadata only, through the existing audited editor). | `apps/api/app/frictionless.py`, `routers/datapackage.py` |
| 3-panel chat | Rebuilt. See section 4. | `apps/web/app/components/ConversationsView.tsx`, `globals.css`, `types.ts` |
| Tests | 19 new tests: risk, scorer, Jev fallback and reordering, SQL guard, Frictionless mapping, and API round trips. Suite: 117 passed. | `apps/api/tests/test_decision_router.py` |

## 3. Prioritised findings

### Fixed in the follow-up pass
| Finding | Fix |
|---|---|
| C2, partly: viewers could run SQL, agents, tools | `require_any_permission` on `/sql/generate`, `/sql/execute`, `/agents/runs`, `/jobs/{id}/retry`, `/tools/{id}/execute`. New global viewers get a `viewer` project membership instead of `member`. Users created earlier keep `member` until an admin changes it; the global-union permission model itself is unchanged. |
| C3, partly: orphan user turn, SQLite lock across LLM calls | The user message is written only after generation succeeds. Streaming and a background job are still open. |
| C4: blocking calls on the event loop | The local agent fallback runs via `run_in_threadpool` in agents, approvals and job retry. |
| H3, partly: cache replays failures | Failed and fallback results are never stored or served; the cache key carries `SQL_GENERATOR_VERSION`. Rows are still cached and there is still no TTL. |
| H5, partly: re-approval loop, truncated objective | An approved job is not held again after re-planning, and restarts use the full approved objective. Plan-hash binding is still open. |
| No-Docker path could not show results | `sqlite_compat.py` adds `date_trunc`/`now()`, rewrites INTERVAL arithmetic, `::` casts and ILIKE, and drops `core.`/`staging.` schemas. The metadata guard re-runs after rewriting. |
| Offline model returned one canned query | `intent_sql` handles counts, by/per grouping, monthly trends, sum/avg/min/max, top N and status filters. |
| Cryptic "env: secret reference" error | Actionable message pointing to Admin > Connectors. |
| Duplicate React key on Workspace | Recommendations are de-duplicated by relation. |

### Closure pass (2026-09-24): status of every open finding

| Finding | Status | What changed |
|---|---|---|
| C1 app DB reachable from user/model SQL | **Closed** | `STAGING_DATABASE_URL` (SELECT-only role on data schemas, created and granted by the API where allowed, grants refreshed on "permission denied") routes every governed read-only query. Production refuses to start without it unless `ALLOW_SHARED_QUERY_ENGINE=true`. The metadata-table guard remains as a second layer; on the SQLite dev path it is the only layer. |
| C2 membership instead of permission | **Closed** | `roles.py`: the project role is authoritative (global admin excepted). Viewer is blocked from SQL/agents/tools/job retry. Conversation edit/delete use the project role. Migration 0003 promotes engineers' `member` memberships to `maintainer` and demotes auto-enrolled viewers. |
| C3 synchronous ask, lock across LLM calls | **Closed** | The user turn is written after generation. `POST /conversations/{id}/messages/stream` (SSE) runs the turn on its own session in a worker thread, sends progress stages, and discards the answer if the client disconnects. `Cache-Control: no-transform` keeps proxies from buffering. |
| C4 blocking calls in async endpoints | **Closed** | `run_in_threadpool` for the local agent paths. |
| H1 regex SQL guard | **Closed** | `sql_guard.py` parses per dialect with sqlglot (single SELECT or set operation, no INTO/locks/commands, function denylist) and is used by every execution path. SQL Server previews run in a rolled-back transaction. SQLite queries have a progress-handler timeout. |
| H2 prompt injection | **Closed** | Client context loses `system` turns. Catalog and retrieved text are fenced as untrusted. Model SQL may only reference catalogued relations, otherwise repair, then deterministic fallback, plus a governance event. |
| H3 cache | **Closed** | SQL only, never rows (hits re-execute locally). Key includes provider/model and generator version. `SQL_CACHE_TTL_HOURS`. Failures and fallbacks are never cached. |
| H4 silent provider fallback | **Closed** | A pinned or routed provider that is unavailable returns 409 with a clear reason. Per-purpose routing (`model_routes`, `/model-routing`, Admin UI). |
| H5 approval not bound to the plan | **Closed** | Frozen plan plus `plan_hash` in the approval; approval runs exactly that plan after hash checks. Reviewer-added risky steps are skipped. Autonomy levels are enforced. |
| H6 Temporal durability | **Closed** | `AgentRunWorkflow` runs prepare, then one activity per step, then finalize, with idempotency keys, heartbeats, bounded retries, deterministic workflow IDs (duplicates rejected) and one cached client. |
| M1 structure / circular import | **Closed** | `main.py` (199 lines) = app + middleware + routers; `core.py` = shared services; `schemas.py` = Pydantic. Routers import `core`. A test imports every router in isolation. |
| M2 migrations every boot | **Closed** | `migrations.py` records versions in `schema_versions` under a Postgres advisory lock. `python -m app.migrate` plus `infra/kubernetes/migrate-job.yaml`; `RUN_MIGRATIONS_ON_STARTUP=false` in Kubernetes. The backfill no longer claims global audit/model-call rows. Catalog re-indexing runs in the background. |
| M3 hot paths | **Closed** | Indexes (messages by conversation+time, audit time/actor, `lower(email)`, feedback context, query runs, model calls). Grouped history query (no N+1). Paginated messages with `X-Has-More`. |
| M4 mutable "current project" | **Closed** | `X-Project-Id` pins every request to a project the user belongs to (403 otherwise). The web app sends it on every call. |
| M5 auth/secrets | **Closed** | Production refuses a weak `JWT_SECRET`. httpOnly `SameSite=Lax` session cookie plus `X-Requested-With` CSRF check. Password change is enforced in production. Throttled sign-in (Redis, with local fallback). `env:` secret denylist plus optional `SECRET_REFERENCE_ALLOWLIST`. |
| M6 notebook freeze | **Closed** | Static limits on `**` and sequence repetition. Python cells run in a killable child process (`NOTEBOOK_PYTHON_TIMEOUT_SECONDS`). |
| Web review items | **Closed** | URL-synced views (`?view=&c=&m=`), 401 handler, cookie auth, lazy Superset SDK, `noUnusedLocals`, accessible modals and `useConfirm`, focus rings, ≥11 px type, dark mode plus theme toggle, jobs polling, seed/toast/project-switch fixes, streaming chat with stages and Stop, earlier-message paging, feedback comments, model-routing and router-evaluation panels, frozen plans on Approvals. |
| P4 learning loop | **Closed (infrastructure)** | `route_decisions` table, feedback written onto decisions, `POST /router/evaluate` replays labelled cases per backend. |

**Live results on 2026-09-24 (scratch database, real keys):**
- All four seeded providers tested healthy: Gemini 3.6/3.5 Flash; OpenRouter Claude Sonnet 5 and DeepSeek V4.1 Flash.
- Gemini wrote correct SQL for new questions in about 1.6 s, and the SQL executed.
- Claude Sonnet 5 produced agent plans; a risky objective was held with a hashed, frozen plan.
- Router evaluation on 10 labelled questions: LLM backend (Gemini 3.6 Flash) 100% accuracy at about 1.4 s; local scorer 80% at under 1 ms.

**Second closure pass (2026-09-24): the previously remaining limits**

| Limit | Status | Evidence |
|---|---|---|
| Docker Compose path untested | **Closed** | Stack run under Docker. `datapilot_reader` was created by the API, and Postgres itself denies it `users` (`permission denied for table users`). Session cookie and SSE streaming work through the containerised web proxy; the agent run completed on the Temporal worker through `AgentRunWorkflow`. The user's port 3001 conflict was a leftover local dev server, since stopped. |
| `core.py` too large | **Closed** | `core.py` is 269 lines: a facade over 15 `app/services/` modules. Routers are unchanged; every router imports in isolation (test). |
| Custom migration runner | **Closed** | Alembic (`apps/api/alembic/`, revisions 0001–0005) with the advisory lock and adoption of databases from the old runner. The Docker database was adopted from `schema_versions` and upgraded to `0005_learning_indexes`, with the pg_trgm index created. Concurrency tested on PostgreSQL 17. |
| Query-string routing, no TanStack Query | See web status below | App Router segments and TanStack Query (web pass). |
| Jev untested; GEPA not run | **Closed** | Jev runs through the OpenRouter Decisions API (`typesafe/jev-1.13`) and was tested live: correct routes and a risk escalation the rule list missed. A GEPA run with live models raised the score from 0.75 to 0.90 (docs/LEARNING_LOOP.md). |
| Model narratives off | **Closed** | `CONVERSATION_MODEL_SUMMARY_ENABLED=true` in `.env`. Tested live in Docker: the DeepSeek answer was grounded in the returned rows and flagged the small sample. |

**Also added in this pass:** verified-query memory (exact reuse measured at 0.72 s vs 8.2 s, plus few-shot retrieval), a multi-model SQL vote with semantic result agreement (2/3 and 3/3 on live PostgreSQL), and an approval-gated index advisor. Several bugs were found only in live runs and fixed with tests: the SQLite cast rewrite for `COUNT(*) FILTER (…)::numeric`, a blank `TYPESAFE_MODEL` overriding the pinned model, fingerprint-based voting that never agreed across models, and `Cache-Control: no-transform` for SSE.

**Honest trade-offs that remain by design:**
- With every feature on (three-model vote, LLM router, model narrative) a turn takes about 6–13 s. Streaming shows each stage. For speed, remove the `sql_candidate_*` routes, set `DECISION_ROUTER_BACKEND=local`, or turn narratives off.
- The multi-model vote only runs where candidates can be executed safely (local sources).
- GEPA needs a few dozen cases to generalise.

### Third pass (2026-09-24): Jev in agents and tools, analytics picker, DDL suggestions

| Item | Status | Where |
|---|---|---|
| Jev picks **which agent** (up to 3 agent options), not just "an agent" | Done | `decision_router.local_scores` |
| Jev picks **which tool** for each agent step, instead of firing every bound tool | Done; the choice is stored as `tool_choice` evidence | `temporal_activities._select_step_tools`, `jev_client.choose_tools` |
| Router's chosen agent carried into the run (`agent_id`, lead agent owns a step) | Done | `routers/agents.py`, `ConversationsView.tsx` |
| Planner output cut off at 800 tokens (silent fallback plan) | Fixed | `_plan_for_job` |
| Tools skipped silently when parameters couldn't be grounded | Fixed (logged; step text used; a unique bare table name is accepted) | `_parameters_for_tool` |
| Jev calls from `/router/decide` and `/router/evaluate` missing from usage | Fixed; `GET /model-usage` → `by_purpose` | `routers/decisions.py`, `routers/model_providers.py` |
| DDL executed by DataPilot | Changed: suggestion-only, driven by slow queries (`SLOW_QUERY_MS`); runs only with `ALLOW_DDL_EXECUTION=true` plus approval | `index_advisor.py`, `routers/learning.py` |
| Superset: one hidden dashboard per query, reachable only by hotlink | Done: a picker of project dashboard, published queries and datasets by source (project-scoped, PII columns excluded, restricted datasets admin-only) | `routers/analytics.py`, `SupersetView.tsx`, [ANALYTICS_EMBEDDING.md](ANALYTICS_EMBEDDING.md) |
| Live proof of Jev decisions | `scripts/demo_jev_agents.py` → `docs/demo/` | [AGENTS_TOOLS_AND_JEV.md](AGENTS_TOOLS_AND_JEV.md) |

All 16 agent and tool gaps (budget enforcement, built-in tool timeouts, self-approval, MCP token
lifecycle, quotas, egress, data residency, …) were closed on 2026-09-24; see
[AGENTS_TOOLS_AND_JEV.md §5](AGENTS_TOOLS_AND_JEV.md#5-improvement-list-status-2026-09-24-closure).

### Original findings (for reference; see closure table above)

### Critical
- **C1: staging and app DB share one engine and login.** `routers/sql.py:491`, `main.py:1483`,
  `connector_runtime.py:645`, `notebook_runtime.py:100` all use the app `engine`. The new guard is a
  tokenizer, not a parser; it is defence in depth only. **Fix:** a separate `staging_engine` with a
  role that has `SELECT` on `staging.*` only, and refuse local execution on SQLite.
- **C2: permission vs membership.** `/sql/execute`, `/sql/generate`, `/agents/runs`,
  `/jobs/{id}/retry` and `/tools/{id}/execute` only call `require_current_project`, so a viewer can
  run SQL and agents. `project_permissions` (`main.py:811`) unions global and project roles.
  Conversation rename/delete check the *global* `user.role`. **Fix:** a `require(perm)` dependency
  using the project role, plus a test that walks `app.routes`.
- **C3: synchronous ask path.** A user message is flushed at `conversations.py` before up to three
  SQL-generation LLM calls (45 s timeout each), plus embeddings and an optional summary call; the
  commit happens at the end. On SQLite this blocks all writers. On Postgres it holds two pooled
  connections per ask. An LLM failure commits an orphan user message. **Fix:** short transaction →
  background job → SSE stream → short final transaction.
- **C4: `async def` endpoints call blocking code.** `agents.py`, `approvals.py` and `jobs.py` run
  the synchronous local agent on the event loop with a single uvicorn worker.

### High
- SQL guard is a regex blocklist copied three times; `SELECT … INTO`, `WAITFOR`, `SHUTDOWN` pass
  `_safe_read_only_sql`. SQL Server runs with `autocommit=True` and no DB-side read-only
  enforcement. → one `sql_guard` built on `sqlglot`, per dialect.
- Untrusted catalog/glossary text and client-supplied `conversation_context` (which accepts
  `role: "system"`) flow straight into the SQL prompt. → server-only context and delimited data
  blocks.
- SQL cache stores live result rows, ignores provider/model/prompt version, has no TTL, caches
  failures, and rehashes the whole catalog per request.
- Provider selection silently falls back from a pinned project provider (data-residency risk).
- Approval binds to the objective text, not the plan: post-approval runs re-plan from
  `job.title[:200]`. → freeze the plan and approve its hash.
- Temporal: one activity for the whole plan (2 min, 5 retries, no heartbeat), so a retry duplicates
  side effects.

### Medium
- `main.py` is 2.5k lines; every router imports ~290 names from it; importing a router alone raises
  a circular `ImportError`. Migrations are `create_all` plus hand-written ALTERs on every boot, and
  `backfill_project_columns` reassigns NULL-project audit rows to the oldest project on each boot.
- Web: no URL routing (back/refresh/deep links broken); project switch leaves stale views; token in
  `localStorage` with no 401 handling; Superset SDK in the initial bundle; the same ~90-name import
  block copied into ~20 files; modals lack focus trap and Esc; 103 declarations at 9–10 px; no dark
  mode.
- Observed during verification: `WorkspaceView.tsx:185` duplicate React key. The local
  deterministic model returns the same canned SQL for every question, and on the no-Docker SQLite
  path generated Postgres SQL cannot execute. The "no Docker" quick start therefore cannot
  demonstrate results.

## 4. The 3-panel chat — before vs after

| Before | After |
|---|---|
| Right panel always showed the *latest* result (and the uncommitted edit had reduced it to a chart plus a row count) | Inspector bound to the **selected** answer, with prev/next ("Result 3 of 5") and tabs: **Result** (chart, paginated table, masked-column marker, CSV), **SQL** (copy, notebook, publish tool, model/latency/cache facts), **Context** (execution target, catalog grounding scores, semantic metrics, approved joins, validation checks, conversation memory), **Decision** (route, confidence, backend, policy, risk triggers, every candidate with reasons) |
| First question in a new chat could vanish (messages effect raced the POST); switching threads mid-request put replies in the wrong thread | Lazy creation with a skip-load guard, AbortController on fetches, replies only applied to the active thread |
| "+" created empty "New analysis" rows | "+" clears the selection; the record is created on first send |
| Failed send left a ghost message | User turn marked "Not answered" with inline Retry; text restored to the composer |
| No search, no grouping, no preview | Search over title/summary/last message; Today / Yesterday / Previous 7 days / Older; snippet and relative time |
| Enter inserted a newline; no auto-scroll | Enter sends, Shift+Enter adds a newline, ↑ recalls the last question; auto-scroll near the bottom, otherwise a "Latest" pill |
| `window.prompt` rename, unconfirmed delete, shared modal state | One typed dialog: rename, confirm-delete, report, publish-tool (uses the message's own question and source), notebook |
| Feedback fire-and-forget | Pressed state shown, duplicate submits ignored |
| Nothing after an answer | Follow-up chips derived from the result's real columns; suggested tool/agent actions from the router (Run tool only when it needs no parameters and no approval) |
| Page-height panels; composer scrolled off | Fixed-height grid; each panel scrolls independently; collapsible side panels (remembered per browser); stacked layout ≤1080 px |

## 5. Jev, GEPA/DSPy and OKF — the devil's-advocate position

### Jev (TypeSafe "System One" decision model, early access since 2026-09-15)
- **For:** it returns typed choices with calibrated probabilities, so it can't produce an
  off-menu tool name. It is reported to be ~40–200× faster and far cheaper than a generative call
  for exactly this job (route/tool selection, guardrail yes/no).
- **Against:**
  - It's early access and a black box.
  - Published tests show adversarial text can shift its verdicts: an injected "pre-approved" field
    dropped a block probability from 0.76 to 0.48.
  - Option ordering matters.
  - It is weak on numbers and dates.
  - Sending question text to a third party is a data-residency decision for a banking workspace.
- **How it is wired here** (original design, superseded: Jev is now a declared provider
  routed to four decision purposes; see [AGENTS_TOOLS_AND_JEV.md](AGENTS_TOOLS_AND_JEV.md)):
  - Behind `DECISION_ROUTER_BACKEND=jev`, and used only for the *route choice*.
  - **Risk and approval stay deterministic, and Jev can never lower them.**
  - State contains only the user's question and registry descriptions; never tool output, rows or
    retrieved documents.
  - Pin `TYPESAFE_MODEL`; the backend name is logged per decision.
  - Any error or timeout falls back to `local`.
  - The adapter's request shape follows TypeSafe's published concepts and **must be verified
    against your API reference before enabling**.
  - For on-prem, the open-weight "Kev" recreation can sit behind the same URL.
- **Gate for turning it on:** replay `GET /router/decisions` through both backends and compare
  against feedback/evaluation labels. Enable only if it wins on your data.

### GEPA / DSPy
- These are **offline optimisers**. They tune prompts/programs from labelled traces; they don't
  make runtime decisions. Here, the thing to optimise is the router policy
  (`DECISION_POLICY_PATH`: weights, thresholds, decision-model instructions, version).
- **Against doing it now:** feedback volume is tiny, and optimising on a few dozen thumbs will
  overfit. Prerequisites:
  1. Persist decisions in their own table (today they live in `message.structured.route`).
  2. Link feedback and outcomes to decision IDs.
  3. Build an eval set from `EvaluationSet` agent cases.
- **Only then:** GEPA proposes a policy, it is replayed, a human reviews it, and it is deployed via
  file. That keeps the documented "no autonomous self-learning" stance in
  `ARCHITECTURE_DECISIONS.md` §2.

### Open Knowledge Foundation — Frictionless Data Package / Table Schema
- **For:** it is a standard, portable description of datasets. CKAN, open-data portals and
  `frictionless-py` read it, so catalog metadata can round-trip with tools outside DataPilot.
- **Against:** it is not a governance model (no lineage, approvals or sensitivity semantics).
  Importing external descriptors is a metadata-poisoning path into LLM prompts (see H2).
- **How it is wired here:**
  - An adapter at the edge; `DataAsset` remains the internal model.
  - DataPilot extensions use a `datapilot:` prefix.
  - Inline data is bounded and PII-masked.
  - Import accepts only titles, descriptions and tags, through the audited editor, never types or
    constraints.
- **Next:** CSV/Parquet upload with a `datapackage.json` sidecar to pre-fill the ingestion mapping.

## 6. Recommended order of work
1. **P0 security:** separate staging role (C1), per-route permissions (C2), required `JWT_SECRET`,
   sqlglot guard, allowlist for `env:` secret names.
2. **P1 reliability:** async ask pipeline with SSE streaming (unlocks a Stop button and real
   progress in the new chat UI), fix async endpoints, per-step Temporal activities, plan-hash
   approvals.
3. **P2 structure:** extract `schemas/`, `deps/`, `services/` (behaviour-neutral, with aliases),
   add Alembic, add a CI check that each router imports on its own.
4. **P3 web:** App Router URLs (`/analysis/[id]?m=`), TanStack Query, 401 interceptor plus
   httpOnly cookie, lazy Superset, `noUnusedLocals` and lint, design tokens and dark mode, modal
   accessibility.
5. **P4 learning loop:** decisions table, feedback linked to decisions, router eval harness, then
   the Jev comparison and GEPA optimisation.
