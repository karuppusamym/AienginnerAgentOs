# Guarded SQL generation & execution

**Router:** `apps/api/app/routers/sql.py`  
**Audience:** Analysts and engineers.

## Purpose

Catalog-grounded, dialect-aware natural-language-to-SQL generation with mandatory read-only validation, and bounded PostgreSQL preview execution.

## Endpoints

| Method | Path |
| --- | --- |
| POST | `/sql/generate` |
| POST | `/sql/execute` |
| GET | `/sql/history` |

## Key models

`SQLQueryCache`, `ModelCallLog`

## Status notes

Enforces exactly one SELECT/WITH statement, rejects DDL/DML, applies a row limit, and returns a full evidence payload (grounding, cache status, validation checklist) that the UI already surfaces in a side panel.

`GET /sql/history` (added by the Aug 8, 2026 concurrent round, verified this revision) returns a persisted per-user/per-project query log.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
