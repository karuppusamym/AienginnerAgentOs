# Model provider registry

**Router:** `apps/api/app/routers/model_providers.py`  
**Audience:** Admins configure providers; the selected provider powers SQL generation and agent planning for everyone in the project.

## Purpose

Register, test, and select model providers (local deterministic, OpenAI-compatible, Gemini, Claude, company providers); view model-call usage/cost.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/model-providers` |
| POST | `/model-providers` |
| PUT | `/model-providers/{provider_id}` |
| POST | `/model-providers/{provider_id}/test` |
| POST | `/model-providers/{provider_id}/default` |
| GET | `/model-usage` |

## Key models

`ModelProvider`, `ModelCallLog`

## Status notes

Secrets are stored as `env:VARIABLE_NAME` references only, never plaintext in the database or browser.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
