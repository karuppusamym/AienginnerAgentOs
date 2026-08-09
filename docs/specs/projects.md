# Projects & membership

**Router:** `apps/api/app/routers/projects.py`  
**Audience:** Admins manage projects/membership; every user selects a current project.

## Purpose

Project creation/selection, membership management, and per-project default model provider.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/projects` |
| POST | `/projects` |
| POST | `/projects/{project_id}/select` |
| GET | `/projects/{project_id}/members` |
| POST | `/projects/{project_id}/members` |
| PUT | `/projects/{project_id}/model-provider` |

## Key models

`Project`, `ProjectMembership`

## Status notes

Every catalog, connector, job, and conversation is project-scoped — there is no cross-project sharing today. See ARCHITECTURE_DECISIONS.md for the project-scoping confirmation from the Aug 8 metadata audit.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
