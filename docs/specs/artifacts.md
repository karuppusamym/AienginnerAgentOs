# Artifacts, versions, comments & review

**Router:** `apps/api/app/routers/artifacts.py`  
**Audience:** Everyone who generates output; governance reviewers approve/request changes.

## Purpose

Durable, versioned storage for generated SQL, pipeline packages, and other governed outputs, with diffs, comments, and review decisions.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/artifacts` |
| POST | `/artifacts` |
| GET | `/artifacts/{artifact_id}/versions` |
| GET | `/artifacts/{artifact_id}/diff` |
| GET | `/artifacts/{artifact_id}/comments` |
| POST | `/artifacts/{artifact_id}/comments` |
| POST | `/artifacts/{artifact_id}/review` |

## Key models

`Artifact`, `ArtifactVersion`, `ArtifactComment`

## Status notes

Real-time co-editing is an explicit non-goal; versioned comments/reviews are the supported collaboration model.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
