import {
  AlertCircle,
  Clock3,
  Layers3,
  RefreshCw,
  Search,
  XCircle,
} from "lucide-react";
import { useState } from "react";
import { api } from "../lib/api";
import type {
  Incident,
  Job,
} from "../types";
import { hasActiveJob, scopes, useIncidents, useInvalidate, useJobs, useQueryErrorToast } from "../lib/queries";
import { StatusPill, LoadingBlock } from "./shared";


const OUTPUT_LABELS: Record<string, string> = { step_skipped: "Step skipped", plan_only: "Plan only (not executed)", tool_choice: "Tool choice" };
const NO_JOBS: Job[] = [];
const NO_INCIDENTS: Incident[] = [];

export function JobsView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  // Polling lives in the queries: every 2 s while a job is active, paused while the
  // tab is hidden, stopped when nothing is running; requests abort on unmount.
  const jobsQuery = useJobs();
  const jobs = jobsQuery.data ?? NO_JOBS;
  const incidentsQuery = useIncidents(hasActiveJob(jobsQuery.data));
  const incidents = incidentsQuery.data ?? NO_INCIDENTS;
  useQueryErrorToast(jobsQuery.error || incidentsQuery.error, notify, "Jobs could not be loaded");
  const invalidate = useInvalidate();
  const load = () => invalidate(scopes.jobs, scopes.incidents);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = jobs.find((item) => item.id === selectedId) || jobs[0] || null;
  const [filter, setFilter] = useState<"all" | "running" | "action">("all");
  const [search, setSearch] = useState("");
  const filtered = jobs.filter((job) => (filter === "all" || (filter === "running" ? ["RUNNING", "QUEUED", "PLANNING"].includes(job.status) : ["WAITING_FOR_APPROVAL", "FAILED"].includes(job.status))) && (search ? job.title.toLowerCase().includes(search.toLowerCase()) || job.job_type.toLowerCase().includes(search.toLowerCase()) : true));
  async function cancelSelected() {
    if (!selected) return;
    try { await api(`/jobs/${selected.id}/cancel`, { method: "POST" }); notify("Job cancelled"); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Job could not be cancelled", "error"); }
  }
  async function retrySelected() { if (!selected) return; try { const result = await api<{ status: string }>(`/jobs/${selected.id}/retry`, { method: "POST" }); notify(`Retry ${result.status.toLowerCase()}`); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Retry failed", "error"); } }
  async function diagnoseSelected() { if (!selected) return; try { await api(`/jobs/${selected.id}/diagnose`, { method: "POST" }); notify("Incident diagnosis recorded"); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Diagnosis failed", "error"); } }
  return (
    <div className="view-stack">
      <div className="view-header"><div><h2>Job operations</h2><p>Inspect state, progress, evidence, and every specialist handoff.</p></div><div className="row-actions"><div className="toolbar-search"><Search size={16} /><input placeholder="Search jobs..." value={search} onChange={(e) => setSearch(e.target.value)} /></div><div className="segmented"><button className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>All</button><button className={filter === "running" ? "active" : ""} onClick={() => setFilter("running")}>Running</button><button className={filter === "action" ? "active" : ""} onClick={() => setFilter("action")}>Needs action</button></div></div></div>
      <div className="jobs-layout">
        <section className="surface jobs-table">
          <div className="table-header job-grid"><span>Job</span><span>Status</span><span>Progress</span><span>Created</span></div>
          {filtered.map((job) => (
            <button key={job.id} className={`data-row job-grid ${selected?.id === job.id ? "selected" : ""}`} onClick={() => setSelectedId(job.id)}>
              <span><strong>{job.title}</strong><small>{job.job_type.replaceAll("_", " ")}</small></span><StatusPill value={job.status} /><span className="progress-cell"><span><i style={{ width: `${job.progress}%` }} /></span><small>{job.progress}%</small></span><span>{new Date(job.created_at).toLocaleString()}</span>
            </button>
          ))}
        </section>
        <aside className="surface trace-panel">
          {selected ? <><div className="section-heading compact"><div><span className="eyebrow">RUN TRACE</span><h3>{selected.title}</h3></div><StatusPill value={selected.status} /></div>{["DRAFT", "PLANNING", "QUEUED", "RUNNING", "WAITING_FOR_APPROVAL", "RETRYING"].includes(selected.status) && <div className="trace-actions"><button className="danger-button" onClick={cancelSelected}><XCircle size={16} />Cancel job</button></div>}{["FAILED", "CANCELLED", "PARTIALLY_SUCCEEDED"].includes(selected.status) && <div className="trace-actions"><button className="secondary-button" onClick={diagnoseSelected}><AlertCircle size={16} />Diagnose</button><button className="primary-button" onClick={retrySelected}><RefreshCw size={16} />Retry</button></div>}<div className="trace-list">{selected.plan.map((step, index) => <div key={`${step.step_index ?? index}-${step.agent}`} className={step.status === "skipped" ? "skipped" : undefined}><span className={`trace-dot ${step.status}`} /> <span><strong>{step.agent}</strong><small>{step.action}</small>{step.status === "skipped" && <small className="skip-reason">Skipped{step.skip_reason ? `: ${step.skip_reason}` : ""}</small>}</span>{step.status === "skipped" ? <span className="status-pill neutral">skipped</span> : <StatusPill value={step.status} />}</div>)}</div><div className="subheading"><h4>Evidence</h4><span>{selected.evidence.length}</span></div><div className="evidence-list">{selected.evidence.map((item, index) => <span key={index}><Layers3 size={15} />{item.label}</span>)}</div><div className="subheading"><h4>Step outputs</h4><span>{selected.outputs?.length || 0}</span></div>{selected.outputs?.length ? <div className="log-list">{(selected.outputs || []).map((output, index) => <div key={`${output.at || output.title || output.type}-${index}`} className={output.type === "step_skipped" || output.type === "plan_only" ? "muted-output" : undefined}><Layers3 size={14} /><span><strong>{output.title || OUTPUT_LABELS[output.type] || output.type}</strong><small>{[output.agent, output.tool, output.summary, output.at ? new Date(output.at).toLocaleString() : ""].filter(Boolean).join(" / ")}</small>{output.data ? <pre className="trace-output-data">{JSON.stringify(output.data, null, 2)}</pre> : null}</span></div>)}</div> : <div className="inline-empty trace-empty">No step outputs were captured for this run.</div>}<div className="subheading"><h4>Execution log</h4><span>{selected.logs?.length || 0}</span></div><div className="log-list">{(selected.logs || []).map((entry, index) => <div key={`${entry.at}-${index}`}><Clock3 size={14} /><span><strong>{entry.message}</strong><small>{new Date(entry.at).toLocaleString()} / {entry.level}</small></span></div>)}</div>{incidents.filter((incident) => incident.job_id === selected.id).map((incident) => <div className="incident-box" key={incident.id}><div><AlertCircle size={17} /><strong>{incident.title}</strong><StatusPill value={incident.status} /></div><p>{incident.root_cause}</p>{incident.remediation.map((item) => <small key={item}>{item}</small>)}</div>)}</> : jobsQuery.isPending ? <LoadingBlock /> : <div className="inline-empty trace-empty">No jobs in this project yet.</div>}
        </aside>
      </div>
    </div>
  );
}
