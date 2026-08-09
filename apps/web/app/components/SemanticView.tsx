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


export function SemanticView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [metrics, setMetrics] = useState<SemanticMetric[]>([]);
  const [editing, setEditing] = useState<SemanticMetric | null>(null);
  const [showForm, setShowForm] = useState(false);
  const emptyForm = { name: "", description: "", formula: "", grain: "", owner: "", dimensions: "", synonyms: "", status: "draft" };
  const [form, setForm] = useState(emptyForm);
  const load = useCallback(() => api<SemanticMetric[]>("/semantic/metrics").then(setMetrics), []);
  useEffect(() => { load().catch((reason) => notify(reason instanceof Error ? reason.message : "Semantic metrics unavailable", "error")); }, [load, notify]);
  function openMetric(metric?: SemanticMetric) { setEditing(metric || null); setForm(metric ? { name: metric.name, description: metric.description || "", formula: metric.formula, grain: metric.grain, owner: metric.owner, dimensions: metric.dimensions.join(", "), synonyms: metric.synonyms.join(", "), status: metric.status } : emptyForm); setShowForm(true); }
  async function save(event: FormEvent) { event.preventDefault(); const payload = { ...form, dimensions: form.dimensions.split(",").map((item) => item.trim()).filter(Boolean), synonyms: form.synonyms.split(",").map((item) => item.trim()).filter(Boolean) }; try { await api(editing ? `/semantic/metrics/${editing.id}` : "/semantic/metrics", { method: editing ? "PUT" : "POST", body: JSON.stringify(payload) }); setShowForm(false); await load(); notify(editing ? "Metric updated" : "Metric created"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Metric could not be saved", "error"); } }
  async function remove(metric: SemanticMetric) { try { await api(`/semantic/metrics/${metric.id}`, { method: "DELETE" }); await load(); notify("Metric removed"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Metric could not be removed", "error"); } }
  return (
    <div className="view-stack"><div className="view-header"><div><h2>Semantic layer</h2><p>Approved metrics, joins, synonyms, and business definitions used to ground every agent response.</p></div><button className="primary-button" onClick={() => openMetric()}><Plus size={17} />Add metric</button></div>
      <div className="semantic-layout"><section className="surface"><div className="section-heading compact"><div><span className="eyebrow">PROJECT METRICS</span><h3>Business calculations</h3></div></div>{metrics.map((metric) => <div className="metric-definition" key={metric.id}><span className="semantic-icon"><Braces size={18} /></span><button className="metric-main" onClick={() => openMetric(metric)}><strong>{metric.name}</strong><small>{metric.formula}</small></button><span><small>Grain</small><strong>{metric.grain}</strong></span><span><small>Owner</small><strong>{metric.owner}</strong></span><span className="row-actions"><StatusPill value={metric.status} /><button className="icon-button" title="Delete metric" onClick={() => remove(metric)}><XCircle size={16} /></button></span></div>)}</section>
        <JoinPoliciesPanel notify={notify} />
      </div>
      {showForm && <Modal title={editing ? "Edit metric" : "Add metric"} onClose={() => setShowForm(false)}><form className="modal-form" onSubmit={save}><label>Name<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label><label>Description<input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label><label>Formula<textarea value={form.formula} onChange={(event) => setForm({ ...form, formula: event.target.value })} rows={3} required /></label><div className="form-grid"><label>Grain<input value={form.grain} onChange={(event) => setForm({ ...form, grain: event.target.value })} required /></label><label>Owner<input value={form.owner} onChange={(event) => setForm({ ...form, owner: event.target.value })} required /></label></div><div className="form-grid"><label>Dimensions<input value={form.dimensions} onChange={(event) => setForm({ ...form, dimensions: event.target.value })} placeholder="status, segment" /></label><label>Synonyms<input value={form.synonyms} onChange={(event) => setForm({ ...form, synonyms: event.target.value })} /></label></div><label>Status<select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}><option value="draft">Draft</option><option value="approved">Approved</option><option value="deprecated">Deprecated</option></select></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary-button"><Check size={17} />Save metric</button></div></form></Modal>}
    </div>
  );
}

export function JoinPoliciesPanel({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const emptyForm = { left_asset_id: "", right_asset_id: "", left_column: "", right_column: "", join_type: "inner" as "inner" | "left", description: "", status: "draft" };
  const [policies, setPolicies] = useState<SemanticJoinPolicy[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [editing, setEditing] = useState<SemanticJoinPolicy | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const load = useCallback(async () => { const [policyData, datasetData] = await Promise.all([api<SemanticJoinPolicy[]>("/semantic/joins"), api<Dataset[]>("/datasets")]); setPolicies(policyData); setDatasets(datasetData); }, []);
  useEffect(() => { load().catch((reason) => notify(reason instanceof Error ? reason.message : "Join policies unavailable", "error")); }, [load, notify]);
  const leftAsset = datasets.find((item) => item.id === form.left_asset_id);
  const rightAsset = datasets.find((item) => item.id === form.right_asset_id);
  const relation = (id: string) => { const asset = datasets.find((item) => item.id === id); return asset ? `${asset.schema_name}.${asset.table_name}` : "Dataset unavailable"; };
  function openPolicy(policy?: SemanticJoinPolicy) { const left = policy ? datasets.find((item) => item.id === policy.left_asset_id) : datasets[0]; const right = policy ? datasets.find((item) => item.id === policy.right_asset_id) : datasets.find((item) => item.id !== left?.id); setEditing(policy || null); setForm(policy ? { left_asset_id: policy.left_asset_id, right_asset_id: policy.right_asset_id, left_column: policy.left_column, right_column: policy.right_column, join_type: policy.join_type, description: policy.description || "", status: policy.status } : { ...emptyForm, left_asset_id: left?.id || "", right_asset_id: right?.id || "", left_column: left?.columns[0]?.name || "", right_column: right?.columns[0]?.name || "" }); setShowForm(true); }
  async function save(event: FormEvent) { event.preventDefault(); try { await api(editing ? `/semantic/joins/${editing.id}` : "/semantic/joins", { method: editing ? "PUT" : "POST", body: JSON.stringify(form) }); setShowForm(false); await load(); notify(editing ? "Join policy updated" : "Join policy created"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Join policy could not be saved", "error"); } }
  async function remove(policy: SemanticJoinPolicy) { try { await api(`/semantic/joins/${policy.id}`, { method: "DELETE" }); await load(); notify("Join policy removed"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Join policy could not be removed", "error"); } }
  return <aside className="surface"><div className="section-heading compact"><div><span className="eyebrow">JOIN POLICY</span><h3>Approved paths</h3></div><button className="icon-button" title="Add join policy" onClick={() => openPolicy()} disabled={datasets.length < 2}><Plus size={16} /></button></div>{policies.length ? <div className="check-list">{policies.map((policy) => <div key={policy.id}><button className="metric-main" onClick={() => openPolicy(policy)}><strong>{relation(policy.left_asset_id)} {policy.join_type.toUpperCase()} {relation(policy.right_asset_id)}</strong><small>{policy.left_column} = {policy.right_column}{policy.description ? ` · ${policy.description}` : ""}</small></button><StatusPill value={policy.status} /><button className="icon-button" title="Delete join policy" onClick={() => remove(policy)}><XCircle size={15} /></button></div>)}</div> : <div className="empty-state"><Network size={18} /><p>No governed join paths yet.</p><small>Approved policies take precedence over inferred identifiers in pipeline generation.</small></div>}<div className="check-list"><div><ShieldCheck size={15} />Only approved policies are used automatically.</div></div>{showForm && <Modal title={editing ? "Edit join policy" : "Add join policy"} onClose={() => setShowForm(false)}><form className="modal-form" onSubmit={save}><div className="form-grid"><label>Left dataset<select value={form.left_asset_id} onChange={(event) => { const asset = datasets.find((item) => item.id === event.target.value); const right = form.right_asset_id === asset?.id ? datasets.find((item) => item.id !== asset?.id) : undefined; setForm({ ...form, left_asset_id: event.target.value, left_column: asset?.columns[0]?.name || "", right_asset_id: right?.id || form.right_asset_id, right_column: right?.columns[0]?.name || form.right_column }); }} required>{datasets.map((asset) => <option key={asset.id} value={asset.id}>{asset.schema_name}.{asset.table_name}</option>)}</select></label><label>Right dataset<select value={form.right_asset_id} onChange={(event) => { const asset = datasets.find((item) => item.id === event.target.value); setForm({ ...form, right_asset_id: event.target.value, right_column: asset?.columns[0]?.name || "" }); }} required>{datasets.filter((asset) => asset.id !== form.left_asset_id).map((asset) => <option key={asset.id} value={asset.id}>{asset.schema_name}.{asset.table_name}</option>)}</select></label></div><div className="form-grid"><label>Left column<select value={form.left_column} onChange={(event) => setForm({ ...form, left_column: event.target.value })} required>{leftAsset?.columns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}</select></label><label>Right column<select value={form.right_column} onChange={(event) => setForm({ ...form, right_column: event.target.value })} required>{rightAsset?.columns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}</select></label></div><div className="form-grid"><label>Join type<select value={form.join_type} onChange={(event) => setForm({ ...form, join_type: event.target.value as "inner" | "left" })}><option value="inner">Inner join</option><option value="left">Left join</option></select></label><label>Status<select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}><option value="draft">Draft</option><option value="approved">Approved</option><option value="deprecated">Deprecated</option></select></label></div><label>Description<input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="Business meaning and cardinality assumptions" /></label><div className="policy-banner"><ShieldCheck size={18} /><span><strong>Generation guardrail</strong><small>For a left join, select the left dataset first when building a pipeline.</small></span></div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary-button"><Check size={17} />Save policy</button></div></form></Modal>}</aside>;
}
