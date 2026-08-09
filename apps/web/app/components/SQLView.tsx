import {
  Activity,
  AlertCircle,
  Archive,
  Bot,
  BookOpen,
  Boxes,
  Braces,
  Check,
  ChevronDown,
  ChevronRight,
  CircleGauge,
  Clock3,
  CalendarClock,
  Code2,
  Database,
  FileSpreadsheet,
  FileUp,
  FlaskConical,
  Gauge,
  GitBranch,
  GitCompare,
  KeyRound,
  Layers3,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  Network,
  PanelLeftClose,
  Play,
  Plus,
  RefreshCw,
  Search,
  Send,
  Server,
  Settings,
  ShieldCheck,
  Sparkles,
  UserPlus,
  Users,
  X,
  XCircle,
} from "lucide-react";
import { embedDashboard, EmbeddedDashboard } from "@superset-ui/embedded-sdk";
import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, SessionUser } from "../lib/api";
import type {
  NavKey,
  Overview,
  Recommendation,
  SecurityCategoryKey,
  SecurityOverview,
  Dataset,
  Connector,
  ModelProvider,
  Project,
  AgentVersion,
  AgentDefinition,
  ToolVersion,
  ToolDefinition,
  SemanticMetric,
  SemanticJoinPolicy,
  PipelineDefinition,
  Incident,
  Job,
  Approval,
  IngestedFile,
  MappingColumn,
  LoadMode,
  IngestionMapping,
  QualityRun,
  QualityRule,
  SQLResult,
  SQLExecutionResult,
  SearchResult,
  Artifact,
  ArtifactVersion,
  IngestionSchedule,
  MappingOption,
  ArtifactComment,
  EvaluationSet,
  NotebookCellData,
  Notebook,
  Conversation,
  ConversationMessage,
  ExternalClient,
  QueryTool,
  QueryToolDraft,
  RelationOption,
  QueryToolUsage,
  QueryToolRegistrySummary,
  PromptArtifact,
  RetentionPolicy,
  SchemaDrift,
  ModelUsage,
} from "../types";
import {
  navItems,
  TOUR_STORAGE_KEY,
  defaultTourSteps,
  connectorLabels,
  connectorDialectForType,
  statusTone,
} from "../lib/constants";
import { StatusPill, LoadingBlock, EmptyState, Modal, Metric, ControlItem, AnalysisChart, SecurityOverviewPanel, PublishedQueryAnalyticsModal } from "./shared";


export function SQLView({ notify, seed, currentUser }: { notify: (message: string, tone?: "ok" | "error") => void; seed?: { question: string; dialect: string } | null; currentUser: SessionUser }) {
  const [question, setQuestion] = useState("Show monthly deposit-account growth and explain unusual changes");
  const [dialect, setDialect] = useState("postgres");
  const [connectorId, setConnectorId] = useState("");
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [sqlArtifacts, setSqlArtifacts] = useState<Artifact[]>([]);
  const [result, setResult] = useState<SQLResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [artifactId, setArtifactId] = useState<string | null>(null);
  const [explainOpen, setExplainOpen] = useState(false);
  const [analyticsStatus, setAnalyticsStatus] = useState<{ published: boolean; dashboard_title?: string } | null>(null);
  const [analyticsOpen, setAnalyticsOpen] = useState(false);
  const checkAnalyticsStatus = useCallback((id: string) => {
    api<{ published: boolean; dashboard_title?: string }>(`/analytics/queries/${id}`)
      .then(setAnalyticsStatus)
      .catch(() => setAnalyticsStatus(null));
  }, []);
  useEffect(() => {
    if (artifactId) checkAnalyticsStatus(artifactId);
    else setAnalyticsStatus(null);
  }, [artifactId, checkAnalyticsStatus]);
  const canSaveSql = ["admin", "engineer", "analyst"].includes(currentUser.role);
  const selectedConnector = connectors.find((connector) => connector.id === connectorId);
  const effectiveDialect = selectedConnector ? connectorDialectForType(selectedConnector.connector_type) : dialect;
  const loadSqlHistory = useCallback(() => api<Artifact[]>("/artifacts").then((items) => setSqlArtifacts(items.filter((item) => item.artifact_type === "sql"))), []);
  useEffect(() => {
    Promise.all([api<Connector[]>("/connectors").then(setConnectors), loadSqlHistory()]).catch(() => undefined);
  }, [loadSqlHistory]);
  useEffect(() => {
    if (!seed) return;
    setQuestion(seed.question);
    setDialect(seed.dialect);
    setConnectorId("");
    setResult(null);
    setArtifactId(null);
  }, [seed]);

  async function generate(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      setResult(await api<SQLResult>("/sql/generate", {
        method: "POST",
        body: JSON.stringify({ question, dialect: effectiveDialect, connector_id: connectorId || null }),
      }));
      notify("SQL draft generated and validated");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "SQL generation failed", "error");
    } finally {
      setLoading(false);
    }
  }
  async function runPreview() {
    if (!result) return;
    if (effectiveDialect !== "postgres") {
      notify("Local execution currently supports PostgreSQL; use the matching enterprise connector for this dialect", "error");
      return;
    }
    setExecuting(true);
    try {
      const execution = await api<SQLExecutionResult>("/sql/execute", {
        method: "POST",
        body: JSON.stringify({ sql: result.sql, dialect: "postgres", limit: 500 }),
      });
      setResult({ ...result, preview: execution.rows, execution });
      notify(`Read-only query returned ${execution.row_count} rows`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Query execution failed", "error");
    } finally {
      setExecuting(false);
    }
  }

  async function saveArtifact() {
    if (!result) return;
    setSaving(true);
    try {
      const artifact = await api<{ id: string; version: number }>("/artifacts", {
        method: "POST",
        body: JSON.stringify({
          artifact_id: artifactId,
          name: question.slice(0, 120),
          artifact_type: "sql",
          content: result.sql,
          metadata: { dialect: effectiveDialect, question, connector_id: connectorId || null, validation: result.validation, sources: result.sources },
        }),
      });
      setArtifactId(artifact.id);
      await loadSqlHistory();
      notify(`SQL artifact saved as version ${artifact.version}`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Artifact could not be saved", "error");
    } finally {
      setSaving(false);
    }
  }
  async function sendFeedback(rating: "helpful" | "not_helpful") {
    try { await api("/feedback", { method: "POST", body: JSON.stringify({ context_type: "sql", context_id: artifactId, rating, comment: `${effectiveDialect}: ${question}` }) }); notify(`Feedback recorded as ${rating.replaceAll("_", " ")}`); } catch (reason) { notify(reason instanceof Error ? reason.message : "Feedback could not be recorded", "error"); }
  }
  async function requestSupersetPublication() {
    if (!artifactId) return;
    setPublishing(true);
    try {
      const request = await api<{ approval_id: string }>("/analytics/publish-sql", {
        method: "POST",
        body: JSON.stringify({ artifact_id: artifactId, name: question.slice(0, 120) }),
      });
      notify(`Superset publication is awaiting approval (${request.approval_id.slice(0, 8)}); "Open in Superset" appears here once an admin approves it`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Superset publication could not be requested", "error");
    } finally { setPublishing(false); }
  }
  async function openSqlArtifact(artifact: Artifact) {
    try {
      const versions = await api<ArtifactVersion[]>(`/artifacts/${artifact.id}/versions`);
      const latest = versions[0];
      if (!latest) return;
      setArtifactId(artifact.id);
      setQuestion(String(latest.artifact_metadata.question || artifact.name));
      setDialect(String(latest.artifact_metadata.dialect || "postgres"));
      setConnectorId(String(latest.artifact_metadata.connector_id || ""));
      const validation = latest.artifact_metadata.validation as SQLResult["validation"] | undefined;
      const sources = latest.artifact_metadata.sources as SQLResult["sources"] | undefined;
      setResult({
        sql: latest.content,
        dialect: String(latest.artifact_metadata.dialect || "postgres"),
        explanation: `Saved SQL artifact ${artifact.name}`,
        validation: validation || { status: "saved", read_only: true, row_limit: 500, risk_level: "low", checks: ["Loaded from versioned SQL history"] },
        sources: sources || [],
        preview: [],
        execution: null,
        provider: { id: "artifact", name: "Saved artifact", model: "history", mode: "saved", latency_ms: 0 },
      });
      notify(`Loaded SQL history item v${latest.version}`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "SQL history could not be opened", "error");
    }
  }
  return (
    <div className="view-stack">
      <div className="view-header">
        <div><h2>Grounded SQL workspace</h2><p>Generate dialect-aware, read-only SQL from catalog metadata and approved business terms.</p></div>
        <div className="sql-source-controls">
          <select value={connectorId} onChange={(event) => setConnectorId(event.target.value)} aria-label="SQL source connection"><option value="">Local PostgreSQL catalog</option>{connectors.map((connector) => <option key={connector.id} value={connector.id}>{connector.name} / {connectorLabels[connector.connector_type] || connector.connector_type}</option>)}</select>
          <select value={dialect} onChange={(event) => setDialect(event.target.value)} disabled={Boolean(connectorId)} aria-label="SQL dialect">
            <option value="sqlserver">SQL Server</option><option value="oracle">Oracle</option><option value="teradata">Teradata</option><option value="bigquery">BigQuery</option><option value="postgres">PostgreSQL</option>
          </select>
        </div>
      </div>
      <form className="sql-question surface" onSubmit={generate}>
        <Sparkles size={19} />
        <input value={question} onChange={(event) => setQuestion(event.target.value)} aria-label="Business question" />
        <button className="primary-button" disabled={loading}>{loading ? <RefreshCw size={17} className="spin" /> : <Play size={17} />}Generate</button>
      </form>
      {!result ? (
        <EmptyState icon={<Code2 size={26} />} title="Ready for a business question" body="The agent will show its SQL, evidence, validation checks, and a limited preview before anything can be saved." />
      ) : (
        <div className="sql-layout">
          <section className="surface code-panel">
            <div className="panel-toolbar"><span><Code2 size={16} />{result.dialect} | {selectedConnector?.name || result.provider.name}</span><StatusPill value={result.validation.status} /></div>
            <pre><code>{result.sql}</code></pre>
            <div className="code-actions"><button className="icon-button" onClick={() => sendFeedback("helpful")} title="Helpful result"><Check size={16} /></button><button className="icon-button" onClick={() => sendFeedback("not_helpful")} title="Result needs improvement"><XCircle size={16} /></button><button className="secondary-button" onClick={() => setExplainOpen(true)}><Layers3 size={16} />Why this result?</button><button className="secondary-button" onClick={saveArtifact} disabled={saving || !canSaveSql}>{saving ? <RefreshCw size={16} className="spin" /> : <Archive size={16} />}Save artifact</button>{analyticsStatus?.published ? <button className="secondary-button" onClick={() => setAnalyticsOpen(true)}><LayoutDashboard size={16} />Open in Superset</button> : <button className="secondary-button" onClick={requestSupersetPublication} disabled={!artifactId || publishing} title={!artifactId ? "Save this SQL as an artifact first" : "Requests admin approval before this query becomes a Superset dashboard"}>{publishing ? <RefreshCw size={16} className="spin" /> : <LayoutDashboard size={16} />}Publish to Superset</button>}<button className="primary-button" onClick={runPreview} disabled={executing}>{executing ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}Run read-only preview</button></div>
          </section>
          <aside className="surface validation-panel">
            <div className="section-heading compact"><div><span className="eyebrow">EVIDENCE</span><h3>Validation</h3></div><StatusPill value={result.validation.risk_level} /></div>
            <p>{result.explanation}</p>
            {result.cache?.hit ? <div className="conversation-memory compact-memory"><span>Reuse</span><p>Reused a saved governed query for the same normalized question and source context.</p></div> : null}
            <div className="check-list">{result.validation.checks.map((check) => <div key={check}><Check size={15} />{check}</div>)}</div>
            <div className="subheading"><h4>Sources used</h4><span>{result.sources.length}</span></div>
            {result.sources.map((source, index) => <div className="source-row" key={index}><Database size={15} /><span><strong>{source.asset || source.term}</strong><small>{source.columns?.join(", ") || source.definition}</small></span></div>)}
            {result.grounding?.catalog_matches?.length ? <><div className="subheading"><h4>Catalog grounding</h4><span>{result.grounding.catalog_matches.length}</span></div>{result.grounding.catalog_matches.slice(0, 4).map((item) => <div className="source-row" key={`${item.relation}-${item.match_type}`}><Layers3 size={15} /><span><strong>{item.relation}</strong><small>{item.match_type} match / score {item.score}</small></span></div>)}</> : null}
            {result.grounding?.semantic_matches?.length ? <><div className="subheading"><h4>Semantic terms</h4><span>{result.grounding.semantic_matches.length}</span></div>{result.grounding.semantic_matches.slice(0, 3).map((item) => <div className="source-row" key={item.name}><Braces size={15} /><span><strong>{item.name}</strong><small>{item.formula} / {item.grain}</small></span></div>)}</> : null}
          </aside>
          <section className="surface preview-panel">
            <div className="section-heading compact"><div><span className="eyebrow">LIMITED PREVIEW</span><h3>Query result</h3></div><span className="caption">Maximum {result.validation.row_limit} rows</span></div>
            {result.preview.length ? <div className="data-table-wrap">
              <table><thead><tr>{Object.keys(result.preview[0] || {}).map((key) => <th key={key}>{key.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{result.preview.map((row, index) => <tr key={index}>{Object.values(row).map((value, valueIndex) => <td key={valueIndex}>{typeof value === "number" ? value.toLocaleString() : value}</td>)}</tr>)}</tbody></table>
            </div> : <div className="inline-empty">No local preview is available for this dialect.</div>}
          </section>
        </div>
      )}
      <section className="surface sql-history-surface">
        <div className="section-heading compact"><div><span className="eyebrow">SQL HISTORY</span><h3>Saved SQL artifacts</h3></div><StatusPill value={`${sqlArtifacts.length} saved`} /></div>
        {sqlArtifacts.length ? <div className="sql-history-list">{sqlArtifacts.slice(0, 8).map((artifact) => <button key={artifact.id} onClick={() => openSqlArtifact(artifact)}><Archive size={16} /><span><strong>{artifact.name}</strong><small>{String(artifact.metadata?.dialect || artifact.artifact_type)} / v{artifact.latest_version} / {new Date(artifact.updated_at).toLocaleString()}</small></span><ChevronRight size={16} /></button>)}</div> : <div className="inline-empty">Saved SQL from this project appears here. Conversation SQL stays inside each analysis thread until it is saved as a report or artifact.</div>}
      </section>
      {analyticsOpen && artifactId && <PublishedQueryAnalyticsModal artifactId={artifactId} title={analyticsStatus?.dashboard_title || "Query analytics"} onClose={() => setAnalyticsOpen(false)} />}
      {explainOpen && result && <Modal title="Why this result?" onClose={() => setExplainOpen(false)}><div className="modal-form"><p>{result.explanation}</p><div className="subheading"><h4>Source and model</h4></div><div className="check-list"><div><Database size={15} />{result.source?.name || selectedConnector?.name || "DataPilot local workspace"} / {result.dialect}</div><div><Bot size={15} />{result.provider.name} / {result.provider.model} ({result.provider.mode})</div><div><CircleGauge size={15} />Validation: {result.validation.status}; risk: {result.validation.risk_level}; row limit: {result.validation.row_limit}</div></div><div className="subheading"><h4>Grounding evidence</h4></div>{result.grounding?.catalog_matches?.slice(0, 5).map((item) => <div className="source-row" key={`${item.relation}-${item.match_type}`}><Layers3 size={15} /><span><strong>{item.relation}</strong><small>{item.match_type} catalog match / score {item.score}</small></span></div>)}{result.grounding?.semantic_matches?.slice(0, 5).map((item) => <div className="source-row" key={item.name}><Braces size={15} /><span><strong>{item.name}</strong><small>{item.formula} at {item.grain}</small></span></div>)}{result.grounding?.join_matches?.slice(0, 5).map((item) => <div className="source-row" key={`${item.left_relation}-${item.right_relation}`}><Network size={15} /><span><strong>{item.left_relation} {item.join_type} {item.right_relation}</strong><small>{item.left_column} = {item.right_column}</small></span></div>)}<div className="subheading"><h4>Safety checks</h4></div><div className="check-list">{result.validation.checks.map((check) => <div key={check}><Check size={15} />{check}</div>)}</div></div></Modal>}
    </div>
  );
}
