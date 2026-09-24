# DataPilot documentation

Use these documents in this order:

1. [System specification](DATAPILOT_SYSTEM_SPEC.md) - authoritative product scope, architecture, diagrams, workflows, agents, tools, governance, deployment, and delivery status.
2. [Implementation status matrix](IMPLEMENTATION_STATUS_MATRIX.md) - completed / partial / not-completed checklist, reconciled directly against the code, kept current as gaps are found and fixed.
3. [Per-domain specs](specs/README.md) - one short, focused page per backend domain (auth, connectors, files, sql, agents, query tools, etc.) with its endpoints, models, and status - read the one page relevant to what you're doing instead of the whole system spec.
4. [Architecture decisions](ARCHITECTURE_DECISIONS.md) - graph database / lineage-traversal recommendation, the agentic harness and self-learning approach, and UI-accessibility direction.
   - [Architecture review, 2026-09](ARCHITECTURE_REVIEW_2026-09.md) - devil's-advocate review: open security/reliability findings, the decision router (Jev/GEPA), Frictionless Data Package interchange, and the 3-panel chat redesign.
5. [Data connections, lineage, semantic layer, agents, and tools](DATA_CONNECTIONS_LINEAGE_AND_TOOLS_GUIDE.md) - plain-language explanation of source vs staging, SQL generation, MCP, semantic definitions, extraction limits, pipeline creation, and lineage.
6. [Enterprise readiness and agent capability assessment](ENTERPRISE_READINESS_AND_AGENT_CAPABILITY_ASSESSMENT.md) - implementation-grounded assessment of enterprise readiness, memory, self-learning, agent harnessing, registry adoption, and usability improvements.
7. [Database MCP and external tool registry](DATABASE_MCP_TOOL_REGISTRY_GUIDE.md) - connector modes and exact external-agent configuration.
8. [SQL Server Express demo](SQLSERVER_EXPRESS_DEMO.md) - local orders/payments databases and direct/MCP connector setup.
8. [AgentGuard governance integration](AgentGuard_Governance_Integration_Guide.docx) - detailed telemetry operating guide.
9. [Kubernetes baseline](../infra/kubernetes/README.md) - production deployment prerequisites.

Historical planning, audit, traceability, and status documents were consolidated into the system specification to prevent competing sources of truth. The per-domain specs are generated from the same source of truth (the router code) and the status matrix, not maintained separately, to avoid the two drifting apart.
