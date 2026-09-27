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
import { ACTIVE_JOB_STATES, hasActiveJob, scopes, useDebouncedValue, useFacets, useInvalidate, usePagedQuery, usePagination, useProjectQuery, useQueryErrorToast, withParams, type Facet, type Paged, type PageParams } from "../lib/queries";
import { StatusPill, LoadingBlock, CollapsibleGroup, GroupBySelect, Pagination, useConfirm } from "./shared";
import { useWorkspace } from "../lib/workspace";


const OUTPUT_LABELS: Record<string, string> = { step_skipped: "Step skipped", plan_only: "Plan only (not executed)", tool_choice: "Tool choice" };
const NO_JOBS: Job[] = [];
const NO_INCIDENTS: Incident[] = [];
const FILTER_STATUSES = { all: "", running: "RUNNING,QUEUED,PLANNING", action: "WAITING_FOR_APPROVAL,FAILED" } as const;
// Pages poll every 2 s only while a job on them is active (paused while the tab is hidden).
const pollActive = { staleTime: 0, refetchInterval: (query: { state: { data?: Paged<Job> } }) => (hasActiveJob(query.state.data?.items) ? 2000 : false) };
const typeLabel = (value: string) => value.replaceAll("_", " ");

function JobRows({ jobs, selectedId, onSelect }: { jobs: Job[]; selectedId?: string; onSelect: (job: Job) => void }) {
  return <>{jobs.map((job) => (
    <button key={job.id} className={`data-row job-grid ${selectedId === job.id ? "selected" : ""}`} onClick={() => onSelect(job)}>
      <span><strong>{job.title}</strong><small>{typeLabel(job.job_type)}</small></span><StatusPill value={job.status} /><span className="progress-cell"><span><i style={{ width: `${job.progress}%` }} /></span><small>{job.progress}%</small></span><span>{new Date(job.created_at).toLocaleString()}</span>
    </button>
  ))}</>;
}

function JobGroupRows({ params, selectedId, onSelect }: { params: PageParams; selectedId?: string; onSelect: (job: Job) => void }) {
  const pagination = usePagination(params, 25);
  const page = usePagedQuery<Job>(scopes.jobs, "/jobs", params, pagination, pollActive);
  const jobs = page.data?.items ?? NO_JOBS;
  if (!jobs.length) return page.isPending ? <LoadingBlock label="Loading jobs" /> : <div className="list-empty">No jobs in this group.</div>;
  return <><JobRows jobs={jobs} selectedId={selectedId} onSelect={onSelect} /><Pagination state={pagination} total={page.data?.total ?? 0} count={jobs.length} busy={page.isFetching} label="jobs" compact /></>;
}

export function JobsView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [confirm, confirmDialog] = useConfirm();
  const { user } = useWorkspace();
  // Operators (jobs:write: admin, engineer) close incidents, like retry and cancel.
  const canOperate = user.role === "admin" || user.role === "engineer";
  const [filter, setFilter] = useState<"all" | "running" | "action">("all");
  const [search, setSearch] = useState("");
  const [groupBy, setGroupBy] = useState<"none" | "job_type">("none");
  const q = useDebouncedValue(search.trim());
  const filters: PageParams = { status: FILTER_STATUSES[filter], q };
  const pagination = usePagination(filters, 50);
  const jobsQuery = usePagedQuery<Job>(scopes.jobs, "/jobs", filters, pagination, { ...pollActive, enabled: groupBy === "none" });
  const jobs = jobsQuery.data?.items ?? NO_JOBS;
  const facets = useFacets<{ total: number; job_type: Facet[] }>(scopes.jobs, groupBy === "none" ? null : "/jobs/facets", filters);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [picked, setPicked] = useState<Job | null>(null);
  const selectedQuery = useProjectQuery<Job>([...scopes.jobs, "one", selectedId], selectedId ? `/jobs/${encodeURIComponent(selectedId)}` : null, {
    staleTime: 0,
    refetchInterval: (query) => (query.state.data && ACTIVE_JOB_STATES.includes(query.state.data.status) ? 2000 : false),
  });
  const selected = (selectedId ? selectedQuery.data || (picked?.id === selectedId ? picked : null) : groupBy === "none" ? jobs[0] : null) || null;
  const selectJob = (job: Job) => { setPicked(job); setSelectedId(job.id); };
  const incidentsQuery = useProjectQuery<Incident[]>([...scopes.incidents, "job", selected?.id], selected ? withParams("/incidents", { job_id: selected.id }) : null);
  const incidents = incidentsQuery.data ?? NO_INCIDENTS;
  useQueryErrorToast(jobsQuery.error || incidentsQuery.error, notify, "Jobs could not be loaded");
  const invalidate = useInvalidate();
  const load = () => invalidate(scopes.jobs, scopes.incidents);
  async function cancelSelected() {
    if (!selected) return;
    try { await api(`/jobs/${selected.id}/cancel`, { method: "POST" }); notify("Job cancelled"); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Job could not be cancelled", "error"); }
  }
  async function retrySelected() { if (!selected) return; try { const result = await api<{ status: string }>(`/jobs/${selected.id}/retry`, { method: "POST" }); notify(`Retry ${result.status.toLowerCase()}`); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Retry failed", "error"); } }
  async function resolveIncident(incident: Incident) {
    if (!(await confirm({ title: "Resolve incident", body: `Mark "${incident.title}" as resolved? The resolution is audited.`, confirmLabel: "Mark resolved", danger: false }))) return;
    try { await api(`/incidents/${incident.id}/resolve`, { method: "POST", body: JSON.stringify({ note: null }) }); notify("Incident resolved"); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Incident could not be resolved", "error"); }
  }
  async function diagnoseSelected() { if (!selected) return; try { await api(`/jobs/${selected.id}/diagnose`, { method: "POST" }); notify("Incident diagnosis recorded"); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Diagnosis failed", "error"); } }
  return (
    <div className="view-stack">
      <div className="view-header"><div><h2>Job operations</h2><p>Inspect state, progress, evidence, and every specialist handoff.</p></div><div className="row-actions"><div className="toolbar-search"><Search size={16} /><input placeholder="Search jobs..." value={search} onChange={(e) => setSearch(e.target.value)} /></div><div className="segmented"><button className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>All</button><button className={filter === "running" ? "active" : ""} onClick={() => setFilter("running")}>Running</button><button className={filter === "action" ? "active" : ""} onClick={() => setFilter("action")}>Needs action</button></div><GroupBySelect value={groupBy} onChange={setGroupBy} options={[{ value: "none", label: "None" }, { value: "job_type", label: "Job type" }]} /></div></div>
      <div className="jobs-layout">
        <section className="surface jobs-table">
          <div className="table-header job-grid"><span>Job</span><span>Status</span><span>Progress</span><span>Created</span></div>
          {groupBy === "none" ? <>
            <JobRows jobs={jobs} selectedId={selected?.id} onSelect={selectJob} />
            {!jobs.length && !jobsQuery.isPending && <div className="list-empty">{q || filter !== "all" ? "No jobs match these filters." : "No jobs in this project yet."}</div>}
            <Pagination state={pagination} total={jobsQuery.data?.total ?? 0} count={jobs.length} busy={jobsQuery.isFetching} label="jobs" />
          </> : !facets.data ? <LoadingBlock label="Grouping jobs" /> : facets.data.job_type.length ? facets.data.job_type.map((facet) => (
            <CollapsibleGroup key={facet.value} title={typeLabel(facet.value)} count={facet.count} defaultOpen={facets.data!.job_type.length === 1}>
              <JobGroupRows params={{ ...filters, job_type: facet.value }} selectedId={selected?.id} onSelect={selectJob} />
            </CollapsibleGroup>
          )) : <div className="list-empty">No jobs match these filters.</div>}
        </section>
        <aside className="surface trace-panel">
          {selected ? <><div className="section-heading compact"><div><span className="eyebrow">RUN TRACE</span><h3>{selected.title}</h3></div><StatusPill value={selected.status} /></div>{selected.status === "SUPERSEDED" && <p className="superseded-note">A later scan of this connector succeeded, so this failure needs no action.</p>}{["DRAFT", "PLANNING", "QUEUED", "RUNNING", "WAITING_FOR_APPROVAL", "RETRYING"].includes(selected.status) && <div className="trace-actions"><button className="danger-button" onClick={cancelSelected}><XCircle size={16} />Cancel job</button></div>}{["FAILED", "CANCELLED", "PARTIALLY_SUCCEEDED"].includes(selected.status) && <div className="trace-actions"><button className="secondary-button" onClick={diagnoseSelected}><AlertCircle size={16} />Diagnose</button><button className="primary-button" onClick={retrySelected}><RefreshCw size={16} />Retry</button></div>}<div className="trace-list">{selected.plan.map((step, index) => <div key={`${step.step_index ?? index}-${step.agent}`} className={step.status === "skipped" ? "skipped" : undefined}><span className={`trace-dot ${step.status}`} /> <span><strong>{step.agent}</strong><small>{step.action}</small>{step.status === "skipped" && <small className="skip-reason">Skipped{step.skip_reason ? `: ${step.skip_reason}` : ""}</small>}</span>{step.status === "skipped" ? <span className="status-pill neutral">skipped</span> : <StatusPill value={step.status} />}</div>)}</div><div className="subheading"><h4>Evidence</h4><span>{selected.evidence.length}</span></div><div className="evidence-list">{selected.evidence.map((item, index) => <span key={index}><Layers3 size={15} />{item.label}</span>)}</div><div className="subheading"><h4>Step outputs</h4><span>{selected.outputs?.length || 0}</span></div>{selected.outputs?.length ? <div className="log-list">{(selected.outputs || []).map((output, index) => <div key={`${output.at || output.title || output.type}-${index}`} className={output.type === "step_skipped" || output.type === "plan_only" ? "muted-output" : undefined}><Layers3 size={14} /><span><strong>{output.title || OUTPUT_LABELS[output.type] || output.type}</strong><small>{[output.agent, output.tool, output.summary, output.at ? new Date(output.at).toLocaleString() : ""].filter(Boolean).join(" / ")}</small>{output.data ? <pre className="trace-output-data">{JSON.stringify(output.data, null, 2)}</pre> : null}</span></div>)}</div> : <div className="inline-empty trace-empty">No step outputs were captured for this run.</div>}<div className="subheading"><h4>Execution log</h4><span>{selected.logs?.length || 0}</span></div><div className="log-list">{(selected.logs || []).map((entry, index) => <div key={`${entry.at}-${index}`}><Clock3 size={14} /><span><strong>{entry.message}{(entry as { repeat?: number }).repeat ? <em className="log-repeat"> ×{(entry as { repeat?: number }).repeat}</em> : null}</strong><small>{new Date(entry.at).toLocaleString()} / {entry.level}</small></span></div>)}</div>{incidents.map((incident) => <div className="incident-box" key={incident.id}><div><AlertCircle size={17} /><strong>{incident.title}</strong><StatusPill value={incident.status} />{incident.status !== "resolved" && <button type="button" className="text-button" disabled={!canOperate} title={canOperate ? "Mark this incident resolved" : "Resolving incidents requires jobs:write (engineer or admin)"} onClick={() => resolveIncident(incident)}>Mark resolved</button>}</div><p>{incident.root_cause}</p>{incident.remediation.map((item) => <small key={item}>{item}</small>)}</div>)}</> : (selectedId && selectedQuery.isPending) || (groupBy === "none" && jobsQuery.isPending) ? <LoadingBlock /> : <div className="inline-empty trace-empty">{groupBy === "none" ? "No jobs in this project yet." : "Select a job to see its run trace."}</div>}
        </aside>
      </div>
      {confirmDialog}
    </div>
  );
}
