import {
  Anchor,
  FlaskConical,
  Play,
  Plus,
  RefreshCw,
  Settings,
  XCircle,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useWorkspace } from "../lib/workspace";
import type {
  EvaluationSet,
} from "../types";
import { StatusPill, Modal, useConfirm } from "./shared";


/** Evaluation sets and replay. Rendered as the Learning → Evaluations tab (`embedded`); /evaluations redirects there. */
export function EvaluationsView({ notify, embedded = false }: { notify: (message: string, tone?: "ok" | "error") => void; embedded?: boolean }) {
  const [confirm, confirmDialog] = useConfirm();
  const { user } = useWorkspace();
  // Baselining needs conversation:write on the API (every role except viewer).
  const canBaseline = user.role !== "viewer";
  const [sets, setSets] = useState<EvaluationSet[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<EvaluationSet | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "SQL grounding baseline", description: "Regression checks for governed SQL generation", case_name: "Account growth", question: "Show monthly deposit account growth", case_type: "sql_generation" as "sql_generation" | "agent_run", dialect: "postgres", expected_tables: "core.accounts", required_tokens: "select, limit", expected_agents: "Planner, Metadata, Policy", expected_tools: "catalog.search", expects_approval: "auto" });
  const load = useCallback(() => api<EvaluationSet[]>("/evaluations").then(setSets), []);
  useEffect(() => { load(); }, [load]);
  function openForm(item?: EvaluationSet) { const first = item?.cases[0]; setEditing(item || null); setForm(item ? { name: item.name, description: item.description || "", case_name: first?.name || "Case", question: first?.question || "", case_type: first?.case_type || "sql_generation", dialect: first?.dialect || "postgres", expected_tables: first?.expected_tables.join(", ") || "", required_tokens: first?.required_sql_tokens.join(", ") || "", expected_agents: first?.expected_agents?.join(", ") || "Planner, Metadata, Policy", expected_tools: first?.expected_tools?.join(", ") || "", expects_approval: first?.expects_approval === true ? "yes" : first?.expects_approval === false ? "no" : "auto" } : { name: "SQL grounding baseline", description: "Regression checks for governed SQL generation", case_name: "Account growth", question: "Show monthly deposit account growth", case_type: "sql_generation", dialect: "postgres", expected_tables: "core.accounts", required_tokens: "select, limit", expected_agents: "Planner, Metadata, Policy", expected_tools: "catalog.search", expects_approval: "auto" }); setShowForm(true); }
  async function create(event: FormEvent) { event.preventDefault(); try { await api(editing ? `/evaluations/${editing.id}` : "/evaluations", { method: editing ? "PUT" : "POST", body: JSON.stringify({ name: form.name, description: form.description, cases: [{ name: form.case_name, question: form.question, case_type: form.case_type, dialect: form.dialect, expected_tables: form.expected_tables.split(",").map((item) => item.trim()).filter(Boolean), required_sql_tokens: form.required_tokens.split(",").map((item) => item.trim()).filter(Boolean), expected_agents: form.expected_agents.split(",").map((item) => item.trim()).filter(Boolean), expected_tools: form.expected_tools.split(",").map((item) => item.trim()).filter(Boolean), expects_approval: form.expects_approval === "auto" ? null : form.expects_approval === "yes" }] }) }); setShowForm(false); setEditing(null); await load(); notify(editing ? "Evaluation version updated" : "Evaluation set created"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not save evaluation", "error"); } }
  async function run(id: string) { setRunning(id); try { const result = await api<{ score: number; status: string }>(`/evaluations/${id}/run`, { method: "POST", body: JSON.stringify({}) }); await load(); notify(`Evaluation ${result.status}: ${result.score}%`); } catch (reason) { notify(reason instanceof Error ? reason.message : "Evaluation failed", "error"); } finally { setRunning(null); } }
  async function promoteBaseline(item: EvaluationSet) {
    const runId = item.latest_run?.id;
    if (!runId) return;
    if (!(await confirm({ title: "Promote baseline", body: `Use the latest replay of "${item.name}" as the golden trace for its agent-run cases? Later replays are scored against it.`, confirmLabel: "Promote baseline", danger: false }))) return;
    const send = (overwrite: boolean) => api<{ promoted?: string[] }>(`/evaluations/${item.id}/baseline`, { method: "POST", body: JSON.stringify({ run_id: runId, overwrite }) });
    try {
      await send(false);
      await load();
      notify("Golden baseline promoted");
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409 && /golden trace/i.test(reason.message) && await confirm({ title: "Replace golden trace", body: `${reason.message}. Replace the existing golden traces with this replay?`, confirmLabel: "Replace baseline" })) {
        try { await send(true); await load(); notify("Golden baseline replaced"); } catch (inner) { notify(inner instanceof Error ? inner.message : "Baseline could not be promoted", "error"); }
        return;
      }
      notify(reason instanceof Error ? reason.message : "Baseline could not be promoted", "error");
    }
  }
  async function remove(item: EvaluationSet) { if (!(await confirm({ title: "Delete evaluation", body: `Delete evaluation "${item.name}" and all replay results?` }))) return; try { await api(`/evaluations/${item.id}`, { method: "DELETE" }); await load(); notify("Evaluation deleted"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Evaluation could not be deleted", "error"); } }
  const intro = <div><h2>Evaluation and replay</h2><p>Measure SQL grounding against expected sources and required query traits. Prompt optimization and agent scorecards read these sets.</p></div>;
  const newButton = <button className="primary-button" onClick={() => openForm()}><Plus size={17} />New evaluation</button>;
  return <div className="view-stack">{embedded ? <section className="surface"><div className="section-heading"><div><span className="eyebrow">EVALUATIONS</span><h3>Evaluation and replay</h3><p>Measure SQL grounding against expected sources and required query traits. Prompt optimization and agent scorecards read these sets.</p></div>{newButton}</div></section> : <div className="view-header">{intro}{newButton}</div>}<section className="surface evaluation-list"><div className="table-header evaluation-grid"><span>Evaluation</span><span>Cases</span><span>Latest score</span><span>Status</span><span /></div>{sets.map((item) => <div className="data-row evaluation-grid" key={item.id}><span><strong>{item.name}</strong><small>{item.description}</small></span><span>{item.cases.length}</span><strong>{item.latest_run ? `${item.latest_run.score}%` : "-"}</strong><StatusPill value={item.latest_run?.status || "not_run"} /><span className="row-actions"><button className="icon-button" title="Edit evaluation" onClick={() => openForm(item)}><Settings size={16} /></button><button className="secondary-button" onClick={() => run(item.id)} disabled={running === item.id}>{running === item.id ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}Replay</button>{item.cases.some((entry) => entry.case_type === "agent_run") && <button className="icon-button" title={!item.latest_run ? "Replay the set first" : canBaseline ? "Promote the latest replay as the golden baseline" : "Promoting baselines requires write access"} disabled={!item.latest_run || !canBaseline} onClick={() => promoteBaseline(item)}><Anchor size={16} /></button>}<button className="icon-button" title="Delete evaluation" onClick={() => remove(item)}><XCircle size={16} /></button></span></div>)}</section>{showForm && <Modal title={editing ? "Edit evaluation" : "Create evaluation"} onClose={() => { setShowForm(false); setEditing(null); }}><form className="modal-form" onSubmit={create}><label>Name<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label><label>Description<input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label><label>Case name<input value={form.case_name} onChange={(event) => setForm({ ...form, case_name: event.target.value })} required /></label><label>Question<textarea value={form.question} onChange={(event) => setForm({ ...form, question: event.target.value })} rows={3} required /></label><div className="form-grid"><label>Dialect<select value={form.dialect} onChange={(event) => setForm({ ...form, dialect: event.target.value })}><option value="postgres">PostgreSQL</option><option value="sqlserver">SQL Server</option><option value="oracle">Oracle</option><option value="teradata">Teradata</option><option value="bigquery">BigQuery</option></select></label><label>Expected tables<input value={form.expected_tables} onChange={(event) => setForm({ ...form, expected_tables: event.target.value })} /></label></div><label>Required SQL tokens<input value={form.required_tokens} onChange={(event) => setForm({ ...form, required_tokens: event.target.value })} /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => { setShowForm(false); setEditing(null); }}>Cancel</button><button className="primary-button"><FlaskConical size={17} />{editing ? "Save" : "Create"}</button></div></form></Modal>}{confirmDialog}</div>;
}
