# Enterprise readiness and agent capability assessment

**Status:** implementation-grounded assessment  
**Reviewed against:** backend, frontend, tests, and existing docs  
**Date:** August 2, 2026

## 1. Executive answer

DataPilot Agent OS is an **enterprise-oriented data and agent governance application**, not just a demo screen. It has real product foundations: project scoping, user roles, connector registry, local PostgreSQL staging, SQL guardrails, semantic metadata, pipeline generation, lineage, artifact versioning, approvals, jobs, audit events, model provider registry, bounded agents, tool registries, external client grants, and MCP exposure.

However, it should be described carefully:

| Question | Answer |
| --- | --- |
| Is it an enterprise application? | Yes, architecturally and functionally it is enterprise-oriented. It implements many enterprise control-plane patterns. |
| Is it production-certified enterprise software today? | Not yet. It still needs SSO completion, production hardening, live external connector certification, RBAC depth, operational SLOs, security review, and user adoption polish. |
| Can it be used now? | Yes for local governed workflows, demonstrations, pilots, and controlled internal evaluation. |
| Can it safely replace a production data platform? | No. It should sit as a governed AI/data workflow layer, not replace a warehouse, catalog, orchestrator, or BI estate. |

The right positioning is:

> DataPilot is a governed AI data-engineering control plane for safe analysis, staging, metadata-grounded SQL, tool publication, pipeline draft generation, approvals, and evidence. It is ready for internal pilot use, but not yet production-enterprise certified.

## 2. What makes it enterprise-oriented

The application has enterprise-grade concepts in the actual implementation:

| Area | Implemented evidence |
| --- | --- |
| Identity and roles | Local users, admin/engineer/analyst/viewer roles, project membership, PingFederate configuration object. |
| Project isolation | Most key resources are project-scoped: assets, files, tools, conversations, jobs, evaluations, semantic objects, query tools, grants. |
| Data access controls | Connectors store secret references, not plaintext credentials in UI. Connectors are read-only by default. |
| SQL safety | SQL generation and execution enforce one read-only `SELECT`/`WITH`, reject DDL/DML, enforce limits, and execute local preview in read-only transactions. |
| Durable evidence | Jobs, logs, outputs, artifacts, versions, approvals, comments, evaluations, lineage, model calls, feedback, and audit events are persisted. |
| Governed agents | Agents are versioned definitions with published versions, model binding, declared tools, max tool calls, low-risk execution boundary, and approval fallback. |
| Tool governance | Internal tools and external query tools are typed, versioned, published, audited, and bounded by JSON Schema, timeout, row limit, allowlist, and grants. |
| External access | REST/OpenAPI-style query tools and MCP `tools/list`/`tools/call` allow external AI clients to discover and invoke only granted tools. |
| Observability | Governance events, model calls, tool executions, connector queries, approvals, and evaluation scores are emitted or persisted. |
| Data engineering workflow | File profiling, mapping, staging, quality rules, pipeline package generation, lineage, scheduled ingestion, and deployment approvals exist. |

These are the correct primitives for enterprise adoption because they make AI behavior inspectable and governable.

## 3. Current enterprise gaps

The biggest remaining gaps are not about adding more AI. They are about certification, clarity, production operations, and lifecycle management.

| Gap | Why it matters | Recommended priority |
| --- | --- | --- |
| Live external connector certification | Drivers exist, but real SQL Server/Oracle/Teradata/BigQuery endpoints need credential, timeout, permission, recovery, and schema-drift validation. | P0 before enterprise rollout |
| SSO end-to-end | PingFederate config exists, but complete browser login/callback/group mapping/logout is not finished. | P0 |
| Production security review | Need threat model, penetration testing, dependency scanning, secret rotation, backup/restore, audit export, and incident runbooks. | P0 |
| Fine-grained RBAC | Current roles are useful but coarse. Enterprises need per-project and per-action permissions. | P1 |
| External DB extraction to staging | A bounded direct-connector extraction contract can stage a scanned source asset with load modes, watermarks, schema-drift checks, catalog records, and lineage. Scheduling, retries, chunk orchestration, and connector certification remain. | P1 |
| Registry usability | Query-tool creation has starter templates, relation-aware draft generation from catalog assets, and usage/health metrics. A full multi-step UI wizard and certification lifecycle are still needed. | P1 |
| Agent evaluation harness | Evaluation sets now support bounded agent replay, golden-trace baselines, approval-boundary simulation, a built-in red-team suite, and per-agent scorecards. Prompt/tool ablation and broader policy coverage remain. | P1 |
| Self-learning loop | Negative feedback creates a human-review suggestion queue. It does not automatically update prompts, semantic metrics, tool ranking, or agent behavior. | P1/P2 |
| Data catalog depth | DataAsset records are useful, but enterprise catalogs need ownership, sensitivity, classifications, freshness, SLAs, glossary terms, and stewardship workflows. | P1/P2 |
| UX onboarding | The UI has a tour and many screens, but the source/staging/tool distinction needs inline guidance, templates, and health checks. | P1 |

## 4. How persisted memory is used

There are three different memory mechanisms. They should not be confused.

### 4.1 Conversation memory

Conversation messages are persisted in `Conversation` and `ConversationMessage`.

When a user asks a follow-up question inside a conversation:

1. DataPilot loads prior messages for that conversation.
2. It builds bounded context from recent user/assistant messages.
3. If the conversation is long, it stores a deterministic summary.
4. The SQL generation request receives the recent context and summary.
5. The response records memory metadata such as `persisted`, `prior_messages_used`, and summary.

This means the chatbot can understand follow-ups like:

```text
First: Show monthly account growth.
Follow-up: Now narrow that to active accounts.
```

The second request can use earlier context in the same topic.

### 4.2 SQL query cache

SQL generation results are cached using:

- project id
- connector id
- dialect
- normalized question
- conversation context signature
- grounding signature

If the same question/source/context appears again, DataPilot can reuse the saved governed query instead of calling the model again.

This is not self-learning. It is deterministic reuse of a validated result.

### 4.3 Catalog and semantic grounding

The model receives grounding from:

- catalog asset search
- vector search
- semantic metrics
- approved join policies
- selected connector/source
- conversation context

This improves answer quality because the model is not asked to guess table names or metric definitions from memory.

## 5. Is self-learning implemented?

No, not in the strict sense.

Implemented:

- user feedback is stored
- evaluation sets can be created and replayed
- evaluation scores are persisted
- SQL cache reuses prior generated outputs
- model calls and failures are logged
- semantic metrics and joins can be manually improved
- prompts and artifacts can be versioned

Not implemented:

- no automatic retraining
- no automatic prompt rewriting based on feedback
- no automatic semantic metric creation from repeated questions
- no tool-ranking optimization based on success rate
- no agent policy adaptation from failed jobs
- no reinforcement-learning loop
- no automatic promotion of a better agent version after evaluation

Recommended product language:

> DataPilot has persisted memory, feedback, evaluation replay, and reusable governed outputs. It does not yet implement autonomous self-learning. Learning should remain human-reviewed before it changes production behavior.

That is the right enterprise posture. Automatic self-learning without review would create governance risk.

## 6. Is agent harnessing implemented?

Partially, yes.

Implemented harness capabilities:

| Harness capability | Current behavior |
| --- | --- |
| Agent definitions | Agents have name, purpose, autonomy level, tool list, and policy. |
| Agent versions | Instructions, model binding, tool names, input schema, config, status, and evaluation score are versioned. |
| Published versions | The runtime uses published versions for execution. |
| Temporal workflow | `datapilot-agent-plan` can run through Temporal or local fallback. |
| Bounded planner | Planner creates 3-6 steps or uses deterministic fallback. |
| Tool budget | Agent loop is capped at 12 tool calls. |
| Tool restrictions | Only enabled, published, low-risk built-in tools run autonomously. |
| Evidence | Plans, grounding, tool results, logs, and outputs are stored on Job. |
| Approval boundary | Risky objectives such as deploy, write, schedule, execute, or publish wait for approval. |

Missing advanced harness capabilities:

- no automatic agent-version score update from a full regression suite
- no historical per-agent benchmark dashboard
- no prompt/tool ablation testing

Conclusion:

> DataPilot has a bounded governed agent runner, not a complete enterprise agent evaluation harness yet.

## 7. How this application is better than a normal chatbot

Normal chatbot pattern:

```text
User asks question -> model guesses SQL/tool call -> maybe executes with broad access -> weak audit
```

DataPilot pattern:

```text
User asks question
-> project and role are checked
-> source and catalog context are retrieved
-> semantic metrics and approved joins are included
-> model generates one read-only SQL statement
-> local guardrails validate it
-> local preview only runs when safe and supported
-> outputs, memory, cache, provenance, and audit are persisted
```

For external AI clients:

```text
Client discovers only granted tools
-> tool has fixed SQL/template/upstream MCP tool
-> caller sends typed values only
-> DataPilot validates parameters and limits
-> execution is audited
```

This is better because it separates:

- who can ask
- what source is selected
- what metadata grounds the answer
- what SQL is generated
- what can actually execute
- what requires approval
- what evidence is retained

That separation is the enterprise value.

## 8. How to make the data tool registry usable

The current query-tool registry is technically strong, but it is still engineer-heavy. To make business and platform teams adopt it, add these features:

### 8.1 Registry marketplace view

Add a browse/search page for published tools with:

- business purpose
- data source
- line of business
- owner
- freshness/SLA
- sensitivity classification
- sample input
- sample output
- row limit
- approval requirement
- last tested status
- usage count (implemented for external invocations)
- last invocation

### 8.2 Guided tool creation

Replace raw-first forms with a wizard:

```text
Choose connector
Choose table/relation
Choose use case
Choose parameters
Preview generated SQL template
Validate allowed relations
Test with sample values
Publish for review
Grant client
Copy MCP/REST usage example
```

DataPilot now includes lookup and filtered-count starter templates. Keep the advanced SQL/JSON editor for engineers, but do not make it the only path.

### 8.3 Tool certification workflow

Add statuses beyond draft/published:

- draft
- tested
- security_review
- data_owner_approved
- published
- deprecated
- retired

### 8.4 Usage analytics

For each tool, show:

- invocations by client (implemented through registry analytics)
- success/failure rate (implemented through registry analytics)
- median latency (implemented through registry analytics)
- rows returned (implemented through registry analytics)
- top parameter keys, not parameter values (implemented through registry analytics)
- recent errors (implemented through registry analytics)
- blocked attempts
- stale tools with zero usage

### 8.5 Natural-language discovery

Add a registry search assistant:

```text
"I need a customer account lookup for retail support."
```

The assistant should return matching tools, required inputs, owner, and invocation examples. It should not execute unless the user has permission.

## 9. How to make the application friendlier

The UI already has a navigation structure, onboarding tour, global search, and clear sections. The next improvements should reduce cognitive load.

Recommended improvements:

| Area | Improvement |
| --- | --- |
| First-run onboarding | Add role-based start paths: Analyst, Data Engineer, Admin, External AI Developer. |
| Source clarity | Show a persistent "where will this run?" banner in Analysis and SQL. |
| Staging clarity | In Files, clearly label "profile only" versus "physically staged in PostgreSQL". |
| Query-tool wizard | Guide non-experts through tool creation instead of requiring raw SQL/JSON Schema first. |
| Templates | Add templates for account lookup, count by date, status filter, recent records, and dimension lookup. |
| Explainability | Add a "why this result" drawer showing source, catalog hits, semantic terms, cache, model, and safety checks. |
| Empty states | Make each empty page show the next action, not just that nothing exists. |
| Admin readiness | Add a checklist for SSO, model provider, connector test, scan, first staged file, first published tool, first grant. |
| Error recovery | Translate connector/query-tool errors into next steps: missing secret, bad schema, unsupported MCP, relation mismatch. |
| Personas | Hide or simplify advanced controls for analysts; keep full controls for engineers/admins. |

## 10. Recommended improvement roadmap

### P0: Enterprise pilot hardening

- Complete PingFederate/OIDC login, callback, logout, and group-role mapping.
- Run real connector certification for PostgreSQL, SQL Server, Oracle, Teradata, and BigQuery.
- Add production secret-manager integration and rotation guidance.
- Add backup/restore and audit export.
- Add security threat model and release checklist.
- Add deployment health checks and operator runbook.

### P1: Usability and adoption

- Add source/staging/tool explanation inside UI.
- Add query-tool wizard and templates.
- Add registry marketplace view.
- Add tool usage analytics.
- Add better connector setup diagnostics.
- Add role-based home pages.

### P1: Agent and evaluation maturity

- Add a historical per-agent benchmark dashboard and controlled agent-version promotion rules.
- Tie agent version publishing to evaluation results.

### P2: Learning loop with human review

- Turn user feedback into review queue items. (Implemented for not-helpful feedback.)
- Suggest semantic metric or synonym updates from repeated questions.
- Suggest query-tool improvements from failed invocations.
- Suggest prompt updates from evaluation failures.
- Require human approval before any suggestion changes runtime behavior.

### P2: External data extraction

- Add scheduled chunking and retries for external extraction contracts.
- Add per-connector extraction certification and operational recovery tests.

## 11. Final verdict

DataPilot is a strong enterprise-style foundation because it treats AI work as governed, versioned, auditable, and project-scoped. It is materially better than a direct chatbot-to-database design.

The main message should be:

> Use DataPilot now for controlled local pilots, governed analysis, staged file workflows, pipeline drafts, semantic grounding, approvals, and external query-tool access. Improve SSO, connector certification, production hardening, registry UX, and agent evaluation before calling it production-enterprise ready.
