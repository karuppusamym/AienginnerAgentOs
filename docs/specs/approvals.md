# Approvals

**Router:** `apps/api/app/routers/approvals.py`  
**Audience:** Governance reviewers, admins, engineers depending on policy.

## Purpose

The human decision gate for risky actions (deployments, writes, recurring schedules, high-risk tool execution, destructive remediation).

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/approvals` |
| POST | `/approvals/{approval_id}/decision` |

## Key models

`Approval`

## Status notes

This is the load-bearing safety mechanism referenced throughout ARCHITECTURE_DECISIONS.md §2 — nothing in the self-learning/harness discussion should bypass this gate.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
