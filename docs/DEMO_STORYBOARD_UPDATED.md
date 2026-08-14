# DataPilot Demo Storyboard (Updated)

This document serves as the canonical sequence of workflows for the E2E Demo automation and presentation.

## Prerequisites
- Services running via Docker Compose (`api`, `web`, `postgres`, `qdrant`, `temporal`, `superset`).
- E2E Playwright Script executed to generate video and screenshots in `docs/videos/` and `docs/screenshots/workflows/`.

## Workflow Sequences (Recorded & Captured)

### 1. Login & Identity Verification
- **Actor:** Administrator (`admin@datapilot.local`)
- **Action:** Sign into the platform using the local fallback account.
- **Outcome:** Authenticates and is redirected to the active workspace (`/files` or `/catalog`).

### 2. Data Ingestion & File Upload
- **Actor:** Engineer / Administrator
- **Action:** Upload local seed data (e.g., CSV/Excel).
- **Outcome:** The file is ingested, mapped to a target staging table, and previewed.

### 3. Catalog & Hybrid Search
- **Actor:** Analyst
- **Action:** Use the global search bar in `/catalog` to find newly ingested tables and metrics.
- **Outcome:** The metadata catalog displays semantic connections and data context.

### 4. SQL Workspace & Agent Run
- **Actor:** Analyst / Engineer
- **Action:** Open the SQL Workspace. Submit a prompt requesting data manipulation or complex query generation.
- **Outcome:** The grounded SQL agent generates dialect-aware SQL and provides a guarded preview. Job is submitted for execution.

### 5. Multi-Agent Run & Approvals
- **Actor:** Temporal Agent & Administrator
- **Action:** An agent determines a risky action (e.g. data modification or publishing). The job enters a "WAITING" state.
- **Outcome:** Admin reviews the queue in `/approvals`, inspects the plan, and approves it. The agent resumes and completes the action.

### 6. Data Quality & Profiling
- **Actor:** Tester / Engineer
- **Action:** View the data quality rules and run results in `/quality`.
- **Outcome:** The system validates the staged data against semantic rules.

### 7. Lineage & Pipelines
- **Actor:** Engineer
- **Action:** View the visual representation of data lineage in `/pipelines`.
- **Outcome:** Shows upstream sources transforming into the target analytical views.

### 8. Governance & Security
- **Actor:** Security Analyst / Admin
- **Action:** View the security posture dashboard.
- **Outcome:** Audit logs, agent telemetry, and configuration settings are displayed.

### 9. Embedded Analytics (Superset)
- **Actor:** Analyst
- **Action:** Navigate to the governed analytics tab (`/analytics`).
- **Outcome:** View the short-lived session token authenticated Apache Superset dashboard embedded securely.

### 10. Connectors & Tools
- **Actor:** Administrator
- **Action:** Register and configure external DB connectors and parameterized HTTP tools.
- **Outcome:** The system successfully connects to the demo environments and registers MCP tools for the agents to use.
