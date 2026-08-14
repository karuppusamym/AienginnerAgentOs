# SQL Server demo (Docker Compose, self-contained)

**Status: superseded / active path.** The demo previously documented here targeted a
Windows-hosted SQL Server Express instance and was blocked on enabling TCP/IP in SQL
Server Configuration Manager on the host — that path is no longer the recommended one.
`compose.yaml` now provisions a real, self-contained SQL Server 2022 container
(`sqlserver-demo`) that needs no host configuration at all: it's reachable from the
`api` container over the Docker network by hostname, on its normal TCP port, the
moment `docker compose up` finishes its healthcheck.

## What's provisioned

- **Container:** `mcr.microsoft.com/mssql/server:2022-latest`, service name `sqlserver-demo`, port `1433` (also published to the host at `localhost:1433` for tools like SSMS/Azure Data Studio).
- **Seed data:** `infra/sqlserver-init/init.sql` runs automatically on first start and creates database `DemoDB`, schema `demo`, with three tables: `demo.customers`, `demo.orders`, `demo.payments`.
- **Credentials:** `sa` / `${MSSQL_SA_PASSWORD:-DataPilot#2026!}`. The `api` service also has `SQLSERVER_DEMO_CREDENTIALS` pre-populated as a convenience reference (`{"server":"sqlserver-demo,1433","database":"DemoDB","username":"sa","password":"DataPilot#2026!"}`) — this is not auto-consumed by the application; it's the exact value to paste into the connector form below.
- **Healthcheck:** `sqlcmd -Q 'SELECT 1'` against the container itself, so `docker compose up` won't report the service healthy until SQL Server is actually accepting connections.

## Registering the connector in DataPilot

DataPilot does not auto-register connectors from environment variables — an admin
adds one explicitly, same as any other source:

1. `docker compose up --build` (or `--profile analytics up --build` if you also want Superset).
2. Sign in, go to **Admin → Connectors → Add connector**.
3. Type: **SQL Server**, mode: **Direct**.
4. Host: `sqlserver-demo`, port `1433`, database: `DemoDB`, username `sa`, password from `MSSQL_SA_PASSWORD` above (store it as a secret reference, not inline).
5. Save, then **Scan** — this exercises the real, live `discover_metadata()` path against an actual SQL Server instance, not a mock.

## MCP-mode variant

`infra/mcp-toolbox/payments-mssql.tools.yaml` backs a second connector path: the
`mcp-toolbox` service in `compose.yaml` fronts this same SQL Server instance over MCP
(`tools/list`/`tools/call`), so the MCP-mode connector scan (`discover_mcp_metadata()`)
can be exercised end-to-end too, without any separate manual MCP server startup —
`mcp-toolbox` depends on `sqlserver-demo`'s healthcheck and starts automatically as
part of the same `docker compose up`.

## What's still open

This closes the "no live SQL Server to test against" gap without needing host
changes. What it does **not** close: Oracle, Teradata, and BigQuery still have no
equivalent live demo/certification path (drivers and adapters are installed and unit
exercised, but not run against a real instance). That remains open — see
`docs/IMPLEMENTATION_STATUS_MATRIX.md` §2.
