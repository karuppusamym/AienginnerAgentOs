# Data connections, staging, lineage, semantic layer, agents, and tools

**Audience:** product owners, data engineers, analysts, and implementers  
**Purpose:** answer the common confusion between source databases, PostgreSQL staging, MCP tools, semantic definitions, generated SQL, pipeline creation, and lineage.

## 1. Short answer

DataPilot separates five concepts that often get mixed together:

| Concept | What it means | Current behavior |
| --- | --- | --- |
| Source connection | A registered system such as PostgreSQL, SQL Server, Oracle, Teradata, BigQuery, local files, or an MCP-backed source. | Stored as a connector with type, mode, database/host, and secret reference. Used for metadata scans, source identity, and governed query tools. |
| Data asset | A catalog record for a table, view, or staged file. | Has source name, schema, table, columns, tags, connector id, and project scope. This is what search, semantic joins, SQL grounding, and pipelines use. |
| PostgreSQL staging | Physical tables in the local PostgreSQL `staging` schema. | Used when structured files are uploaded, mapped, and staged. Local SQL preview can execute against these staged tables. |
| Semantic layer | Business definitions such as metrics and approved joins. | Project-scoped. Metrics describe formulas and grains; approved joins link two catalog assets. It can describe external scanned assets or local staged assets. |
| Tools | Governed executable capabilities exposed to agents or external clients. | Internal tools are registry-bound. External query tools are fixed, parameterized, published, granted, audited, and optionally backed by direct drivers or MCP. |

The important rule is this: **a source name or connector does not automatically mean arbitrary SQL can run there.** DataPilot can generate dialect-aware SQL for a selected source, but execution is restricted by the available governed path.

## 2. Source versus staging

A source is the origin system. Examples:

- `Retail Postgres`
- `Retail SQL Server`
- `Oracle CUSTOMER`
- `BigQuery Finance`
- `Local files`
- `Retail Oracle Toolbox` through MCP

Staging is a physical landing area inside DataPilot's local PostgreSQL. In the current implementation, uploaded structured files can be profiled, mapped, and loaded into `staging.<table_name>`.

Example:

```text
Source file: accounts_2026.csv
Mapping: source columns -> target columns
Staged table: staging.accounts_2026
Catalog asset: source_name = Local files, schema_name = staging, table_name = accounts_2026
```

External databases are cataloged through connectors. Their scanned tables become `DataAsset` records, but they are not automatically copied into local staging.

## 3. How source identity is maintained

DataPilot keeps identity at multiple levels:

| Level | Stored identity | Why it matters |
| --- | --- | --- |
| Connector | `id`, `name`, `connector_type`, `connection_mode`, `host`, `database`, `secret_reference` | Defines where a source lives and how DataPilot may connect. |
| Data asset | `connector_id`, `source_name`, `schema_name`, `table_name`, columns, tags | Defines the dataset that catalog search, SQL generation, semantic joins, and pipelines reference. |
| Ingestion mapping | source file id, target schema/table, column mapping, latest relation, run count | Tracks how a local file was loaded into staging. |
| Job/artifact/audit | job id, artifact versions, audit events, execution evidence | Shows what was generated, approved, executed, and reviewed. |
| Lineage edge | source asset/relation -> target relation plus column mapping | Shows generated pipeline lineage. |

Use connector and asset IDs as system identity. Names are human-friendly labels and search metadata; they should not be treated as the only durable identity.

## 4. Is lineage the same from creation to everywhere?

Not exactly. There are two related evidence paths:

1. **Ingestion evidence:** when a file is mapped and staged, DataPilot records the mapping, latest staged relation, job evidence, workflow artifact, and audit event.
2. **Pipeline lineage:** when a pipeline is generated, DataPilot creates explicit `LineageEdge` records from selected source assets to the generated target relation.

So the lineage story is continuous from a user perspective, but implementation differs by workflow:

- File -> staging is tracked through ingestion mapping, job, artifact, catalog asset, and audit.
- Source asset -> generated target view is tracked through `LineageEdge`.
- Arbitrary SQL lineage is not generally parsed and persisted for every ad hoc SQL query.

## 5. SQL generation and execution by target

| Target | Can DataPilot generate SQL? | Can DataPilot execute preview? | Notes |
| --- | --- | --- | --- |
| Local PostgreSQL staging | Yes, PostgreSQL dialect. | Yes, bounded read-only preview. | This is the strongest local path. |
| Scanned external direct connector | Yes, dialect-aware SQL can be generated from catalog context. | Not through general `/sql/execute`; use fixed query tools for execution. | Direct connector query execution exists behind governed query tools. |
| MCP-backed source | Query tools can call named upstream MCP tools. | Not by forwarding arbitrary generated SQL. | Production MCP tools require a named upstream tool. |
| Local query tool with no connector | Fixed SQL template can run against local PostgreSQL. | Yes, with typed parameters and limits. | Useful for reusable local data access. |

The current analyst flow is:

```text
Question -> retrieve catalog/semantic context -> generate one read-only SQL statement -> validate safety -> preview only when it is local PostgreSQL
```

External source execution is intentionally stricter:

```text
Admin creates fixed query tool -> test -> publish -> grant to external client -> client invokes with typed parameters -> DataPilot audits result
```

## 6. Direct connectors versus MCP connectors

DataPilot has two connection modes behind the same governed query-tool contract:

| Mode | How it works | What is allowed |
| --- | --- | --- |
| `direct` | DataPilot uses a native database driver. | Read-only probes, metadata scans, and fixed parameterized query-tool execution. |
| `mcp` | DataPilot connects to an upstream HTTP MCP server. | MCP handshake, `tools/list`, then `tools/call` for a named upstream tool. |

For MCP mode, DataPilot does not send the query tool's SQL template to a generic `execute_sql` endpoint. The query tool must name the upstream MCP tool to call. This keeps external access discoverable, typed, and auditable.

## 7. Semantic layer for source and staging

The semantic layer is project-scoped and works over catalog assets.

Semantic metrics include:

- business name
- description
- formula
- grain
- dimensions
- synonyms
- owner
- status

Semantic joins include:

- left asset id
- right asset id
- left/right columns
- join type
- description
- status

Because both external scanned tables and staged PostgreSQL tables become `DataAsset` records, semantic definitions can refer to either. The difference is execution:

- Semantic context over staged assets can support local SQL preview and local pipeline deployment.
- Semantic context over external assets can support discovery and SQL drafting, but execution must go through governed connector/query-tool paths.

Only approved join policies are used automatically by pipeline generation.

## 8. Can we extract source data to staging and create a pipeline?

For local structured files: yes.

```text
Upload file
Profile file
Confirm source-to-target mapping
Stage rows into PostgreSQL
Create catalog asset
Run quality rules
Generate pipeline/view package
Approve deployment
Persist lineage
Optionally create an approved schedule with watermark
```

For arbitrary external databases: not as a general automatic extraction pipeline in the current local build.

Current external database support is:

- register connector
- test read-only connection
- scan metadata for direct connectors
- create governed fixed query tools
- expose tools through REST/OpenAPI/MCP

General incremental extraction from external databases into local staging is called out as a later connector capability. To add it, the platform would need a connector-runner extraction contract, source watermarks per external table, batch/chunk handling, retry/recovery, schema drift handling, and lineage from external asset to staged target.

## 9. End-to-end flow

### A. Local file to staged data to SQL

```text
User uploads CSV/JSON/Excel/Parquet
DataPilot profiles columns and sample rows
User confirms mapping and target table
DataPilot writes staging.<target_table>
DataPilot creates/updates a DataAsset
Qdrant indexes searchable context
User asks a question
SQL Analyst generates PostgreSQL SQL
Guardrail validates one read-only SELECT/WITH
DataPilot executes bounded preview against PostgreSQL
Conversation, model provenance, cache, and audit are saved
```

### B. Staged data to generated pipeline and lineage

```text
User selects one or more DataAsset records
Pipeline planner checks selected assets and approved semantic joins
Pipeline generator emits PostgreSQL view, dbt, and/or Dataform artifacts
DataPilot stores PipelineDefinition and PipelineVersion
DataPilot records LineageEdge records from source relations to target relation
Deployment requires approval
Approved local PostgreSQL deployment creates/updates the governed target view
```

### C. External database to governed tool

```text
Admin creates connector
DataPilot tests direct driver or MCP handshake
Direct connector can scan metadata into DataAsset records
Admin creates fixed parameterized query tool
DataPilot validates SQL template, parameters, allowed relations, row limit, timeout
Admin tests, publishes, and grants the tool to an external client
Client discovers tool through REST/OpenAPI/MCP
Client invokes with typed parameters only
DataPilot executes direct read-only query or upstream MCP tool call
Invocation result, duration, row count, and audit are saved
```

## 10. How agents use this

Agents do not receive broad database authority. An agent is a versioned instruction set with a model binding and declared tool names.

| Agent | Uses | Boundary |
| --- | --- | --- |
| Planner | Creates a bounded 3-6 step plan. | Draft only. |
| Metadata | Searches catalog, semantic metrics, and lineage. | Read-only project context. |
| SQL Analyst | Drafts dialect-aware read-only SQL. | Preview only through allowed local path or governed tools. |
| Pipeline | Generates pipeline artifacts and lineage. | Deployment requires approval. |
| Quality | Profiles data and checks rules. | Remediation can require approval. |
| Policy | Checks risk, project scope, and approval requirements. | Local policy is authoritative. |
| Troubleshooter | Explains failed jobs and suggests bounded remediation. | Does not perform arbitrary fixes. |

The internal agent loop can run only enabled, published, low-risk built-in tools with typed inputs. Higher-risk actions create or wait for approval.

## 11. Practical decision guide

Use this rule of thumb:

| Need | Use this path |
| --- | --- |
| Analyze uploaded data | Stage it into PostgreSQL, then generate/preview SQL. |
| Reuse a loaded file as governed data | Save mapping, stage with replace/append/upsert, then use DataAsset and quality rules. |
| Build a repeatable local transform | Generate a pipeline from staged DataAsset records and approve view deployment. |
| Describe business definitions | Create semantic metrics and approved joins for the relevant DataAsset records. |
| Let another AI client access data | Publish a fixed query tool and grant it to that client. |
| Query an external database safely | Use a direct connector query tool or MCP-backed named upstream tool. |
| Copy any external database table into staging | Not currently a general feature; requires a future extraction pipeline capability. |

## 12. Key boundaries to remember

- PostgreSQL staging is DataPilot's local physical execution surface.
- A connector/catalog asset can describe an external source without copying its data.
- Generated SQL is not the same as approved execution authority.
- MCP is for named typed tool calls, not unrestricted SQL passthrough.
- Semantic metrics and joins are metadata; they guide generation and pipelines but do not move data by themselves.
- Pipeline lineage is explicit for generated pipelines; ad hoc SQL lineage is not fully parser-backed.
- Approvals, jobs, artifacts, audit events, and governance telemetry are part of the product behavior, not optional UI decoration.

