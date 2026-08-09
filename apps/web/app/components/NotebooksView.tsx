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


export function NotebooksView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [selected, setSelected] = useState<Notebook | null>(null);
  const [busy, setBusy] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [analyticsStatus, setAnalyticsStatus] = useState<{ published: boolean; dashboard_title?: string } | null>(null);
  const [analyticsOpen, setAnalyticsOpen] = useState(false);
  const load = useCallback(() => api<Notebook[]>("/notebooks").then((data) => { setNotebooks(data); setSelected((current) => data.find((item) => item.id === current?.id) || data[0] || null); }), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!selected) { setAnalyticsStatus(null); return; }
    api<{ published: boolean; dashboard_title?: string }>(`/analytics/queries/${selected.id}`)
      .then(setAnalyticsStatus)
      .catch(() => setAnalyticsStatus(null));
  }, [selected?.id]);
  async function createNotebook() {
    setBusy(true);
    try {
      const result = await api<Notebook>("/notebooks", { method: "POST", body: JSON.stringify({ name: `Analysis ${new Date().toLocaleDateString()}`, cells: [{ id: "notes", type: "markdown", source: "# Analysis" }, { id: "query", type: "sql", source: "SELECT 1 AS value" }, { id: "calculation", type: "python", source: "row_count = len(last_rows)\nrow_count" }] }) });
      await load();
      setSelected(result);
      notify("Notebook created");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Notebook could not be created", "error");
    } finally {
      setBusy(false);
    }
  }
  function updateCell(id: string, source: string) { setSelected((current) => current ? { ...current, cells: current.cells.map((cell) => cell.id === id ? { ...cell, source } : cell) } : current); }
  function addCell(type: NotebookCellData["type"]) { setSelected((current) => current ? { ...current, cells: [...current.cells, { id: `cell-${Date.now()}`, type, source: type === "sql" ? "SELECT 1 AS value" : type === "python" ? "sum([1, 2, 3])" : "## Notes" }] } : current); }
  async function save(runAfter = false) {
    if (!selected) return;
    setBusy(true);
    try {
      const saved = await api<{ id: string }>("/notebooks", { method: "POST", body: JSON.stringify({ notebook_id: selected.id, name: selected.name, cells: selected.cells }) });
      if (runAfter) {
        const result = await api<{ status: string; outputs: Notebook["outputs"]; job_id: string }>(`/notebooks/${saved.id}/run`, { method: "POST" });
        notify(`Notebook ${result.status}; trace ${result.job_id.slice(0, 8)}`);
      } else notify("Notebook version saved");
      await load();
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Notebook operation failed", "error"); } finally { setBusy(false); }
  }
  async function remove() {
    if (!selected || !window.confirm(`Delete notebook "${selected.name}" and its version history?`)) return;
    try { await api(`/notebooks/${selected.id}`, { method: "DELETE" }); await load(); notify("Notebook deleted"); }
    catch (reason) { notify(reason instanceof Error ? reason.message : "Notebook could not be deleted", "error"); }
  }
  async function requestSupersetPublication() {
    if (!selected) return;
    setPublishing(true);
    try {
      // Save first so the approval always points at an immutable notebook
      // version, rather than the user's unsaved editor text.
      const saved = await api<{ id: string }>("/notebooks", { method: "POST", body: JSON.stringify({ notebook_id: selected.id, name: selected.name, cells: selected.cells }) });
      const request = await api<{ approval_id: string }>("/analytics/publish-sql", { method: "POST", body: JSON.stringify({ notebook_id: saved.id, name: selected.name }) });
      await load();
      notify(`Notebook SQL publication is awaiting approval (${request.approval_id.slice(0, 8)}); "Open in Superset" appears here once an admin approves it`);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Superset publication could not be requested", "error"); }
    finally { setPublishing(false); }
  }
  return <div className="view-stack"><div className="view-header"><div><h2>Governed notebooks</h2><p>Versioned SQL, notes, safe calculations, outputs, and review history.</p></div><button className="primary-button" onClick={createNotebook} disabled={busy}>{busy ? <RefreshCw size={17} className="spin" /> : <Plus size={17} />}New notebook</button></div><div className="notebook-layout"><section className="surface notebook-list">{notebooks.map((notebook) => <button key={notebook.id} className={selected?.id === notebook.id ? "selected" : ""} onClick={() => setSelected(notebook)}><BookOpen size={17} /><span><strong>{notebook.name}</strong><small>v{notebook.version} / {notebook.status}</small></span><ChevronRight size={16} /></button>)}</section><section className="surface notebook-editor">{selected ? <><div className="section-heading compact"><div><span className="eyebrow">NOTEBOOK</span><input className="notebook-name" value={selected.name} onChange={(event) => setSelected({ ...selected, name: event.target.value })} aria-label="Notebook name" />{selected.job_id && <small className="notebook-run-link">Last run trace: <code>{selected.job_id}</code></small>}</div><div className="row-actions"><button className="icon-button" title="Delete notebook" onClick={remove} disabled={busy}><XCircle size={16} /></button><button className="secondary-button" onClick={() => save(false)} disabled={busy}><Archive size={16} />Save</button>{analyticsStatus?.published ? <button className="secondary-button" onClick={() => setAnalyticsOpen(true)}><LayoutDashboard size={16} />Open in Superset</button> : <button className="secondary-button" onClick={requestSupersetPublication} disabled={busy || publishing} title="Requests admin approval before this notebook's SQL cell becomes a Superset dashboard">{publishing ? <RefreshCw size={16} className="spin" /> : <LayoutDashboard size={16} />}Publish SQL</button>}<button className="primary-button" onClick={() => save(true)} disabled={busy}>{busy ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}Run all</button></div></div><div className="notebook-toolbar"><button onClick={() => addCell("sql")}><Database size={15} />SQL</button><button onClick={() => addCell("python")}><Code2 size={15} />Python</button><button onClick={() => addCell("markdown")}><MessageSquare size={15} />Notes</button></div><div className="notebook-cells">{selected.cells.map((cell, index) => <div className="notebook-cell" key={cell.id}><div><span>{index + 1}</span><StatusPill value={cell.type} /></div><textarea value={cell.source} onChange={(event) => updateCell(cell.id, event.target.value)} rows={cell.type === "markdown" ? 3 : 5} aria-label={`${cell.type} cell ${index + 1}`} />{selected.outputs.find((output) => output.cell_id === cell.id) && <pre>{JSON.stringify(selected.outputs.find((output) => output.cell_id === cell.id), null, 2)}</pre>}</div>)}</div>{analyticsOpen && selected && <PublishedQueryAnalyticsModal artifactId={selected.id} title={analyticsStatus?.dashboard_title || "Notebook query analytics"} onClose={() => setAnalyticsOpen(false)} />}</> : <EmptyState icon={<BookOpen size={24} />} title="No notebook selected" body="Create a notebook to begin a governed local analysis." />}</section></div></div>;
}
