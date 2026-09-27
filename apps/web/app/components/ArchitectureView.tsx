"use client";

import { useState } from "react";
import { Activity, ArrowDown, ArrowRight, Boxes, BrainCircuit, CheckCircle2, Database, FileStack, GitBranch, Layers3, LockKeyhole, Search, Server, ShieldCheck, Workflow } from "lucide-react";

const parts = [
  { id: "web", label: "Web workspace", kind: "Experience", icon: Layers3, tech: "Next.js · React · TypeScript", summary: "The authenticated DataPilot UI: project-aware pages for data work, agents, jobs and governance.", details: "The App Router serves each workspace view inside a shared shell. The shell handles sign-in, role-based navigation, project switching, theme, notifications and shared query state. Browser requests use the same-origin /api path, rewritten to the API service.", files: "apps/web/app · apps/web/next.config.ts" },
  { id: "api", label: "Application API", kind: "Control plane", icon: Server, tech: "FastAPI · SQLAlchemy", summary: "Owns product workflows, authorization, validation and the HTTP API.", details: "Routers expose workspace features; service modules implement SQL generation, connectors, agents, quality, artifacts and more. The API enforces project scope, roles, read-only query guards, approvals and audit records. Alembic manages schema changes.", files: "apps/api/app/main.py · routers/ · services/" },
  { id: "agents", label: "Agents & model routing", kind: "Intelligence", icon: BrainCircuit, tech: "Provider adapters · policy-bounded runs", summary: "Routes questions, builds bounded plans, and invokes approved tools through configured model providers.", details: "Generation and decision models are configured separately. Runs persist a plan and evidence, execute through registered tools, and pause for approval when risk policy requires it. A deterministic local provider and policy fallbacks support offline use.", files: "apps/api/app/model_runtime.py · decision_router.py · services/agents.py" },
  { id: "data", label: "Data & metadata", kind: "Data plane", icon: Database, tech: "PostgreSQL · SQLAlchemy · native connectors", summary: "Stores application metadata and stages governed datasets for downstream workflows.", details: "PostgreSQL is the Compose default; SQLite supports direct local development. Uploaded CSV, JSON, Excel and Parquet files can be profiled and staged into PostgreSQL. Connector adapters scan catalogs and expose bounded, read-only access to external systems.", files: "apps/api/app/database.py · staging.py · connector_runtime.py" },
  { id: "search", label: "Grounding & vector search", kind: "Context", icon: Search, tech: "PostgreSQL search · Qdrant", summary: "Retrieves catalog, file and semantic context to ground analysis and SQL generation.", details: "Hybrid retrieval combines PostgreSQL keyword matching with Qdrant vector search. Retrieved assets, semantic metrics and approved joins are passed into question routing and dialect-aware SQL generation. The vector service is part of the Docker Compose stack.", files: "apps/api/app/grounding.py · vector_store.py" },
  { id: "workflow", label: "Durable jobs", kind: "Execution", icon: Workflow, tech: "Temporal · worker · Redis", summary: "Runs long-lived agent, ingestion and operational workflows with durable state and retry support.", details: "The API starts Temporal workflows; a separate worker executes activities and records job plans, logs, outputs and evidence. Approvals can hold risky actions until a decision resumes execution. Redis supports rate limiting, with an in-process fallback.", files: "apps/api/app/temporal_workflows.py · worker.py" },
  { id: "governance", label: "Governance & artifacts", kind: "Controls", icon: ShieldCheck, tech: "Approvals · audit · versioned records", summary: "Keeps risky actions reviewable and preserves the history of decisions and outputs.", details: "Approval gates protect consequential runs, deployments and publishing. Tool calls and decisions are audited; SQL execution is guarded; artifacts are versioned. Optional telemetry exports sanitized events to configured providers while enforcement stays in the application.", files: "apps/api/app/routers/approvals.py · services/audit.py · services/outputs.py" },
  { id: "analytics", label: "Analytics (optional)", kind: "Serving", icon: Activity, tech: "Apache Superset · guest-token embed", summary: "Embeds governed dashboards in the workspace when the analytics profile is enabled.", details: "Superset is an optional Compose profile. DataPilot brokers short-lived dashboard-scoped guest tokens; approved saved SQL can be published to Superset. The core workspace does not require Superset.", files: "apps/api/app/services/superset.py · infra/superset/" },
  { id: "files", label: "Files & artifacts", kind: "Workspace data", icon: FileStack, tech: "Local staging · versioned outputs", summary: "Connects uploaded source files to queryable tables, notebooks and saved deliverables.", details: "Files are profiled before staging; mappings can be reviewed and loaded with version, append or merge behavior. SQL, notebooks, pipeline definitions and other outputs are stored as versioned artifacts with execution traces.", files: "apps/api/app/staging.py · services/outputs.py" },
  { id: "security", label: "Identity & access", kind: "Trust boundary", icon: LockKeyhole, tech: "Local accounts · roles · project scope", summary: "Applies identity, role and project boundaries across workspace actions.", details: "Local user and role management is the active authentication mode. API permissions are checked per request and project. PingFederate has configuration support, while the full browser SSO handshake remains a deployment-specific integration.", files: "apps/api/app/auth.py · authz.py · roles.py" },
];

export function ArchitectureView() {
  const [selectedId, setSelectedId] = useState("api");
  const selected = parts.find((part) => part.id === selectedId) ?? parts[0];
  const SelectedIcon = selected.icon;
  return (
    <div className="architecture-page">
      <section className="architecture-intro">
        <div><div className="eyebrow"><Boxes size={15} /> PRODUCT MAP</div><h2>How DataPilot fits together</h2><p>A local-first, governed AI data engineering workspace. Select a component to see what is implemented and where it lives in the codebase.</p></div>
        <div className="architecture-stack"><span><CheckCircle2 size={15} /> Core stack</span><strong>Web → API → data, models & workflows</strong><small>Superset runs as an optional analytics profile.</small></div>
      </section>

      <section className="architecture-map" aria-label="DataPilot architecture components">
        <div className="architecture-lane-label"><span>PEOPLE & EXPERIENCE</span><i /></div>
        <button className={`architecture-node featured${selectedId === "web" ? " selected" : ""}`} onClick={() => setSelectedId("web")} aria-pressed={selectedId === "web"}><Layers3 /><span><small>EXPERIENCE</small><strong>Web workspace</strong><em>Next.js · React</em></span><ArrowDown className="node-down" /></button>
        <div className="architecture-flow"><span /><ArrowDown size={15} /><span /></div>
        <div className="architecture-lane-label"><span>APPLICATION & INTELLIGENCE</span><i /></div>
        <div className="architecture-node-row">
          {parts.filter((part) => ["api", "agents", "security", "governance"].includes(part.id)).map((part) => <Node key={part.id} part={part} selected={selectedId === part.id} onClick={() => setSelectedId(part.id)} />)}
        </div>
        <div className="architecture-flow"><span /><ArrowDown size={15} /><span /></div>
        <div className="architecture-lane-label"><span>DATA, EXECUTION & SERVING</span><i /></div>
        <div className="architecture-node-row bottom">
          {parts.filter((part) => ["data", "search", "workflow", "files", "analytics"].includes(part.id)).map((part) => <Node key={part.id} part={part} selected={selectedId === part.id} onClick={() => setSelectedId(part.id)} />)}
        </div>
        <div className="architecture-flow"><span /><ArrowDown size={15} /><span /></div>
        <div className="architecture-external"><GitBranch size={16} /><span>Governed data sources & downstream tools</span><small>PostgreSQL · SQL Server · Oracle · BigQuery · MCP clients</small></div>
      </section>

      <aside className="architecture-detail" aria-live="polite">
        <div className="detail-icon"><SelectedIcon size={20} /></div>
        <div className="detail-content"><div className="detail-heading"><div><span>{selected.kind}</span><h3>{selected.label}</h3></div><code>{selected.tech}</code></div><p>{selected.details}</p><div className="detail-files"><strong>Implementation</strong><code>{selected.files}</code></div></div>
        <div className="detail-summary"><strong>In short</strong><p>{selected.summary}</p></div>
      </aside>
      <p className="architecture-footnote">The diagram reflects the current repository and Compose setup. External credentials and endpoints are needed to exercise live provider and connector integrations.</p>
    </div>
  );
}

function Node({ part, selected, onClick }: { part: typeof parts[number]; selected: boolean; onClick: () => void }) {
  const Icon = part.icon;
  return <button className={`architecture-node${selected ? " selected" : ""}`} onClick={onClick} aria-pressed={selected}><Icon /><span><small>{part.kind.toUpperCase()}</small><strong>{part.label}</strong><em>{part.tech}</em></span><ArrowRight className="node-arrow" /></button>;
}
