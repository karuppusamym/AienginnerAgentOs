# Connectors, metadata scan & schema drift

**Router:** `apps/api/app/routers/connectors.py`  
**Audience:** Engineers/admins register and scan sources; everyone benefits from the resulting catalog.

## Purpose

Register data sources (PostgreSQL, SQL Server, Oracle, Teradata, BigQuery, local files), test connectivity, run read-only metadata scans, and review/acknowledge schema drift.

## Endpoints

| Method | Path |
| --- | --- |
| GET | `/connectors` |
| POST | `/connectors` |
| PUT | `/connectors/{connector_id}` |
| DELETE | `/connectors/{connector_id}` |
| POST | `/connectors/{connector_id}/test` |
| POST | `/connectors/{connector_id}/scan` |
| GET | `/schema-drift` |
| POST | `/schema-drift/{event_id}/acknowledge` |

## Key models

`Connector`, `DataAsset`, `SchemaDriftEvent`

## Status notes

Metadata scanning is read-only for both connection modes: driver-backed for `connection_mode: "direct"`, and (as of Aug 8, 2026, this revision) `tools/list`-backed for `connection_mode: "mcp"` via `discover_mcp_metadata()` — each upstream MCP tool's input/output JSON Schema is cataloged as a queryable asset with inferred PII/date/id tags. Previously MCP-mode connectors could be queried but not scanned; that gap is closed. Schema drift detection + acknowledgment is fully implemented — more complete than earlier docs suggested.

A local SQL Server Express demo (`DataPilotDemo` direct connector, `DataPilotMcpDemo`/`payments-mssql.tools.yaml` MCP connector) is provisioned per `docs/SQLSERVER_EXPRESS_DEMO.md`; live scanning is still blocked pending SQL Server TCP/IP being enabled on the host.

---

_Part of the per-domain spec set — see [`README.md`](./README.md) for the full index, [`../DATAPILOT_SYSTEM_SPEC.md`](../DATAPILOT_SYSTEM_SPEC.md) for overall architecture, and [`../IMPLEMENTATION_STATUS_MATRIX.md`](../IMPLEMENTATION_STATUS_MATRIX.md) for the completed/partial/not-completed checklist._
