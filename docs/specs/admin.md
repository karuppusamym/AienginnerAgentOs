# User administration

**Router:** `apps/api/app/routers/admin.py`  
**Audience:** Admins only.

## Purpose

Admin-only user creation, role assignment, and activation/deactivation.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/admin/users` |
| POST | `/admin/users` |
| PUT | `/admin/users/{user_id}` |

## Key models

`User`

## Status notes

Roles are coarse (admin/engineer/analyst/viewer) plus project membership. Fine-grained per-action RBAC is an open P1 gap.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
