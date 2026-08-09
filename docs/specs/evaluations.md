# Evaluation sets & replay

**Router:** `apps/api/app/routers/evaluations.py`  
**Audience:** Admins/engineers building test coverage for agents and SQL generation.

## Purpose

Create evaluation cases, replay them against agents/SQL generation, run red-team suites, and set golden-trace baselines.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/evaluations` |
| POST | `/evaluations` |
| POST | `/evaluations/red-team` |
| PUT | `/evaluations/{evaluation_set_id}` |
| DELETE | `/evaluations/{evaluation_set_id}` |
| POST | `/evaluations/{evaluation_set_id}/run` |
| POST | `/evaluations/{evaluation_set_id}/baseline` |

## Key models

`EvaluationSet`, `EvaluationRun`

## Status notes

This is the data source for the agent scorecard/promotion-recommendation feature — see the `agents` domain above and ARCHITECTURE_DECISIONS.md §2.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
