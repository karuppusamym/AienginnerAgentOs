# Governed notebooks

**Router:** `apps/api/app/routers/notebooks.py`  
**Audience:** Analysts/engineers.

## Purpose

Markdown, read-only SQL, and restricted-Python notebook cells, each execution preserved as a versioned artifact.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/notebooks` |
| POST | `/notebooks` |
| DELETE | `/notebooks/{notebook_id}` |
| POST | `/notebooks/{notebook_id}/run` |

## Key models

`Artifact (notebook kind)`

## Status notes

The Python environment is a restricted expression evaluator — imports, file/network access, and arbitrary functions are prohibited by design.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
