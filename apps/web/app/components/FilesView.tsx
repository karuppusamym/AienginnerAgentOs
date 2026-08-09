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
import { StatusPill, LoadingBlock, EmptyState, Modal, Metric, ControlItem, AnalysisChart, SecurityOverviewPanel } from "./shared";


export function FilesView({ notify, currentUser }: { notify: (message: string, tone?: "ok" | "error") => void; currentUser: SessionUser }) {
  const [files, setFiles] = useState<IngestedFile[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [selected, setSelected] = useState<IngestedFile | null>(null);
  const [uploading, setUploading] = useState(false);
  const [staging, setStaging] = useState(false);
  const [showConnector, setShowConnector] = useState(false);
  const [editingConnector, setEditingConnector] = useState<Connector | null>(null);
  const emptyConnectorForm = { name: "", connector_type: "sql_server", description: "", host: "", database: "", secret_reference: "env:SQLSERVER_CREDENTIALS" };
  const [connectorForm, setConnectorForm] = useState(emptyConnectorForm);
  const [targetTable, setTargetTable] = useState("");
  const [mappingColumns, setMappingColumns] = useState<MappingColumn[]>([]);
  const [loadMode, setLoadMode] = useState<LoadMode>("versioned");
  const [keyColumn, setKeyColumn] = useState("");
  const canManageConnections = ["admin", "engineer"].includes(currentUser.role);
  const connectorTypeHelp: Record<string, string> = {
    postgres: "PostgreSQL read-only metadata and parameterized query access.",
    sql_server: "SQL Server read-only metadata and parameterized query access.",
    oracle: "Oracle read-only metadata and parameterized query access.",
    teradata: "Teradata read-only metadata and parameterized query access.",
    bigquery: "BigQuery dataset metadata and read-only query access.",
    local_files: "Local file source registered for catalog context.",
  };
  const load = useCallback(() => Promise.all([api<IngestedFile[]>("/files"), api<Connector[]>("/connectors")]).then(([fileData, connectorData]) => { setFiles(fileData); setConnectors(connectorData); }), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!selected || selected.profile.kind !== "structured") {
      setMappingColumns([]);
      setTargetTable("");
      setLoadMode("versioned");
      setKeyColumn("");
      return;
    }
    const confirmed = selected.profile.confirmed_mapping;
    setMappingColumns(confirmed?.columns || (selected.profile.columns || []).map((column) => ({
      source_name: column.name,
      target_name: column.name.toLowerCase().replace(/[^a-z0-9_]+/g, "_"),
      target_type: column.inferred_type as MappingColumn["target_type"],
      nullable: column.null_count > 0,
    })));
    setTargetTable(confirmed?.target_table || selected.filename.replace(/\.[^.]+$/, "").toLowerCase().replace(/[^a-z0-9_]+/g, "_"));
    setLoadMode(confirmed?.load_mode || "versioned");
    setKeyColumn(confirmed?.key_columns?.[0] || "");
  }, [selected]);

  async function uploadFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    const data = new FormData();
    data.append("file", file);
    data.append("stage_to_postgres", "false");
    try {
      const item = await api<IngestedFile>("/files/ingest", { method: "POST", body: data });
      setSelected(item);
      await load();
      notify(`${file.name} profiled and ready for schema confirmation`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "File ingestion failed", "error");
    } finally {
      setUploading(false);
      event.target.value = "";
    }
  }

  function updateMapping(index: number, patch: Partial<MappingColumn>) {
    setMappingColumns((current) => current.map((column, columnIndex) => columnIndex === index ? { ...column, ...patch } : column));
  }

  function openConnector(connector?: Connector) {
    setEditingConnector(connector || null);
    setConnectorForm(connector ? {
      name: connector.name,
      connector_type: connector.connector_type,
      description: connector.description || "",
      host: connector.host || "",
      database: connector.database || "",
      secret_reference: connector.secret_reference || "",
    } : emptyConnectorForm);
    setShowConnector(true);
  }

  async function saveConnector(event: FormEvent) {
    event.preventDefault();
    try {
      const payload = { ...connectorForm, read_only: true };
      await api(editingConnector ? `/connectors/${editingConnector.id}` : "/connectors", {
        method: editingConnector ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      setShowConnector(false);
      setEditingConnector(null);
      await load();
      notify(editingConnector ? "Connection updated" : "Connection added");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Connection could not be saved", "error");
    }
  }

  async function testConnector(id: string) {
    try {
      const result = await api<{ message: string }>(`/connectors/${id}/test`, { method: "POST" });
      await load();
      notify(result.message);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Connection test failed", "error");
    }
  }

  async function scanConnector(id: string) {
    try {
      const result = await api<{ status: string; assets_discovered?: number }>(`/connectors/${id}/scan`, { method: "POST" });
      await load();
      notify(result.status === "QUEUED" ? "Metadata scan queued" : `Metadata scan completed: ${result.assets_discovered || 0} assets`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Metadata scan failed", "error");
    }
  }

  async function deleteConnector(id: string) {
    try {
      await api(`/connectors/${id}`, { method: "DELETE" });
      await load();
      notify("Connection deleted");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Connection could not be deleted", "error");
    }
  }

  async function saveAndStage() {
    if (!selected || !targetTable.trim() || !mappingColumns.length) return;
    setStaging(true);
    try {
      const mapping = await api<IngestionMapping>(`/files/${selected.id}/schema`, {
        method: "POST",
        body: JSON.stringify({
          mapping_id: selected.profile.confirmed_mapping?.id,
          name: `${selected.filename} staging mapping`,
          target_table: targetTable,
          columns: mappingColumns,
        }),
      });
      const staged = await api<IngestedFile & { mapping: IngestionMapping; job_id: string }>(`/files/${selected.id}/stage`, {
        method: "POST",
        body: JSON.stringify({ mapping_id: mapping.id, load_mode: loadMode, key_columns: loadMode === "upsert" ? [keyColumn] : [] }),
      });
      setSelected(staged);
      await load();
      notify(`${staged.profile.staged_table?.loaded_rows || 0} rows loaded to ${staged.profile.staged_table?.relation}`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Mapped staging failed", "error");
    } finally {
      setStaging(false);
    }
  }

  return (
    <div className="view-stack">
      <div className="view-header">
        <div><h2>Local file ingestion</h2><p>Profile files before staging them as governed local datasets.</p></div>
        <label className="primary-button file-button">
          {uploading ? <RefreshCw size={17} className="spin" /> : <FileUp size={17} />}
          {uploading ? "Profiling" : "Upload file"}
          <input type="file" accept=".csv,.json,.xlsx,.parquet,.pdf" onChange={uploadFile} disabled={uploading} />
        </label>
      </div>
      <section className="surface connection-surface">
        <div className="section-heading compact">
          <div><span className="eyebrow">CONNECTIONS</span><h3>Registered data sources</h3></div>
          {canManageConnections && <button className="primary-button" onClick={() => openConnector()}><Plus size={17} />Add connection</button>}
        </div>
        {connectors.length ? (
          <div className="connection-list">
            {connectors.map((connector) => (
              <div className="connection-row" key={connector.id}>
                <span className="connection-icon"><Database size={17} /></span>
                <span><strong>{connector.name}</strong><small>{connectorLabels[connector.connector_type] || connector.connector_type} / {connector.database || connector.host || "not configured"}</small>{connector.description && <small>{connector.description}</small>}</span>
                <StatusPill value={connector.status} />
                {canManageConnections && <span className="row-actions"><button className="icon-button" title="Test connection" onClick={() => testConnector(connector.id)}><Gauge size={16} /></button><button className="icon-button" title="Scan metadata" onClick={() => scanConnector(connector.id)}><RefreshCw size={16} /></button><button className="icon-button" title="Edit connection" onClick={() => openConnector(connector)}><Settings size={16} /></button><button className="icon-button" title="Delete connection" onClick={() => deleteConnector(connector.id)}><XCircle size={16} /></button></span>}
              </div>
            ))}
          </div>
        ) : (
          <div className="inline-empty">No external connections are registered for this project.</div>
        )}
      </section>
      <div className="two-column file-columns">
        <section className="surface">
          <div className="section-heading compact"><div><span className="eyebrow">INGESTED FILES</span><h3>Recent uploads</h3></div></div>
          {files.length === 0 ? (
            <EmptyState icon={<FileSpreadsheet size={24} />} title="No local files yet" body="Upload CSV, Excel, Parquet, JSON, or PDF to create a profile." />
          ) : (
            <div className="file-list">
              {files.map((file) => (
                <button key={file.id} className={selected?.id === file.id ? "selected" : ""} onClick={() => setSelected(file)}>
                  <span className="file-type">{file.filename.split(".").pop()?.toUpperCase()}</span>
                  <span><strong>{file.filename}</strong><small>{(file.size_bytes / 1024).toFixed(1)} KB / {file.row_count ?? "document"} {file.row_count ? "rows" : ""}</small></span>
                  <StatusPill value={file.status} />
                  <ChevronRight size={16} />
                </button>
              ))}
            </div>
          )}
        </section>
        <section className="surface profile-panel">
          {selected ? (
            <>
              <div className="section-heading compact"><div><span className="eyebrow">PROFILE</span><h3>{selected.filename}</h3></div><StatusPill value={selected.status} /></div>
              {selected.profile.kind === "structured" ? (
                <>
                  <div className="detail-stats"><div><span>Rows</span><strong>{selected.profile.row_count?.toLocaleString()}</strong></div><div><span>Columns</span><strong>{selected.profile.column_count}</strong></div><div><span>Stage</span><strong>PostgreSQL</strong></div></div>
                  {selected.profile.staged_table && (
                    <div className="staging-relation"><Database size={17} /><span><small>Physical relation</small><strong>{selected.profile.staged_table.relation}</strong></span><StatusPill value="queryable" /></div>
                  )}
                  <div className="mapping-target">
                    <label>Target table<input value={targetTable} onChange={(event) => setTargetTable(event.target.value)} /></label>
                    <span><small>Workflow runs</small><strong>{selected.profile.confirmed_mapping ? "versioned" : "draft"}</strong></span>
                  </div>
                  <div className="ingestion-controls">
                    <div className="segmented" aria-label="Load mode">
                      {(["versioned", "replace", "append", "upsert"] as LoadMode[]).map((mode) => <button type="button" className={loadMode === mode ? "active" : ""} key={mode} onClick={() => setLoadMode(mode)}>{mode === "upsert" ? "Merge" : mode === "replace" ? "Replace" : mode === "append" ? "Append" : "Versioned"}</button>)}
                    </div>
                    {loadMode === "upsert" && <label>Merge key<select value={keyColumn} onChange={(event) => setKeyColumn(event.target.value)} required><option value="">Select column</option>{mappingColumns.map((column) => <option value={column.target_name} key={column.source_name}>{column.target_name}</option>)}</select></label>}
                  </div>
                  <div className="subheading"><h4>Schema mapping</h4><span>{mappingColumns.length} fields</span></div>
                  <div className="mapping-grid mapping-header"><span>Source</span><span>Target</span><span>Type</span><span>Nullable</span></div>
                  <div className="mapping-list">
                    {mappingColumns.map((column, index) => (
                      <div className="mapping-grid" key={column.source_name}>
                        <strong>{column.source_name}</strong>
                        <input value={column.target_name} onChange={(event) => updateMapping(index, { target_name: event.target.value })} aria-label={`Target name for ${column.source_name}`} />
                        <select value={column.target_type} onChange={(event) => updateMapping(index, { target_type: event.target.value as MappingColumn["target_type"] })} aria-label={`Target type for ${column.source_name}`}><option value="string">string</option><option value="integer">integer</option><option value="number">number</option><option value="boolean">boolean</option></select>
                        <input type="checkbox" checked={column.nullable} onChange={(event) => updateMapping(index, { nullable: event.target.checked })} aria-label={`${column.source_name} nullable`} />
                      </div>
                    ))}
                  </div>
                  <div className="mapping-actions"><button className="primary-button" onClick={saveAndStage} disabled={staging || !targetTable.trim() || (loadMode === "upsert" && !keyColumn)}>{staging ? <RefreshCw size={17} className="spin" /> : <Database size={17} />}{staging ? "Staging" : selected.profile.staged_table ? "Run mapping again" : "Confirm and stage"}</button></div>
                </>
              ) : (
                <div className="document-preview"><pre>{selected.profile.preview || "Metadata indexed."}</pre></div>
              )}
            </>
          ) : (
            <EmptyState icon={<CircleGauge size={24} />} title="Select a file profile" body="Schema, null counts, distinct values, and a safe sample appear here." />
          )}
        </section>
      </div>
      {showConnector && <Modal title={editingConnector ? "Edit connection" : "Add connection"} onClose={() => setShowConnector(false)}><form className="modal-form" onSubmit={saveConnector}><div className="form-grid"><label>Name<input value={connectorForm.name} onChange={(event) => setConnectorForm({ ...connectorForm, name: event.target.value })} required /></label><label>Connection type<select value={connectorForm.connector_type} onChange={(event) => setConnectorForm({ ...connectorForm, connector_type: event.target.value })}><option value="postgres">PostgreSQL</option><option value="sql_server">SQL Server</option><option value="oracle">Oracle</option><option value="teradata">Teradata</option><option value="bigquery">BigQuery</option><option value="local_files">Local files</option></select></label></div><div className="connector-type-note"><ShieldCheck size={16} />{connectorTypeHelp[connectorForm.connector_type]}</div><label>Description<textarea value={connectorForm.description} onChange={(event) => setConnectorForm({ ...connectorForm, description: event.target.value })} rows={3} placeholder="Business owner, domain, allowed use, and data sensitivity." /></label><div className="form-grid"><label>Host / project<input value={connectorForm.host} onChange={(event) => setConnectorForm({ ...connectorForm, host: event.target.value })} /></label><label>Database / dataset<input value={connectorForm.database} onChange={(event) => setConnectorForm({ ...connectorForm, database: event.target.value })} /></label></div><label>Secret reference<input value={connectorForm.secret_reference} onChange={(event) => setConnectorForm({ ...connectorForm, secret_reference: event.target.value })} placeholder="env:POSTGRES_CREDENTIALS" /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowConnector(false)}>Cancel</button><button className="primary-button"><Check size={17} />{editingConnector ? "Save connection" : "Add connection"}</button></div></form></Modal>}
    </div>
  );
}
