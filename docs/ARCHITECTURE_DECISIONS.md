# Architecture decisions: graph engineering, agentic harness, and UI accessibility

**Status:** recommendation, grounded in the current codebase — not a hype answer
**Date:** August 8, 2026 (§6–§8 added in a same-day follow-up revision)
**Answers requested:** do we need Neo4j / a graph database; should we build self-learning agents and an "agentic harness"; how do we make the product understandable to any analyst/developer; general rethink of direction; do we need Kafka/a message queue and OCP worker infrastructure; is DataPilot enterprise-ready and scalable; does accepting a learning suggestion change behavior automatically

## 1. Do we need Neo4j or a graph database?

**Short answer: not yet, and not Neo4j specifically. The current relational edge-list model is the right choice at this stage.** Revisit if and when a concrete traversal feature needs it.

**Update:** the traversal feature this section anticipated has since been built — `GET /lineage/graph` (verified in `IMPLEMENTATION_STATUS_MATRIX.md`) does bounded multi-hop upstream/downstream/both traversal over `LineageEdge`, implemented as an in-memory BFS with a `depth<=20` cap rather than a SQL recursive CTE. Same outcome as step 1 below, different mechanism — still zero new infrastructure, still no graph database. The recommendation in this section holds: this is exactly the kind of feature that should trigger revisiting §1, and it did, and the answer was still "no graph database needed."

### What "graph-shaped" data already exists

| Data | Where | Current representation |
| --- | --- | --- |
| Pipeline lineage (what feeds what) | `LineageEdge` (`source_asset_id` → `target_asset_id`, per pipeline) | Relational edge list in PostgreSQL |
| Approved joins between tables | `SemanticJoinPolicy` (`left_asset_id` ↔ `right_asset_id`, join type/columns) | Relational edge list in PostgreSQL |
| Catalog/document relationships for retrieval | Qdrant vectors + Postgres keyword search | Hybrid index, not a graph |
| Agent → tool → tool-version bindings | `AgentDefinition`/`AgentVersion`/`ToolDefinition` foreign keys | Relational, shallow (1-2 hops, not traversed) |

All four are genuinely graph-shaped (nodes + edges), but every current query against them is **zero or one hop**: "list the edges for this project," "list the joins for this asset," "list this agent's tools." Nothing in the product today asks a multi-hop question like "everything transitively upstream of this table" or "if I change this column, what breaks three pipelines downstream." That's the actual test for whether you need a graph database: not "is the data graph-shaped" (most data is, a little), but "do you need to traverse it at arbitrary depth, fast, interactively."

### Why not Neo4j now

- No current feature requires multi-hop traversal. Adding Neo4j today would be solving a problem the product doesn't have yet.
- It would be a second source of truth to keep in sync with Postgres, which is explicitly the system's **authoritative transactional store** per `DATAPILOT_SYSTEM_SPEC.md` §4.2. Every additional derived store (Qdrant already plays this role) adds a rebuild/consistency story you have to design, test, and operate. Qdrant earns its place because vector search has no relational equivalent; lineage/join traversal does have a relational equivalent (recursive CTEs) that's good enough at today's scale.
- Operationally it's another container in `compose.yaml`, another health check, another thing to secure and back up — real cost for a product that hasn't finished SSO or connector certification yet.

### What to do instead, in order

1. **PostgreSQL recursive CTEs** (`WITH RECURSIVE`) against `LineageEdge` and `SemanticJoinPolicy` for "upstream of," "downstream of," and "shortest join path between two assets" queries. This is standard, well-understood, and needs no new infrastructure — just new queries in `apps/api/app/routers/pipelines.py` and `semantic.py`. This covers the vast majority of what people mean by "lineage graph" and "relationship graph" in a data catalog product.
2. **If** traversal queries become a real bottleneck (large graphs, sub-second interactive exploration UI, centrality/community-detection style analytics) — reach for the **Apache AGE** extension for PostgreSQL first. It adds openCypher graph queries on top of your existing Postgres instance, so you get graph query ergonomics without a second database, a second backup story, or a second credential to govern.
3. **Only if** you outgrow that (very large graphs, need for graph-native algorithms like PageRank/community detection at scale, or a dedicated graph-visualization product surface) does a standalone graph database like Neo4j earn its keep — and at that point it should follow the same pattern as Qdrant: derived, rebuildable from Postgres, never the source of truth, never holding secrets.

**Recommendation:** don't add Neo4j now. If you want the "blast radius" / transitive-lineage feature, say so and it can be built directly on `LineageEdge` with recursive CTEs — same governance model, zero new infrastructure, and it'll tell us empirically whether traversal depth/performance ever justifies step 2 or 3 above.

## 2. Self-learning agents and "agentic harness" engineering

**Short answer: build the harness, don't build unsupervised self-learning.** DataPilot's own documented positioning (`ENTERPRISE_READINESS_AND_AGENT_CAPABILITY_ASSESSMENT.md` §5) is explicit that autonomous self-learning is a governance risk for this product category, and that's correct — an agent that quietly rewrites its own prompts or promotes itself based on its own scoring is exactly the kind of uninspectable behavior this product exists to prevent in the systems it manages. The fix is not "add self-learning," it's "make the human-reviewed learning loop faster and more visible," which is harness engineering, not autonomy.

### What "harness" means here, concretely

An agent harness is the scaffolding around a model call that makes it bounded, observable, and improvable: a planner, a tool-execution loop with budgets, an evaluation suite, a promotion gate, and a feedback channel. DataPilot already has most of these pieces; they're just not fully wired together.

| Harness component | Status before this session | What changed / what's next |
| --- | --- | --- |
| Bounded planner (3–6 steps, deterministic fallback) | ✅ Implemented | No change |
| Tool-execution loop with a hard budget (≤12 calls, low-risk built-ins only) | ✅ Implemented | No change |
| Durable execution + evidence (Temporal, job logs, model provenance) | ✅ Implemented | No change |
| Evaluation suite (replay, golden traces, red-team cases) | ✅ Implemented | No change |
| **Evaluation → version score** | 🔴 Was dead code — `AgentVersion.evaluation_score` existed on the model but nothing ever wrote to it | ✅ **Fixed this session** — `GET /agents/{id}/scorecard` now persists the measured score onto the latest version |
| **Evaluation → promotion signal** | 🔴 Did not exist | ✅ **Fixed this session** — scorecard now returns a `promotion_recommendation` (ready / below_threshold / not_evaluated / current) with a plain-language reason, surfaced as a banner in the agent editor UI with a one-click "Publish recommended version" action |
| Human approval still required to publish | ✅ Preserved | The recommendation never auto-publishes — `POST /agents/{id}/versions/{version}/publish` is still a deliberate human action. This is the load-bearing safety property; don't remove it. |
| Feedback → suggestion queue | ✅ Implemented (`LearningSuggestion`) | ✅ **Upgraded**: repeated "not helpful" signals in the same area now fold into one suggestion with `occurrence_count`/escalating `severity` instead of one row per feedback event, and a full review UI exists (Admin → Governance → Learning Loop). Still requires human review before it changes behavior — correct, keep it that way |
| Per-agent historical benchmark dashboard | 🔴 Not built | Next candidate: a trend view over scorecard history, not just the latest number |
| Prompt/tool ablation testing | 🔴 Not built | Would let you answer "does removing this tool from the allowed list change pass rate," a real harness-maturity feature, but higher effort |
| Reflection/self-critique step in the planner loop | 🔴 Not built | Worth prototyping behind a flag: have the planner re-check its own plan against the grounding context before executing, still within the existing tool-call budget |
| **Tool-parameter construction** | 🟡 Investigated this session — real, working, but narrow | `_parameters_for_tool()` in `temporal_activities.py` only fills a required field named exactly `query`/`objective` (string) or `limit` (integer); any other required field means the tool is silently skipped (`continue`), not attempted with a guess. This is a deliberate safety choice (the code's own docstring: *"uncertain contracts are never guessed"*) and it's the real ceiling on what an autonomous agent run can actually invoke today — a well-planned step calling a well-suited published tool still goes nowhere if the tool needs, say, a date range. The fix isn't a bigger hardcoded field-name table; it's an LLM-driven parameter-fill step gated by the tool's own JSON Schema validation (fill via the model, reject on schema mismatch, never execute on a guess) — same safety property, wider coverage. Not built this session; recorded as the top harness-improvement candidate. |

### Direct answer: does accepting a learning suggestion change anything automatically?

**No.** Verified against the actual code (`apps/api/app/routers/governance.py::review_learning_suggestion`): clicking "Accept" does exactly three things — flips `LearningSuggestion.status` to `"accepted"`, records who reviewed it and their note, and writes an audit event. It does not edit a prompt, retrain anything, change a tool, alter an RBAC policy, or touch any other row in the database. The `proposed_change.action` field on every suggestion says this explicitly in its own text: *"Review evidence and propose a versioned improvement; do not change runtime behavior automatically."*

This is deliberate, not an oversight — see the framing below. What *was* missing, and is fixed as of this revision, was pure friction: a reviewer who accepted a suggestion had no way to jump straight to the screen where they'd actually make the fix. The review modal now shows a "review_target"-aware deep link (e.g., a `sql_grounding` suggestion links to the SQL workspace, `catalog_metadata` links to the dataset catalog) that just navigates — it still requires the human to look at the evidence and make the change themselves.

### The one-sentence framing to use with stakeholders

*"DataPilot agents learn from evaluation, not from themselves — every improvement is measured, scored, and requires a human click to take effect."* That's a selling point for an enterprise audience, not a limitation; keep it as the design principle for anything built on top of this harness.

## 3. Making the product understandable to any analyst, developer, or admin

This was already partially scoped in `ENTERPRISE_READINESS_AND_AGENT_CAPABILITY_ASSESSMENT.md` §9. Restated and prioritized:

1. **Role-based landing.** Today everyone lands on the same Workspace view. An analyst wants Analysis + Datasets; an engineer wants Files + Pipelines + Quality; an admin wants Admin + Registry. A first-run "what are you here to do" choice (already half-built as a tour) should set a default landing tab per role.
2. **Explainability is already strong — don't rebuild it, promote it.** `SQLView` and `ConversationsView` already surface source, catalog grounding, semantic terms, cache-hit status, and a plain-language validation checklist per result. This is the "why this result" feature the enterprise-readiness doc asked for — it exists. The gap is discoverability, not functionality: it's a side panel that's easy to miss on first use. A short first-run callout pointing at it would close that gap cheaply.
3. **Source vs. staging vs. tool distinction.** New users conflate "connector" (a registered source), "staged data" (physically loaded into Postgres), and "query tool" (a published, external-facing capability). A one-line clarifying label at the top of Files, SQL, and the Tool Marketplace would remove a recurring point of confusion for people new to the product.
4. **The Datasets metadata-edit affordance added this session is a template for this pattern** — every screen that shows system-generated content should have an obvious, permission-gated "review / correct this" action, not just a read-only view.

## 4. Overall rethink — what actually changes and what doesn't

- **Keep the architecture.** FastAPI + Postgres-as-source-of-truth + Temporal + Qdrant-as-derived-index is the right shape for a governed AI data platform. Nothing above argues for replacing any of it.
- **Don't add infrastructure speculatively.** Neo4j, a vector-store swap, a new message queue like Kafka (see §6) — none of these are justified by a concrete, present need. Add them when a feature demands it, not because they're associated with "AI platform" architecture in the abstract. The corollary, also applied this revision: don't leave infrastructure *unused* either — Redis was already provisioned and doing nothing until this revision wired it into rate limiting.
- **The real leverage right now is closing loops that already have both endpoints built** — this session's two fixes (metadata edit, evaluation-gated promotion) are both examples: the read side and the write side existed separately; the fix was connecting them, not building new subsystems.
- **Documentation is being restructured into per-domain files** (see `docs/specs/`) so a new analyst, developer, or admin can read the one page relevant to what they're doing instead of one very long document. This is a discoverability fix, matching the same philosophy as item 2 above.

## 5. Before testing with real datasets

Since real-dataset testing is coming next, two things are worth doing first if you hit friction:

- If lineage/relationship traversal turns out to matter once real pipelines exist, come back to §1 — the recursive-CTE approach can be built in an afternoon once we know exactly which traversal question you need answered.
- If agent evaluation surfaces low pass rates against real data, that's the harness in §2 doing its job — treat it as signal to improve grounding/prompts, not as a reason to loosen the human-approval gate.

## 6. Do we need Kafka or a message queue?

**Short answer: no, and this was checked against the actual code, not assumed.** DataPilot already has two pieces of async/queue-shaped infrastructure; the fix needed wasn't "add Kafka," it was "use what's already provisioned."

### What already exists and what it's for

| Need | What handles it today | Kafka would add |
| --- | --- | --- |
| Durable, retryable background work (metadata scans, scheduled ingestion, agent plan execution) | **Temporal** (`apps/api/app/worker.py`, `temporal_workflows.py`) — has retries, history, and visibility built in | Nothing Temporal doesn't already do better for this shape of work; Kafka is a log, not a workflow engine, you'd still need something like Temporal *or* Celery on top of it |
| Client abuse protection / request throttling | **Redis**, as of this revision (`apps/api/app/rate_limit.py`) — was provisioned in `compose.yaml`/`infra/kubernetes/configmap.yaml` (`REDIS_URL`) but, verified by grep before this change, referenced by zero application code. Dead infrastructure sitting next to an unaddressed gap. | Nothing — this isn't a fan-out/streaming problem |
| Fan-out to many independent consumers of the same event stream | Nothing today, because nothing in the product needs it yet | This is the one legitimate Kafka use case — and DataPilot doesn't have it |

### When Kafka would actually earn its place

Reach for it only if a concrete requirement shows up that these tools genuinely can't cover: multiple independent downstream systems (not just DataPilot's own worker) need to consume the same event stream (e.g., "every schema-drift event should also land in a customer's SIEM, a data-quality dashboard, and a Slack bot, independently, with replay"), or event throughput needs durable ordered log semantics beyond what a workflow engine + a Postgres outbox table can provide. Neither condition holds today. Adding Kafka now would mean: a new stateful cluster to run and back up, a new client library in `apps/api/requirements.txt`, and a second "what happens if this queue backs up" story — for zero features the product currently needs. This is the same reasoning as §1's Neo4j answer: don't add infrastructure speculatively.

**Recommendation:** keep Temporal as the durable execution engine, keep Redis for cross-cutting cross-request state (rate limiting today; a good future candidate is caching or a JWT revocation/blocklist if session invalidation becomes a requirement), and revisit Kafka only if a genuine multi-consumer event-fan-out requirement appears.

## 7. Is DataPilot an enterprise application, or still local-only? Is it scalable?

Answered directly, without hedging into marketing language:

**Enterprise-shaped, not enterprise-certified.** The architecture (stateless FastAPI pods behind a Service, project-scoped multi-tenancy, RBAC roles, Temporal for durable execution, a Kubernetes baseline with HPAs) is the right shape for an enterprise deployment and is not a "local-only" design — nothing in the request path assumes a single machine or a single user. What's not yet true: PingFederate/SSO is a config contract without a working OIDC handshake (🔴), there's been no security review or penetration test (🔴), production hardening like secrets-manager integration and backup/restore drills hasn't been exercised (🔴), and the new `/auth/me` granular permissions are informational only — not yet enforced by any endpoint (🟡, see `IMPLEMENTATION_STATUS_MATRIX.md` §2). Calling it "enterprise-ready" today would be overselling it; calling it "just a local tool" undersells the actual architecture. The honest framing for a presentation: **enterprise-shaped platform, mid-way through enterprise certification** — the remaining work is closing specific, named, tracked gaps, not a rearchitecture.

**Scalable by design, not yet proven at scale.** As of this revision:

- API and web are stateless and scale horizontally via Kubernetes `HorizontalPodAutoscaler`s (api: 2–8 replicas, web: 2–6, worker: 2–10, all added/verified this revision), not via multiple processes per pod — this is the standard container-native scaling pattern and it's correctly applied here.
- The Temporal worker pool scales independently of the API, so a burst of scheduled ingestions or agent runs doesn't starve interactive HTTP traffic, and vice versa.
- The one real, unresolved capacity question is Postgres connection exhaustion at max replica counts — documented with the actual math in `infra/kubernetes/README.md` ("Connection pool sizing") and made tunable via `DB_POOL_SIZE`/`DB_POOL_MAX_OVERFLOW` this revision, but not yet load-tested.
- Autoscaling triggers on CPU utilization only — fine for the API, a real gap for the worker if it turns out to be I/O-bound under real workloads rather than CPU-bound (a custom Temporal-queue-depth metric would close that; not built).
- No load test has been run against this deployment. "Scalable architecture" and "proven at scale" are different claims — this document is only making the first one.

## 8. Rate limiting on the external gateway

Added this revision, closing a real gap: `/external/v1/*` and `/mcp` are designed for arbitrary external AI clients to call over the network, and had zero request throttling. `apps/api/app/rate_limit.py` adds a Redis-backed fixed-window limiter (`EXTERNAL_QUERY_TOOL_RATE_LIMIT_PER_MINUTE`, default 60/client/minute), wired into the single choke-point function both the REST invoke endpoint and the MCP `tools/call` handler share (`_invoke_external_query_tool` in `main.py`), so one change covers both surfaces. It fails open if Redis is unreachable — a rate limiter should never become a new outage vector for an already-governed, read-only gateway — which also means it's not yet a hard security control on its own; pair it with the RBAC-enforcement fix in §2 of `IMPLEMENTATION_STATUS_MATRIX.md` before treating this as sufficient for a hostile-multi-tenant threat model.

## 9. What happens to the source database when an external MCP/agent calls a query tool a lot?

Two separate concerns, both real, both now addressed:

**Request rate** — already covered by §8: a Redis-backed per-client limiter caps how often any one external accessor can call the gateway at all (default 60/min), independent of what's behind the tool.

**Concurrent physical connections against the source** — this was the actual open gap. Direct-driver connectors (`pymssql`/`psycopg`/`oracledb`/`teradatasql`) open a brand-new physical connection per query and close it afterward; there is no connection pool, by design, because these are occasional governed reads, not an OLTP workload. Without a ceiling, enough simultaneous external calls against the same connector could open an unbounded number of simultaneous connections against the source database — the kind of thing that trips a source DBA's own connection-limit alarms before DataPilot ever notices a problem. Fixed this revision with `apps/api/app/connection_guard.py`: a `threading.BoundedSemaphore` per `connector_id` (the existing sync-threadpool concurrency model — FastAPI's sync `def` routes run in Starlette's threadpool, so this is the correct primitive, not `asyncio`), capped by `CONNECTOR_MAX_CONCURRENT_CONNECTIONS` (default 8, tunable per deployment). A caller that would exceed the budget waits up to 5 seconds, then gets a clear HTTP 503 asking it to retry, instead of the source database silently absorbing an unbounded number of new connections. This is a DataPilot-side safety ceiling, not a replacement for the source database's own connection limits or a connection pooler (e.g., pgbouncer) in front of it — pair both if the source is connection-constrained in production.

## 10. Durability for long-running source-to-staging extraction

Every other ingestion path in the product — recurring `/schedules/*` runs, metadata scans — already executes through Temporal for retry-on-crash, execution history, and visibility into an in-flight run. `POST /extractions/{id}/run` (the one-off "pull this source into staging now" endpoint) was the sole exception: it ran synchronously in the HTTP request thread, so a worker crash or pod restart mid-extraction lost the run with no retry and no record of how far it got. Fixed this revision by extracting the handler's core logic into `extraction_runtime.run_external_extraction_now()` and adding a matching `ExternalExtractionWorkflow`/`execute_external_extraction` Temporal activity pair, following the exact pattern `ScheduledIngestionWorkflow` already established. The endpoint now dispatches to Temporal first and falls back to the synchronous path only when `TEMPORAL_ADDRESS` isn't configured (mirrors `POST /schedules/{id}/run`) — so a long extraction now gets the same durability guarantee as every other ingestion path, not a special case that could silently die with the request. The response code changed from `201` to `202` to reflect that the run may now be asynchronous.
