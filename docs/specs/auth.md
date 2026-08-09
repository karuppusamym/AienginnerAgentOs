# Authentication & SSO configuration

**Router:** `apps/api/app/routers/auth.py`  
**Audience:** Everyone logs in here; only admins configure `auth-providers`.

## Purpose

Local email/password login, session identity, password changes, and the PingFederate/OIDC configuration contract.

## Endpoints

| Method | Path |
| --- | --- |
| POST | `/auth/login` |
| GET | `/auth/me` |
| POST | `/auth/change-password` |
| GET | `/auth-providers` |
| PUT | `/auth-providers/{provider_id}` |

## Key models

`User`, `AuthProvider`

## Status notes

Local auth is fully implemented and is the active mode. PingFederate has a configuration contract but the full OIDC login/callback/logout/group-mapping handshake is not finished — this is the top P0 gap in ENTERPRISE_READINESS_AND_AGENT_CAPABILITY_ASSESSMENT.md.

`GET /auth/me` also returns `effective_project_role` and a granular `permissions` array (via a `ROLE_PERMISSIONS` map in `main.py`: `catalog:read`, `catalog:write`, `semantic:write`, `query:write`, `pipeline:write`, `quality:write`, `registry:write`, `jobs:write`, `conversation:write`, `feedback:write`, etc.).

**Updated this revision:** this is no longer purely informational. `require_permission(user, permission)` in `main.py` checks a request against this same `ROLE_PERMISSIONS` map, and backs `require_data_editor`/`require_workspace_editor`/a direct `semantic:write` check across 9 router files (32 call sites: artifacts, connectors, conversations, evaluations, files, notebooks, pipelines, prompts, workspace). It's real enforcement, verified by reading the function. Two things keep it from being complete: (1) roughly a dozen other write-gated endpoints in `agents.py`/`approvals.py`/`artifacts.py`/`connectors.py`/`files.py`/`projects.py`/`quality.py`/`query_tools.py`/`semantic.py` still use inline `user.role not in {"admin","engineer"}` checks that bypass this map entirely; (2) `require_permission()` takes only a `User`, not a `db: Session`, so it can only evaluate the user's *global* `User.role` — unlike `session_user_output()` (which powers this same `/auth/me` response and correctly blends global role with project-membership role), it never looks up project membership. A user whose project-level role differs from their account-level role is authorized on the wrong basis. See `IMPLEMENTATION_STATUS_MATRIX.md` §2 for the full breakdown.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
