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


export function ApprovalsView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [selected, setSelected] = useState<Approval | null>(null);
  const [filter, setFilter] = useState<"pending" | "decided">("pending");
  const [search, setSearch] = useState("");
  const load = useCallback(() => api<Approval[]>("/approvals").then((data) => { setApprovals(data); setSelected((current) => data.find((item) => item.id === current?.id) || data[0] || null); }), []);
  useEffect(() => { load(); }, [load]);
  const filtered = approvals.filter((approval) => (filter === "pending" ? approval.status === "pending" : approval.status !== "pending") && (search ? approval.title.toLowerCase().includes(search.toLowerCase()) || approval.action_type.toLowerCase().includes(search.toLowerCase()) : true));
  async function decide(decision: "approved" | "rejected") {
    if (!selected) return;
    try {
      await api(`/approvals/${selected.id}/decision`, { method: "POST", body: JSON.stringify({ decision, note: decision === "approved" ? "Reviewed in local workspace" : "Returned for revision" }) });
      notify(`Action ${decision}`);
      await load();
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Decision failed", "error"); }
  }
  return (
    <div className="view-stack"><div className="view-header"><div><h2>Approval inbox</h2><p>Review evidence and decide every controlled write, schedule, or external action.</p></div><div className="row-actions"><div className="toolbar-search"><Search size={16} /><input placeholder="Search approvals..." value={search} onChange={(e) => setSearch(e.target.value)} /></div><div className="segmented"><button className={filter === "pending" ? "active" : ""} onClick={() => { setFilter("pending"); setSelected(approvals.find((item) => item.status === "pending") || null); }}>Pending</button><button className={filter === "decided" ? "active" : ""} onClick={() => { setFilter("decided"); setSelected(approvals.find((item) => item.status !== "pending") || null); }}>Decided</button></div></div></div>
      <div className="approval-layout"><section className="surface approval-list">{filtered.map((approval) => <button key={approval.id} className={selected?.id === approval.id ? "selected" : ""} onClick={() => setSelected(approval)}><span className={`risk-mark ${approval.risk_level}`}><ShieldCheck size={18} /></span><span><strong>{approval.title}</strong><small>{approval.action_type.replaceAll("_", " ")} / {new Date(approval.created_at).toLocaleDateString()}</small></span><StatusPill value={approval.status} /><ChevronRight size={16} /></button>)}</section>
        <aside className="surface approval-detail">{selected ? <><div className="section-heading compact"><div><span className="eyebrow">DECISION REQUIRED</span><h3>{selected.title}</h3></div><StatusPill value={selected.risk_level} /></div><div className="evidence-box"><h4>Action summary</h4><p>{selected.evidence.summary || selected.evidence.objective}</p></div><div className="subheading"><h4>Guardrails and checks</h4></div><div className="check-list">{(selected.evidence.checks || selected.evidence.guardrails || []).map((check) => <div key={check}><ShieldCheck size={15} />{check}</div>)}</div><div className="approval-actions"><button className="danger-button" disabled={selected.status !== "pending"} onClick={() => decide("rejected")}><XCircle size={17} />Reject</button><button className="primary-button" disabled={selected.status !== "pending"} onClick={() => decide("approved")}><Check size={17} />Approve action</button></div></> : <EmptyState icon={<ShieldCheck size={24} />} title="No approvals" body="Controlled agent actions will appear here." />}</aside>
      </div>
    </div>
  );
}
