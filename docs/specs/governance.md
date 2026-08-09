# Audit, feedback & learning suggestions

**Router:** `apps/api/app/routers/governance.py`  
**Audience:** Everyone generates audit events implicitly; governance reviewers act on the learning-suggestion queue.

## Purpose

The durable audit event log, user feedback capture, and the human-review queue that feedback feeds into.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/policies/effective` |
| GET | `/audit` |
| POST | `/feedback` |
| GET | `/feedback` |
| GET | `/learning-suggestions` |
| PUT | `/learning-suggestions/{suggestion_id}` |

## Key models

`AuditEvent`, `UserFeedback`, `LearningSuggestion`

## Status notes

This is DataPilot's actual "learning loop": feedback becomes a suggestion, a human reviews it, nothing changes runtime behavior automatically. See ARCHITECTURE_DECISIONS.md §2 for why this is the right posture, not a limitation.

As of Aug 8, 2026 (this revision), `POST /feedback` does trend detection: it looks for an existing open `LearningSuggestion` in the same category within a 30-day window and increments `occurrence_count`/escalates `severity`/appends to `recent_signals` (capped at 10) instead of always creating a new row, so repeated complaints surface as one growing signal rather than noise. A full review UI now exists (Admin → Governance → "LEARNING LOOP"): filter by open/accepted/dismissed, see occurrence count and severity, accept or dismiss with an audited note. Previously the backend endpoints existed with no UI at all.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
