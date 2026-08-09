# Retention policies

**Router:** `apps/api/app/routers/retention_policies.py`  
**Audience:** Admins.

## Purpose

Configure and run data/record retention cleanup under approval.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/retention-policies` |
| POST | `/retention-policies` |
| POST | `/retention-policies/{policy_id}/run` |

## Key models

`RetentionPolicy`

## Status notes

Retention execution routes through the approval boundary like other destructive actions.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
