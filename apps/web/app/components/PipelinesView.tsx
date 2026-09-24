import {
  Bot,
  ChevronRight,
  CalendarClock,
  Database,
  FileUp,
  GitBranch,
  Play,
  Plus,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type {
  Dataset,
  PipelineDefinition,
  Job,
  IngestionSchedule,
  MappingOption,
} from "../types";
import { StatusPill, Modal, useConfirm } from "./shared";


export function PipelinesView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [confirm, confirmDialog] = useConfirm();
  const [objective, setObjective] = useState("Ingest daily transaction files, validate schema, and publish a clean local table");
  const [steps, setSteps] = useState<Job["plan"]>([]);
  const [busy, setBusy] = useState(false);
  const [schedules, setSchedules] = useState<IngestionSchedule[]>([]);
  const [mappings, setMappings] = useState<MappingOption[]>([]);
  const [showSchedule, setShowSchedule] = useState(false);
  const [showGenerator, setShowGenerator] = useState(false);
  const [pipelines, setPipelines] = useState<PipelineDefinition[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [search, setSearch] = useState("");
  const [scheduleSearch, setScheduleSearch] = useState("");
  const [selectedPipeline, setSelectedPipeline] = useState<PipelineDefinition | null>(null);
  const [editingPipeline, setEditingPipeline] = useState<PipelineDefinition | null>(null);
  const [pipelineForm, setPipelineForm] = useState({ name: "", source_asset_id: "", target_schema: "curated", target_table: "" });
  const [scheduleForm, setScheduleForm] = useState({ name: "", mapping_id: "", cron: "0 6 * * *", load_mode: "append", key_column: "", watermark_column: "" });
  const loadSchedules = useCallback(() => Promise.all([api<IngestionSchedule[]>("/schedules"), api<MappingOption[]>("/ingestion-mappings"), api<PipelineDefinition[]>("/pipelines"), api<Dataset[]>("/datasets")]).then(([scheduleData, mappingData, pipelineData, datasetData]) => { setSchedules(scheduleData); setMappings(mappingData); setPipelines(pipelineData); setDatasets(datasetData); setSelectedPipeline((current) => pipelineData.find((item) => item.id === current?.id) || pipelineData[0] || null); setScheduleForm((current) => ({ ...current, mapping_id: current.mapping_id || mappingData[0]?.id || "" })); setPipelineForm((current) => ({ ...current, source_asset_id: current.source_asset_id || datasetData.find((item) => item.asset_type === "staged_file")?.id || datasetData[0]?.id || "" })); }), []);
  useEffect(() => { loadSchedules(); }, [loadSchedules]);
  const selectedMapping = mappings.find((mapping) => mapping.id === scheduleForm.mapping_id);
  async function draft() {
    setBusy(true);
    try {
      const result = await api<{ plan: Job["plan"]; approval_id?: string }>("/agents/runs", { method: "POST", body: JSON.stringify({ objective, autonomy_level: 3 }) });
      setSteps(result.plan);
      notify(result.approval_id ? "Pipeline draft is waiting for approval" : "Pipeline draft completed");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Could not draft pipeline", "error");
    } finally { setBusy(false); }
  }
  async function createSchedule(event: FormEvent) {
    event.preventDefault();
    try {
      const result = await api<{ approval_id: string }>("/schedules", { method: "POST", body: JSON.stringify({ name: scheduleForm.name, mapping_id: scheduleForm.mapping_id, cron: scheduleForm.cron, timezone: "UTC", load_mode: scheduleForm.load_mode, key_columns: scheduleForm.load_mode === "upsert" ? [scheduleForm.key_column] : [], watermark_column: scheduleForm.watermark_column || null }) });
      setShowSchedule(false);
      await loadSchedules();
      notify(`Schedule submitted for approval: ${result.approval_id.slice(0, 8)}`);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not create schedule", "error"); }
  }
  async function runSchedule(id: string) {
    try { const result = await api<{ status: string }>(`/schedules/${id}/run`, { method: "POST" }); notify(`Schedule run ${result.status.toLowerCase()}`); window.setTimeout(loadSchedules, 800); } catch (reason) { notify(reason instanceof Error ? reason.message : "Schedule run failed", "error"); }
  }
  function openPipelineGenerator(pipeline?: PipelineDefinition) {
    setEditingPipeline(pipeline || null);
    if (pipeline) {
      setPipelineForm((current) => ({ ...current, name: pipeline.name }));
      setObjective(pipeline.objective);
    } else {
      setPipelineForm((current) => ({ ...current, name: "", target_table: "" }));
    }
    setShowGenerator(true);
  }
  async function generatePipeline(event: FormEvent) {
    event.preventDefault();
    try {
      const saved = editingPipeline
        ? await api<PipelineDefinition>(`/pipelines/${editingPipeline.id}`, { method: "PUT", body: JSON.stringify({ name: pipelineForm.name, objective }) })
        : await api<PipelineDefinition>("/pipelines/generate", { method: "POST", body: JSON.stringify({ name: pipelineForm.name, objective, source_asset_ids: [pipelineForm.source_asset_id], target_schema: pipelineForm.target_schema, target_table: pipelineForm.target_table }) });
      setShowGenerator(false);
      setEditingPipeline(null);
      await loadSchedules();
      setSelectedPipeline(saved);
      notify(editingPipeline ? "Pipeline saved as a new draft version" : "Executable pipeline draft and lineage created");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Pipeline generation failed", "error"); }
  }
  async function deployPipeline(id: string) {
    try { await api(`/pipelines/${id}/deploy`, { method: "POST" }); await loadSchedules(); notify("Pipeline deployment submitted for approval"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Deployment request failed", "error"); }
  }
  async function deletePipeline(pipeline: PipelineDefinition) {
    if (!(await confirm({ title: "Delete pipeline", body: `Delete pipeline "${pipeline.name}" from the registry?` }))) return;
    try {
      await api(`/pipelines/${pipeline.id}`, { method: "DELETE" });
      await loadSchedules();
      setSelectedPipeline((current) => current?.id === pipeline.id ? null : current);
      notify("Pipeline deleted from registry");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Pipeline could not be deleted", "error"); }
  }
  return (
    <div className="view-stack">
      <div className="view-header"><div><h2>Pipeline designer</h2><p>Generate versioned transformations from catalog datasets, review lineage, approve deployment, and schedule refreshes.</p></div><div className="row-actions"><button className="secondary-button" onClick={draft} disabled={busy}>{busy ? <RefreshCw className="spin" size={17} /> : <Sparkles size={17} />}Plan with agents</button><button className="primary-button" onClick={() => openPipelineGenerator()} disabled={!datasets.length}><Plus size={17} />New pipeline</button></div></div>
      <section className="surface pipeline-command"><label>Pipeline objective<textarea value={objective} onChange={(event) => setObjective(event.target.value)} rows={3} /></label></section>
      <section className="pipeline-canvas">
        {(selectedPipeline?.definition.nodes?.map((node) => ({ agent: node.type, action: node.label, status: selectedPipeline.status === "active" ? "complete" : "waiting" })) || (steps.length ? steps : [
          { agent: "Source", action: "Local file drop", status: "complete" },
          { agent: "Profile", action: "Infer and validate schema", status: "complete" },
          { agent: "Quality", action: "Run null and uniqueness checks", status: "waiting" },
          { agent: "Publish", action: "Write governed staging table", status: "waiting" },
        ])).map((step, index, all) => (
          <div className="pipeline-node-wrap" key={`${step.agent}-${index}`}>
            <div className={`pipeline-node ${step.status}`}><span className="node-icon">{index === 0 ? <FileUp size={18} /> : index === all.length - 1 ? <Database size={18} /> : <Bot size={18} />}</span><span><small>{step.agent}</small><strong>{step.action}</strong></span><StatusPill value={step.status} /></div>
            {index < all.length - 1 && <div className="pipeline-edge"><ChevronRight size={18} /></div>}
          </div>
        ))}
      </section>
      <section className="surface schedule-surface"><div className="section-heading"><div><span className="eyebrow">VERSIONED DEFINITIONS</span><h3>Generated pipelines</h3><p>Each draft contains executable local SQL, validation checks, and persisted source-to-target lineage.</p></div><div className="toolbar-search"><Search size={14} /><input placeholder="Search pipelines..." value={search} onChange={(e) => setSearch(e.target.value)} /></div></div><div className="table-header pipeline-registry-grid"><span>Pipeline</span><span>Source to target</span><span>Version</span><span>Status</span><span /></div>{pipelines.filter(p => search ? p.name.toLowerCase().includes(search.toLowerCase()) || p.objective.toLowerCase().includes(search.toLowerCase()) : true).map((pipeline) => <div className={`data-row pipeline-registry-grid ${selectedPipeline?.id === pipeline.id ? "selected" : ""}`} key={pipeline.id} onClick={() => setSelectedPipeline(pipeline)}><span><strong>{pipeline.name}</strong><small>{pipeline.objective}</small></span><span><strong>{pipeline.definition.target?.relation || "-"}</strong><small>{pipeline.definition.sources?.map((source) => source.relation).join(", ")}</small></span><span>v{pipeline.current_version}</span><StatusPill value={pipeline.status} /><span className="row-actions"><button className="icon-button" title="Edit pipeline" onClick={(event) => { event.stopPropagation(); openPipelineGenerator(pipeline); }}><Settings size={16} /></button>{pipeline.status === "draft" && <button className="icon-button" title="Request deployment approval" onClick={(event) => { event.stopPropagation(); deployPipeline(pipeline.id); }}><Play size={16} /></button>}<button className="icon-button" title="Delete pipeline" onClick={(event) => { event.stopPropagation(); deletePipeline(pipeline); }}><XCircle size={16} /></button></span></div>)}{!pipelines.length && <div className="inline-empty">Generate a pipeline from a real catalog dataset.</div>}{selectedPipeline?.generated_code && <pre className="registry-code"><code>{selectedPipeline.generated_code}</code></pre>}</section>
      <div className="policy-banner"><ShieldCheck size={19} /><span><strong>Controlled execution</strong><small>Writes, schedules, and external publication require an approval before the runner receives them.</small></span></div>
      <section className="surface schedule-surface">
        <div className="section-heading"><div><span className="eyebrow">DURABLE AUTOMATION</span><h3>Ingestion schedules</h3><p>Approved mappings run through the local worker with optional incremental watermarks.</p></div><div className="row-actions"><div className="toolbar-search"><Search size={14} /><input placeholder="Search schedules..." value={scheduleSearch} onChange={(e) => setScheduleSearch(e.target.value)} /></div><button className="primary-button" onClick={() => setShowSchedule(true)} disabled={!mappings.length}><CalendarClock size={17} />Add schedule</button></div></div>
        <div className="table-header schedule-grid"><span>Schedule</span><span>Mapping</span><span>Mode</span><span>Next run</span><span /></div>
        {schedules.filter(s => scheduleSearch ? s.name.toLowerCase().includes(scheduleSearch.toLowerCase()) || (s.target_table || "").toLowerCase().includes(scheduleSearch.toLowerCase()) : true).map((schedule) => <div className="data-row schedule-grid" key={schedule.id}><span><strong>{schedule.name}</strong><small>{schedule.cron} / UTC</small></span><span><strong>{schedule.target_table}</strong><small>{schedule.filename}</small></span><span><StatusPill value={schedule.enabled ? schedule.load_mode : "awaiting_approval"} />{schedule.last_watermark && <small>{schedule.last_watermark}</small>}</span><span>{schedule.next_run_at ? new Date(schedule.next_run_at).toLocaleString() : "-"}</span><button className="icon-button" title="Run now" disabled={!schedule.enabled} onClick={() => runSchedule(schedule.id)}><Play size={16} /></button></div>)}
        {!schedules.length && <div className="inline-empty">No ingestion schedules have been requested.</div>}
      </section>
      {showSchedule && <Modal title="Schedule ingestion" onClose={() => setShowSchedule(false)}><form className="modal-form" onSubmit={createSchedule}><label>Name<input value={scheduleForm.name} onChange={(event) => setScheduleForm({ ...scheduleForm, name: event.target.value })} required /></label><label>Mapping<select value={scheduleForm.mapping_id} onChange={(event) => setScheduleForm({ ...scheduleForm, mapping_id: event.target.value, key_column: "", watermark_column: "" })} required>{mappings.map((mapping) => <option value={mapping.id} key={mapping.id}>{mapping.filename} / {mapping.target_table}</option>)}</select></label><div className="form-grid"><label>Cron<input value={scheduleForm.cron} onChange={(event) => setScheduleForm({ ...scheduleForm, cron: event.target.value })} required /></label><label>Load mode<select value={scheduleForm.load_mode} onChange={(event) => setScheduleForm({ ...scheduleForm, load_mode: event.target.value })}><option value="append">Append</option><option value="upsert">Merge</option></select></label></div><div className="form-grid"><label>Watermark<select value={scheduleForm.watermark_column} onChange={(event) => setScheduleForm({ ...scheduleForm, watermark_column: event.target.value })}><option value="">None</option>{selectedMapping?.columns.map((column) => <option value={column.target_name} key={column.target_name}>{column.target_name}</option>)}</select></label>{scheduleForm.load_mode === "upsert" && <label>Merge key<select value={scheduleForm.key_column} onChange={(event) => setScheduleForm({ ...scheduleForm, key_column: event.target.value })} required><option value="">Select key</option>{selectedMapping?.columns.map((column) => <option value={column.target_name} key={column.target_name}>{column.target_name}</option>)}</select></label>}</div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowSchedule(false)}>Cancel</button><button className="primary-button"><CalendarClock size={17} />Request approval</button></div></form></Modal>}
      {showGenerator && <Modal title={editingPipeline ? "Edit pipeline" : "Generate executable pipeline"} onClose={() => { setShowGenerator(false); setEditingPipeline(null); }}><form className="modal-form" onSubmit={generatePipeline}><label>Name<input value={pipelineForm.name} onChange={(event) => setPipelineForm({ ...pipelineForm, name: event.target.value })} required /></label>{!editingPipeline && <><label>Source dataset<select value={pipelineForm.source_asset_id} onChange={(event) => setPipelineForm({ ...pipelineForm, source_asset_id: event.target.value })} required>{datasets.map((dataset) => <option value={dataset.id} key={dataset.id}>{dataset.schema_name}.{dataset.table_name} / {dataset.row_count ?? "unknown"} rows</option>)}</select></label><div className="form-grid"><label>Target schema<input value={pipelineForm.target_schema} onChange={(event) => setPipelineForm({ ...pipelineForm, target_schema: event.target.value })} required /></label><label>Target table<input value={pipelineForm.target_table} onChange={(event) => setPipelineForm({ ...pipelineForm, target_table: event.target.value })} required /></label></div></>}<label>Objective<textarea value={objective} onChange={(event) => setObjective(event.target.value)} rows={4} required /></label>{editingPipeline && <div className="modal-note"><GitBranch size={16} />Saving creates the next draft version and deployment must be requested again.</div>}<div className="modal-actions"><button type="button" className="secondary-button" onClick={() => { setShowGenerator(false); setEditingPipeline(null); }}>Cancel</button><button className="primary-button"><Sparkles size={16} />{editingPipeline ? "Save version" : "Generate"}</button></div></form></Modal>}
      {confirmDialog}
    </div>
  );
}
