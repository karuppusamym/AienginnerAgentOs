"use client";

import {
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Database,
  FlaskConical,
  Gauge,
  GitCompare,
  Lightbulb,
  ListChecks,
  Network,
  Play,
  Plus,
  RefreshCw,
  Route,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  TrendingUp,
  XCircle,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../lib/api";
import {
  isEndpointUnavailable,
  optimizationIsActive,
  scopes,
  useApiMutation,
  useConnectors,
  useDdlSuggestions,
  useEvaluationSets,
  useIndexRecommendations,
  usePromptOptimization,
  usePromptOptimizations,
  useDebouncedValue,
  usePagedQuery,
  usePagination,
  useProjectQuery,
  useQueryErrorToast,
  type Facet,
} from "../lib/queries";
import { useWorkspace, type Notify } from "../lib/workspace";
import { connectorDialectForType } from "../lib/constants";
import type { IndexRecommendation, LearningSuggestion, NavKey, PromptCandidate, PromptOptimizationDetail, RouterDecisionRecord, SlowQuery, SqlTuningDetail, SqlTuningRun, VerifiedQuery } from "../types";
import { EmptyState, EndpointUnavailable, LoadingBlock, Modal, Pagination, StatusPill, formatScore, useConfirm } from "./shared";
import { EvaluationsView } from "./EvaluationsView";

export type LearningTab = "verified" | "optimization" | "indexes" | "router" | "suggestions" | "evaluations";

export const LEARNING_TABS: LearningTab[] = ["verified", "optimization", "indexes", "router", "suggestions", "evaluations"];

const TABS: { key: LearningTab; label: string; icon: typeof Check }[] = [
  { key: "verified", label: "Verified queries", icon: ListChecks },
  { key: "optimization", label: "Prompt optimization", icon: Sparkles },
  { key: "indexes", label: "Performance & DDL suggestions", icon: Database },
  { key: "router", label: "Router & tool choice", icon: Route },
  { key: "suggestions", label: "Suggestions", icon: Lightbulb },
  { key: "evaluations", label: "Evaluations", icon: FlaskConical },
];

/**
 * Tabs a role may open. Learning owns every feedback loop (docs/UX_CONSOLIDATION.md §4.2):
 * suggestion review stays admin-only (as the API enforces), the curation tabs are
 * admin/engineer, and Evaluations (the former /evaluations page) stays open to every role.
 */
export function learningTabsFor(role: string, hidden: string[] = []): LearningTab[] {
  return learningTabsForRole(role).filter((tab) => !hidden.includes(`learning:${tab}`));
}

function learningTabsForRole(role: string): LearningTab[] {
  if (role === "admin") return LEARNING_TABS;
  if (role === "engineer") return LEARNING_TABS.filter((tab) => tab !== "suggestions");
  return ["evaluations"];
}

const when = (value?: string | null) => (value ? new Date(value).toLocaleString() : "-");
const shortId = (value?: string | null) => (value ? value.slice(0, 8) : "-");

/**
 * Learning & quality: the loop that turns feedback and evaluations into verified
 * examples, optimised prompts (GEPA), index DDL suggestions (advice for a DBA, never
 * executed automatically) and router policy — every runtime change goes through Approvals.
 */
export function LearningView({ notify, tab, onTab, runId, onRun, role = "admin" }: {
  notify: Notify;
  tab: LearningTab;
  onTab: (tab: LearningTab) => void;
  runId: string;
  onRun: (id: string) => void;
  role?: string;
}) {
  const { user } = useWorkspace();
  const allowed = learningTabsFor(role, user.hidden_screens || []);
  return (
    <div className="view-stack">
      <div className="view-header">
        <div>
          <h2>Learning and quality</h2>
          <p>Curate verified queries, optimise the SQL-generation prompt against evaluation cases, review performance (index DDL) suggestions, routing decisions, feedback-derived suggestions and evaluation sets. Changes that alter runtime behaviour are sent to Approvals; index DDL is only ever a suggestion for a DBA.</p>
        </div>
      </div>
      <div className="tabs" role="tablist" aria-label="Learning sections">
        {TABS.filter((item) => allowed.includes(item.key)).map((item) => {
          const Icon = item.icon;
          return <button key={item.key} role="tab" aria-selected={tab === item.key} className={tab === item.key ? "active" : ""} onClick={() => onTab(item.key)}><Icon size={16} />{item.label}</button>;
        })}
      </div>
      {tab === "verified" && <VerifiedQueriesPanel notify={notify} />}
      {tab === "optimization" && <PromptOptimizationPanel notify={notify} runId={runId} onRun={onRun} />}
      {tab === "indexes" && <PerformancePanel notify={notify} />}
      {tab === "router" && (
        <>
          <RouterDecisionsPanel notify={notify} />
          <RouterEvaluationPanel notify={notify} />
          <ToolChoiceEvaluationPanel notify={notify} />
        </>
      )}
      {tab === "suggestions" && <LearningSuggestionsPanel notify={notify} />}
      {tab === "evaluations" && <EvaluationsView notify={notify} embedded />}
    </div>
  );
}

// ------------------------------------------------------------------ verified queries

const VERIFIED_STATUS_FILTERS = ["all", "active", "needs_review", "retired"] as const;
type VerifiedFilter = (typeof VERIFIED_STATUS_FILTERS)[number];
const EMPTY_VERIFIED_FORM = { question: "", sql: "", dialect: "postgres", connector_id: "" };

function VerifiedQueriesPanel({ notify }: { notify: Notify }) {
  const connectors = useConnectors().data;
  const [confirm, confirmDialog] = useConfirm();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<VerifiedFilter>("all");
  const needle = useDebouncedValue(search.trim());
  const filters = { status: status === "all" ? "" : status, q: needle };
  const pagination = usePagination(filters, 50);
  const query = usePagedQuery<VerifiedQuery>(scopes.verifiedQueries, "/verified-queries", filters, pagination);
  const facets = useProjectQuery<{ total: number; status: Facet[] }>([...scopes.verifiedQueries, "facets"], "/verified-queries/facets");
  const [openId, setOpenId] = useState("");
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState(EMPTY_VERIFIED_FORM);
  const [formError, setFormError] = useState("");
  useQueryErrorToast(query.error, notify, "Verified queries could not be loaded", { ignoreUnavailable: true });
  const setStatusMutation = useApiMutation(({ id, status: next }: { id: string; status: string }) => api(`/verified-queries/${id}`, { method: "PUT", body: JSON.stringify({ status: next }) }), [scopes.verifiedQueries]);
  const removeMutation = useApiMutation((id: string) => api(`/verified-queries/${id}`, { method: "DELETE" }), [scopes.verifiedQueries]);
  const createMutation = useApiMutation((body: { question: string; sql: string; dialect: string; connector_id?: string }) => api<VerifiedQuery>("/verified-queries", { method: "POST", body: JSON.stringify(body) }), [scopes.verifiedQueries]);

  const filtered = useMemo(() => query.data?.items ?? [], [query.data]);
  const counts = useMemo(() => {
    const result: Record<string, number> = { all: facets.data?.total ?? 0 };
    for (const facet of facets.data?.status ?? []) result[facet.value] = facet.count;
    return result;
  }, [facets.data]);

  async function changeStatus(item: VerifiedQuery, next: "active" | "retired") {
    try {
      await setStatusMutation.mutateAsync({ id: item.id, status: next });
      notify(next === "active" ? "Verified query promoted to active" : "Verified query retired");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Status could not be changed", "error"); }
  }
  async function remove(item: VerifiedQuery) {
    if (!(await confirm({ title: "Delete verified query", body: `Delete "${item.question}"? It will no longer be used as an example or reused as an answer. Retiring keeps the history instead.` }))) return;
    try {
      await removeMutation.mutateAsync(item.id);
      notify("Verified query deleted");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Verified query could not be deleted", "error"); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setFormError("");
    try {
      await createMutation.mutateAsync({ question: form.question.trim(), sql: form.sql.trim(), dialect: form.dialect, ...(form.connector_id ? { connector_id: form.connector_id } : {}) });
      setAdding(false);
      setForm(EMPTY_VERIFIED_FORM);
      notify("Verified query added");
    } catch (reason) {
      // 422 = the SQL failed validation; show the API's reason next to the form.
      setFormError(reason instanceof ApiError && reason.status === 422 ? `SQL failed validation: ${reason.message}` : reason instanceof Error ? reason.message : "Verified query could not be saved");
    }
  }

  if (isEndpointUnavailable(query.error)) return <section className="surface admin-surface"><EndpointUnavailable feature="Verified queries" endpoint="GET /api/verified-queries" /></section>;
  const busy = setStatusMutation.isPending || removeMutation.isPending;
  return (
    <section className="surface admin-surface">
      <div className="section-heading">
        <div><span className="eyebrow">FEW-SHOT MEMORY</span><h3>Verified queries</h3><p>Question and SQL pairs confirmed by feedback, evaluations, optimisation or a reviewer. Active entries are used as examples and can be reused as answers; entries needing review are not used until promoted.</p></div>
        <div className="row-actions">
          <div className="toolbar-search"><Search size={16} /><input placeholder="Search question or SQL..." value={search} onChange={(event) => setSearch(event.target.value)} aria-label="Search verified queries" /></div>
          <select value={status} onChange={(event) => setStatus(event.target.value as VerifiedFilter)} aria-label="Filter by status">
            {VERIFIED_STATUS_FILTERS.map((value) => <option key={value} value={value}>{value === "all" ? "All statuses" : value.replaceAll("_", " ")} ({counts[value] || 0})</option>)}
          </select>
          <button className="primary-button" onClick={() => { setForm(EMPTY_VERIFIED_FORM); setFormError(""); setAdding(true); }}><Plus size={16} />Add verified query</button>
        </div>
      </div>
      {query.isPending ? <LoadingBlock label="Loading verified queries" /> : filtered.length ? (
        <>
          <div className="table-header verified-grid"><span>Question</span><span>Dialect</span><span>Status</span><span>Uses</span><span>Last used</span><span /></div>
          {filtered.map((item) => {
            const open = openId === item.id;
            return (
              <div key={item.id}>
                <div className={`data-row verified-grid${open ? " selected" : ""}`}>
                  <span>
                    <button type="button" className="row-toggle" aria-expanded={open} onClick={() => setOpenId(open ? "" : item.id)} title={open ? "Hide SQL" : "Show SQL"}>
                      {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}<strong>{item.question}</strong>
                    </button>
                    <small>{item.source} · added {new Date(item.created_at).toLocaleDateString()}</small>
                  </span>
                  <span className="mono">{item.dialect}</span>
                  <StatusPill value={item.status} />
                  <span className="mono">{item.uses}</span>
                  <span>{item.last_used_at ? new Date(item.last_used_at).toLocaleDateString() : "never"}</span>
                  <span className="row-actions">
                    {item.status !== "active" && <button className="icon-button" title="Promote to active" aria-label={`Promote ${item.question}`} disabled={busy} onClick={() => void changeStatus(item, "active")}><Check size={16} /></button>}
                    {item.status !== "retired" && <button className="icon-button" title="Retire" aria-label={`Retire ${item.question}`} disabled={busy} onClick={() => void changeStatus(item, "retired")}><XCircle size={16} /></button>}
                    <button className="icon-button danger" title="Delete" aria-label={`Delete ${item.question}`} disabled={busy} onClick={() => void remove(item)}><Trash2 size={16} /></button>
                  </span>
                </div>
                {open && (
                  <div className="row-detail">
                    <pre className="inspector-sql">{item.sql}</pre>
                    <small className="caption">Connector: {connectors?.find((connector) => connector.id === item.connector_id)?.name || (item.connector_id ? shortId(item.connector_id) : "DataPilot workspace")} · last used {when(item.last_used_at)}</small>
                  </div>
                )}
              </div>
            );
          })}
          <Pagination state={pagination} total={query.data?.total ?? 0} count={filtered.length} busy={query.isFetching} label="verified queries" />
        </>
      ) : <div className="inline-empty">{counts.all ? "No verified queries match these filters." : "No verified queries yet. Helpful feedback and passing evaluation cases add them for review."}</div>}
      {adding && (
        <Modal title="Add verified query" onClose={() => setAdding(false)}>
          <form className="modal-form" onSubmit={submit}>
            <label>Question<textarea rows={2} value={form.question} onChange={(event) => setForm({ ...form, question: event.target.value })} required maxLength={2000} autoFocus /></label>
            <label>SQL<textarea className="mono-input" rows={8} value={form.sql} onChange={(event) => setForm({ ...form, sql: event.target.value })} required spellCheck={false} /></label>
            <div className="form-grid">
              <label>Dialect<select value={form.dialect} onChange={(event) => setForm({ ...form, dialect: event.target.value })}><option value="postgres">PostgreSQL</option><option value="sqlserver">SQL Server</option><option value="oracle">Oracle</option><option value="teradata">Teradata</option><option value="bigquery">BigQuery</option></select></label>
              <label>Data source<select value={form.connector_id} onChange={(event) => { const connector = connectors?.find((item) => item.id === event.target.value); setForm({ ...form, connector_id: event.target.value, dialect: connector ? connectorDialectForType(connector.connector_type) : form.dialect }); }}><option value="">DataPilot workspace</option>{(connectors || []).filter((connector) => connector.connector_type !== "local_files").map((connector) => <option key={connector.id} value={connector.id}>{connector.name}</option>)}</select></label>
            </div>
            <p className="modal-hint">The SQL is validated by the same read-only guard used for generated SQL before it is stored.</p>
            {formError && <p className="form-error" role="alert">{formError}</p>}
            <div className="modal-actions">
              <button type="button" className="secondary-button" onClick={() => setAdding(false)}>Cancel</button>
              <button className="primary-button" disabled={createMutation.isPending}>{createMutation.isPending ? <RefreshCw size={16} className="spin" /> : <Check size={16} />}Add verified query</button>
            </div>
          </form>
        </Modal>
      )}
      {confirmDialog}
    </section>
  );
}

// ------------------------------------------------------------------ prompt optimization (GEPA)

function clampInt(value: number, min: number, max: number, fallback: number) {
  return Number.isFinite(value) ? Math.min(max, Math.max(min, Math.round(value))) : fallback;
}

function PromptOptimizationPanel({ notify, runId, onRun }: { notify: Notify; runId: string; onRun: (id: string) => void }) {
  const runs = usePromptOptimizations();
  const evaluations = useEvaluationSets();
  const [form, setForm] = useState({ purpose: "sql_generation", iterations: 4, minibatch: 4, evaluation_set_id: "" });
  useQueryErrorToast(runs.error, notify, "Optimization runs could not be loaded", { ignoreUnavailable: true });
  const start = useApiMutation((body: { purpose: string; iterations: number; minibatch: number; evaluation_set_id?: string }) => api<{ id: string; status: string }>("/prompt-optimizations", { method: "POST", body: JSON.stringify(body) }), [scopes.promptOptimizations]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      const created = await start.mutateAsync({
        purpose: form.purpose,
        iterations: clampInt(form.iterations, 1, 8, 4),
        minibatch: clampInt(form.minibatch, 2, 8, 4),
        ...(form.evaluation_set_id ? { evaluation_set_id: form.evaluation_set_id } : {}),
      });
      notify(`Optimization ${created.status || "queued"}`);
      onRun(created.id);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Optimization could not be started", "error"); }
  }

  if (isEndpointUnavailable(runs.error)) return <section className="surface admin-surface"><EndpointUnavailable feature="Prompt optimization" endpoint="GET /api/prompt-optimizations" /></section>;
  const list = runs.data ?? [];
  const selectedId = runId || list[0]?.id || "";
  return (
    <div className="learning-split">
      <div className="learning-column">
        <section className="surface admin-surface">
          <div className="section-heading compact"><div><span className="eyebrow">GEPA</span><h3>Start optimization</h3><p>Reflective prompt evolution over evaluation cases. The best candidate is only proposed; activation requires approval.</p></div></div>
          <form className="modal-form learning-form" onSubmit={submit}>
            <label>Purpose<select value={form.purpose} onChange={(event) => setForm({ ...form, purpose: event.target.value })}><option value="sql_generation">SQL generation</option></select></label>
            <div className="form-grid">
              <label>Iterations (1-8)<input type="number" min={1} max={8} value={form.iterations} onChange={(event) => setForm({ ...form, iterations: Number(event.target.value) })} required /></label>
              <label>Minibatch (2-8)<input type="number" min={2} max={8} value={form.minibatch} onChange={(event) => setForm({ ...form, minibatch: Number(event.target.value) })} required /></label>
            </div>
            <label>Evaluation set<select value={form.evaluation_set_id} onChange={(event) => setForm({ ...form, evaluation_set_id: event.target.value })}><option value="">Default (verified queries and evaluation cases)</option>{(evaluations.data || []).map((set) => <option key={set.id} value={set.id}>{set.name} ({set.cases.length} case{set.cases.length === 1 ? "" : "s"})</option>)}</select></label>
            <div className="form-end"><button className="primary-button" disabled={start.isPending}>{start.isPending ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}Start optimization</button></div>
          </form>
        </section>
        <section className="surface admin-surface">
          <div className="section-heading compact"><div><span className="eyebrow">RUNS</span><h3>Optimization runs</h3></div>{list.some((run) => optimizationIsActive(run.status)) && <span className="caption"><RefreshCw size={12} className="spin" /> updating</span>}</div>
          {runs.isPending ? <LoadingBlock label="Loading runs" /> : list.length ? list.map((run) => {
            const total = run.iterations || 0;
            const done = Math.min(run.iterations_done || 0, total || Infinity);
            return (
              <button key={run.id} type="button" className={`data-row run-row${run.id === selectedId ? " selected" : ""}`} onClick={() => onRun(run.id)} aria-current={run.id === selectedId ? "true" : undefined}>
                <span><strong>{run.purpose.replaceAll("_", " ")}</strong><small>{when(run.created_at)}</small></span>
                <span className="run-scores">{formatScore(run.baseline_score)} <TrendingUp size={12} /> {formatScore(run.best_score)}</span>
                <span className="progress-cell"><span><i style={{ width: `${total ? Math.round((done / total) * 100) : 0}%` }} /></span><small>{done}/{total || "-"}</small></span>
                <StatusPill value={run.status} />
              </button>
            );
          }) : <div className="inline-empty">No optimization runs yet.</div>}
        </section>
      </div>
      <div className="learning-column">
        {selectedId ? <OptimizationDetail key={selectedId} id={selectedId} notify={notify} /> : <section className="surface admin-surface"><EmptyState icon={<Sparkles size={24} />} title="No run selected" body="Start an optimization or pick a run to see score progression, Pareto-front candidates and the instruction diff." /></section>}
      </div>
    </div>
  );
}

function OptimizationDetail({ id, notify }: { id: string; notify: Notify }) {
  const detail = usePromptOptimization(id);
  const [candidateId, setCandidateId] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [applied, setApplied] = useState<{ approval_id: string; prompt_version: number } | null>(null);
  useQueryErrorToast(detail.error, notify, "Optimization run could not be loaded", { ignoreUnavailable: true });
  const apply = useApiMutation((candidate_id: string) => api<{ approval_id: string; prompt_version: number }>(`/prompt-optimizations/${id}/apply`, { method: "POST", body: JSON.stringify({ candidate_id }) }), [scopes.approvals, scopes.promptOptimizations]);

  if (isEndpointUnavailable(detail.error)) return <section className="surface admin-surface"><EndpointUnavailable feature="Optimization run detail" endpoint={`GET /api/prompt-optimizations/${id}`} /></section>;
  if (detail.isPending) return <section className="surface admin-surface"><LoadingBlock label="Loading optimization run" /></section>;
  const run = detail.data;
  if (!run) return <section className="surface admin-surface"><div className="inline-empty">This run could not be loaded.</div></section>;

  const candidates = run.candidates || [];
  const baseline = candidates.find((item) => item.origin === "baseline") || candidates[0];
  const bestId = run.best_candidate_id || [...candidates].sort((a, b) => (b.mean_score ?? -1) - (a.mean_score ?? -1))[0]?.id || "";
  const selected = candidates.find((item) => item.id === candidateId) || candidates.find((item) => item.id === bestId) || baseline;
  const front = candidates.filter((item) => item.on_pareto_front);
  const listed = showAll ? candidates : (front.length ? front : candidates);
  const active = optimizationIsActive(run.status);
  const canApply = run.status === "completed" && !!selected && selected.id !== baseline?.id;

  async function applyCandidate() {
    if (!selected) return;
    try {
      const result = await apply.mutateAsync(selected.id);
      setApplied(result);
      notify(`Prompt v${result.prompt_version} sent to Approvals for activation`);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Candidate could not be applied", "error"); }
  }

  return (
    <>
      <section className="surface admin-surface">
        <div className="section-heading compact">
          <div><span className="eyebrow">RUN {shortId(run.id)}</span><h3>{run.purpose.replaceAll("_", " ")}</h3><p>Started {when(run.created_at)}{run.completed_at ? ` · finished ${when(run.completed_at)}` : ""}</p></div>
          <span className="row-actions">{active && <RefreshCw size={14} className="spin" aria-label="Running" />}<StatusPill value={run.status} /></span>
        </div>
        {run.error && <p className="form-error learning-pad" role="alert">{run.error}</p>}
        <dl className="fact-grid learning-facts">
          <div><dt>Baseline</dt><dd>{formatScore(run.baseline_score)}</dd></div>
          <div><dt>Best</dt><dd>{formatScore(run.best_score)}</dd></div>
          <div><dt>Improvement</dt><dd>{run.best_score != null && run.baseline_score != null ? `${run.best_score - run.baseline_score >= 0 ? "+" : ""}${formatScore(run.best_score - run.baseline_score, true)}` : "-"}</dd></div>
          <div><dt>Iterations</dt><dd>{run.iterations_done ?? 0} / {run.iterations ?? "-"}</dd></div>
          <div><dt>Candidates</dt><dd>{candidates.length} ({front.length} on Pareto front)</dd></div>
          <div><dt>Cases</dt><dd>{run.cases?.length ?? 0}</dd></div>
        </dl>
        <div className="subheading"><h4>Score progression</h4><span>mean score per candidate, in order proposed</span></div>
        <ScoreProgression candidates={candidates} baselineScore={run.baseline_score ?? baseline?.mean_score ?? null} selectedId={selected?.id} onSelect={setCandidateId} />
      </section>

      <section className="surface admin-surface">
        <div className="section-heading compact">
          <div><span className="eyebrow">PARETO FRONT</span><h3>Candidates</h3><p>A candidate is on the front when no other candidate scores at least as well on every case.</p></div>
          <label className="check-option"><input type="checkbox" checked={showAll} onChange={(event) => setShowAll(event.target.checked)} />Show all {candidates.length}</label>
        </div>
        {listed.length ? (
          <>
            <div className="table-header candidate-grid"><span>Candidate</span><span>Origin</span><span>Parent</span><span>Mean score</span><span /></div>
            {listed.map((item) => (
              <button key={item.id} type="button" className={`data-row candidate-grid${item.id === selected?.id ? " selected" : ""}`} onClick={() => setCandidateId(item.id)} aria-pressed={item.id === selected?.id}>
                <span><strong>{shortId(item.id)}{item.id === bestId ? " · best" : ""}</strong><small>{item.instructions.split("\n")[0].slice(0, 90)}</small></span>
                <span>{item.origin || "-"}</span>
                <span className="mono">{item.parent_id ? shortId(item.parent_id) : "-"}</span>
                <span className="mono">{formatScore(item.mean_score)}</span>
                <span>{item.on_pareto_front && <span className="chip">front</span>}</span>
              </button>
            ))}
          </>
        ) : <div className="inline-empty">{active ? "Candidates appear as the run proposes them." : "No candidates were recorded."}</div>}
        {selected && (
          <div className="apply-bar">
            <span><strong>Selected {shortId(selected.id)}</strong><small>{selected.id === baseline?.id ? "This is the baseline prompt." : `Mean score ${formatScore(selected.mean_score)} vs baseline ${formatScore(baseline?.mean_score ?? run.baseline_score)}`}</small></span>
            {applied ? (
              <span className="caption"><ShieldCheck size={13} /> Prompt v{applied.prompt_version} awaiting approval · <Link className="text-button" href="/approvals">Open Approvals</Link></span>
            ) : (
              <button className="primary-button" disabled={!canApply || apply.isPending} title={run.status !== "completed" ? "Available when the run has completed" : selected.id === baseline?.id ? "Select a non-baseline candidate" : "Request approval to activate this prompt"} onClick={() => void applyCandidate()}>
                {apply.isPending ? <RefreshCw size={16} className="spin" /> : <ShieldCheck size={16} />}Apply (request approval)
              </button>
            )}
          </div>
        )}
      </section>

      {selected && baseline && (
        <section className="surface admin-surface">
          <div className="section-heading compact"><div><span className="eyebrow"><GitCompare size={12} /> DIFF</span><h3>Instructions vs baseline</h3></div></div>
          {selected.id === baseline.id ? <div className="inline-empty">Select a candidate to compare it with the baseline instructions.</div> : <InstructionDiff before={baseline.instructions} after={selected.instructions} />}
        </section>
      )}

      <CaseScoreGrid run={run} candidates={candidates} baselineId={baseline?.id} front={front} selected={selected} />

      {!!run.log?.length && (
        <section className="surface admin-surface">
          <div className="section-heading compact"><div><span className="eyebrow">LOG</span><h3>Optimizer log</h3></div></div>
          <div className="log-list optimizer-log">{run.log.map((entry, index) => <div key={`${entry.at}-${index}`}><span><strong>{entry.message}</strong><small>{when(entry.at)}</small></span></div>)}</div>
        </section>
      )}
    </>
  );
}

/** Mean score per candidate (dots), best-so-far (line) and the baseline (dashed). */
function ScoreProgression({ candidates, baselineScore, selectedId, onSelect }: { candidates: PromptCandidate[]; baselineScore: number | null; selectedId?: string; onSelect: (id: string) => void }) {
  const points = candidates.map((item, index) => ({ item, index, score: item.mean_score ?? null })).filter((point): point is { item: PromptCandidate; index: number; score: number } => point.score != null);
  if (!points.length) return <div className="inline-empty">Scores appear as candidates are evaluated.</div>;
  const width = 480;
  const height = 150;
  const pad = { left: 40, right: 12, top: 12, bottom: 22 };
  const values = [...points.map((point) => point.score), ...(baselineScore != null ? [baselineScore] : [])];
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (max - min < 0.02) { min -= 0.05; max += 0.05; }
  const span = max - min;
  const lastIndex = Math.max(1, candidates.length - 1);
  const x = (index: number) => pad.left + (index / lastIndex) * (width - pad.left - pad.right);
  const y = (value: number) => pad.top + (1 - (value - min) / span) * (height - pad.top - pad.bottom);
  let best = -Infinity;
  const bestPath = points.map((point, order) => {
    best = Math.max(best, point.score);
    return `${order === 0 ? "M" : "L"}${x(point.index).toFixed(1)},${y(best).toFixed(1)}`;
  }).join(" ");
  return (
    <div className="score-progression">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Mean score for ${points.length} candidates, best ${formatScore(Math.max(...points.map((point) => point.score)))}`}>
        <line className="axis" x1={pad.left} x2={width - pad.right} y1={height - pad.bottom} y2={height - pad.bottom} />
        <text className="axis-label" x={pad.left - 6} y={y(max) + 4} textAnchor="end">{formatScore(max)}</text>
        <text className="axis-label" x={pad.left - 6} y={y(min) + 4} textAnchor="end">{formatScore(min)}</text>
        {baselineScore != null && <line className="baseline" x1={pad.left} x2={width - pad.right} y1={y(baselineScore)} y2={y(baselineScore)} />}
        <path className="best-line" d={bestPath} />
        {points.map((point) => (
          <circle
            key={point.item.id}
            className={`point${point.item.on_pareto_front ? " front" : ""}${point.item.id === selectedId ? " selected" : ""}`}
            cx={x(point.index)}
            cy={y(point.score)}
            r={point.item.id === selectedId ? 6 : 4.5}
            onClick={() => onSelect(point.item.id)}
          >
            <title>{`${shortId(point.item.id)} · ${point.item.origin || "candidate"} · ${formatScore(point.score)}${point.item.on_pareto_front ? " · Pareto front" : ""}`}</title>
          </circle>
        ))}
        <text className="axis-label" x={pad.left} y={height - 6}>1</text>
        <text className="axis-label" x={width - pad.right} y={height - 6} textAnchor="end">{candidates.length}</text>
      </svg>
      <div className="score-legend"><span><i className="legend-best" />best so far</span><span><i className="legend-baseline" />baseline</span><span><i className="legend-front" />Pareto front</span></div>
    </div>
  );
}

type DiffLine = { kind: "same" | "add" | "del"; text: string };

/** Line-level LCS diff (instructions are short; very large inputs fall back to replace-all). */
export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.split("\n");
  const b = after.split("\n");
  if (a.length * b.length > 400_000) return [...a.map((text) => ({ kind: "del" as const, text })), ...b.map((text) => ({ kind: "add" as const, text }))];
  const table = Array.from({ length: a.length + 1 }, () => new Uint32Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const lines: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { lines.push({ kind: "same", text: a[i] }); i += 1; j += 1; }
    else if (table[i + 1][j] >= table[i][j + 1]) { lines.push({ kind: "del", text: a[i] }); i += 1; }
    else { lines.push({ kind: "add", text: b[j] }); j += 1; }
  }
  while (i < a.length) { lines.push({ kind: "del", text: a[i] }); i += 1; }
  while (j < b.length) { lines.push({ kind: "add", text: b[j] }); j += 1; }
  return lines;
}

function InstructionDiff({ before, after }: { before: string; after: string }) {
  const lines = useMemo(() => lineDiff(before, after), [before, after]);
  const added = lines.filter((line) => line.kind === "add").length;
  const removed = lines.filter((line) => line.kind === "del").length;
  return (
    <div className="instruction-diff">
      <div className="diff-summary"><span className="diff-add-count">+{added}</span> <span className="diff-del-count">-{removed}</span> lines</div>
      <pre aria-label="Instruction diff">
        {lines.map((line, index) => <span key={index} className={`diff-line diff-${line.kind}`}><b aria-hidden="true">{line.kind === "add" ? "+" : line.kind === "del" ? "-" : " "}</b>{line.text || " "}{"\n"}</span>)}
      </pre>
    </div>
  );
}

/** Per-case scores for the baseline, the Pareto front and the selected candidate. */
function CaseScoreGrid({ run, candidates, baselineId, front, selected }: { run: PromptOptimizationDetail; candidates: PromptCandidate[]; baselineId?: string; front: PromptCandidate[]; selected?: PromptCandidate }) {
  const cases = run.cases || [];
  const columns = useMemo(() => {
    const ids = new Set<string>();
    const picked: PromptCandidate[] = [];
    const add = (item?: PromptCandidate) => { if (item && !ids.has(item.id) && picked.length < 7) { ids.add(item.id); picked.push(item); } };
    add(candidates.find((item) => item.id === baselineId));
    add(selected);
    front.forEach(add);
    return picked;
  }, [candidates, baselineId, front, selected]);
  if (!cases.length || !columns.length) return null;
  return (
    <section className="surface admin-surface">
      <div className="section-heading compact"><div><span className="eyebrow">CASES</span><h3>Per-case scores</h3><p>Baseline, selected candidate and Pareto front (up to 7 columns).</p></div></div>
      <div className="case-grid-scroll">
        <table className="case-grid">
          <thead><tr><th scope="col">Case</th>{columns.map((item) => <th key={item.id} scope="col" className={item.id === selected?.id ? "selected" : undefined} title={item.id}>{item.id === baselineId ? "baseline" : shortId(item.id)}</th>)}</tr></thead>
          <tbody>
            {cases.map((item) => (
              <tr key={item.id}>
                <th scope="row" title={item.question}><span>{item.question}</span>{item.source && <small>{item.source}</small>}</th>
                {columns.map((candidate) => {
                  const score = candidate.scores?.[item.id];
                  const level = score == null ? null : Math.max(0, Math.min(1, score > 1 ? score / 100 : score));
                  return <td key={candidate.id} className={level == null ? "empty" : undefined} style={level == null ? undefined : { ["--score" as string]: level.toFixed(2) }}>{score == null ? "-" : formatScore(score)}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ performance & DDL suggestions

const indexKey = (item: { relation: string; columns: string[] }) => `${item.relation}(${item.columns.join(",")})`;
const formatMs = (value?: number | null) => (value == null || !Number.isFinite(value) ? "-" : `${Math.round(value).toLocaleString()} ms`);
type SaveResult = { suggestion_id?: string; statement?: string; executed?: boolean; approval_id?: string };

async function copyText(value: string, notify: Notify, label = "DDL copied") {
  try { await navigator.clipboard.writeText(value); notify(label); } catch { notify("Clipboard unavailable", "error"); }
}

/**
 * DataPilot only runs read queries. When executed queries are slow, the API proposes
 * index DDL; it is saved as a suggestion for a DBA and never executed automatically
 * (a server with DDL execution enabled routes it through Approvals instead).
 */
function PerformancePanel({ notify }: { notify: Notify }) {
  const [includeFast, setIncludeFast] = useState(false);
  const query = useIndexRecommendations(includeFast ? 0 : null);
  const saved = useDdlSuggestions();
  const [results, setResults] = useState<Record<string, SaveResult>>({});
  const [openKey, setOpenKey] = useState("");
  const [openSaved, setOpenSaved] = useState("");
  const [knownThreshold, setKnownThreshold] = useState<number | null>(null);
  useQueryErrorToast(query.error, notify, "Index recommendations could not be loaded", { ignoreUnavailable: true });
  useQueryErrorToast(saved.error, notify, "Saved DDL suggestions could not be loaded", { ignoreUnavailable: true });
  const save = useApiMutation((item: IndexRecommendation) => api<SaveResult>("/sql/index-recommendations/apply", { method: "POST", body: JSON.stringify({ relation: item.relation, columns: item.columns }) }), [scopes.ddlSuggestions, scopes.approvals, scopes.indexRecommendations]);
  const items = useMemo(() => query.data ?? [], [query.data]);
  // The slow-query threshold arrives with each recommendation; remember it for the empty state.
  const threshold = items.find((item) => item.threshold_ms != null)?.threshold_ms ?? knownThreshold;
  useEffect(() => { if (threshold != null && threshold !== knownThreshold) setKnownThreshold(threshold); }, [threshold, knownThreshold]);

  async function saveSuggestion(item: IndexRecommendation) {
    try {
      const result = await save.mutateAsync(item);
      setResults((current) => ({ ...current, [indexKey(item)]: result }));
      notify(result.approval_id ? `DDL execution is enabled on this server: the index on ${item.relation} was sent to Approvals` : `DDL suggestion for ${item.relation} saved for DBA review. Nothing was executed.`);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Suggestion could not be saved", "error"); }
  }

  if (isEndpointUnavailable(query.error)) return <section className="surface admin-surface"><EndpointUnavailable feature="Index recommendations" endpoint="GET /api/sql/index-recommendations" /></section>;
  const savedItems = saved.data ?? [];
  return (
    <>
      <section className="surface admin-surface">
        <div className="section-heading">
          <div>
            <span className="eyebrow">QUERY PERFORMANCE</span>
            <h3>Performance &amp; DDL suggestions</h3>
            <p>DataPilot only runs read queries. When queries are slow it suggests index DDL for a DBA to review; DDL is never run automatically.</p>
          </div>
          <div className="row-actions">
            <label className="check-option" title="Also derive candidates from queries faster than the slow-query threshold"><input type="checkbox" checked={includeFast} onChange={(event) => setIncludeFast(event.target.checked)} />Include fast queries</label>
            <button className="secondary-button" onClick={() => void query.refetch()} disabled={query.isFetching}><RefreshCw size={16} className={query.isFetching ? "spin" : undefined} />Refresh</button>
          </div>
        </div>
        <div className="subheading"><h4>Index recommendations</h4><span>{includeFast ? "Candidates from all recent queries" : `Queries slower than ${threshold != null ? formatMs(threshold) : "the slow-query threshold"}`}</span></div>
        {query.isPending ? <LoadingBlock label="Analysing query history" /> : items.length ? (
          <>
            <div className="table-header perf-grid"><span>Relation</span><span>Columns</span><span>Slow-query evidence</span><span>Status</span><span /></div>
            {items.map((item) => {
              const key = indexKey(item);
              const result = results[key];
              const open = openKey === key;
              const slow = item.slow_queries ?? null;
              const over = item.avg_ms != null && item.threshold_ms != null && item.avg_ms > item.threshold_ms;
              return (
                <div key={key}>
                  <div className={`data-row perf-grid${open ? " selected" : ""}`}>
                    <span>
                      <button type="button" className="row-toggle" aria-expanded={open} onClick={() => setOpenKey(open ? "" : key)} title={open ? "Hide DDL" : "Show DDL"}>{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}<strong>{item.relation}</strong></button>
                      <small>{item.reason}</small>
                      {(item.source || item.dialect) && <small className="perf-source">{item.source === "local" ? "DataPilot workspace" : item.source || "-"}{item.dialect ? ` · ${item.dialect}` : ""}</small>}
                    </span>
                    <span className="mono">{item.columns.join(", ")}</span>
                    <span className="perf-evidence">
                      <strong>{slow != null ? `${slow.toLocaleString()} slow` : `${item.occurrences.toLocaleString()} seen`}{slow != null && <> of {item.occurrences.toLocaleString()}</>}</strong>
                      <small>avg <b className={over ? "perf-over" : undefined}>{formatMs(item.avg_ms)}</b> · max {formatMs(item.max_ms)}{item.threshold_ms != null && <> vs {formatMs(item.threshold_ms)} threshold</>}</small>
                    </span>
                    <StatusPill value={item.exists ? "exists" : result?.approval_id ? "pending" : result ? "saved" : "suggested"} />
                    <span className="row-actions">
                      <button type="button" className="secondary-button compact" onClick={() => void copyText(item.statement, notify)} title="Copy the CREATE INDEX statement"><Copy size={14} />Copy DDL</button>
                      {result?.approval_id ? <Link className="text-button" href="/approvals">In Approvals</Link> : (
                        <button type="button" className="secondary-button compact" disabled={item.exists || !!result || save.isPending} title={item.exists ? "An equivalent index already exists" : result ? "Saved for DBA review" : "Save this DDL for DBA review (it is not executed)"} onClick={() => void saveSuggestion(item)}>{result ? <Check size={14} /> : <Save size={14} />}{result ? "Saved" : "Save suggestion"}</button>
                      )}
                    </span>
                  </div>
                  {open && (
                    <div className="row-detail">
                      <pre className="inspector-sql">{item.statement}</pre>
                      {item.verify_note && <small className="caption"><ShieldCheck size={12} /> {item.verify_note}</small>}
                    </div>
                  )}
                </div>
              );
            })}
          </>
        ) : (
          <div className="inline-empty">
            {includeFast
              ? "No index candidates in the recent workload. They appear once executed queries filter or join on unindexed columns."
              : `No queries slower than ${threshold != null ? formatMs(threshold) : "the slow-query threshold"} in recent workload. Turn on "Include fast queries" to see candidates from every query.`}
          </div>
        )}
      </section>

      <SlowQueriesSection notify={notify} includeFast={includeFast} />

      <section className="surface admin-surface">
        <div className="section-heading compact"><div><span className="eyebrow">FOR DBA REVIEW</span><h3>Saved DDL suggestions</h3><p>Hand these statements to the database owner; DataPilot does not execute them.</p></div>{saved.isFetching && <RefreshCw size={14} className="spin" aria-label="Refreshing" />}</div>
        {isEndpointUnavailable(saved.error) ? <EndpointUnavailable feature="Saved DDL suggestions" endpoint="GET /api/sql/ddl-suggestions" /> : saved.isPending ? <LoadingBlock label="Loading saved suggestions" /> : savedItems.length ? (
          <>
            <div className="table-header ddl-grid"><span>Index</span><span>Dialect</span><span>Saved</span><span /></div>
            {savedItems.map((item) => {
              const open = openSaved === item.id;
              return (
                <div key={item.id}>
                  <div className={`data-row ddl-grid${open ? " selected" : ""}`}>
                    <span>
                      <button type="button" className="row-toggle" aria-expanded={open} onClick={() => setOpenSaved(open ? "" : item.id)} title={open ? "Hide DDL" : "Show DDL"}>{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}<strong>{item.relation} ({item.columns.join(", ")})</strong></button>
                      {item.rationale && <small>{item.rationale}</small>}
                    </span>
                    <span className="mono">{item.dialect || "-"}</span>
                    <span>{new Date(item.created_at).toLocaleDateString()}{item.created_by && <small>by {item.created_by}</small>}</span>
                    <button type="button" className="secondary-button compact" onClick={() => void copyText(item.statement, notify)}><Copy size={14} />Copy DDL</button>
                  </div>
                  {open && <div className="row-detail"><pre className="inspector-sql">{item.statement}</pre></div>}
                </div>
              );
            })}
          </>
        ) : <div className="inline-empty">No saved DDL suggestions yet. Use "Save suggestion" on a recommendation to keep it for DBA review.</div>}
      </section>
    </>
  );
}

// ------------------------------------------------------------------ SQL tuning (equivalent faster rewrites)

const tuningIsActive = (status?: string | null) => status === "QUEUED" || status === "RUNNING";
const sqlKey = (sql: string) => sql.replace(/\s+/g, " ").trim().toLowerCase();
const oneLine = (sql: string, max = 140) => { const flat = sql.replace(/\s+/g, " ").trim(); return flat.length > max ? `${flat.slice(0, max)}…` : flat; };

/**
 * Slow queries and plan-guided tuning: a model proposes rewrites, each is executed and kept only
 * when it returns exactly the original result and is measurably faster. Nothing changes until the
 * winning SQL is approved as the verified query for its question.
 */
function SlowQueriesSection({ notify, includeFast }: { notify: Notify; includeFast: boolean }) {
  const slow = useProjectQuery<SlowQuery[]>(["sql-slow-queries", includeFast], `/sql/slow-queries${includeFast ? "?min_ms=0" : ""}`);
  const runs = useProjectQuery<SqlTuningRun[]>(["sql-tuning"], "/sql/tune", {
    refetchInterval: (query) => ((query.state.data || []).some((run) => tuningIsActive(run.status)) ? 2500 : false),
  });
  const [selectedRun, setSelectedRun] = useState("");
  useQueryErrorToast(slow.error, notify, "Slow queries could not be loaded", { ignoreUnavailable: true });
  const start = useApiMutation((item: SlowQuery) => api<SqlTuningRun>("/sql/tune", { method: "POST", body: JSON.stringify({ query_run_id: item.query_run_id, iterations: 6 }) }), [["sql-tuning"]]);
  const runList = useMemo(() => runs.data ?? [], [runs.data]);
  const anyActive = runList.some((run) => tuningIsActive(run.status));
  const latestBySql = useMemo(() => {
    const map = new Map<string, SqlTuningRun>();
    for (const run of runList) if (!map.has(sqlKey(run.sql))) map.set(sqlKey(run.sql), run);
    return map;
  }, [runList]);

  async function tune(item: SlowQuery) {
    try {
      const run = await start.mutateAsync(item);
      setSelectedRun(run.id);
      notify("Tuning started: rewrites are verified against the original result before they count");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Tuning could not be started", "error"); }
  }

  if (isEndpointUnavailable(slow.error)) return <section className="surface admin-surface"><EndpointUnavailable feature="Slow queries and SQL tuning" endpoint="GET /api/sql/slow-queries" /></section>;
  const items = slow.data ?? [];
  return (
    <>
      <section className="surface admin-surface">
        <div className="section-heading compact">
          <div>
            <span className="eyebrow"><Gauge size={12} /> QUERY TUNING</span>
            <h3>Slow queries</h3>
            <p>Tune asks the model routed to SQL tuning for rewrites guided by the execution plan. A rewrite counts only when it returns exactly the same result and runs faster; no indexes or schema changes are made.</p>
          </div>
          <button className="secondary-button" onClick={() => { void slow.refetch(); void runs.refetch(); }} disabled={slow.isFetching}><RefreshCw size={16} className={slow.isFetching ? "spin" : undefined} />Refresh</button>
        </div>
        {slow.isPending ? <LoadingBlock label="Loading slow queries" /> : items.length ? (
          <>
            <div className="table-header tune-grid"><span>Query</span><span>Source</span><span>Timing</span><span>Last tuning</span><span /></div>
            {items.map((item) => {
              const last = latestBySql.get(sqlKey(item.sql));
              return (
                <div key={item.query_run_id} className="data-row tune-grid">
                  <span><strong className="mono" title={item.sql}>{oneLine(item.sql)}</strong>{item.question && <small>{item.question}</small>}</span>
                  <span className="mono">{item.connector_id ? "connector" : "workspace"} · {item.dialect}</span>
                  <span className="perf-evidence"><strong>avg <b className={item.avg_ms > item.threshold_ms ? "perf-over" : undefined}>{formatMs(item.avg_ms)}</b></strong><small>max {formatMs(item.max_ms)} · {item.count.toLocaleString()} run{item.count === 1 ? "" : "s"}</small></span>
                  <span>{last ? <button type="button" className="text-button" onClick={() => setSelectedRun(last.id)} title="Open this tuning run">{last.speedup_pct != null && last.result === "improved" ? `${last.speedup_pct}% faster` : (last.result || last.status).replaceAll("_", " ").toLowerCase()}</button> : <small className="caption">never tuned</small>}</span>
                  <span className="row-actions">
                    <button type="button" className="secondary-button compact" disabled={anyActive || start.isPending} title={anyActive ? "A tuning run is already in progress" : "Search for a faster rewrite with the same result"} onClick={() => void tune(item)}>
                      {start.isPending && start.variables?.query_run_id === item.query_run_id ? <RefreshCw size={14} className="spin" /> : <Zap size={14} />}Tune
                    </button>
                  </span>
                </div>
              );
            })}
          </>
        ) : <div className="inline-empty">{includeFast ? "No executed queries in the recent workload yet." : "No slow queries in the recent workload. Turn on \"Include fast queries\" to tune any recent query."}</div>}
        {!!runList.length && (
          <>
            <div className="subheading"><h4>Tuning runs</h4><span>most recent first</span></div>
            {runList.slice(0, 8).map((run) => (
              <button key={run.id} type="button" className={`data-row tune-run-grid${run.id === selectedRun ? " selected" : ""}`} onClick={() => setSelectedRun(run.id === selectedRun ? "" : run.id)} aria-pressed={run.id === selectedRun}>
                <span><strong className="mono">{oneLine(run.sql, 110)}</strong><small>{when(run.created_at)}{run.question ? ` · ${run.question}` : ""}</small></span>
                <span className="mono">{formatMs(run.baseline_ms)} → {formatMs(run.best_ms)}</span>
                <span className={run.result === "improved" ? "tune-speedup" : undefined}>{run.result === "improved" && run.speedup_pct != null ? `-${run.speedup_pct}%` : "-"}</span>
                <span className="row-actions">{tuningIsActive(run.status) && <RefreshCw size={14} className="spin" aria-label="Running" />}<StatusPill value={run.result && !tuningIsActive(run.status) ? run.result : run.status.toLowerCase()} /></span>
              </button>
            ))}
          </>
        )}
      </section>
      {selectedRun && <SqlTuningRunView id={selectedRun} notify={notify} />}
    </>
  );
}

function SqlTuningRunView({ id, notify }: { id: string; notify: Notify }) {
  const detail = useProjectQuery<SqlTuningDetail>(["sql-tuning", id], `/sql/tune/${id}`, {
    refetchInterval: (query) => (tuningIsActive(query.state.data?.status) ? 2000 : false),
  });
  const [openAttempt, setOpenAttempt] = useState<number | null>(null);
  const [question, setQuestion] = useState("");
  const [applied, setApplied] = useState<{ approval_id: string } | null>(null);
  useQueryErrorToast(detail.error, notify, "Tuning run could not be loaded", { ignoreUnavailable: true });
  const apply = useApiMutation((payload: { question?: string }) => api<{ approval_id: string }>(`/sql/tune/${id}/apply`, { method: "POST", body: JSON.stringify(payload) }), [scopes.approvals, ["sql-tuning"]]);

  if (detail.isPending) return <section className="surface admin-surface"><LoadingBlock label="Loading tuning run" /></section>;
  const run = detail.data;
  if (!run) return <section className="surface admin-surface"><div className="inline-empty">This tuning run could not be loaded.</div></section>;
  const report = run.report;
  const attempts = report?.attempts ?? [];
  const active = tuningIsActive(run.status);
  const improved = report?.status === "improved" && !!report.winning_sql;
  const needsQuestion = improved && !report?.question;
  const pendingApproval = applied || (run.approval?.status === "pending" ? { approval_id: run.approval.id } : null);
  const lastLog = run.logs[run.logs.length - 1];

  async function requestApproval() {
    try {
      const result = await apply.mutateAsync(needsQuestion ? { question: question.trim() } : {});
      setApplied(result);
      notify("Tuned SQL sent to Approvals; the verified query changes only after approval");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Rewrite could not be applied", "error"); }
  }

  return (
    <section className="surface admin-surface">
      <div className="section-heading compact">
        <div><span className="eyebrow">TUNING RUN {shortId(run.id)}</span><h3>{run.question || "Query tuning"}</h3><p>Started {when(run.created_at)}{report?.model ? ` · model ${report.model}` : ""}{report?.engine ? ` · ${report.engine} (${(report.plan_support || "no plan").replaceAll("_", " ")})` : ""}</p></div>
        <span className="row-actions">{active && <RefreshCw size={14} className="spin" aria-label="Running" />}<StatusPill value={active ? run.status.toLowerCase() : report?.status || run.status.toLowerCase()} /></span>
      </div>
      {active && <p className="caption learning-pad">{run.progress}% · {lastLog?.message || "Queued"}</p>}
      {(report?.error || run.error) && <p className="form-error learning-pad" role="alert">{report?.error || run.error}</p>}
      {report?.baseline && (
        <dl className="fact-grid learning-facts">
          <div><dt>Baseline (median)</dt><dd>{formatMs(report.baseline_ms)}</dd></div>
          <div><dt>Best equivalent</dt><dd>{formatMs(report.best_ms)}</dd></div>
          <div><dt>Speedup</dt><dd className={improved ? "tune-speedup" : undefined}>{improved && report.speedup_pct != null ? `${report.speedup_pct}% faster` : "none found"}</dd></div>
          <div><dt>Attempts</dt><dd>{attempts.length} / {report.settings?.iterations ?? "-"}</dd></div>
          <div><dt>Reference result</dt><dd>{report.baseline.row_count.toLocaleString()} rows · {report.baseline.columns.length} cols{report.order_sensitive ? " · ordered" : ""}</dd></div>
          <div><dt>Stopped</dt><dd>{report.stopped_reason || (active ? "running" : "-")}</dd></div>
        </dl>
      )}
      {!!report?.baseline?.plan_summary?.flags?.length && (
        <div className="learning-pad"><small className="caption">Plan warnings: {report.baseline.plan_summary.flags.join(" · ")}</small></div>
      )}
      {attempts.length ? (
        <>
          <div className="subheading"><h4>Attempts</h4><span>each candidate is executed and compared with the original result before it is timed</span></div>
          <div className="table-header attempt-grid"><span>#</span><span>Time</span><span>Same result</span><span>Outcome</span></div>
          {attempts.map((attempt) => {
            const open = openAttempt === attempt.attempt;
            return (
              <div key={attempt.attempt}>
                <div className={`data-row attempt-grid${open ? " selected" : ""}${attempt.improved ? " attempt-best" : ""}`}>
                  <span><button type="button" className="row-toggle" aria-expanded={open} onClick={() => setOpenAttempt(open ? null : attempt.attempt)} title={open ? "Hide SQL" : "Show SQL"}>{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}<strong>{attempt.attempt}</strong></button></span>
                  <span className="mono">{formatMs(attempt.ms)}</span>
                  <span className={attempt.equivalent ? "tune-ok" : "tune-bad"} aria-label={attempt.equivalent ? "equivalent" : "not equivalent"}>{attempt.equivalent ? <><Check size={14} /> same</> : <><XCircle size={14} /> {attempt.rejected_reason?.startsWith("not equivalent") ? "differs" : "not run"}</>}</span>
                  <span><strong>{attempt.improved ? (report?.winning_attempt === attempt.attempt ? "Winner" : "Improved") : attempt.rejected_reason || "-"}</strong>{attempt.notes && <small>{attempt.notes}</small>}</span>
                </div>
                {open && (
                  <div className="row-detail">
                    <pre className="inspector-sql">{attempt.sql || "(no SQL returned)"}</pre>
                    {!!attempt.runs?.length && <small className="caption">Runs: {attempt.runs.map((ms) => formatMs(ms)).join(", ")}</small>}
                    {!!attempt.plan_summary?.flags?.length && <small className="caption">Plan: {attempt.plan_summary.flags.join(" · ")}</small>}
                  </div>
                )}
              </div>
            );
          })}
        </>
      ) : !report?.error && <div className="inline-empty">{active ? "Attempts appear as the tuner proposes and verifies rewrites." : "No attempts were recorded."}</div>}
      {report?.original_sql && improved && (
        <>
          <div className="subheading"><h4><GitCompare size={13} /> Original vs winning SQL</h4><span>{formatMs(report.baseline_ms)} → {formatMs(report.best_ms)}</span></div>
          <div className="sql-compare">
            <div><small>Original</small><pre className="inspector-sql">{report.original_sql}</pre></div>
            <div><small>Winning rewrite (attempt {report.winning_attempt})</small><pre className="inspector-sql">{report.winning_sql}</pre></div>
          </div>
          {!!report.plan_diff?.length && <ul className="plan-diff">{report.plan_diff.map((line) => <li key={line}>{line}</li>)}</ul>}
        </>
      )}
      {improved && (
        <div className="apply-bar">
          <span><strong>Use the faster SQL</strong><small>Becomes the verified query for this question only after approval; nothing is changed automatically.</small></span>
          {pendingApproval ? (
            <span className="caption"><ShieldCheck size={13} /> Awaiting approval · <Link className="text-button" href="/approvals">Open Approvals</Link></span>
          ) : run.approval?.status === "approved" ? (
            <span className="caption"><Check size={13} /> Approved and active</span>
          ) : (
            <span className="row-actions">
              {needsQuestion && <input aria-label="Question this SQL answers" placeholder="Question this SQL answers" value={question} onChange={(event) => setQuestion(event.target.value)} />}
              <button className="primary-button" disabled={apply.isPending || (needsQuestion && question.trim().length < 3)} onClick={() => void requestApproval()}>
                {apply.isPending ? <RefreshCw size={16} className="spin" /> : <ShieldCheck size={16} />}Apply via approval
              </button>
            </span>
          )}
        </div>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ router decisions

const FEEDBACK_LABELS: Record<string, string> = { helpful: "helpful", not_helpful: "not helpful", positive: "helpful", negative: "not helpful" };

function backendName(backend: string) {
  return backend.startsWith("jev:") ? `jev (${backend.slice(4)})` : backend;
}

const ROUTER_BACKENDS = ["local", "llm", "jev"];

function RouterDecisionsPanel({ notify }: { notify: Notify }) {
  const [backend, setBackend] = useState("all");
  const [search, setSearch] = useState("");
  const needle = useDebouncedValue(search.trim());
  const filters = { backend: backend === "all" ? "" : backend, q: needle };
  const pagination = usePagination(filters, 50);
  const query = usePagedQuery<RouterDecisionRecord>(scopes.routerDecisions, "/router/decisions", filters, pagination);
  useQueryErrorToast(query.error, notify, "Router decisions could not be loaded", { ignoreUnavailable: true });
  const filtered = useMemo(() => query.data?.items ?? [], [query.data]);
  const backends = useMemo(() => Array.from(new Set([...ROUTER_BACKENDS, ...filtered.map((item) => item.backend.split(":")[0])])).sort(), [filtered]);
  const total = query.data?.total ?? 0;
  const rated = filtered.filter((item) => item.outcome?.feedback);
  const helpful = rated.filter((item) => ["helpful", "positive"].includes(String(item.outcome?.feedback))).length;

  if (isEndpointUnavailable(query.error)) return <section className="surface admin-surface"><EndpointUnavailable feature="Router decisions" endpoint="GET /api/router/decisions" /></section>;
  return (
    <section className="surface admin-surface">
      <div className="section-heading">
        <div><span className="eyebrow">DECISION ROUTER</span><h3>Recent decisions</h3><p>Routing decisions, newest first, with backend, confidence and what the user said about the answer.</p></div>
        <div className="row-actions">
          <div className="toolbar-search"><Search size={16} /><input placeholder="Search questions..." value={search} onChange={(event) => setSearch(event.target.value)} aria-label="Search decisions" /></div>
          <select value={backend} onChange={(event) => setBackend(event.target.value)} aria-label="Filter by backend"><option value="all">All backends</option>{backends.map((name) => <option key={name} value={name}>{name}</option>)}</select>
          <button className="icon-button" title="Refresh" aria-label="Refresh decisions" onClick={() => void query.refetch()}><RefreshCw size={16} className={query.isFetching ? "spin" : undefined} /></button>
        </div>
      </div>
      <p className="admin-hint learning-pad">{total.toLocaleString()} decision{total === 1 ? "" : "s"} · on this page {rated.length} rated · {rated.length ? `${Math.round((helpful / rated.length) * 100)}% helpful` : "no feedback yet"}</p>
      {query.isPending ? <LoadingBlock label="Loading decisions" /> : filtered.length ? (
        <>
          <div className="table-header decision-grid"><span>Question</span><span>Route</span><span>Backend</span><span>Confidence</span><span>Feedback</span></div>
          {filtered.map((item: RouterDecisionRecord) => (
            <div className="data-row decision-grid" key={item.id}>
              <span><strong title={item.question}>{item.question}</strong><small>{when(item.created_at)}{item.risk?.escalated_by ? ` · risk escalated by ${item.risk.escalated_by}` : ""}</small></span>
              <span>{item.route === "agent_run" ? <Network size={13} /> : null} {String(item.route).replaceAll("_", " ")}</span>
              <span className="mono" title={item.backend}>{backendName(item.backend)}</span>
              <span className="confidence-cell"><span className={`score-bar score-bar--${item.confidence >= 0.6 ? "brand" : "muted"}`}><i style={{ width: `${Math.max(2, Math.round(item.confidence * 100))}%` }} /></span><small>{Math.round(item.confidence * 100)}%</small></span>
              {item.outcome?.feedback ? <StatusPill value={FEEDBACK_LABELS[String(item.outcome.feedback)] || String(item.outcome.feedback)} /> : <span className="caption">-</span>}
            </div>
          ))}
          <Pagination state={pagination} total={total} count={filtered.length} busy={query.isFetching} label="decisions" />
        </>
      ) : <div className="inline-empty">{needle || backend !== "all" ? "No decisions match these filters." : "No routing decisions recorded for this project yet."}</div>}
    </section>
  );
}

// ------------------------------------------------------------------ tool choice evaluation

type ToolChoiceResult = { agent: string; step: string; expected: string; got: string | null; probability: number | null; backend: string; correct: boolean; error?: string | null };
type ToolChoiceReport = { cases: number; skipped: { agent: string; step: string; reason: string }[]; backends: Record<string, { accuracy: number | null; avg_latency_ms: number | null; effective_backend: string | null; errors?: number; results: ToolChoiceResult[] }> };

const SAMPLE_TOOL_CASES = [
  "Metadata | Retrieve the lineage graph for staging.transactions, upstream and downstream | lineage.query",
  "Metadata | Profile the dataset columns: types, null rates and distinct values | dataset.profile",
  "Metadata | Find catalogued tables about customer accounts | catalog.search",
  "SQL Analyst | Draft a read-only query for total amount by transaction type | sql.generate",
  "Troubleshooter | Inspect the failed job's logs and error | job.inspect",
  "Troubleshooter | Trace which downstream tables are affected by the failed load | lineage.query",
].join("\n");

/** Labelled "agent step -> expected tool" cases replayed through the local chooser and Jev (tool_selection). */
function ToolChoiceEvaluationPanel({ notify }: { notify: Notify }) {
  const [text, setText] = useState(SAMPLE_TOOL_CASES);
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<ToolChoiceReport | null>(null);
  const cases = text.split("\n").map((line) => line.split("|").map((part) => part.trim())).filter((parts) => parts.length >= 3 && parts.every(Boolean)).map(([agent, step, expected_tool]) => ({ agent, step, expected_tool }));

  async function run() {
    if (!cases.length) { notify("Add at least one line: agent | step | expected tool", "error"); return; }
    setRunning(true);
    try {
      setReport(await api<ToolChoiceReport>("/router/evaluate-tools", { method: "POST", body: JSON.stringify({ cases, backends: ["local", "jev"] }) }));
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Tool choice evaluation failed", "error");
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="surface admin-surface">
      <div className="section-heading">
        <div><span className="eyebrow">TOOL SELECTION</span><h3>Tool choice evaluation</h3><p>One case per line: <code>agent | plan step | expected tool</code>. Each step is offered the agent&apos;s bound tools, exactly as in an agent run, and scored with the local word-overlap chooser and the decision model routed to tool selection (Jev).</p></div>
        <div className="row-actions"><button className="primary-button" onClick={() => void run()} disabled={running}>{running ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}{running ? "Evaluating" : `Evaluate ${cases.length} case${cases.length === 1 ? "" : "s"}`}</button></div>
      </div>
      <div className="learning-pad">
        <label className="field-label" htmlFor="tool-choice-cases">Cases</label>
        <textarea id="tool-choice-cases" className="code-input tool-cases" rows={8} value={text} onChange={(event) => setText(event.target.value)} spellCheck={false} />
      </div>
      {report && (
        <div className="learning-pad">
          <div className="three-column compact-cards score-cards">
            {Object.entries(report.backends).map(([name, item]) => (
              <div className="control-item score-card" key={name}>
                <span><strong>{name === "jev" ? "Jev" : "Local chooser"}</strong><small title={item.effective_backend || undefined}>{item.effective_backend || "-"}</small></span>
                <span><strong>{item.accuracy != null ? `${Math.round(item.accuracy * 100)}%` : "-"}</strong><small>{item.avg_latency_ms != null ? `${Math.round(item.avg_latency_ms)} ms avg` : ""}{item.errors ? ` · ${item.errors} failed` : ""}</small></span>
              </div>
            ))}
          </div>
          {report.skipped.length ? <p className="admin-hint">{report.skipped.length} case{report.skipped.length === 1 ? "" : "s"} skipped: {report.skipped.map((item) => `${item.agent} (${item.reason})`).join("; ")}</p> : null}
          <div className="table-header decision-grid"><span>Step</span><span>Expected</span><span>Local</span><span>Jev</span><span></span></div>
          {(report.backends.local?.results || report.backends.jev?.results || []).map((row, index) => {
            const jev = report.backends.jev?.results[index];
            const local = report.backends.local?.results[index];
            return (
              <div className="data-row decision-grid" key={`${row.agent}-${index}`}>
                <span><strong title={row.step}>{row.step}</strong><small>{row.agent}</small></span>
                <span className="mono">{row.expected}</span>
                <span className="mono">{local ? `${local.correct ? "✓" : "✗"} ${local.got || "-"}` : "-"}</span>
                <span className="mono">{jev?.error ? <span className="tool-choice-error" title={jev.error}>no answer<small>{jev.error}</small></span> : jev ? `${jev.correct ? "✓" : "✗"} ${jev.got || "-"}${jev.probability != null ? ` ${Math.round(jev.probability * 100)}%` : ""}` : "-"}</span>
                <span></span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ router evaluation (moved from Admin -> Governance)

type RouterEvaluation = {
  cases: number;
  backends: Record<string, { accuracy: number | null; avg_latency_ms: number | null; effective_backend: string | null; results: { question: string; expected: string; got: string; confidence: number; backend: string; correct: boolean }[] }>;
};
const ROUTE_EVAL_BACKENDS = ["local", "llm", "jev"] as const;
const ROUTER_SAMPLE_CASES = "How many orders were placed per month? | sql_analysis\nRun the monthly revenue reconciliation agent | agent_run\nWhat does it mean? | clarify";

const BACKEND_KIND_LABELS: Record<string, string> = { llm: "LLM", jev: "Jev", local: "Local" };

/**
 * The backend that actually answered: "llm:gemini-3.6-flash" / "jev:typesafe/jev-1.13-…" show
 * the kind and model; only "local (…)" — e.g. "local (jev unavailable)" — is a fallback.
 */
function EffectiveBackend({ value }: { value: string | null }) {
  if (!value) return <span>-</span>;
  if (value.startsWith("local (")) {
    const reason = value.slice("local (".length).replace(/\)$/, "");
    return <span className="effective-backend"><strong>Local</strong><span className="chip fallback-chip" title={`Fell back to local rules: ${reason}`}>fallback</span><small>{reason}</small></span>;
  }
  const separator = value.indexOf(":");
  if (separator > 0) {
    const kind = value.slice(0, separator);
    const model = value.slice(separator + 1);
    return <span className="effective-backend" title={value}><strong>{BACKEND_KIND_LABELS[kind] || kind}</strong><small className="mono">{model}</small></span>;
  }
  return <span className="effective-backend" title={value}><strong>{BACKEND_KIND_LABELS[value] || value}</strong></span>;
}

/** Replays labelled questions through each decision-router backend (POST /router/evaluate). */
export function RouterEvaluationPanel({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [casesText, setCasesText] = useState(ROUTER_SAMPLE_CASES);
  const [backends, setBackends] = useState<Record<string, boolean>>({ local: true, llm: true, jev: true });
  const [includeFeedback, setIncludeFeedback] = useState(true);
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<RouterEvaluation | null>(null);
  const [openBackend, setOpenBackend] = useState("");
  async function run(event: FormEvent) {
    event.preventDefault();
    const cases = casesText.split("\n").map((line) => line.split("|").map((part) => part.trim())).filter(([question, route]) => question && route).map(([question, route]) => ({ question, expected_route: route }));
    const selected = ROUTE_EVAL_BACKENDS.filter((name) => backends[name]);
    if (!selected.length) { notify("Choose at least one backend", "error"); return; }
    if (!cases.length && !includeFeedback) { notify("Add at least one labelled case (question | expected_route) or include feedback", "error"); return; }
    setRunning(true);
    try {
      setReport(await api<RouterEvaluation>("/router/evaluate", { method: "POST", body: JSON.stringify({ backends: selected, cases, include_feedback: includeFeedback }) }));
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Router evaluation failed", "error");
    } finally {
      setRunning(false);
    }
  }
  const rows = report ? Object.entries(report.backends) : [];
  // Best = highest accuracy; ties go to the lowest average latency.
  const best = rows.filter(([, item]) => item.accuracy != null).sort(([, a], [, b]) => (b.accuracy! - a.accuracy!) || ((a.avg_latency_ms ?? Infinity) - (b.avg_latency_ms ?? Infinity)))[0]?.[0] || "";
  const openItem = openBackend ? report?.backends[openBackend] : undefined;
  return (
    <section className="surface admin-surface">
      <div className="section-heading"><div><span className="eyebrow">DECISION ROUTER</span><h3>Router evaluation</h3><p>Replay labelled questions, plus answers users rated, through each routing backend. Enable a backend only if it wins on your own data.</p></div></div>
      <form className="modal-form router-eval-form" onSubmit={run}>
        <label>Labelled cases (one per line: question | expected_route)<textarea rows={4} value={casesText} onChange={(event) => setCasesText(event.target.value)} placeholder="How many orders per month? | sql_analysis" /></label>
        <div className="router-eval-options">
          {ROUTE_EVAL_BACKENDS.map((name) => <label key={name} className="check-option"><input type="checkbox" checked={!!backends[name]} onChange={(event) => setBackends((current) => ({ ...current, [name]: event.target.checked }))} />{name}</label>)}
          <label className="check-option"><input type="checkbox" checked={includeFeedback} onChange={(event) => setIncludeFeedback(event.target.checked)} />Include rated answers</label>
          <button className="primary-button" disabled={running}>{running ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}Run evaluation</button>
        </div>
      </form>
      {report && <>
        <div className="subheading"><h4>Results</h4><span>{report.cases} case{report.cases === 1 ? "" : "s"}</span></div>
        <div className="table-header router-eval-grid"><span>Backend</span><span>Effective</span><span>Accuracy</span><span>Avg latency</span><span /></div>
        {rows.map(([name, item]) => (
          <div key={name} className={`data-row router-eval-grid${name === best ? " best" : ""}${openBackend === name ? " selected" : ""}`}>
            <span><strong>{name}</strong>{name === best && <span className="chip best-chip" title="Highest accuracy (ties: lowest latency)">best</span>}</span>
            <EffectiveBackend value={item.effective_backend} />
            <span className="mono">{item.accuracy == null ? "-" : `${Math.round(item.accuracy * 100)}%`}</span>
            <span className="mono">{item.avg_latency_ms == null ? "-" : `${Math.round(item.avg_latency_ms)} ms`}</span>
            <button type="button" className="text-button" onClick={() => setOpenBackend(openBackend === name ? "" : name)} aria-expanded={openBackend === name} aria-controls="router-eval-cases">{openBackend === name ? "Hide cases" : "Cases"}</button>
          </div>
        ))}
        {openItem && (
          <div className="router-eval-case-panel" id="router-eval-cases">
            <div className="subheading"><h4>Cases for {openBackend}</h4><span>{openItem.results.filter((result) => result.correct).length} of {openItem.results.length} correct</span></div>
            <div className="router-eval-cases">{openItem.results.map((result, index) => <div key={index} className={result.correct ? "" : "miss"}>{result.correct ? <Check size={13} aria-label="correct" /> : <XCircle size={13} aria-label="wrong" />}<span><strong>{result.question}</strong><small>expected {result.expected} · got {result.got} ({Math.round(result.confidence * 100)}%)</small></span></div>)}</div>
          </div>
        )}
      </>}
    </section>
  );
}

// ------------------------------------------------------------------ learning-loop suggestions (moved from Admin -> Governance)

// Maps a learning suggestion's proposed_change.review_target (the
// FeedbackCreate.context_type it originated from — sql/agent_run/dataset/
// notebook/artifact) to the nav section where a human would actually go to
// make the versioned change the suggestion is asking for review of. This is
// UI-only wayfinding: it does not touch any prompt, tool, or policy, and
// nothing about it violates the "no automatic runtime change" governance
// posture documented in ARCHITECTURE_DECISIONS.md §2 — it just removes the
// friction of a reviewer having to remember which screen owns which area.
const REVIEW_TARGET_NAV: Record<string, { key: NavKey; label: string }> = {
  sql: { key: "sql", label: "Open SQL workspace" },
  agent_run: { key: "agents", label: "Open agent registry" },
  dataset: { key: "datasets", label: "Open dataset catalog" },
  notebook: { key: "notebooks", label: "Open notebooks" },
  artifact: { key: "artifacts", label: "Open artifacts" },
};

/** Feedback-derived suggestions (admin-only on the API). Reviewing records a decision; it never changes runtime behaviour. */
function LearningSuggestionsPanel({ notify }: { notify: Notify }) {
  const { navigate } = useWorkspace();
  const [suggestions, setSuggestions] = useState<LearningSuggestion[]>([]);
  const [suggestionFilter, setSuggestionFilter] = useState<"open" | "accepted" | "dismissed">("open");
  const [reviewingSuggestion, setReviewingSuggestion] = useState<LearningSuggestion | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const loadSuggestions = useCallback(async (status: "open" | "accepted" | "dismissed") => { try { setSuggestions(await api<LearningSuggestion[]>(`/learning-suggestions?status=${status}`)); } catch (reason) { notify(reason instanceof Error ? reason.message : "Learning suggestions unavailable", "error"); } }, [notify]);
  useEffect(() => { void loadSuggestions(suggestionFilter); }, [loadSuggestions, suggestionFilter]);
  function openReview(suggestion: LearningSuggestion) { setReviewingSuggestion(suggestion); setReviewNote(""); }
  async function submitReview(status: "accepted" | "dismissed") {
    if (!reviewingSuggestion) return;
    try {
      await api(`/learning-suggestions/${reviewingSuggestion.id}`, { method: "PUT", body: JSON.stringify({ status, note: reviewNote || null }) });
      notify(status === "accepted" ? "Suggestion accepted — apply the change as a versioned update yourself" : "Suggestion dismissed");
      setReviewingSuggestion(null);
      await loadSuggestions(suggestionFilter);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Review could not be saved", "error"); }
  }
  return <>
    <section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">LEARNING LOOP</span><h3>Feedback-derived suggestions</h3><p>Repeated not-helpful feedback in the same area is grouped into one suggestion with escalating severity. Nothing here changes runtime behavior automatically — review and apply changes yourself.</p></div><select value={suggestionFilter} onChange={(event) => setSuggestionFilter(event.target.value as typeof suggestionFilter)} aria-label="Filter suggestions by status"><option value="open">Open</option><option value="accepted">Accepted</option><option value="dismissed">Dismissed</option></select></div>{suggestions.length ? <div className="table-header suggestion-grid"><span>Signal</span><span>Category</span><span>Occurrences</span><span>Severity</span><span /></div> : <div className="inline-empty">No {suggestionFilter} suggestions for this project.</div>}{suggestions.map((suggestion) => <div className="data-row suggestion-grid" key={suggestion.id}><span><strong>{suggestion.title}</strong><small>{suggestion.rationale}</small></span><span>{suggestion.category.replaceAll("_", " ")}</span><span className="mono">{suggestion.occurrence_count}</span><StatusPill value={suggestion.severity} />{suggestion.status === "open" ? <button className="secondary-button" onClick={() => openReview(suggestion)}><Check size={15} />Review</button> : <span className="caption">{suggestion.status} {suggestion.review_note ? `— ${suggestion.review_note}` : ""}</span>}</div>)}</section>
    {reviewingSuggestion && <Modal title={reviewingSuggestion.title} onClose={() => setReviewingSuggestion(null)}><p className="modal-description">{reviewingSuggestion.rationale}</p><div className="policy-details"><div><span>Category</span><strong>{reviewingSuggestion.category.replaceAll("_", " ")}</strong></div><div><span>Occurrences</span><strong>{reviewingSuggestion.occurrence_count}</strong></div><div><span>Severity</span><strong>{reviewingSuggestion.severity}</strong></div></div>{reviewingSuggestion.proposed_change.recent_signals?.length ? <div className="tool-list">{reviewingSuggestion.proposed_change.recent_signals.map((signal, index) => <div key={signal.feedback_id || index}><span><small>{signal.comment || "No comment provided"}</small></span></div>)}</div> : null}
{reviewingSuggestion.proposed_change.review_target && REVIEW_TARGET_NAV[reviewingSuggestion.proposed_change.review_target] && (
  <div className="modal-note">
    <ShieldCheck size={16} />
    <span>
      Accepting only records your decision — it never changes a prompt, tool, or policy by itself. To make the actual fix, go review it yourself.
      <button type="button" className="link-button" onClick={() => navigate(REVIEW_TARGET_NAV[reviewingSuggestion.proposed_change.review_target!].key)}>
        {REVIEW_TARGET_NAV[reviewingSuggestion.proposed_change.review_target!].label} →
      </button>
    </span>
  </div>
)}
<label>Review note<textarea rows={4} value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="What you decided and why, for the audit trail" /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => submitReview("dismissed")}><XCircle size={16} />Dismiss</button><button className="primary-button" onClick={() => submitReview("accepted")}><Check size={16} />Accept</button></div></Modal>}
  </>;
}
