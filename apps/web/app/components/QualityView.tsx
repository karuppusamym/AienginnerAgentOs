import {
  AlertCircle,
  Check,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type {
  Dataset,
  QualityRun,
  QualityRule,
} from "../types";
import { StatusPill, EmptyState, Modal, Metric, useConfirm } from "./shared";


export function QualityView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [confirm, confirmDialog] = useConfirm();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [rules, setRules] = useState<QualityRule[]>([]);
  const [runs, setRuns] = useState<QualityRun[]>([]);
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [busyRuleId, setBusyRuleId] = useState<string | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [search, setSearch] = useState("");
  const [ruleForm, setRuleForm] = useState({ name: "", rule_type: "not_null", column_name: "", severity: "error", values: "", min: "", max: "" });
  const load = useCallback(() => Promise.all([
    api<Dataset[]>("/datasets"),
    api<QualityRule[]>("/quality/rules"),
    api<QualityRun[]>("/quality/runs"),
  ]).then(([datasetData, ruleData, runData]) => {
    setDatasets(datasetData);
    setRules(ruleData);
    setRuns(runData);
    setSelectedAssetId((current) => current || datasetData[0]?.id || "");
  }), []);
  useEffect(() => { load(); }, [load]);
  
  const uniqueDatasets = Array.from(new Map(datasets.map(d => [`${d.schema_name}.${d.table_name}`, d])).values());
  const selectedDataset = uniqueDatasets.find((dataset) => dataset.id === selectedAssetId);
  const filteredRules = rules.filter(r => search ? (r.name.toLowerCase().includes(search.toLowerCase()) || r.dataset.toLowerCase().includes(search.toLowerCase()) || r.column_name.toLowerCase().includes(search.toLowerCase())) : true);

  async function suggest() {
    if (!selectedAssetId) return;
    setSuggesting(true);
    try {
      const created = await api<QualityRule[]>(`/quality/assets/${selectedAssetId}/suggest`, { method: "POST" });
      await load();
      notify(created.length ? `${created.length} grounded quality rules created` : "Suggested rules already exist");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Quality suggestions failed", "error");
    } finally { setSuggesting(false); }
  }

  async function createRule(event: FormEvent) {
    event.preventDefault();
    if (!selectedAssetId) return;
    const config = ruleForm.rule_type === "accepted_values"
      ? { values: ruleForm.values.split(",").map((value) => value.trim()).filter(Boolean) }
      : ruleForm.rule_type === "range"
        ? { min: ruleForm.min === "" ? null : Number(ruleForm.min), max: ruleForm.max === "" ? null : Number(ruleForm.max), allow_null: true }
        : {};
    try {
      await api("/quality/rules", { method: "POST", body: JSON.stringify({ asset_id: selectedAssetId, name: ruleForm.name, rule_type: ruleForm.rule_type, column_name: ruleForm.column_name, severity: ruleForm.severity, config }) });
      setShowForm(false);
      setRuleForm({ name: "", rule_type: "not_null", column_name: "", severity: "error", values: "", min: "", max: "" });
      await load();
      notify("Quality rule created and versioned");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Quality rule could not be created", "error"); }
  }

  async function runRule(rule: QualityRule) {
    setBusyRuleId(rule.id);
    try {
      const result = await api<QualityRun>(`/quality/rules/${rule.id}/run`, { method: "POST" });
      await load();
      notify(result.failed_rows ? `${result.failed_rows} rows written to quarantine` : `${result.checked_rows} rows passed`);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Quality execution failed", "error"); }
    finally { setBusyRuleId(null); }
  }

  async function deleteRule(ruleId: string) {
    if (!(await confirm({ title: "Delete quality rule", body: "Delete this quality rule? Its run history is kept." }))) return;
    try {
      await api(`/quality/rules/${ruleId}`, { method: "DELETE" });
      await load();
      notify("Quality rule deleted");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Failed to delete rule", "error"); }
  }

  const passing = runs.filter((run) => run.status === "passed").length;
  const failed = runs.filter((run) => run.status === "failed" || run.status === "error").length;
  const coveredAssets = new Set(rules.map((rule) => rule.asset_id)).size;
  return (
    <div className="view-stack">
      <div className="view-header"><div><h2>Data quality</h2><p>Execute governed checks against local datasets and isolate failed rows.</p></div><div className="quality-actions"><div className="toolbar-search"><Search size={16} /><input placeholder="Search rules..." value={search} onChange={(e) => setSearch(e.target.value)} /></div><select value={selectedAssetId} onChange={(event) => setSelectedAssetId(event.target.value)} aria-label="Quality dataset">{uniqueDatasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.schema_name}.{dataset.table_name}</option>)}</select><button className="secondary-button" onClick={() => { setRuleForm((current) => ({ ...current, column_name: selectedDataset?.columns[0]?.name || "" })); setShowForm(true); }} disabled={!selectedDataset}><Plus size={17} />Add rule</button><button className="primary-button" onClick={suggest} disabled={suggesting || !selectedAssetId}>{suggesting ? <RefreshCw className="spin" size={17} /> : <Sparkles size={17} />}Suggest checks</button></div></div>
      <section className="metric-grid three"><Metric label="Coverage" value={`${coveredAssets}/${uniqueDatasets.length}`} detail="Datasets with active rules" icon={<ShieldCheck size={19} />} tone="teal" /><Metric label="Passing runs" value={passing} detail="Real local evaluations" icon={<Check size={19} />} tone="blue" /><Metric label="Needs review" value={failed} detail="Failed or errored runs" icon={<AlertCircle size={19} />} tone="amber" /></section>
      <section className="surface"><div className="table-header quality-grid"><span>Dataset</span><span>Rule</span><span>Pass rate</span><span>Status</span><span /></div>{filteredRules.length ? filteredRules.map((rule) => <div className="data-row quality-grid" key={rule.id}><strong>{rule.dataset}</strong><span><strong>{rule.name}</strong><small>{rule.rule_type.replaceAll("_", " ")} / {rule.column_name}</small></span><span className="mono">{rule.latest_run ? `${rule.latest_run.pass_rate}%` : "Not run"}</span><StatusPill value={rule.latest_run?.status || "ready"} /><div className="row-actions"><button className="icon-button" title="Run quality check" onClick={() => runRule(rule)} disabled={busyRuleId === rule.id}>{busyRuleId === rule.id ? <RefreshCw className="spin" size={16} /> : <Play size={16} />}</button><button className="icon-button danger" title="Delete rule" onClick={() => deleteRule(rule.id)}><Trash2 size={16} /></button></div></div>) : <EmptyState icon={<ShieldCheck size={24} />} title="No quality rules" body="No rules found matching your criteria." />}</section>
      {runs.length > 0 && <section className="surface"><div className="section-heading compact"><div><span className="eyebrow">RUN HISTORY</span><h3>Recent evaluations</h3></div><StatusPill value={`${runs.length} runs`} /></div><div className="quality-run-list">{runs.slice(0, 8).map((run) => <div key={run.id}><span><strong>{run.rule_name}</strong><small>{run.dataset}</small></span><span className="mono">{run.failed_rows}/{run.checked_rows} failed</span><StatusPill value={run.status} /><span><small>Quarantine</small><strong>{run.quarantine_relation || "None"}</strong></span></div>)}</div></section>}
      {showForm && <Modal title="Add quality rule" onClose={() => setShowForm(false)}><form className="modal-form" onSubmit={createRule}><label>Name<input value={ruleForm.name} onChange={(event) => setRuleForm({ ...ruleForm, name: event.target.value })} required /></label><div className="form-grid"><label>Column<select value={ruleForm.column_name} onChange={(event) => setRuleForm({ ...ruleForm, column_name: event.target.value })} required>{selectedDataset?.columns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}</select></label><label>Rule type<select value={ruleForm.rule_type} onChange={(event) => setRuleForm({ ...ruleForm, rule_type: event.target.value })}><option value="not_null">Not null</option><option value="unique">Unique</option><option value="accepted_values">Accepted values</option><option value="range">Numeric range</option></select></label></div>{ruleForm.rule_type === "accepted_values" && <label>Accepted values<input value={ruleForm.values} onChange={(event) => setRuleForm({ ...ruleForm, values: event.target.value })} placeholder="active, closed, pending" required /></label>}{ruleForm.rule_type === "range" && <div className="form-grid"><label>Minimum<input type="number" value={ruleForm.min} onChange={(event) => setRuleForm({ ...ruleForm, min: event.target.value })} /></label><label>Maximum<input type="number" value={ruleForm.max} onChange={(event) => setRuleForm({ ...ruleForm, max: event.target.value })} /></label></div>}<label>Severity<select value={ruleForm.severity} onChange={(event) => setRuleForm({ ...ruleForm, severity: event.target.value })}><option value="error">Error</option><option value="warning">Warning</option></select></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary-button">Create rule</button></div></form></Modal>}
      {confirmDialog}
    </div>
  );
}
