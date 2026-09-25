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
import { scopes, useDebouncedValue, useInvalidate, usePagedQuery, usePagination, useProjectQuery, useQueryErrorToast, type Facet } from "../lib/queries";
import { StatusPill, EmptyState, LoadingBlock, Modal, Metric, Pagination, useConfirm } from "./shared";
import { useWorkspace } from "../lib/workspace";

const NO_RULES: QualityRule[] = [];


export function QualityView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [confirm, confirmDialog] = useConfirm();
  const { user } = useWorkspace();
  // Remediation needs quality:write on the API (admin, engineer); every request still goes through Approvals.
  const canRemediate = user.role === "admin" || user.role === "engineer";
  const [remediatingRunId, setRemediatingRunId] = useState<string | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [runs, setRuns] = useState<QualityRun[]>([]);
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [busyRuleId, setBusyRuleId] = useState<string | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search.trim());
  const pagination = usePagination(q, 50);
  const rulesQuery = usePagedQuery<QualityRule>(scopes.qualityRules, "/quality/rules", { q }, pagination, { staleTime: 0 });
  useQueryErrorToast(rulesQuery.error, notify, "Quality rules could not be loaded");
  const rules = rulesQuery.data?.items ?? NO_RULES;
  const ruleFacets = useProjectQuery<{ total: number; asset: Facet[] }>([...scopes.qualityRules, "facets"], "/quality/rules/facets", { staleTime: 0 });
  const invalidate = useInvalidate();
  const [ruleForm, setRuleForm] = useState({ name: "", rule_type: "not_null", column_name: "", severity: "error", values: "", min: "", max: "" });
  const load = useCallback(() => Promise.all([
    api<Dataset[]>("/datasets"),
    api<QualityRun[]>("/quality/runs"),
    invalidate(scopes.qualityRules),
  ]).then(([datasetData, runData]) => {
    setDatasets(datasetData);
    setRuns(runData);
    setSelectedAssetId((current) => current || datasetData[0]?.id || "");
  }), [invalidate]);
  useEffect(() => { load(); }, [load]);
  
  const uniqueDatasets = Array.from(new Map(datasets.map(d => [`${d.schema_name}.${d.table_name}`, d])).values());
  const selectedDataset = uniqueDatasets.find((dataset) => dataset.id === selectedAssetId);

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

  async function remediate(run: QualityRun, action: "recheck" | "purge_quarantine") {
    const purge = action === "purge_quarantine";
    const ok = await confirm({
      title: purge ? "Purge quarantined rows" : "Re-check failed rows",
      body: purge
        ? `Request approval to permanently purge the quarantined rows in ${run.quarantine_relation} for "${run.rule_name}"? This is high risk and runs only after an approver accepts.`
        : `Request approval to re-check the failed rows of "${run.rule_name}" on ${run.dataset}?`,
      confirmLabel: "Request approval",
      danger: purge,
    });
    if (!ok) return;
    setRemediatingRunId(run.id);
    try {
      const result = await api<{ approval_id: string }>(`/quality/runs/${run.id}/remediate`, { method: "POST", body: JSON.stringify({ action, note: null }) });
      notify(`Remediation sent for approval: ${result.approval_id.slice(0, 8)}`);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Remediation could not be requested", "error"); }
    finally { setRemediatingRunId(null); }
  }

  const passing = runs.filter((run) => run.status === "passed").length;
  const failed = runs.filter((run) => run.status === "failed" || run.status === "error").length;
  const coveredAssets = ruleFacets.data?.asset.length ?? 0;
  return (
    <div className="view-stack">
      <div className="view-header"><div><h2>Data quality</h2><p>Execute governed checks against local datasets and isolate failed rows.</p></div><div className="quality-actions"><div className="toolbar-search"><Search size={16} /><input placeholder="Search rules..." value={search} onChange={(e) => setSearch(e.target.value)} /></div><select value={selectedAssetId} onChange={(event) => setSelectedAssetId(event.target.value)} aria-label="Quality dataset">{uniqueDatasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.schema_name}.{dataset.table_name}</option>)}</select><button className="secondary-button" onClick={() => { setRuleForm((current) => ({ ...current, column_name: selectedDataset?.columns[0]?.name || "" })); setShowForm(true); }} disabled={!selectedDataset}><Plus size={17} />Add rule</button><button className="primary-button" onClick={suggest} disabled={suggesting || !selectedAssetId}>{suggesting ? <RefreshCw className="spin" size={17} /> : <Sparkles size={17} />}Suggest checks</button></div></div>
      <section className="metric-grid three"><Metric label="Coverage" value={`${coveredAssets}/${uniqueDatasets.length}`} detail="Datasets with active rules" icon={<ShieldCheck size={19} />} tone="teal" /><Metric label="Passing runs" value={passing} detail="Real local evaluations" icon={<Check size={19} />} tone="blue" /><Metric label="Needs review" value={failed} detail="Failed or errored runs" icon={<AlertCircle size={19} />} tone="amber" /></section>
      <section className="surface"><div className="table-header quality-grid"><span>Dataset</span><span>Rule</span><span>Pass rate</span><span>Status</span><span /></div>{rules.length ? rules.map((rule) => <div className="data-row quality-grid" key={rule.id}><strong>{rule.dataset}</strong><span><strong>{rule.name}</strong><small>{rule.rule_type.replaceAll("_", " ")} / {rule.column_name}</small></span><span className="mono">{rule.latest_run ? `${rule.latest_run.pass_rate}%` : "Not run"}</span><StatusPill value={rule.latest_run?.status || "ready"} /><div className="row-actions"><button className="icon-button" title="Run quality check" onClick={() => runRule(rule)} disabled={busyRuleId === rule.id}>{busyRuleId === rule.id ? <RefreshCw className="spin" size={16} /> : <Play size={16} />}</button><button className="icon-button danger" title="Delete rule" onClick={() => deleteRule(rule.id)}><Trash2 size={16} /></button></div></div>) : rulesQuery.isPending ? <LoadingBlock label="Loading quality rules" /> : <EmptyState icon={<ShieldCheck size={24} />} title="No quality rules" body={q ? "No rules match your search." : "Add a rule or let DataPilot suggest grounded checks for a dataset."} />}<Pagination state={pagination} total={rulesQuery.data?.total ?? 0} count={rules.length} busy={rulesQuery.isFetching} label="rules" /></section>
      {runs.length > 0 && <section className="surface"><div className="section-heading compact"><div><span className="eyebrow">RUN HISTORY</span><h3>Recent evaluations</h3></div><StatusPill value={`${runs.length} runs`} /></div><div className="quality-run-list">{runs.slice(0, 8).map((run) => { const needsAction = run.status === "failed" || run.status === "error"; const denied = "Remediation requires quality:write (engineer or admin)"; return <div key={run.id} className="has-actions"><span><strong>{run.rule_name}</strong><small>{run.dataset}</small></span><span className="mono">{run.failed_rows}/{run.checked_rows} failed</span><StatusPill value={run.status} /><span><small>Quarantine</small><strong>{run.quarantine_relation || "None"}</strong></span><span className="quality-run-actions">{needsAction && <><button className="icon-button" title={canRemediate ? "Re-check failed rows (sent for approval)" : denied} disabled={!canRemediate || remediatingRunId === run.id} onClick={() => remediate(run, "recheck")}><RefreshCw className={remediatingRunId === run.id ? "spin" : undefined} size={16} /></button>{run.quarantine_relation && <button className="icon-button danger" title={canRemediate ? "Purge quarantined rows (sent for approval)" : denied} disabled={!canRemediate || remediatingRunId === run.id} onClick={() => remediate(run, "purge_quarantine")}><Trash2 size={16} /></button>}</>}</span></div>; })}</div></section>}
      {showForm && <Modal title="Add quality rule" onClose={() => setShowForm(false)}><form className="modal-form" onSubmit={createRule}><label>Name<input value={ruleForm.name} onChange={(event) => setRuleForm({ ...ruleForm, name: event.target.value })} required /></label><div className="form-grid"><label>Column<select value={ruleForm.column_name} onChange={(event) => setRuleForm({ ...ruleForm, column_name: event.target.value })} required>{selectedDataset?.columns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}</select></label><label>Rule type<select value={ruleForm.rule_type} onChange={(event) => setRuleForm({ ...ruleForm, rule_type: event.target.value })}><option value="not_null">Not null</option><option value="unique">Unique</option><option value="accepted_values">Accepted values</option><option value="range">Numeric range</option></select></label></div>{ruleForm.rule_type === "accepted_values" && <label>Accepted values<input value={ruleForm.values} onChange={(event) => setRuleForm({ ...ruleForm, values: event.target.value })} placeholder="active, closed, pending" required /></label>}{ruleForm.rule_type === "range" && <div className="form-grid"><label>Minimum<input type="number" value={ruleForm.min} onChange={(event) => setRuleForm({ ...ruleForm, min: event.target.value })} /></label><label>Maximum<input type="number" value={ruleForm.max} onChange={(event) => setRuleForm({ ...ruleForm, max: event.target.value })} /></label></div>}<label>Severity<select value={ruleForm.severity} onChange={(event) => setRuleForm({ ...ruleForm, severity: event.target.value })}><option value="error">Error</option><option value="warning">Warning</option></select></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary-button">Create rule</button></div></form></Modal>}
      {confirmDialog}
    </div>
  );
}
