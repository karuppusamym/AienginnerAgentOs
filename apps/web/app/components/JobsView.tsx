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


export function JobsView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selected, setSelected] = useState<Job | null>(null);
  const [filter, setFilter] = useState<"all" | "running" | "action">("all");
  const load = useCallback(() => Promise.all([api<Job[]>("/jobs"), api<Incident[]>("/incidents")]).then(([data, incidentData]) => { setJobs(data); setIncidents(incidentData); setSelected((current) => data.find((item) => item.id === current?.id) || data[0] || null); }), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { const timer = window.setInterval(() => { if (jobs.some((job) => ["RUNNING", "QUEUED", "PLANNING", "RETRYING"].includes(job.status))) load(); }, 2000); return () => window.clearInterval(timer); }, [jobs, load]);
  const filtered = jobs.filter((job) => filter === "all" || (filter === "running" ? ["RUNNING", "QUEUED", "PLANNING"].includes(job.status) : ["WAITING_FOR_APPROVAL", "FAILED"].includes(job.status)));
  async function cancelSelected() {
    if (!selected) return;
    try { await api(`/jobs/${selected.id}/cancel`, { method: "POST" }); notify("Job cancelled"); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Job could not be cancelled", "error"); }
  }
  async function retrySelected() { if (!selected) return; try { const result = await api<{ status: string }>(`/jobs/${selected.id}/retry`, { method: "POST" }); notify(`Retry ${result.status.toLowerCase()}`); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Retry failed", "error"); } }
  async function diagnoseSelected() { if (!selected) return; try { await api(`/jobs/${selected.id}/diagnose`, { method: "POST" }); notify("Incident diagnosis recorded"); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Diagnosis failed", "error"); } }
  return (
    <div className="view-stack">
      <div className="view-header"><div><h2>Job operations</h2><p>Inspect state, progress, evidence, and every specialist handoff.</p></div><div className="segmented"><button className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>All</button><button className={filter === "running" ? "active" : ""} onClick={() => setFilter("running")}>Running</button><button className={filter === "action" ? "active" : ""} onClick={() => setFilter("action")}>Needs action</button></div></div>
      <div className="jobs-layout">
        <section className="surface jobs-table">
          <div className="table-header job-grid"><span>Job</span><span>Status</span><span>Progress</span><span>Created</span></div>
          {filtered.map((job) => (
            <button key={job.id} className={`data-row job-grid ${selected?.id === job.id ? "selected" : ""}`} onClick={() => setSelected(job)}>
              <span><strong>{job.title}</strong><small>{job.job_type.replaceAll("_", " ")}</small></span><StatusPill value={job.status} /><span className="progress-cell"><span><i style={{ width: `${job.progress}%` }} /></span><small>{job.progress}%</small></span><span>{new Date(job.created_at).toLocaleString()}</span>
            </button>
          ))}
        </section>
        <aside className="surface trace-panel">
          {selected ? <><div className="section-heading compact"><div><span className="eyebrow">RUN TRACE</span><h3>{selected.title}</h3></div><StatusPill value={selected.status} /></div>{["DRAFT", "PLANNING", "QUEUED", "RUNNING", "WAITING_FOR_APPROVAL", "RETRYING"].includes(selected.status) && <div className="trace-actions"><button className="danger-button" onClick={cancelSelected}><XCircle size={16} />Cancel job</button></div>}{["FAILED", "CANCELLED", "PARTIALLY_SUCCEEDED"].includes(selected.status) && <div className="trace-actions"><button className="secondary-button" onClick={diagnoseSelected}><AlertCircle size={16} />Diagnose</button><button className="primary-button" onClick={retrySelected}><RefreshCw size={16} />Retry</button></div>}<div className="trace-list">{selected.plan.map((step, index) => <div key={index}><span className={`trace-dot ${step.status}`} /> <span><strong>{step.agent}</strong><small>{step.action}</small></span><StatusPill value={step.status} /></div>)}</div><div className="subheading"><h4>Evidence</h4><span>{selected.evidence.length}</span></div><div className="evidence-list">{selected.evidence.map((item, index) => <span key={index}><Layers3 size={15} />{item.label}</span>)}</div><div className="subheading"><h4>Step outputs</h4><span>{selected.outputs?.length || 0}</span></div>{selected.outputs?.length ? <div className="log-list">{(selected.outputs || []).map((output, index) => <div key={`${output.at || output.title || output.type}-${index}`}><Layers3 size={14} /><span><strong>{output.title || output.type}</strong><small>{[output.agent, output.tool, output.summary, output.at ? new Date(output.at).toLocaleString() : ""].filter(Boolean).join(" / ")}</small>{output.data ? <pre className="trace-output-data">{JSON.stringify(output.data, null, 2)}</pre> : null}</span></div>)}</div> : <div className="inline-empty trace-empty">No step outputs were captured for this run.</div>}<div className="subheading"><h4>Execution log</h4><span>{selected.logs?.length || 0}</span></div><div className="log-list">{(selected.logs || []).map((entry, index) => <div key={`${entry.at}-${index}`}><Clock3 size={14} /><span><strong>{entry.message}</strong><small>{new Date(entry.at).toLocaleString()} / {entry.level}</small></span></div>)}</div>{incidents.filter((incident) => incident.job_id === selected.id).map((incident) => <div className="incident-box" key={incident.id}><div><AlertCircle size={17} /><strong>{incident.title}</strong><StatusPill value={incident.status} /></div><p>{incident.root_cause}</p>{incident.remediation.map((item) => <small key={item}>{item}</small>)}</div>)}</> : <LoadingBlock />}
        </aside>
      </div>
    </div>
  );
}
