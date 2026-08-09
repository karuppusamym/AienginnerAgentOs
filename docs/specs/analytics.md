# Embedded Superset analytics

**Router:** `apps/api/app/routers/analytics.py`
**Audience:** Everyone views embedded dashboards; admins get editor access; publishing a query dashboard requires workspace-editor write access to request, and admin/engineer approval to complete.

## Purpose

Optional embedded Apache Superset dashboards with DataPilot-brokered guest access, an admin-only editor handoff, and an approval-gated path to publish a saved SQL/notebook query as its own dedicated analytics dashboard.

## Two distinct dashboard identities

DataPilot provisions two kinds of Superset dashboard, and they are deliberately kept separate so that publishing a query can never overwrite the project's primary dashboard:

1. **Project dashboard** (`GET /analytics/config`, `POST /analytics/guest-token`) — one dashboard per project, tracked in `SupersetProjectDashboard` (unique per `project_id`), built from whichever local relation `resolve_superset_dataset()` picks (the most recently staged/mapped file or pipeline output). No approval step — this only surfaces data the requesting user already has read access to inside the project's own PostgreSQL schema.
2. **Query dashboard** (`GET /analytics/queries/{artifact_id}`, `POST /analytics/queries/{artifact_id}/guest-token`) — one dedicated dashboard per published SQL/notebook artifact, tracked in `SupersetQueryDashboard` (unique per `project_id` + `artifact_id`). This *is* approval-gated: `POST /analytics/publish-sql` only ever creates an `Approval` (`action_type="publish_superset_query"`); the dashboard is provisioned and the immutable SQL is registered as a Superset virtual dataset only once an admin/engineer approves it (`POST /approvals/{id}/decision`).

Both flows call the same underlying `superset_client.get_embed_configuration()`/`create_guest_token()`, but the query flow passes an explicit `dashboard_key` (`f"query-{artifact_id}"`) so its Superset dashboard slug is derived from the artifact, not the project — before this session, both flows resolved to the identical `datapilot-project-{slug}` slug, so publishing any query silently replaced whatever the project's primary dashboard was showing.

## Endpoints

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/analytics/config` | Project's primary dashboard; no approval required. |
| POST | `/analytics/guest-token` | Guest token for the primary dashboard. |
| POST | `/analytics/editor-session` | Admin-only short-lived Superset SQL editor handoff. |
| POST | `/analytics/publish-sql` | Request publication of a saved SQL artifact or notebook's SQL cell — creates an `Approval`, does not publish anything itself. |
| GET | `/analytics/queries/{artifact_id}` | Whether that artifact has an approved, dedicated dashboard yet (drives the "Publish to Superset" vs "Open in Superset" hotlink in `SQLView.tsx`/`NotebooksView.tsx`). |
| POST | `/analytics/queries/{artifact_id}/guest-token` | Guest token scoped to that artifact's own dashboard; 409 if not yet approved. |

## Key models

`SupersetProjectDashboard`, `SupersetQueryDashboard`

## Status notes

Superset is explicitly not the system of record for authorization — DataPilot brokers short-lived, dashboard-scoped guest tokens. Query/notebook publication is approval-gated end to end: the SQL is copied into the `Approval.evidence` at request time, revalidated as read-only and re-executed for a live column preview at decision time, and only then registered in Superset — an editor cannot change the query between review and publication. The project's primary dashboard (`/analytics/config`) is intentionally not approval-gated, since it only exposes data the viewer already has query access to in the project's own PostgreSQL schema; see `IMPLEMENTATION_STATUS_MATRIX.md` for the discussion of why plain file-stage-to-Postgres itself still has no approval step, which is the one real remaining edge in that reasoning.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
