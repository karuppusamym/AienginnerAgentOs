# Data quality rules & runs

**Router:** `apps/api/app/routers/quality.py`  
**Audience:** Data engineers.

## Purpose

Create/suggest quality rules, run them against staged data, inspect pass rates and failure samples, and remediate quarantined rows.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/quality/rules` |
| POST | `/quality/rules` |
| POST | `/quality/assets/{asset_id}/suggest` |
| GET | `/quality/runs` |
| POST | `/quality/rules/{rule_id}/run` |
| POST | `/quality/runs/{run_id}/remediate` |

## Key models

`QualityRule`, `QualityRun`

## Status notes

Remediation can require approval depending on configuration.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
