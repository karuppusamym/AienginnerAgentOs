# Persistent analysis conversations

**Router:** `apps/api/app/routers/conversations.py`  
**Audience:** Analysts.

## Purpose

Multi-turn grounded analysis with conversation memory/summarization, saved reports, and the same SQL safety guarantees as the SQL workspace.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/conversations` |
| POST | `/conversations` |
| GET | `/conversations/{conversation_id}/messages` |
| POST | `/conversations/{conversation_id}/messages` |
| POST | `/conversations/{conversation_id}/report` |
| DELETE | `/conversations/{conversation_id}` |

## Key models

`Conversation`, `ConversationMessage`

## Status notes

Follow-up questions reuse prior context and a deterministic summary once a thread gets long; this is deterministic reuse, not learning — see ARCHITECTURE_DECISIONS.md §2.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
