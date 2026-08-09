# Pipeline generation, deployment & lineage

**Router:** `apps/api/app/routers/pipelines.py`  
**Audience:** Data engineers; approvals route through governance reviewers.

## Purpose

Generate a local pipeline/view package from a staged dataset, produce basic dbt/Dataform package emission, deploy a PostgreSQL view after approval, and record/list lineage edges.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/pipelines` |
| POST | `/pipelines/generate` |
| GET | `/pipelines/{pipeline_id}/packages/{package_target}` |
| GET | `/pipelines/{pipeline_id}/packages/{package_target}/delivery-config` |
| PUT | `/pipelines/{pipeline_id}/packages/{package_target}/delivery-config` |
| GET | `/pipelines/{pipeline_id}/packages/{package_target}/archive` |
| POST | `/pipelines/{pipeline_id}/packages/{package_target}/validate` |
| PUT | `/pipelines/{pipeline_id}` |
| DELETE | `/pipelines/{pipeline_id}` |
| POST | `/pipelines/{pipeline_id}/deploy` |
| GET | `/lineage` |
| GET | `/lineage/graph` |

## Key models

`PipelineDefinition`, `PipelineVersion`, `LineageEdge`

## Status notes

`/lineage` is a flat, filterable edge list for list/audit views. `/lineage/graph` (verified in `IMPLEMENTATION_STATUS_MATRIX.md` this revision) adds genuine bounded multi-hop traversal — `?relation=...&direction=upstream|downstream|both&depth=1-20` — implemented as an in-memory BFS over `LineageEdge` adjacency, capped at depth 20 to prevent unbounded walks. This closes the graph-traversal gap noted in `ARCHITECTURE_DECISIONS.md` §1 without adding a graph database, exactly the recursive-CTE-style incremental path that document recommended (built as an application-level BFS rather than a SQL recursive CTE, which is an equally valid implementation of the same "no new infrastructure" principle).

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
