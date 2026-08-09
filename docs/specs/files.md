# File ingestion, staging, external extraction & schedules

**Router:** `apps/api/app/routers/files.py`  
**Audience:** Data engineers primarily.

## Purpose

Upload CSV/JSON/Excel/Parquet, profile and map to a target schema, stage into PostgreSQL (versioned/replace/append/key-merge), configure bounded external-DB extraction, and manage recurring ingestion schedules with watermarks.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/files` |
| POST | `/files/ingest` |
| GET | `/files/{file_id}/mappings` |
| GET | `/ingestion-mappings` |
| GET | `/external-extractions` |
| POST | `/external-extractions` |
| POST | `/external-extractions/{extraction_id}/run` |
| GET | `/schedules` |
| POST | `/schedules` |
| POST | `/schedules/{schedule_id}/run` |
| POST | `/schedules/{schedule_id}/disable` |
| POST | `/files/{file_id}/schema` |
| POST | `/files/{file_id}/stage` |

## Key models

`IngestedFile`, `IngestionMapping`, `ExternalExtraction`, `IngestionSchedule`

## Status notes

External extraction exists but scheduling/retry/chunking for large external sources and per-connector certification remain open (P1/P2).

Ingested file columns are now annotated for PII via `annotate_columns()` (`app/pii.py`, verified this revision) — pattern/heuristic classification (email, phone, government ID, payment card, bank account, DOB, address, name) tags `sensitivity: "pii"` and a `pii_category` on matching columns at ingest time. Heuristic-based, not a managed DLP classifier — will miss PII in oddly-named or free-text columns.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
