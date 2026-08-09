# System health & workspace overview

**Router:** `apps/api/app/routers/system.py`  
**Audience:** Everyone (health checks are unauthenticated); overview/security dashboards need a logged-in session.

## Purpose

Liveness/readiness probes, observability status, the workspace overview dashboard, and the security posture dashboard.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/health` |
| GET | `/health/live` |
| GET | `/health/ready` |
| GET | `/observability/status` |
| GET | `/overview` |
| GET | `/security-overview` |

## Key models

`Incident`

## Status notes

`/security-overview` was found undocumented in prior specs during the Aug 8, 2026 audit — see IMPLEMENTATION_STATUS_MATRIX.md. It classifies Incident records into prompt-injection / PII / toxic-content categories via keyword matching, not a trained classifier.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
