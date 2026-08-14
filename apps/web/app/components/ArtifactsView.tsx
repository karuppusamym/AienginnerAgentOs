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


export function ArtifactsView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [selected, setSelected] = useState<Artifact | null>(null);
  const [versions, setVersions] = useState<ArtifactVersion[]>([]);
  const [comments, setComments] = useState<ArtifactComment[]>([]);
  const [comment, setComment] = useState("");
  const [diff, setDiff] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    api<Artifact[]>("/artifacts").then((data) => {
      setArtifacts(data);
      setSelected(data[0] || null);
    });
  }, []);

  useEffect(() => {
    if (!selected) {
      setVersions([]);
      return;
    }
    Promise.all([api<ArtifactVersion[]>(`/artifacts/${selected.id}/versions`), api<ArtifactComment[]>(`/artifacts/${selected.id}/comments`)]).then(([versionData, commentData]) => { setVersions(versionData); setComments(commentData); setDiff(""); });
  }, [selected]);

  async function comparePrevious() {
    if (!selected || versions.length < 2) return;
    const result = await api<{ diff: string }>(`/artifacts/${selected.id}/diff?from_version=${versions[1].version}&to_version=${versions[0].version}`);
    setDiff(result.diff || "No content changes");
  }
  async function addComment() {
    if (!selected || !comment.trim()) return;
    await api(`/artifacts/${selected.id}/comments`, { method: "POST", body: JSON.stringify({ body: comment, version: versions[0]?.version }) });
    setComment("");
    setComments(await api<ArtifactComment[]>(`/artifacts/${selected.id}/comments`));
    notify("Review comment added");
  }
  async function review(decision: "approved" | "changes_requested") {
    if (!selected) return;
    await api(`/artifacts/${selected.id}/review`, { method: "POST", body: JSON.stringify({ decision }) });
    setArtifacts((current) => current.map((artifact) => artifact.id === selected.id ? { ...artifact, status: decision } : artifact));
    setSelected({ ...selected, status: decision });
    notify(`Artifact ${decision.replaceAll("_", " ")}`);
  }

  return (
    <div className="view-stack">
      <div className="view-header"><div><h2>Artifact repository</h2><p>Versioned SQL, workflows, quality rules, prompts, and runbooks produced in the workspace.</p></div><div className="row-actions"><div className="toolbar-search"><Search size={16} /><input placeholder="Search artifacts..." value={search} onChange={(e) => setSearch(e.target.value)} /></div><StatusPill value={`${artifacts.length} artifacts`} /></div></div>
      {!artifacts.length ? <section className="surface"><EmptyState icon={<Archive size={26} />} title="No saved artifacts" body="Save an approved SQL draft or workflow to create its first durable version." /></section> : (
        <div className="artifact-layout">
          <section className="surface artifact-list">
            <div className="table-header artifact-grid"><span>Artifact</span><span>Type</span><span>Version</span><span>Updated</span></div>
            {artifacts.filter(a => search ? a.name.toLowerCase().includes(search.toLowerCase()) || a.artifact_type.toLowerCase().includes(search.toLowerCase()) : true).map((artifact) => <button key={artifact.id} className={`data-row artifact-grid ${selected?.id === artifact.id ? "selected" : ""}`} onClick={() => setSelected(artifact)}><span><strong>{artifact.name}</strong><small>{artifact.status}</small></span><StatusPill value={artifact.artifact_type} /><span className="mono">v{artifact.latest_version}</span><span>{new Date(artifact.updated_at).toLocaleString()}</span></button>)}
          </section>
          <aside className="surface artifact-detail">
            {selected && versions[0] ? <><div className="section-heading compact"><div><span className="eyebrow">LATEST VERSION</span><h3>{selected.name}</h3></div><StatusPill value={selected.status} /></div><pre><code>{diff || versions[0].content}</code></pre><div className="artifact-review-actions"><button className="secondary-button" disabled={versions.length < 2} onClick={comparePrevious}><GitCompare size={16} />Compare previous</button><button className="secondary-button" onClick={() => review("changes_requested")}><MessageSquare size={16} />Request changes</button><button className="primary-button" onClick={() => review("approved")}><Check size={16} />Approve</button></div><div className="subheading"><h4>Version history</h4><span>{versions.length}</span></div><div className="version-list">{versions.map((version) => <div key={version.id}><span className="version-number">v{version.version}</span><span><strong>{String(version.artifact_metadata.dialect || selected.artifact_type)}</strong><small>{new Date(version.created_at).toLocaleString()}</small></span></div>)}</div><div className="subheading"><h4>Review comments</h4><span>{comments.length}</span></div><div className="comment-composer"><input value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Add review comment" /><button className="icon-button" onClick={addComment} disabled={!comment.trim()} title="Add comment"><Send size={16} /></button></div><div className="comment-list">{comments.map((item) => <div key={item.id}><MessageSquare size={14} /><span><strong>{item.author}</strong><small>{item.body} / {new Date(item.created_at).toLocaleString()}</small></span></div>)}</div></> : <LoadingBlock label="Loading artifact" />}
          </aside>
        </div>
      )}
    </div>
  );
}
