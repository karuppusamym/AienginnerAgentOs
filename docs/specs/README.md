# DataPilot domain specs

Per-domain breakdown of the system, generated from `docs/DATAPILOT_SYSTEM_SPEC.md`, `docs/IMPLEMENTATION_STATUS_MATRIX.md`, and the current `apps/api/app/routers/` structure so each domain can be read independently. Endpoints are reconciled directly against the code (`apps/api/app/routers/<domain>.py`), not hand-maintained separately from it, so this list can't silently drift the way a single giant spec document tends to.

For overall scope/architecture/deployment, start with [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md). For the completed/partial/not-completed checklist, see [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md). For the graph-database and agentic-harness architecture questions, see [`../ARCHITECTURE_DECISIONS.md`](../ARCHITECTURE_DECISIONS.md).

| Domain | Router file | Purpose |
| --- | --- | --- |
| [System health & workspace overview](./system.md) | `apps/api/app/routers/system.py` | Liveness/readiness probes, observability status, the workspace overview dashboard, and the security posture dashboard. |
| [Authentication & SSO configuration](./auth.md) | `apps/api/app/routers/auth.py` | Local email/password login, session identity, password changes, and the PingFederate/OIDC configuration contract. |
| [User administration](./admin.md) | `apps/api/app/routers/admin.py` | Admin-only user creation, role assignment, and activation/deactivation. |
| [Projects & membership](./projects.md) | `apps/api/app/routers/projects.py` | Project creation/selection, membership management, and per-project default model provider. |
| [Model provider registry](./model_providers.md) | `apps/api/app/routers/model_providers.py` | Register, test, and select model providers (local deterministic, OpenAI-compatible, Gemini, Claude, company providers); view model-call usage/cost. |
| [Connectors, metadata scan & schema drift](./connectors.md) | `apps/api/app/routers/connectors.py` | Register data sources (PostgreSQL, SQL Server, Oracle, Teradata, BigQuery, local files), test connectivity, run read-only metadata scans, and review/acknowledge schema drift. |
| [Dataset catalog, search & recommendations](./workspace.md) | `apps/api/app/routers/workspace.py` | Browse the project's data catalog, hybrid keyword+vector search, suggested next questions, and manual metadata review/editing. |
| [File ingestion, staging, external extraction & schedules](./files.md) | `apps/api/app/routers/files.py` | Upload CSV/JSON/Excel/Parquet, profile and map to a target schema, stage into PostgreSQL (versioned/replace/append/key-merge), configure bounded external-DB extraction, and manage recurring ingestion schedules with watermarks. |
| [Guarded SQL generation & execution](./sql.md) | `apps/api/app/routers/sql.py` | Catalog-grounded, dialect-aware natural-language-to-SQL generation with mandatory read-only validation, and bounded PostgreSQL preview execution. |
| [Persistent analysis conversations](./conversations.md) | `apps/api/app/routers/conversations.py` | Multi-turn grounded analysis with conversation memory/summarization, saved reports, and the same SQL safety guarantees as the SQL workspace. |
| [Pipeline generation, deployment & lineage](./pipelines.md) | `apps/api/app/routers/pipelines.py` | Generate a local pipeline/view package from a staged dataset, produce basic dbt/Dataform package emission, deploy a PostgreSQL view after approval, and record/list lineage edges. |
| [Data quality rules & runs](./quality.md) | `apps/api/app/routers/quality.py` | Create/suggest quality rules, run them against staged data, inspect pass rates and failure samples, and remediate quarantined rows. |
| [Jobs, incidents & operations](./jobs.md) | `apps/api/app/routers/jobs.py` | Track long-running Temporal-backed work (agent plans, scans, schedules), cancel/retry/diagnose jobs, and manage incidents. |
| [Approvals](./approvals.md) | `apps/api/app/routers/approvals.py` | The human decision gate for risky actions (deployments, writes, recurring schedules, high-risk tool execution, destructive remediation). |
| [Agent registry & bounded orchestration](./agents.md) | `apps/api/app/routers/agents.py` | Version agent instructions, bind models and tools, publish reviewed versions, start bounded agent runs (Temporal-backed, ≤12 tool calls), and view the evaluation-based promotion scorecard. |
| [Internal tool registry](./tools.md) | `apps/api/app/routers/tools.py` | Register, version, and publish built-in or allowlisted-HTTP tools that agents can call; execute and audit tool runs. |
| [External query-tool gateway](./query_tools.md) | `apps/api/app/routers/query_tools.py` | A separate, external-facing registry: fixed read-only SQL/MCP query templates published as REST/OpenAPI/MCP tools for external AI clients (VS Code, Google ADK, other MCP clients), with per-client credentials and grants. |
| [Semantic layer](./semantic.md) | `apps/api/app/routers/semantic.py` | Business metric definitions and approved join policies that ground SQL generation instead of letting the model guess table relationships. |
| [Artifacts, versions, comments & review](./artifacts.md) | `apps/api/app/routers/artifacts.py` | Durable, versioned storage for generated SQL, pipeline packages, and other governed outputs, with diffs, comments, and review decisions. |
| [Evaluation sets & replay](./evaluations.md) | `apps/api/app/routers/evaluations.py` | Create evaluation cases, replay them against agents/SQL generation, run red-team suites, and set golden-trace baselines. |
| [Governed notebooks](./notebooks.md) | `apps/api/app/routers/notebooks.py` | Markdown, read-only SQL, and restricted-Python notebook cells, each execution preserved as a versioned artifact. |
| [Audit, feedback & learning suggestions](./governance.md) | `apps/api/app/routers/governance.py` | The durable audit event log, user feedback capture, and the human-review queue that feedback feeds into. |
| [Prompt versioning](./prompts.md) | `apps/api/app/routers/prompts.py` | Save and roll back prompt artifacts used across the product. |
| [Retention policies](./retention_policies.md) | `apps/api/app/routers/retention_policies.py` | Configure and run data/record retention cleanup under approval. |
| [Embedded Superset analytics](./analytics.md) | `apps/api/app/routers/analytics.py` | Optional embedded Apache Superset dashboards with DataPilot-brokered guest access, and an admin-only editor handoff. |
