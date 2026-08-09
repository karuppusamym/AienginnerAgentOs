# Dataset catalog, search & recommendations

**Router:** `apps/api/app/routers/workspace.py`  
**Audience:** Analysts primarily; engineers/admins for corrections.

## Purpose

Browse the project's data catalog, hybrid keyword+vector search, suggested next questions, and manual metadata review/editing.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/datasets` |
| PUT | `/datasets/{asset_id}` |
| POST | `/datasets/import` |
| GET | `/recommendations` |
| GET | `/search` |

## Key models

`DataAsset` — now includes `owner`, `sensitivity`, `freshness_sla_hours`, `metadata_status`.

## Status notes

`PUT /datasets/{asset_id}` (description/tags edit) was added Aug 8, 2026 to close a real gap — metadata was previously write-only from the API's perspective. `owner`/`sensitivity`/`freshness_sla_hours`/`metadata_status` fields have since been added to the model and are now fully covered by the edit UI (`DatasetsView.tsx`) as well.

`POST /datasets/import` was added Aug 8, 2026 (this revision) — accepts a `schema_name,table_name,column_name,...` CSV upload and creates/updates `DataAsset` rows without a live connection, tagged `metadata_status="manual_import"`. UI: Dataset explorer → "Import catalog CSV."

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
