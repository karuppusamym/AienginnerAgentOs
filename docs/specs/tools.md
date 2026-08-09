# Internal tool registry

**Router:** `apps/api/app/routers/tools.py`  
**Audience:** Admins/engineers register tools; agents invoke published versions.

## Purpose

Register, version, and publish built-in or allowlisted-HTTP tools that agents can call; execute and audit tool runs.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/tools` |
| POST | `/tools` |
| GET | `/tools/executions` |
| GET | `/tools/{tool_id}` |
| PUT | `/tools/{tool_id}` |
| POST | `/tools/{tool_id}/versions` |
| POST | `/tools/{tool_id}/versions/{version_number}/publish` |
| POST | `/tools/{tool_id}/execute` |

## Key models

`ToolDefinition`, `ToolVersion`, `ToolExecution`

## Built-in handlers (`app/tool_runtime.py: BUILTIN_HANDLERS`)

| Tool | Risk | Approval | What it does |
| --- | --- | --- | --- |
| `catalog.search` | low | no | Hybrid catalog + semantic search |
| `dataset.profile` | low | no | Read a `DataAsset`'s persisted profile |
| `sql.preview` | medium | no | Bounded read-only SQL execution |
| `job.inspect` | low | no | Read a job's trace/evidence/logs |
| `lineage.query` | low | no | Find upstream/downstream lineage edges |
| `sql.generate` | low | no | Catalog-grounded, dialect-aware SQL drafting (deterministic templating; same fallback path `/sql/generate` uses without a model provider) |
| `file.profile` | low | no | Read an `IngestedFile`'s persisted profile |
| `quality.run` | medium | no | Execute a persisted `QualityRule`, record a `QualityRun` |
| `pipeline.stage` | high | **yes** | Write a governed local staging relation + register the catalog `DataAsset` |
| `schedule.run` | high | **yes** | Run one approved `IngestionSchedule` now |

`_execute_bound_tools()` (the loop `POST /agents/runs` and the local fallback both use) only ever auto-selects `risk_level == "low"` tools for the bounded orchestration loop — `sql.preview` (medium), `quality.run` (medium), `pipeline.stage` and `schedule.run` (high + approval-gated) never fire autonomously. They still execute through the explicit `POST /tools/{id}/execute` path (immediately for medium risk with no approval flag, through the `Approval` flow for the two `requires_approval=True` tools).

**Parameter filling for an autonomous run is two-tier (Aug 9, 2026).** `_parameters_for_tool()` (deterministic, no model call) grounds objective/query text, exact project-scoped UUIDs mentioned in the objective, matched catalog relations, bounded limits, and declared defaults. Only when that can't satisfy every required field does `_llm_parameters_for_tool()` get a guarded turn — real provider only, output must pass the same `validate_parameters()` check, and any foreign-key-shaped field must resolve to a real project-scoped row or the fill is discarded outright. Both tiers land on the same outcome when they fail: skip the tool, never guess. Evidence entries carry `parameter_source: "heuristic"|"model"` so a completed run stays explainable about which tier supplied which value.

## Status notes

Arbitrary code execution and arbitrary outbound hosts are rejected; HTTP tools must target `TOOL_HTTP_ALLOWLIST`.

**All ten seeded tools now have a working handler (fixed Aug 8, 2026).** Previously, `seed.py` declared 10 `ToolDefinition` rows but only wired a `ToolVersion`/handler for 5 of them (`catalog.search`, `dataset.profile`, `sql.preview`, `job.inspect`, `lineage.query`). The other 5 — `sql.generate`, `file.profile`, `quality.run`, `pipeline.stage`, `schedule.run` — were referenced by name on the seeded SQL Analyst, Pipeline, and Quality agents but had zero implementation: `POST /tools/{id}/execute` would 409 ("publish a tool version before executing it") for any of them, and the bounded orchestration loop silently skipped them (no error, just never invoked). Concretely, the Pipeline agent's three bound tools were *all* unimplemented (it could never do anything), the Quality agent could only ever search the catalog, never run a quality rule, and the SQL Analyst agent could search and preview but never draft SQL — real SQL generation only ever happened through the separate `/sql/generate` route the SQL workspace UI calls directly, invisible to any agent. All five now have real handlers (see table above), covered by `test_newly_wired_builtin_tool_handlers_execute_for_real` and `test_seeded_sql_analyst_agent_autonomously_generates_sql` in `apps/api/tests/test_api.py`. The migration is idempotent — `ensure_control_plane()` in `seed.py` adds the missing `ToolVersion` rows on next startup even for an existing database, no reset required.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
