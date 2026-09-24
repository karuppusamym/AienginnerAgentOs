import {
  AlertCircle,
  Braces,
  Check,
  Network,
  Plus,
  Search,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type {
  Dataset,
  SemanticMetric,
  SemanticJoinPolicy,
} from "../types";
import { RelationshipExplorer } from "./RelationshipExplorer";
import { StatusPill, Modal } from "./shared";


export function SemanticView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [metrics, setMetrics] = useState<SemanticMetric[]>([]);
  const [editing, setEditing] = useState<SemanticMetric | null>(null);
  const [showForm, setShowForm] = useState(false);
  const emptyForm = { name: "", description: "", formula: "", grain: "", owner: "", dimensions: "", synonyms: "", status: "draft" };
  const [form, setForm] = useState(emptyForm);
  const [search, setSearch] = useState("");
  const [graphVersion, setGraphVersion] = useState(0);
  const load = useCallback(() => api<SemanticMetric[]>("/semantic/metrics").then(setMetrics), []);
  useEffect(() => { load().catch((reason) => notify(reason instanceof Error ? reason.message : "Semantic metrics unavailable", "error")); }, [load, notify]);
  function openMetric(metric?: SemanticMetric) { setEditing(metric || null); setForm(metric ? { name: metric.name, description: metric.description || "", formula: metric.formula, grain: metric.grain, owner: metric.owner, dimensions: metric.dimensions.join(", "), synonyms: metric.synonyms.join(", "), status: metric.status } : emptyForm); setShowForm(true); }
  async function save(event: FormEvent) { event.preventDefault(); const payload = { ...form, dimensions: form.dimensions.split(",").map((item) => item.trim()).filter(Boolean), synonyms: form.synonyms.split(",").map((item) => item.trim()).filter(Boolean) }; try { await api(editing ? `/semantic/metrics/${editing.id}` : "/semantic/metrics", { method: editing ? "PUT" : "POST", body: JSON.stringify(payload) }); setShowForm(false); await load(); notify(editing ? "Metric updated" : "Metric created"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Metric could not be saved", "error"); } }
  async function remove(metric: SemanticMetric) { try { await api(`/semantic/metrics/${metric.id}`, { method: "DELETE" }); await load(); notify("Metric removed"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Metric could not be removed", "error"); } }
  return (
    <div className="view-stack"><div className="view-header"><div><h2>Semantic layer</h2><p>Approved metrics, joins, synonyms, and business definitions used to ground every agent response.</p></div><div className="quality-actions"><div className="toolbar-search"><Search size={16} /><input placeholder="Search metrics..." value={search} onChange={(e) => setSearch(e.target.value)} /></div><button className="primary-button" onClick={() => openMetric()}><Plus size={17} />Add metric</button></div></div>
      <RelationshipExplorer notify={notify} refreshKey={graphVersion} />
      <div className="semantic-layout"><section className="surface"><div className="section-heading compact"><div><span className="eyebrow">PROJECT METRICS</span><h3>Business calculations</h3></div></div>{metrics.filter(m => search ? m.name.toLowerCase().includes(search.toLowerCase()) : true).map((metric) => <div className="metric-definition" key={metric.id}><span className="semantic-icon"><Braces size={18} /></span><button className="metric-main" onClick={() => openMetric(metric)}><strong>{metric.name}</strong><small>{metric.formula}</small></button><span><small>Grain</small><strong>{metric.grain}</strong></span><span><small>Owner</small><strong>{metric.owner}</strong></span><span className="row-actions"><StatusPill value={metric.status} /><button className="icon-button" title="Delete metric" onClick={() => remove(metric)}><XCircle size={16} /></button></span></div>)}</section>
        <JoinPoliciesPanel notify={notify} onChange={() => setGraphVersion((version) => version + 1)} />
      </div>
      {showForm && <Modal title={editing ? "Edit metric" : "Add metric"} onClose={() => setShowForm(false)}><form className="modal-form" onSubmit={save}><label>Name<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label><label>Description<input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label><label>Formula<textarea value={form.formula} onChange={(event) => setForm({ ...form, formula: event.target.value })} rows={3} required /></label><div className="form-grid"><label>Grain<input value={form.grain} onChange={(event) => setForm({ ...form, grain: event.target.value })} required /></label><label>Owner<input value={form.owner} onChange={(event) => setForm({ ...form, owner: event.target.value })} required /></label></div><div className="form-grid"><label>Dimensions<input value={form.dimensions} onChange={(event) => setForm({ ...form, dimensions: event.target.value })} placeholder="status, segment" /></label><label>Synonyms<input value={form.synonyms} onChange={(event) => setForm({ ...form, synonyms: event.target.value })} /></label></div><label>Status<select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}><option value="draft">Draft</option><option value="approved">Approved</option><option value="deprecated">Deprecated</option></select></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary-button"><Check size={17} />Save metric</button></div></form></Modal>}
    </div>
  );
}

export function JoinPoliciesPanel({ notify, onChange }: { notify: (message: string, tone?: "ok" | "error") => void; onChange?: () => void }) {
  const emptyForm = { left_asset_id: "", right_asset_id: "", left_column: "", right_column: "", join_type: "inner" as "inner" | "left", description: "", status: "draft" };
  const [policies, setPolicies] = useState<SemanticJoinPolicy[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [editing, setEditing] = useState<SemanticJoinPolicy | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [search, setSearch] = useState("");
  // Previously deduplicated by bare "schema.table" name before this list
  // ever reached state -- a real bug, not a convenience: once two different
  // sources both catalog e.g. "core.accounts" (a SQL Server connector scan
  // and a locally-staged file), a Map keyed by that bare string silently
  // keeps only whichever one loaded last and drops the other entirely, so
  // it was permanently unselectable in the "Add join policy" form below,
  // with no indication a collision even happened. Found by re-checking this
  // panel against the same duplicate-name scenario that /semantic/graph's
  // node labels were already fixed for (see routers/semantic.py) -- that
  // fix never reached this component's own, separate dataset list. Keep
  // every asset; disambiguate the label instead (below), the same way the
  // graph already does.
  const load = useCallback(async () => { const [policyData, datasetData] = await Promise.all([api<SemanticJoinPolicy[]>("/semantic/joins"), api<Dataset[]>("/datasets")]); setPolicies(policyData); setDatasets(datasetData); }, []);
  useEffect(() => { load().catch((reason) => notify(reason instanceof Error ? reason.message : "Join policies unavailable", "error")); }, [load, notify]);
  const leftAsset = datasets.find((item) => item.id === form.left_asset_id);
  const rightAsset = datasets.find((item) => item.id === form.right_asset_id);
  const relationCounts = new Map<string, number>();
  datasets.forEach((item) => { const key = `${item.schema_name}.${item.table_name}`; relationCounts.set(key, (relationCounts.get(key) || 0) + 1); });
  const datasetLabel = (asset: Dataset) => {
    const bare = `${asset.schema_name}.${asset.table_name}`;
    if ((relationCounts.get(bare) || 0) <= 1) return bare;
    return `${bare} (${asset.source?.name || (asset.connector_id ? "connector" : "local catalog")})`;
  };
  const relation = (id: string) => { const asset = datasets.find((item) => item.id === id); return asset ? datasetLabel(asset) : "Dataset unavailable"; };
  // Mirrors group_key() in routers/semantic.py: an approved policy is only
  // actually executable if both sides can be queried through the same
  // connector (or are both local-workspace assets). New policies are
  // blocked from crossing this boundary server-side now, but a policy
  // approved before that check existed -- or created while the dataset
  // picker above still silently collapsed duplicate-named assets from
  // different sources into one option -- could already violate it. Flag
  // those here instead of showing them identically to a safe policy.
  // Mirrors group_key() in routers/semantic.py: a direct-driver connector's
  // assets really do share one physical DB connection, but an MCP-backed
  // connector's assets are individually-invoked tools with no cross-tool
  // join path, so each one is its own atomic group even under the same
  // connector_id (see toolbox.yaml's multiple backends behind one connector).
  const groupKey = (asset?: Dataset) => {
    if (!asset?.connector_id) return "__local__";
    if (asset.source?.connection_mode === "mcp") return `${asset.connector_id}:${asset.id}`;
    return asset.connector_id;
  };
  const crossesConnectors = (policy: SemanticJoinPolicy) => {
    const left = datasets.find((item) => item.id === policy.left_asset_id);
    const right = datasets.find((item) => item.id === policy.right_asset_id);
    return Boolean(left && right && groupKey(left) !== groupKey(right));
  };
  function openPolicy(policy?: SemanticJoinPolicy) { const left = policy ? datasets.find((item) => item.id === policy.left_asset_id) : datasets[0]; const right = policy ? datasets.find((item) => item.id === policy.right_asset_id) : datasets.find((item) => item.id !== left?.id); setEditing(policy || null); setForm(policy ? { left_asset_id: policy.left_asset_id, right_asset_id: policy.right_asset_id, left_column: policy.left_column, right_column: policy.right_column, join_type: policy.join_type, description: policy.description || "", status: policy.status } : { ...emptyForm, left_asset_id: left?.id || "", right_asset_id: right?.id || "", left_column: left?.columns[0]?.name || "", right_column: right?.columns[0]?.name || "" }); setShowForm(true); }
  async function save(event: FormEvent) { event.preventDefault(); try { await api(editing ? `/semantic/joins/${editing.id}` : "/semantic/joins", { method: editing ? "PUT" : "POST", body: JSON.stringify(form) }); setShowForm(false); await load(); onChange?.(); notify(editing ? "Join policy updated" : "Join policy created"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Join policy could not be saved", "error"); } }
  async function remove(policy: SemanticJoinPolicy) { try { await api(`/semantic/joins/${policy.id}`, { method: "DELETE" }); await load(); onChange?.(); notify("Join policy removed"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Join policy could not be removed", "error"); } }
  return <aside className="surface"><div className="section-heading compact"><div><span className="eyebrow">JOIN POLICY</span><h3>Approved paths</h3></div><div className="quality-actions"><div className="toolbar-search"><Search size={14} /><input placeholder="Search joins..." value={search} onChange={(e) => setSearch(e.target.value)} /></div><button className="icon-button" title="Add join policy" onClick={() => openPolicy()} disabled={datasets.length < 2}><Plus size={16} /></button></div></div>{policies.length ? <div className="check-list">{policies.filter(p => search ? relation(p.left_asset_id).toLowerCase().includes(search.toLowerCase()) || relation(p.right_asset_id).toLowerCase().includes(search.toLowerCase()) : true).map((policy) => <div key={policy.id}><button className="metric-main" onClick={() => openPolicy(policy)}><strong>{crossesConnectors(policy) && <AlertCircle size={14} className="join-policy-warning" aria-label="Crosses connectors, cannot execute" />} {relation(policy.left_asset_id)} {policy.join_type.toUpperCase()} {relation(policy.right_asset_id)}</strong><small>{policy.left_column} = {policy.right_column}{policy.description ? ` · ${policy.description}` : ""}{crossesConnectors(policy) ? " · can't be queried together in one call (different connectors, or different MCP tools) — cannot execute as written, edit or remove" : ""}</small></button><StatusPill value={policy.status} /><button className="icon-button" title="Delete join policy" onClick={() => remove(policy)}><XCircle size={15} /></button></div>)}</div> : <div className="empty-state"><Network size={18} /><p>No governed join paths yet.</p><small>Approved policies take precedence over inferred identifiers in pipeline generation.</small></div>}<div className="check-list"><div><ShieldCheck size={15} />Only approved policies are used automatically.</div></div>{showForm && <Modal title={editing ? "Edit join policy" : "Add join policy"} onClose={() => setShowForm(false)}><form className="modal-form" onSubmit={save}><div className="form-grid"><label>Left dataset<select value={form.left_asset_id} onChange={(event) => { const asset = datasets.find((item) => item.id === event.target.value); const right = form.right_asset_id === asset?.id ? datasets.find((item) => item.id !== asset?.id) : undefined; setForm({ ...form, left_asset_id: event.target.value, left_column: asset?.columns[0]?.name || "", right_asset_id: right?.id || form.right_asset_id, right_column: right?.columns[0]?.name || form.right_column }); }} required>{datasets.map((asset) => <option key={asset.id} value={asset.id}>{datasetLabel(asset)}</option>)}</select></label><label>Right dataset<select value={form.right_asset_id} onChange={(event) => { const asset = datasets.find((item) => item.id === event.target.value); setForm({ ...form, right_asset_id: event.target.value, right_column: asset?.columns[0]?.name || "" }); }} required>{datasets.filter((asset) => asset.id !== form.left_asset_id).map((asset) => <option key={asset.id} value={asset.id}>{datasetLabel(asset)}</option>)}</select></label></div><div className="form-grid"><label>Left column<select value={form.left_column} onChange={(event) => setForm({ ...form, left_column: event.target.value })} required>{leftAsset?.columns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}</select></label><label>Right column<select value={form.right_column} onChange={(event) => setForm({ ...form, right_column: event.target.value })} required>{rightAsset?.columns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}</select></label></div><div className="form-grid"><label>Join type<select value={form.join_type} onChange={(event) => setForm({ ...form, join_type: event.target.value as "inner" | "left" })}><option value="inner">Inner join</option><option value="left">Left join</option></select></label><label>Status<select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}><option value="draft">Draft</option><option value="approved">Approved</option><option value="deprecated">Deprecated</option></select></label></div><label>Description<input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="Business meaning and cardinality assumptions" /></label><div className="policy-banner"><ShieldCheck size={18} /><span><strong>Generation guardrail</strong><small>For a left join, select the left dataset first when building a pipeline.</small></span></div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary-button"><Check size={17} />Save policy</button></div></form></Modal>}</aside>;
}
