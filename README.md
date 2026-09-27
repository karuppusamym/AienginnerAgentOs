# DataPilot Agent OS

DataPilot is a local-first, governed AI data engineering workspace. The current
build provides an executable product workflow, not only UI mockups: local users,
configurable model providers, connector definitions, metadata browsing, physical
file staging, guarded SQL execution, hybrid search, versioned artifacts, durable
multi-agent runs, approvals, job traces, quality controls, a semantic layer, and
optional Apache Superset. PingFederate remains disabled by default; local user
and role management is the active authentication mode.

## Verified local workflow

The Docker Compose stack currently supports these end-to-end paths:

1. Sign in with the seeded administrator or create users from Admin.
2. Upload CSV, JSON, Excel, or Parquet data, review and edit its source-to-target schema mapping, and load PostgreSQL tables using versioned, replace, append, or key-based merge behavior.
3. Find catalog and ingested-file context through combined PostgreSQL keyword search and Qdrant vector search.
4. Generate dialect-aware SQL, run guarded read-only PostgreSQL previews, and reject write or DDL statements.
5. Save generated SQL as a durable artifact and add later versions without overwriting history.
6. Start bounded multi-agent jobs through a real Temporal worker. Risky objectives wait for approval and resume only after approval.
7. Configure OpenAI-compatible, Gemini, Claude, and company model providers. Provider tests make a live call when an `env:` secret is available, a tested provider can be selected as the default SQL-generation model, and the local deterministic provider remains usable offline.
8. Browse a bootstrapped Apache Superset dashboard directly inside DataPilot when the analytics profile is enabled. DataPilot brokers short-lived, dashboard-scoped guest tokens, so normal portal users do not log in to Superset separately.
9. Create or suggest executable quality rules, inspect pass rates and failure samples, and query rejected rows from physical tables under `quarantine`.
10. Approve recurring append or merge ingestion schedules, execute them through Temporal, and advance a persisted source watermark so later runs only process newer rows.
11. Create governed markdown, read-only SQL, and restricted Python notebooks and preserve every execution as a versioned artifact and job trace.
12. Review artifact diffs, add version-specific comments, approve or request changes, and replay model evaluation sets with persisted scores.
13. Change local passwords and let administrators assign roles or activate/deactivate accounts without enabling PingFederate.
14. Create and switch projects, assign project memberships, select a tested model per project, and manage semantic metrics from executable UI controls.
15. Use Gemini 3.6 Flash for validated SQL generation and bounded Temporal agent planning, with model-output repair and deterministic policy fallback.
16. Create and version agent instructions, bind models and tools, and publish reviewed agent versions.
17. Register parameterized HTTP tools, publish their JSON Schema contracts, and execute them through approval and audit controls.
18. Generate a real local pipeline from a staged dataset, approve its PostgreSQL view deployment, and inspect persisted lineage.
19. Diagnose failed jobs into incidents, retry them through Temporal, or cancel active workflow executions.
20. Connect governed query tools through native database drivers or an upstream HTTP MCP server, register searchable purpose/source/LOB/owner/tag metadata, and expose granted tools to VS Code or a Google ADK agent.

## Start locally

Prerequisites:

- Docker Desktop with Compose
- Ports `3001`, `8000`, `5433`, `6333`, `6380`, `7233`, and `8233` available
- Port `8088` available when the Superset profile is enabled

Copy `.env.example` to `.env` and change the local secrets before sharing the
environment. Then start the core stack:

```powershell
docker compose up --build
```

Open:

- DataPilot: `http://localhost:3001`
- API documentation: `http://localhost:8000/docs`
- API liveness: `http://localhost:8000/health/live`
- API readiness (includes metadata database connectivity): `http://localhost:8000/health/ready`
- Temporal UI: `http://localhost:8233`
- Qdrant: `http://localhost:6333/dashboard`
- Superset with analytics profile: `http://localhost:8088`

The seeded local administrator is:

- Email: `admin@datapilot.local`
- Password: `ChangeMe123!`

These defaults are for local bootstrap only.

To include Apache Superset:

```powershell
docker compose --profile analytics up --build
```

Synthetic catalog fixtures are disabled by default. `ENABLE_DEMO_DATA=true` is reserved for automated tests; normal demos should ingest a CSV/JSON/Excel/Parquet file and use that staged relation throughout SQL, quality, pipeline, notebook, and analytics workflows.

The DataPilot **Superset** navigation item embeds the governed local dashboard
without a second login. The portal's **Open editor** action performs a short-lived
admin-only handoff into the standalone Superset editor without asking for
credentials again. Opening `http://localhost:8088` directly still shows
Superset's native login page because that path has no DataPilot session context.

The analytics profile also runs an idempotent bootstrap service that creates the
`core.accounts` dataset, account count and distribution charts, a recent-account
table, the dashboard layout, and the allowed DataPilot embed domains.

Generated SQL is not merely copied into the editor: save a local PostgreSQL SQL
artifact, or save a notebook containing a SQL cell, then choose **Publish to
Superset**. DataPilot validates the immutable saved version locally, creates an
approval request, and only after approval registers that exact query as a
Superset virtual dataset and updates the embedded dashboard. External-connector
SQL remains executable only through its governed connector/query-tool path; it
is not silently published through the local Superset connection.

## Run without Docker

API:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r apps\api\requirements.txt
uvicorn apps.api.app.main:app --reload --port 8000
```

Web:

```powershell
cd apps\web
npm install
$env:INTERNAL_API_URL = "http://localhost:8000"
npm run dev
```

The API uses SQLite when `DATABASE_URL` is not set, which keeps the direct local
development path self-contained.

### Database migrations (Alembic)

Schema changes are Alembic revisions in `apps/api/alembic/versions/` (recorded in
the `alembic_version` table). API startup runs `alembic upgrade head` unless
`RUN_MIGRATIONS_ON_STARTUP=false`; Kubernetes runs it once per release through
`python -m app.migrate` (`infra/kubernetes/migrate-job.yaml`). On PostgreSQL the
upgrade holds an advisory lock, so replicas starting together wait instead of racing.
Databases migrated by the earlier `schema_versions` runner are stamped at the
matching revision automatically. From `apps/api` (uses `DATABASE_URL`):

```powershell
alembic upgrade head        # or: python -m app.migrate
alembic current             # alembic history
alembic revision --autogenerate -m "add widgets table"   # after editing app/models.py
alembic check               # fails if models.py has changes no revision covers
```

When you change `app/models.py`, add a revision (autogenerate, then review it).
The baseline builds new databases from the current models, so guard every step in
a revision (`app.migrations.has_table` / `has_column` / `has_index`) to keep it a
no-op where the object already exists. As a safety net, startup and `app.migrate`
also run `Base.metadata.create_all` (checkfirst) after the upgrade. That way a
brand-new table appears even before its revision exists. New columns, indexes and
data changes on existing tables still need a revision.

The web app calls its API through a same-origin `/api/*` path that Next.js rewrites
to `INTERNAL_API_URL` (see `apps/web/next.config.ts`), defaulting to `http://api:8000`
for the Docker Compose network. Running the web app directly (outside Compose) needs
`INTERNAL_API_URL` set to wherever the API is actually reachable — `http://localhost:8000`
for the standalone `uvicorn` command above. `NEXT_PUBLIC_API_URL` is no longer read by
the frontend and can be ignored.

## Enterprise configuration

Real credentials are not required to evaluate the product. Add connector secret
references and model provider secret references through Admin. SQL Server,
Oracle, Teradata, and BigQuery connectors run driver-backed read-only probes,
catalog scans, and governed parameterized query tools. PingFederate configuration is stored through Admin using OIDC-first
settings; live SSO activation requires the company issuer and client details.

Connector secrets use `env:VARIABLE_NAME`. The environment variable can contain
a JSON object such as `{"username":"reader","password":"..."}`. SQL Server,
Oracle, and Teradata also accept a plain password when the corresponding
`*_USERNAME` variable exists. BigQuery accepts service-account JSON directly or
under a `service_account` property; that property may also contain a mounted JSON
file path.

The following boundaries are intentional and must not be mistaken for completed
live integrations:

- SQL Server, Oracle, Teradata, and BigQuery adapters and drivers are installed for metadata and fixed parameterized read-only query tools; live verification requires reachable company endpoints and credentials. General unrestricted query execution is intentionally unsupported.
- PingFederate has an admin configuration contract; the complete browser redirect, callback, group mapping, and logout handshake requires issuer metadata and a registered client.
- Gemini 3.6 Flash and 3.5 Flash are validated through an environment-backed key. OpenAI, Claude, and company-provider calls still require their corresponding environment credentials. Secrets are not stored directly in the database.
- Governance telemetry is provider-neutral and supports comma-separated fan-out through `GOVERNANCE_PROVIDERS`: `agentguard`, standards-based `otlp` (for Phoenix, Langfuse, or another compatible collector), and signed `webhook` (for an internal or vendor gateway). It exports sanitized model, tool-execution, connector-query, and approval-decision metadata; the application keeps approval, authorization, and audit enforcement locally. For AgentGuard specifically, LLM generations can include redacted input/output when `AGENTGUARD_CAPTURE_CONTENT=true`, while non-LLM custom governance spans follow `AGENTGUARD_EXPORT_GOVERNANCE_EVENTS` and default to off when `AGENTGUARD_INCLUDE_INFRA_SPANS=false`. See `.env.example` for endpoint/header configuration; no vendor credentials are stored in source control.
- Notebook cells, artifact comments, diffs, reviews, evaluation replay, and version history are implemented. Simultaneous real-time co-editing is intentionally outside this local build.
- Schedule execution processes uploaded local files with append or key-based merge and optional watermarks. General incremental extraction directly from external databases remains a later connector capability.

The authoritative [system specification](docs/DATAPILOT_SYSTEM_SPEC.md) covers
scope, current delivery status, architecture, workflows, agents, tools,
governance, deployment, and the remaining external certification work. The
[documentation index](docs/README.md) links the focused supporting guides. For a
plain-language explanation of source connections, PostgreSQL staging, semantic
definitions, SQL execution boundaries, MCP, pipelines, and lineage, see
[`docs/DATA_CONNECTIONS_LINEAGE_AND_TOOLS_GUIDE.md`](docs/DATA_CONNECTIONS_LINEAGE_AND_TOOLS_GUIDE.md).

Database connection modes, Google MCP Toolbox examples, external tool discovery,
VS Code configuration, and the Google ADK account-agent example are documented in
[`docs/DATABASE_MCP_TOOL_REGISTRY_GUIDE.md`](docs/DATABASE_MCP_TOOL_REGISTRY_GUIDE.md).

For a detailed mapping of how the system addresses the OWASP Top 10 for Large Language Model Applications, see
[`docs/OWASP_TOP_10_LLM_MAPPING.md`](docs/OWASP_TOP_10_LLM_MAPPING.md).

For a production-platform baseline, [infra/kubernetes/README.md](infra/kubernetes/README.md)
contains the Kustomize deployment manifests and prerequisite checklist. The
manifests require managed backing services and organization-specific secrets;
they are not applied by the local Compose workflow.

## Generating the Demo and Videos
You can programmatically generate the demo screenshots and record the complete application flow by running the Playwright E2E script:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install playwright pytest-playwright
playwright install chromium
python scripts\e2e_playwright_demo.py
```

The resulting screenshots will be saved to `docs/screenshots/workflows/` and the video recordings will be in `docs/videos/`.
