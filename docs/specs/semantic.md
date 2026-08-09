# Semantic layer

**Router:** `apps/api/app/routers/semantic.py`  
**Audience:** Admins/analysts who own metric definitions.

## Purpose

Business metric definitions and approved join policies that ground SQL generation instead of letting the model guess table relationships.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/semantic/metrics` |
| POST | `/semantic/metrics` |
| PUT | `/semantic/metrics/{metric_id}` |
| DELETE | `/semantic/metrics/{metric_id}` |
| GET | `/semantic/joins` |
| POST | `/semantic/joins` |
| PUT | `/semantic/joins/{policy_id}` |
| DELETE | `/semantic/joins/{policy_id}` |
| GET | `/semantic/graph` |

## Key models

`SemanticMetric` (now with `asset_id` metric-to-asset binding), `SemanticJoinPolicy`

## Status notes

`SemanticJoinPolicy` is a relational edge list (same graph-shaped-but-not-graph-queried pattern as lineage) — see ARCHITECTURE_DECISIONS.md §1.

`GET /semantic/graph` (added by the Aug 8, 2026 concurrent round, verified this revision) returns a read-only relationship view: nodes from `DataAsset`, edges from governed `SemanticJoinPolicy` plus inferred column-name-matched suggestions marked `governed: false` pending review. Computed live from relational data, not a graph database — the exact pattern ARCHITECTURE_DECISIONS.md §1 recommended before this was built.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
