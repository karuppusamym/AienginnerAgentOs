# Prompt versioning

**Router:** `apps/api/app/routers/prompts.py`  
**Audience:** Admins/engineers.

## Purpose

Save and roll back prompt artifacts used across the product.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/prompts` |
| POST | `/prompts` |
| POST | `/prompts/{prompt_id}/rollback` |

## Key models

`Artifact (prompt kind)`

## Status notes

Versioned like any other artifact; rollback is a first-class action, not a manual restore.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
