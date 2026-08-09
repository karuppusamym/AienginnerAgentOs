# Local SQL Server Express demo

The local Windows SQL Server Express instance now contains:

- `DataPilotDemo`: `demo.customers`, `demo.orders`, and `demo.payments`.
- `DataPilotMcpDemo`: `demo.payment_summary` for the separate MCP demonstration.

The DataPilot Postgres control plane contains two read-only connector records:

- `Local SQL Express - Payments`: direct SQL Server connector targeting `DataPilotDemo`.
- `SQL Express MCP - Payment Summary`: MCP connector targeting `DataPilotMcpDemo` and `http://host.docker.internal:5000/mcp`.

The second path uses `infra/mcp-toolbox/payments-mssql.tools.yaml` and must be
started with the official MCP Toolbox after the host SQL Server TCP endpoint is
enabled.

The Windows instance currently accepts local shared-memory connections but does
not expose TCP. Docker cannot reach `localhost\\SQLEXPRESS` through shared
memory. Enable TCP/IP on port 1433 in SQL Server Configuration Manager (run it
as Administrator), restart `SQL Server (SQLEXPRESS)`, and then test/scan the
direct connector from the DataPilot UI. Credentials are held through the
`SQLSERVER_CREDENTIALS` environment reference and are not sent to the browser.
