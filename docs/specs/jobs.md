# Jobs, incidents & operations

**Router:** `apps/api/app/routers/jobs.py`  
**Audience:** Everyone who starts async work; admins/engineers for diagnosis.

## Purpose

Track long-running Temporal-backed work (agent plans, scans, schedules), cancel/retry/diagnose jobs, and manage incidents.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/jobs` |
| GET | `/jobs/{job_id}` |
| POST | `/jobs/{job_id}/cancel` |
| POST | `/jobs/{job_id}/retry` |
| POST | `/jobs/{job_id}/diagnose` |
| GET | `/incidents` |
| POST | `/incidents/{incident_id}/resolve` |
| GET | `/jobs/{job_id}/events` |

## Key models

`Job`, `Incident`

## Status notes

`Job` is the product-facing record; Temporal workflow identity is linked but the job record is authoritative for UI/API purposes.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
