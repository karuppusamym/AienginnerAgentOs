import { useSupersetStatus } from "../lib/queries";
import dynamic from "next/dynamic";
import {
  Archive,
  Bot,
  Braces,
  Check,
  ChevronRight,
  CircleGauge,
  Code2,
  Database,
  FileSpreadsheet,
  Layers3,
  LayoutDashboard,
  Network,
  Play,
  RefreshCw,
  Sparkles,
  Workflow,
  XCircle,
  Plus,
  Trash2,
  Gauge,
  Zap,
  Clock,
  AlertTriangle,
  Copy,
} from "lucide-react";
import { FormEvent, KeyboardEvent as ReactKeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, SessionUser } from "../lib/api";
import { SaveAsMenu } from "./SaveAsMenu";
import type {
  Connector,
  SQLResult,
  SQLExecutionResult,
  PastedSqlRun,
  SqlPerformanceReport,
  SqlTuningDetail,
  SqlTuningReportExtras,
  Artifact,
  ArtifactVersion,
  CompositionColumn,
  CompositionJob,
  CompositionPlan,
  CompositionPlanResponse,
  CompositionResult,
  CompositionStepState,
} from "../types";

// Editable plan rows keep list fields as text so typing commas/new lines is never fought by re-parsing.
type EditableStep = { name: string; purpose: string; depends: string; inputs: string; rules: string; columns: CompositionColumn[] };
type EditablePlan = { title: string; steps: EditableStep[]; final: { purpose: string; depends: string; rules: string; columns: CompositionColumn[] } };
const splitList = (value: string) => value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
const splitLines = (value: string) => value.split("\n").map((item) => item.trim()).filter(Boolean);
function toEditablePlan(plan: CompositionPlan): EditablePlan {
  return {
    title: plan.title,
    steps: plan.steps.map((step) => ({ name: step.name, purpose: step.purpose, depends: step.depends_on.join(", "), inputs: step.inputs.filter((item) => !step.depends_on.includes(item)).join(", "), rules: step.rules.join("\n"), columns: step.columns })),
    final: { purpose: plan.final.purpose, depends: plan.final.depends_on.join(", "), rules: plan.final.rules.join("\n"), columns: plan.final.columns },
  };
}
function fromEditablePlan(plan: EditablePlan): CompositionPlan {
  return {
    title: plan.title,
    steps: plan.steps.map((step) => ({ name: step.name.trim(), purpose: step.purpose, depends_on: splitList(step.depends), inputs: splitList(step.inputs), rules: splitLines(step.rules), columns: step.columns })),
    final: { purpose: plan.final.purpose, depends_on: splitList(plan.final.depends), rules: splitLines(plan.final.rules), columns: plan.final.columns },
  };
}
function compositionStepIcon(status: CompositionStepState["status"]) {
  if (status === "ok" || status === "repaired" || status === "fallback") return <Check size={15} className="compose-ok" />;
  if (status === "failed") return <XCircle size={15} className="compose-failed" />;
  if (status === "running") return <RefreshCw size={15} className="spin" />;
  return <ChevronRight size={15} className="compose-waiting" />;
}
import {
  connectorLabels,
  connectorDialectForType,
} from "../lib/constants";
import { StatusPill, EmptyState, Modal } from "./shared";

// The Superset embedded SDK is only needed once a published dashboard is opened.
const PublishedQueryAnalyticsModal = dynamic(() => import("./PublishedQueryAnalyticsModal").then((module) => module.PublishedQueryAnalyticsModal), { ssr: false });


export function SQLView({ notify, seed, currentUser, onSeedConsumed }: { notify: (message: string, tone?: "ok" | "error") => void; seed?: { question: string; dialect: string } | null; currentUser: SessionUser; onSeedConsumed?: () => void }) {
  const [question, setQuestion] = useState("Show monthly deposit-account growth and explain unusual changes");
  const [mode, setMode] = useState<"ask" | "paste" | "compose">("ask");
  const [spec, setSpec] = useState("");
  const [planning, setPlanning] = useState(false);
  const [planInfo, setPlanInfo] = useState<CompositionPlanResponse | null>(null);
  const [editablePlan, setEditablePlan] = useState<EditablePlan | null>(null);
  const [planErrors, setPlanErrors] = useState<string[]>([]);
  const [building, setBuilding] = useState(false);
  const [compositionJob, setCompositionJob] = useState<CompositionJob | null>(null);
  const [composition, setComposition] = useState<CompositionResult | null>(null);
  const pollCancelled = useRef(false);
  useEffect(() => () => { pollCancelled.current = true; }, []);
  const [showHints, setShowHints] = useState(false);
  const [hints, setHints] = useState("");
  const [pastedSql, setPastedSql] = useState("");
  const [explaining, setExplaining] = useState(false);
  const pasteRef = useRef<HTMLTextAreaElement>(null);
  const [runLimit, setRunLimit] = useState(500);
  const [runTimeout, setRunTimeout] = useState(30);
  const [pasteRun, setPasteRun] = useState<PastedSqlRun | null>(null);
  const [running, setRunning] = useState(false);
  const [perf, setPerf] = useState<SqlPerformanceReport | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [tuneDetail, setTuneDetail] = useState<SqlTuningDetail | null>(null);
  const [tuning, setTuning] = useState(false);
  const [tuneApplyOpen, setTuneApplyOpen] = useState(false);
  const [tuneQuestion, setTuneQuestion] = useState("");
  const [tuneBusy, setTuneBusy] = useState(false);
  const [canSaveVerified, setCanSaveVerified] = useState(false);
  const [verifiedModalOpen, setVerifiedModalOpen] = useState(false);
  const [verifiedQuestion, setVerifiedQuestion] = useState("");
  const [savingVerified, setSavingVerified] = useState(false);
  const superset = useSupersetStatus();
  const supersetDown = superset.data !== undefined && !superset.data.available;
  const [dialect, setDialect] = useState("postgres");
  const [connectorId, setConnectorId] = useState("");
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [sqlArtifacts, setSqlArtifacts] = useState<Artifact[]>([]);
  const [result, setResult] = useState<SQLResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [artifactId, setArtifactId] = useState<string | null>(null);
  const [explainOpen, setExplainOpen] = useState(false);
  const [toolModalOpen, setToolModalOpen] = useState(false);
  const [notebookModalOpen, setNotebookModalOpen] = useState(false);
  const [reportName, setReportName] = useState("");
  const [analyticsStatus, setAnalyticsStatus] = useState<{ published: boolean; dashboard_title?: string } | null>(null);
  const [analyticsOpen, setAnalyticsOpen] = useState(false);
  const checkAnalyticsStatus = useCallback((id: string) => {
    api<{ published: boolean; dashboard_title?: string }>(`/analytics/queries/${id}`)
      .then(setAnalyticsStatus)
      .catch(() => setAnalyticsStatus(null));
  }, []);
  useEffect(() => {
    if (artifactId) checkAnalyticsStatus(artifactId);
    else setAnalyticsStatus(null);
  }, [artifactId, checkAnalyticsStatus]);
  const canSaveSql = ["admin", "engineer", "analyst"].includes(currentUser.role);
  const localConnector = connectors.find((connector) => connector.connector_type === "local_files");
  const externalConnectors = connectors.filter((connector) => connector.connector_type !== "local_files");
  const selectedConnector = connectors.find((connector) => connector.id === connectorId);
  const resolvedConnector = selectedConnector || localConnector || null;
  const effectiveDialect = resolvedConnector ? connectorDialectForType(resolvedConnector.connector_type) : dialect;
  const executionTarget = resolvedConnector
    ? `${resolvedConnector.name} / ${resolvedConnector.database || resolvedConnector.host || connectorLabels[resolvedConnector.connector_type] || resolvedConnector.connector_type}`
    : "DataPilot local workspace / PostgreSQL staging";
  const loadSqlHistory = useCallback(() => api<Artifact[]>("/artifacts").then((items) => setSqlArtifacts(items.filter((item) => item.artifact_type === "sql"))), []);
  useEffect(() => {
    Promise.all([api<Connector[]>("/connectors").then(setConnectors), loadSqlHistory()]).catch(() => undefined);
  }, [loadSqlHistory]);
  useEffect(() => {
    if (!seed) return;
    setQuestion(seed.question);
    setDialect(seed.dialect || "postgres");
    setConnectorId("");
    setResult(null);
    setArtifactId(null);
    // Clear the seed in the shell so revisiting SQL does not re-apply it.
    onSeedConsumed?.();
  }, [seed, onSeedConsumed]);

  async function generate(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      const effectiveQuestion = hints.trim() ? `${question}\n\nAdditional context: ${hints.trim()}` : question;
      setResult(await api<SQLResult>("/sql/generate", {
        method: "POST",
        body: JSON.stringify({ question: effectiveQuestion, dialect: effectiveDialect, connector_id: resolvedConnector?.id || null }),
      }));
      setCanSaveVerified(false);
      notify("SQL draft generated and validated");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "SQL generation failed", "error");
    } finally {
      setLoading(false);
    }
  }
  async function explainSql(event?: { preventDefault(): void }) {
    event?.preventDefault();
    if (!pastedSql.trim()) return;
    setExplaining(true);
    try {
      setResult(await api<SQLResult>("/sql/explain", {
        method: "POST",
        body: JSON.stringify({ sql: pastedSql, dialect: effectiveDialect, connector_id: resolvedConnector?.id || null }),
      }));
      setArtifactId(null);
      setCanSaveVerified(true);
      notify("SQL validated and explained");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "SQL could not be explained", "error");
    } finally {
      setExplaining(false);
    }
  }
  function highlightLine(line: number | null) {
    const editor = pasteRef.current;
    if (!editor || !line) return;
    const lines = editor.value.split("\n");
    const start = lines.slice(0, line - 1).reduce((total, item) => total + item.length + 1, 0);
    editor.focus();
    editor.setSelectionRange(start, start + (lines[line - 1]?.length ?? 0));
    editor.scrollTop = Math.max(0, (line - 4) * 19);
  }
  function pasteRunAsResult(run: PastedSqlRun): SQLResult {
    const execution: SQLExecutionResult = { columns: run.columns, rows: run.rows as SQLExecutionResult["rows"], row_count: run.row_count, truncated: run.truncated, limit: run.limit, duration_ms: run.duration_ms ?? undefined, protected_columns: run.protected_columns };
    return {
      sql: run.sql,
      dialect: run.dialect,
      explanation: `Pasted SQL (${run.lines.toLocaleString()} lines) executed read-only in ${run.duration_ms?.toLocaleString()} ms: ${run.row_count.toLocaleString()}${run.truncated ? "+" : ""} rows.`,
      source: run.source,
      validation: { status: "passed", read_only: true, row_limit: run.limit, risk_level: "low", checks: ["Single read-only SELECT", "References only catalogued tables", `Row limit ${run.limit.toLocaleString()} / timeout ${run.timeout_seconds} s`] },
      sources: [],
      preview: execution.rows,
      execution,
      provider: { id: "pasted", name: "Pasted SQL", model: "-", mode: "pasted_run", latency_ms: 0 },
    };
  }
  async function analyzePerformance(durationMs?: number | null, sqlText = pastedSql) {
    if (!sqlText.trim()) return;
    setAnalyzing(true);
    try {
      const report = await api<SqlPerformanceReport>("/sql/analyze", {
        method: "POST",
        body: JSON.stringify({ sql: sqlText, dialect: effectiveDialect, connector_id: resolvedConnector?.id || null, duration_ms: durationMs ?? null }),
      });
      setPerf(report);
      const high = report.issues.filter((issue) => issue.severity === "high").length;
      notify(report.issues.length ? `Plan analysed: ${report.issues.length} issue${report.issues.length === 1 ? "" : "s"}${high ? ` (${high} high)` : ""}` : "Plan analysed: no obvious problems found");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Performance analysis failed", "error");
    } finally {
      setAnalyzing(false);
    }
  }
  async function runPasted(event?: FormEvent) {
    event?.preventDefault();
    if (!pastedSql.trim()) return;
    setRunning(true);
    setPerf(null);
    try {
      const run = await api<PastedSqlRun>("/sql/run", {
        method: "POST",
        body: JSON.stringify({ sql: pastedSql, dialect: effectiveDialect, connector_id: resolvedConnector?.id || null, limit: runLimit, timeout_seconds: runTimeout }),
      });
      setPasteRun(run);
      if (run.status === "error") {
        highlightLine(run.error?.line ?? null);
        notify(`Query failed${run.error?.line ? ` at line ${run.error.line}${run.error.column ? `, column ${run.error.column}` : ""}` : ""}: ${run.error?.message || "unknown error"}`, "error");
        return;
      }
      setResult(pasteRunAsResult(run));
      setArtifactId(null);
      setCanSaveVerified(true);
      notify(`Returned ${run.row_count.toLocaleString()}${run.truncated ? "+" : ""} rows in ${run.duration_ms?.toLocaleString()} ms${run.slow ? " (slow: analysing the plan)" : ""}`);
      if (run.slow) void analyzePerformance(run.duration_ms, run.sql);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Query execution failed", "error");
    } finally {
      setRunning(false);
    }
  }
  function onPasteKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      void runPasted();
    }
  }
  async function startRewrite() {
    if (!pastedSql.trim()) return;
    setTuning(true);
    setTuneDetail(null);
    pollCancelled.current = false;
    try {
      const started = await api<{ id: string }>("/sql/tune", {
        method: "POST",
        body: JSON.stringify({ sql: pastedSql, dialect: effectiveDialect, connector_id: resolvedConnector?.id || null, iterations: 6 }),
      });
      let detail = await api<SqlTuningDetail>(`/sql/tune/${started.id}`);
      setTuneDetail(detail);
      while (!["SUCCEEDED", "FAILED", "CANCELLED"].includes(detail.status) && !pollCancelled.current) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        detail = await api<SqlTuningDetail>(`/sql/tune/${started.id}`);
        setTuneDetail(detail);
      }
      const report = detail.report;
      if (report?.status === "improved") notify(`Found an equivalent rewrite ${report.speedup_pct}% faster (${report.baseline_ms} ms → ${report.best_ms} ms)`);
      else if (report?.status === "no_improvement") notify("No faster equivalent rewrite was found; see the attempts for why");
      else if (detail.status === "FAILED") notify(report?.error || "The tuning run failed", "error");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Rewrite could not be started", "error");
    } finally {
      setTuning(false);
    }
  }
  function loadRewrittenSql() {
    const winning = tuneDetail?.report?.winning_sql;
    if (!winning) return;
    setPastedSql(winning);
    setPasteRun(null);
    setPerf(null);
    setMode("paste");
    notify("Rewritten SQL loaded into the editor: Run it to see the new timing");
  }
  async function requestRewriteApproval(event: FormEvent) {
    event.preventDefault();
    if (!tuneDetail) return;
    setTuneBusy(true);
    try {
      const response = await api<{ approval_id: string }>(`/sql/tune/${tuneDetail.id}/apply`, { method: "POST", body: JSON.stringify(tuneQuestion.trim() ? { question: tuneQuestion.trim() } : {}) });
      setTuneApplyOpen(false);
      setTuneDetail({ ...tuneDetail, approval: { id: response.approval_id, status: "pending", created_at: new Date().toISOString() } });
      notify(`Approval requested (${response.approval_id.slice(0, 8)}): the rewrite becomes the verified query once approved`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Approval could not be requested", "error");
    } finally {
      setTuneBusy(false);
    }
  }
  async function saveRewriteArtifact() {
    const report = tuneDetail?.report;
    if (!report?.winning_sql) return;
    setTuneBusy(true);
    try {
      const artifact = await api<{ id: string; version: number }>("/artifacts", {
        method: "POST",
        body: JSON.stringify({
          name: `Tuned SQL (${report.speedup_pct}% faster) ${new Date().toLocaleDateString()}`.slice(0, 120),
          artifact_type: "sql",
          content: report.winning_sql,
          metadata: { dialect: report.dialect || effectiveDialect, connector_id: report.connector_id || null, question: report.question || "Pasted SQL (tuned)", tuning: { job_id: tuneDetail?.id, baseline_ms: report.baseline_ms, best_ms: report.best_ms, speedup_pct: report.speedup_pct, verified_equivalent: true } },
        }),
      });
      await loadSqlHistory();
      notify(`Tuned SQL saved as artifact version ${artifact.version}`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Artifact could not be saved", "error");
    } finally {
      setTuneBusy(false);
    }
  }
  async function planComposition(event: FormEvent) {
    event.preventDefault();
    if (spec.trim().length < 10) return;
    setPlanning(true);
    try {
      const response = await api<CompositionPlanResponse>("/sql/compose/plan", {
        method: "POST",
        body: JSON.stringify({ spec, dialect: effectiveDialect, connector_id: resolvedConnector?.id || null }),
      });
      setPlanInfo(response);
      setEditablePlan(toEditablePlan(response.plan));
      setPlanErrors(response.errors);
      setCompositionJob(null);
      setComposition(null);
      notify(response.valid ? `Plan ready: ${response.plan.steps.length} steps. Review and edit before building.` : "The plan needs fixes before it can be built", response.valid ? "ok" : "error");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Planning failed", "error");
    } finally {
      setPlanning(false);
    }
  }
  function updateStep(index: number, patch: Partial<EditableStep>) {
    setEditablePlan((plan) => plan && { ...plan, steps: plan.steps.map((step, position) => (position === index ? { ...step, ...patch } : step)) });
  }
  function addStep() {
    setEditablePlan((plan) => plan && { ...plan, steps: [...plan.steps, { name: `step_${plan.steps.length + 1}`, purpose: "", depends: plan.steps.length ? plan.steps[plan.steps.length - 1].name : "", inputs: "", rules: "", columns: [] }] });
  }
  function removeStep(index: number) {
    setEditablePlan((plan) => plan && { ...plan, steps: plan.steps.filter((_, position) => position !== index) });
  }
  function compositionAsResult(built: CompositionResult): SQLResult {
    return {
      sql: built.sql,
      dialect: built.dialect,
      explanation: `${built.title}: ${built.stats.steps} steps composed into one read-only WITH statement (${built.lines} lines, ${built.stats.model_calls} model calls, ${built.stats.repairs} repairs).`,
      validation: { status: built.validation.status, read_only: built.validation.read_only, row_limit: built.validation.row_limit, risk_level: built.validation.risk_level, checks: built.validation.checks },
      sources: Object.entries(built.lineage).map(([step, inputs]) => ({ term: step, definition: inputs.join(", ") })),
      preview: built.preview,
      execution: built.execution,
      provider: built.provider || { id: "composer", name: "SQL composer", model: "-", mode: "composed", latency_ms: built.stats.duration_ms },
    };
  }
  async function buildComposition() {
    if (!editablePlan) return;
    setBuilding(true);
    setComposition(null);
    setPlanErrors([]);
    pollCancelled.current = false;
    try {
      let job = await api<CompositionJob>("/sql/compose/build", {
        method: "POST",
        body: JSON.stringify({ plan: fromEditablePlan(editablePlan), dialect: effectiveDialect, connector_id: resolvedConnector?.id || null, spec }),
      });
      setCompositionJob(job);
      while (!["SUCCEEDED", "FAILED", "CANCELLED"].includes(job.status) && !pollCancelled.current) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        job = await api<CompositionJob>(`/sql/compose/${job.id}`);
        setCompositionJob(job);
      }
      if (job.result) {
        setComposition(job.result);
        setPlanErrors(job.result.validation.errors);
        if (job.result.status === "completed") {
          setResult(compositionAsResult(job.result));
          setArtifactId(null);
          setCanSaveVerified(false);
          notify(`Composed ${job.result.lines} lines of validated SQL from ${job.result.stats.steps} steps`);
        } else {
          notify("Some steps failed; fix the plan or rules and build again", "error");
        }
      } else if (job.status === "FAILED") {
        notify("The composition job failed; see Jobs for its log", "error");
      }
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Build failed", "error");
    } finally {
      setBuilding(false);
    }
  }
  async function saveVerifiedQuery(event: FormEvent) {
    event.preventDefault();
    if (!result) return;
    setSavingVerified(true);
    try {
      await api("/verified-queries", {
        method: "POST",
        body: JSON.stringify({ question: verifiedQuestion, sql: result.sql, dialect: effectiveDialect, connector_id: resolvedConnector?.id || null }),
      });
      setVerifiedModalOpen(false);
      setVerifiedQuestion("");
      notify("Saved as a verified query — future matching questions can reuse it");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Could not save as a verified query", "error");
    } finally {
      setSavingVerified(false);
    }
  }
  async function runPreview() {
    if (!result) return;
    setExecuting(true);
    try {
      const execution = await api<SQLExecutionResult>("/sql/execute", {
        method: "POST",
        body: JSON.stringify({ sql: result.sql, dialect: effectiveDialect, connector_id: resolvedConnector?.id || null, limit: 500 }),
      });
      setResult({ ...result, preview: execution.rows, execution });
      notify(`Read-only query returned ${execution.row_count} rows`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Query execution failed", "error");
    } finally {
      setExecuting(false);
    }
  }

  async function saveArtifact() {
    if (!result) return;
    const composedResult = composition !== null && composition.status === "completed" && composition.sql === result.sql;
    const pastedName = mode === "paste" && result.sql === pastedSql ? `Pasted SQL (${(result.sql.match(/\n/g)?.length ?? 0) + 1} lines) ${new Date().toLocaleDateString()}` : null;
    setSaving(true);
    try {
      const artifact = await api<{ id: string; version: number }>("/artifacts", {
        method: "POST",
        body: JSON.stringify({
          artifact_id: artifactId,
          name: (composedResult ? composition.title : pastedName || question).slice(0, 120),
          artifact_type: "sql",
          content: result.sql,
          metadata: {
            dialect: effectiveDialect,
            question: composedResult ? composition.title : pastedName || question,
            connector_id: resolvedConnector?.id || null,
            validation: result.validation,
            sources: result.sources,
            ...(composedResult ? { composition: { plan: compositionJob?.plan || (editablePlan ? fromEditablePlan(editablePlan) : null), spec: spec.slice(0, 4000), job_id: compositionJob?.id || null, lines: composition.lines, steps: composition.stats.steps, lineage: composition.lineage } } : {}),
          },
        }),
      });
      setArtifactId(artifact.id);
      await loadSqlHistory();
      notify(`SQL artifact saved as version ${artifact.version}`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Artifact could not be saved", "error");
    } finally {
      setSaving(false);
    }
  }
  async function sendFeedback(rating: "helpful" | "not_helpful") {
    try { await api("/feedback", { method: "POST", body: JSON.stringify({ context_type: "sql", context_id: artifactId, rating, comment: `${effectiveDialect}: ${question}` }) }); notify(`Feedback recorded as ${rating.replaceAll("_", " ")}`); } catch (reason) { notify(reason instanceof Error ? reason.message : "Feedback could not be recorded", "error"); }
  }

  async function publishTool(event: FormEvent) {
    event.preventDefault();
    if (!result) return;
    const slug = ("tool_" + reportName.toLowerCase().replace(/[^a-z0-9_.-]+/g, "_")).slice(0, 120);
    try {
      await api("/query-tools", { method: "POST", body: JSON.stringify({
        name: slug,
        description: `Published from the SQL workspace: ${reportName}`,
        purpose: question || reportName,
        data_source: selectedConnector?.name || "DataPilot workspace",
        line_of_business: "general",
        owner: currentUser.email || currentUser.name,
        sql_template: result.sql,
        parameter_schema: { type: "object", properties: {}, additionalProperties: false },
        requires_approval: true,
      }) });
      setToolModalOpen(false); setReportName(""); notify("Tool publication requested and sent to Approvals");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not publish tool", "error"); }
  }

  async function ejectNotebook(event: FormEvent) {
    event.preventDefault();
    if (!result) return;
    try {
      await api("/notebooks", { method: "POST", body: JSON.stringify({ name: reportName, cells: [{ id: `cell-${Date.now()}`, type: "sql", source: result.sql }] }) });
      setNotebookModalOpen(false); setReportName(""); notify("Notebook created");
    } catch (reason) { notify("Could not create notebook", "error"); }
  }
  async function requestSupersetPublication() {
    if (!artifactId) return;
    setPublishing(true);
    try {
      const request = await api<{ approval_id: string; status: string; auto_review?: { reason: string } }>("/analytics/publish-sql", {
        method: "POST",
        body: JSON.stringify({ artifact_id: artifactId, name: question.slice(0, 120) }),
      });
      notify(request.status === "auto_approved" ? `Published to Superset: auto-approved by policy (${request.auto_review?.reason || "read-only, no PII"})` : `Superset publication is awaiting approval (${request.approval_id.slice(0, 8)}); "Open in Superset" appears here once an admin approves it`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Superset publication could not be requested", "error");
    } finally { setPublishing(false); }
  }
  async function openSqlArtifact(artifact: Artifact) {
    try {
      const versions = await api<ArtifactVersion[]>(`/artifacts/${artifact.id}/versions`);
      const latest = versions[0];
      if (!latest) return;
      setArtifactId(artifact.id);
      setQuestion(String(latest.artifact_metadata.question || artifact.name));
      setDialect(String(latest.artifact_metadata.dialect || "postgres"));
      setConnectorId(String(latest.artifact_metadata.connector_id || ""));
      const validation = latest.artifact_metadata.validation as SQLResult["validation"] | undefined;
      const sources = latest.artifact_metadata.sources as SQLResult["sources"] | undefined;
      setResult({
        sql: latest.content,
        dialect: String(latest.artifact_metadata.dialect || "postgres"),
        explanation: `Saved SQL artifact ${artifact.name}`,
        validation: validation || { status: "saved", read_only: true, row_limit: 500, risk_level: "low", checks: ["Loaded from versioned SQL history"] },
        sources: sources || [],
        preview: [],
        execution: null,
        provider: { id: "artifact", name: "Saved artifact", model: "history", mode: "saved", latency_ms: 0 },
      });
      setCanSaveVerified(false);
      notify(`Loaded SQL history item v${latest.version}`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "SQL history could not be opened", "error");
    }
  }
  return (
    <div className="view-stack">
      <div className="view-header">
        <div><h2>Grounded SQL workspace</h2><p>Generate dialect-aware, read-only SQL from catalog metadata and approved business terms.</p></div>
        <div className="sql-source-controls">
          <select value={connectorId} onChange={(event) => setConnectorId(event.target.value)} aria-label="SQL source connection"><option value="">DataPilot local workspace / PostgreSQL staging</option>{externalConnectors.map((connector) => <option key={connector.id} value={connector.id}>{connector.name} / {connectorLabels[connector.connector_type] || connector.connector_type}</option>)}</select>
          <span className="analysis-dialect">{selectedConnector ? `${connectorLabels[selectedConnector.connector_type] || selectedConnector.connector_type} source` : "PostgreSQL local source"}</span>
        </div>
      </div>
      <div className="segmented" role="tablist" aria-label="SQL input mode">
        <button role="tab" aria-selected={mode === "ask"} className={mode === "ask" ? "active" : ""} onClick={() => setMode("ask")}>Ask a question</button>
        <button role="tab" aria-selected={mode === "paste"} className={mode === "paste" ? "active" : ""} onClick={() => setMode("paste")}>Paste SQL</button>
        <button role="tab" aria-selected={mode === "compose"} className={mode === "compose" ? "active" : ""} onClick={() => setMode("compose")}>Build from business logic</button>
      </div>
      {mode === "compose" ? (
        <div className="compose-stack">
          <form className="sql-question surface paste-sql-form" onSubmit={planComposition}>
            <textarea className="compose-spec" rows={8} value={spec} maxLength={24000} onChange={(event) => setSpec(event.target.value)} placeholder="Describe the business logic in full: entities, filters, eligibility rules, calculations, grain, edge cases and the final output. Long specifications are split into small, separately validated steps." aria-label="Business logic specification" />
            <div className="compose-spec-actions">
              <button className="primary-button" disabled={planning || building || spec.trim().length < 10}>{planning ? <RefreshCw size={17} className="spin" /> : <Workflow size={17} />}Plan</button>
              <small>{spec.length.toLocaleString()} / 24,000</small>
            </div>
          </form>
          {editablePlan && (
            <section className="surface compose-plan">
              <div className="section-heading compact">
                <div><span className="eyebrow">SQL PROGRAM PLAN</span><h3><input className="compose-title" value={editablePlan.title} onChange={(event) => setEditablePlan({ ...editablePlan, title: event.target.value })} aria-label="Program title" /></h3></div>
                <div className="compose-plan-actions">
                  {planInfo && <span className="caption">{planInfo.provider.name} / {planInfo.executable ? "each step executes bounded on PostgreSQL" : "validated only (source not executable here)"}</span>}
                  <button type="button" className="secondary-button" onClick={addStep} disabled={building}><Plus size={16} />Add step</button>
                  <button type="button" className="primary-button" onClick={buildComposition} disabled={building || !editablePlan.steps.length}>{building ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}Build</button>
                </div>
              </div>
              {planErrors.length > 0 && <div className="conversation-memory compact-memory execution-error"><span>Needs attention</span>{planErrors.slice(0, 12).map((error) => <p key={error}>{error}</p>)}</div>}
              {planInfo && <p className="caption">Inputs can be catalogued tables ({planInfo.catalog_relations.slice(0, 6).join(", ")}{planInfo.catalog_relations.length > 6 ? ", ..." : ""}) or earlier step names. One rule per line.</p>}
              <ol className="compose-step-list">
                {editablePlan.steps.map((step, index) => {
                  const state = (composition?.steps || compositionJob?.progress_detail?.steps || []).find((item) => item.name === step.name);
                  return (
                    <li key={index} className={`compose-step${state ? ` ${state.status}` : ""}`}>
                      <div className="compose-step-head">
                        <span className="compose-step-index">{index + 1}</span>
                        <input className="mono-input" value={step.name} onChange={(event) => updateStep(index, { name: event.target.value })} aria-label={`Step ${index + 1} name`} />
                        <input value={step.purpose} onChange={(event) => updateStep(index, { purpose: event.target.value })} placeholder="Purpose" aria-label={`Step ${index + 1} purpose`} />
                        {state && <span className="compose-step-status" title={state.error || undefined}>{compositionStepIcon(state.status)}{state.status}{state.row_count !== null ? ` / ${state.row_count} rows` : ""}</span>}
                        <button type="button" className="icon-button" title="Remove step" onClick={() => removeStep(index)} disabled={building}><Trash2 size={15} /></button>
                      </div>
                      <div className="compose-step-body">
                        <label>Depends on<input value={step.depends} onChange={(event) => updateStep(index, { depends: event.target.value })} placeholder="earlier_step, another_step" /></label>
                        <label>Catalog inputs<input value={step.inputs} onChange={(event) => updateStep(index, { inputs: event.target.value })} placeholder="schema.table" /></label>
                        <label className="compose-rules">Business rules<textarea rows={Math.min(6, Math.max(2, step.rules.split("\n").length))} value={step.rules} onChange={(event) => updateStep(index, { rules: event.target.value })} /></label>
                        {step.columns.length > 0 && <small className="compose-columns">Outputs: {step.columns.map((column) => column.name).join(", ")}</small>}
                        {state?.error && <small className="compose-step-error">{state.error}</small>}
                      </div>
                    </li>
                  );
                })}
              </ol>
              <div className="compose-final">
                <label>Final SELECT<input value={editablePlan.final.purpose} onChange={(event) => setEditablePlan({ ...editablePlan, final: { ...editablePlan.final, purpose: event.target.value } })} /></label>
                <label>Reads steps<input value={editablePlan.final.depends} onChange={(event) => setEditablePlan({ ...editablePlan, final: { ...editablePlan.final, depends: event.target.value } })} placeholder="Defaults to the steps nothing else uses" /></label>
                <label className="compose-rules">Final rules<textarea rows={2} value={editablePlan.final.rules} onChange={(event) => setEditablePlan({ ...editablePlan, final: { ...editablePlan.final, rules: event.target.value } })} /></label>
              </div>
              {(building || compositionJob) && (
                <div className="compose-progress">
                  <div className="compose-progress-bar"><span style={{ width: `${compositionJob?.progress ?? 0}%` }} /></div>
                  <small>{compositionJob ? `${compositionJob.status.toLowerCase()} / ${compositionJob.progress}%` : "starting"}{composition ? ` / ${composition.lines} lines / ${composition.stats.model_calls} model calls / ${composition.stats.repairs} repairs` : ""}{composition?.final ? ` / final: ${composition.final.status}` : ""}</small>
                  {composition?.warnings.map((warning) => <small key={warning}>{warning}</small>)}
                </div>
              )}
            </section>
          )}
        </div>
      ) : mode === "ask" ? (
        <form className="sql-question surface" onSubmit={generate}>
          <Sparkles size={19} />
          <input value={question} onChange={(event) => setQuestion(event.target.value)} aria-label="Business question" />
          <button type="button" className="icon-button" title={showHints ? "Hide extra context" : "Add extra context"} onClick={() => setShowHints((value) => !value)}><Layers3 size={16} /></button>
          <button className="primary-button" disabled={loading}>{loading ? <RefreshCw size={17} className="spin" /> : <Play size={17} />}Generate</button>
        </form>
      ) : (
        <form className="surface pst-form" onSubmit={runPasted}>
          <textarea ref={pasteRef} className="mono-input pst-editor" rows={14} value={pastedSql} onChange={(event) => setPastedSql(event.target.value)} onKeyDown={onPasteKeyDown} placeholder="Paste a read-only SELECT (any length, CTEs and comments welcome) against catalogued tables. Ctrl+Enter runs it." spellCheck={false} wrap="off" aria-label="Pasted SQL" />
          <div className="pst-toolbar">
            <small className="pst-count">{pastedSql ? `${(pastedSql.match(/\n/g)?.length ?? 0) + 1} lines / ${pastedSql.length.toLocaleString()} chars` : "Empty"}</small>
            <label>Rows<select value={runLimit} onChange={(event) => setRunLimit(Number(event.target.value))} aria-label="Row limit">{[100, 500, 1000, 5000].map((value) => <option key={value} value={value}>{value.toLocaleString()}</option>)}</select></label>
            <label>Timeout<select value={runTimeout} onChange={(event) => setRunTimeout(Number(event.target.value))} aria-label="Statement timeout">{[15, 30, 60, 120, 300].map((value) => <option key={value} value={value}>{value} s</option>)}</select></label>
            <span className="pst-actions">
              <button type="button" className="secondary-button" onClick={explainSql} disabled={explaining || !pastedSql.trim()} title="Validate against the guard and explain the query in business terms">{explaining ? <RefreshCw size={16} className="spin" /> : <Layers3 size={16} />}Explain &amp; validate</button>
              <button type="button" className="secondary-button" onClick={() => analyzePerformance(pasteRun?.status === "ok" ? pasteRun.duration_ms : null)} disabled={analyzing || !pastedSql.trim()} title="Capture the execution plan and explain what makes the query slow">{analyzing ? <RefreshCw size={16} className="spin" /> : <Gauge size={16} />}Analyze performance</button>
              <button type="button" className="secondary-button" onClick={startRewrite} disabled={tuning || !pastedSql.trim()} title="Ask the tuning model for faster rewrites; only rewrites that return exactly the same result are kept">{tuning ? <RefreshCw size={16} className="spin" /> : <Zap size={16} />}Rewrite for speed</button>
              <button className="primary-button" disabled={running || !pastedSql.trim()} title="Execute read-only on the selected source (Ctrl+Enter)">{running ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}Run</button>
            </span>
          </div>
        </form>
      )}
      {mode === "paste" && pasteRun && <PasteRunSummary run={pasteRun} onJump={highlightLine} />}
      {mode === "paste" && perf && <PerformancePanel report={perf} onRewrite={startRewrite} rewriting={tuning} notify={notify} />}
      {mode === "paste" && tuneDetail && (
        <TuningPanel
          detail={tuneDetail}
          running={tuning}
          busy={tuneBusy}
          canSave={canSaveSql}
          onUse={loadRewrittenSql}
          onApprove={() => { setTuneQuestion(tuneDetail.report?.question || ""); setTuneApplyOpen(true); }}
          onSaveArtifact={saveRewriteArtifact}
          onClose={() => { pollCancelled.current = true; setTuneDetail(null); }}
        />
      )}
      {mode === "ask" && showHints && (
        <div className="surface sql-hints">
          <label>Additional context<textarea rows={2} value={hints} onChange={(event) => setHints(event.target.value)} placeholder="Extra detail for the model: tables to prefer, filters, time range, definitions..." /></label>
        </div>
      )}
      {!result ? (
        <EmptyState icon={<Code2 size={26} />} title="Ready for a business question" body="The agent will show its SQL, evidence, validation checks, and a limited preview before anything can be saved." />
      ) : (
        <div className="sql-layout">
          <section className="surface code-panel">
            <div className="panel-toolbar"><span><Code2 size={16} />{result.dialect} | {selectedConnector?.name || result.provider.name}{composition && composition.sql === result.sql ? ` | ${composition.lines.toLocaleString()} lines / ${composition.stats.steps} steps` : ""}</span><StatusPill value={result.validation.status} /></div>
            <pre><code>{result.sql}</code></pre>
            <div className="code-actions"><button className="icon-button" onClick={() => sendFeedback("helpful")} title="Helpful result"><Check size={16} /></button><button className="icon-button" onClick={() => sendFeedback("not_helpful")} title="Result needs improvement"><XCircle size={16} /></button><button className="secondary-button" onClick={() => setExplainOpen(true)}><Layers3 size={16} />Why this result?</button>{analyticsStatus?.published && <button className="secondary-button" onClick={() => setAnalyticsOpen(true)}><LayoutDashboard size={16} />Open in Superset</button>}<SaveAsMenu items={[
              { key: "artifact", label: artifactId ? "Save as artifact (new version)" : "Save as artifact", icon: <Archive size={15} />, onSelect: saveArtifact, busy: saving, disabled: !canSaveSql, title: canSaveSql ? "Versioned SQL artifact in this project" : "Your role cannot save SQL" },
              { key: "verified", label: "Save as verified query", icon: <Sparkles size={15} />, onSelect: () => { setVerifiedQuestion(mode === "ask" ? question : ""); setVerifiedModalOpen(true); }, disabled: !canSaveVerified || !canSaveSql, title: !canSaveSql ? "Your role cannot save verified queries" : !canSaveVerified ? "Only SQL you pasted or reviewed yourself can become a verified query" : "Future matching questions reuse this exact SQL" },
              { key: "tool", label: "Publish as query tool", icon: <Network size={15} />, onSelect: () => { setToolModalOpen(true); setReportName((mode === "paste" ? "pasted_query" : question).slice(0, 50)); }, title: "Publishes an API tool after approval" },
              { key: "superset", label: "Publish to Superset", icon: <LayoutDashboard size={15} />, onSelect: requestSupersetPublication, busy: publishing, hidden: Boolean(analyticsStatus?.published), disabled: !artifactId || supersetDown, title: supersetDown ? `Superset unavailable: ${superset.data?.reason}` : !artifactId ? "Save this SQL as an artifact first" : "Requests admin approval before this query becomes a Superset dashboard" },
              { key: "notebook", label: "Open as notebook", icon: <FileSpreadsheet size={15} />, onSelect: () => { setNotebookModalOpen(true); setReportName((mode === "paste" ? "Pasted SQL" : question).slice(0, 50)); } },
            ]} /><button className="primary-button" onClick={runPreview} disabled={executing} title="Execute a bounded read-only preview; no source data is changed">{executing ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}Run read-only preview</button></div>
          </section>
          <aside className="surface validation-panel">
            <div className="section-heading compact"><div><span className="eyebrow">EVIDENCE</span><h3>Validation</h3></div><StatusPill value={result.validation.risk_level} /></div>
            <p>{result.explanation}</p>
            <div className="conversation-memory compact-memory"><span>Execution target</span><p>{executionTarget}</p></div>
            {result.execution?.error ? <div className="conversation-memory compact-memory execution-error"><span>Execution error</span><p>{result.execution.error}</p></div> : null}
            {result.cache?.hit ? <div className="conversation-memory compact-memory"><span>Reuse</span><p>Reused a saved governed query for the same normalized question and source context.</p></div> : null}
            <div className="check-list">{result.validation.checks.map((check) => <div key={check}><Check size={15} />{check}</div>)}</div>
            <div className="subheading"><h4>Sources used</h4><span>{result.sources.length}</span></div>
            {result.sources.map((source, index) => <div className="source-row" key={index}><Database size={15} /><span><strong>{source.asset || source.term}</strong><small>{source.columns?.join(", ") || source.definition}</small></span></div>)}
            {result.grounding?.catalog_matches?.length ? <><div className="subheading"><h4>Catalog grounding</h4><span>{result.grounding.catalog_matches.length}</span></div>{result.grounding.catalog_matches.slice(0, 4).map((item) => <div className="source-row" key={`${item.relation}-${item.match_type}`}><Layers3 size={15} /><span><strong>{item.relation}</strong><small>{item.match_type} match / score {item.score}</small></span></div>)}</> : null}
            {result.grounding?.semantic_matches?.length ? <><div className="subheading"><h4>Semantic terms</h4><span>{result.grounding.semantic_matches.length}</span></div>{result.grounding.semantic_matches.slice(0, 3).map((item) => <div className="source-row" key={item.name}><Braces size={15} /><span><strong>{item.name}</strong><small>{item.formula} / {item.grain}</small></span></div>)}</> : null}
          </aside>
          <section className="surface preview-panel">
            <div className="section-heading compact"><div><span className="eyebrow">LIMITED PREVIEW</span><h3>Query result</h3></div><span className="caption">Maximum {result.validation.row_limit} rows</span></div>
            {result.execution?.error ? <div className="inline-empty">Preview unavailable because query execution failed for the selected source.</div> : result.preview.length ? <div className="data-table-wrap">
              <table><thead><tr>{Object.keys(result.preview[0] || {}).map((key) => <th key={key}>{key.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{result.preview.map((row, index) => <tr key={index}>{Object.values(row).map((value, valueIndex) => <td key={valueIndex}>{typeof value === "number" ? value.toLocaleString() : value}</td>)}</tr>)}</tbody></table>
            </div> : <div className="inline-empty">No preview rows returned for this source.</div>}
          </section>
        </div>
      )}
      <section className="surface sql-history-surface">
        <div className="section-heading compact"><div><span className="eyebrow">SQL HISTORY</span><h3>Saved SQL artifacts</h3></div><StatusPill value={`${sqlArtifacts.length} saved`} /></div>
        {sqlArtifacts.length ? <div className="sql-history-list">{sqlArtifacts.slice(0, 8).map((artifact) => <button key={artifact.id} onClick={() => openSqlArtifact(artifact)}><Archive size={16} /><span><strong>{artifact.name}</strong><small>{String(artifact.metadata?.dialect || artifact.artifact_type)} / v{artifact.latest_version} / {new Date(artifact.updated_at).toLocaleString()}</small></span><ChevronRight size={16} /></button>)}</div> : <div className="inline-empty">Saved SQL from this project appears here. Conversation SQL stays inside each analysis thread until it is saved as a report or artifact.</div>}
      </section>
      {analyticsOpen && artifactId && <PublishedQueryAnalyticsModal artifactId={artifactId} title={analyticsStatus?.dashboard_title || "Query analytics"} onClose={() => setAnalyticsOpen(false)} />}
      {toolModalOpen && <Modal title="Publish as API Tool" onClose={() => setToolModalOpen(false)}><form className="modal-form" onSubmit={publishTool}><label>Tool name<input value={reportName} onChange={(event) => setReportName(event.target.value)} required /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setToolModalOpen(false)}>Cancel</button><button className="primary-button"><Network size={16} />Request Approval</button></div></form></Modal>}
      {notebookModalOpen && <Modal title="Eject to Notebook" onClose={() => setNotebookModalOpen(false)}><form className="modal-form" onSubmit={ejectNotebook}><label>Notebook title<input value={reportName} onChange={(event) => setReportName(event.target.value)} required /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setNotebookModalOpen(false)}>Cancel</button><button className="primary-button"><FileSpreadsheet size={16} />Create Notebook</button></div></form></Modal>}
      {tuneApplyOpen && tuneDetail && <Modal title="Save rewrite as verified query" onClose={() => setTuneApplyOpen(false)}><form className="modal-form" onSubmit={requestRewriteApproval}><label>Business question this SQL answers<input value={tuneQuestion} onChange={(event) => setTuneQuestion(event.target.value)} placeholder="e.g. Monthly active accounts by region" required minLength={3} /></label><p className="caption">Creates an approval request. Once approved, the verified-equivalent rewrite becomes the verified query for this question; nothing changes before that.</p><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setTuneApplyOpen(false)} disabled={tuneBusy}>Cancel</button><button className="primary-button" disabled={tuneBusy}>{tuneBusy ? "Requesting…" : "Request approval"}</button></div></form></Modal>}
      {verifiedModalOpen && <Modal title="Save as verified query" onClose={() => setVerifiedModalOpen(false)}><form className="modal-form" onSubmit={saveVerifiedQuery}><label>Business question this SQL answers<input value={verifiedQuestion} onChange={(event) => setVerifiedQuestion(event.target.value)} placeholder="e.g. Show monthly active accounts by region" required minLength={3} /></label><p className="caption">Future questions that match this one closely will reuse this exact SQL instead of generating fresh.</p><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setVerifiedModalOpen(false)} disabled={savingVerified}>Cancel</button><button className="primary-button" disabled={savingVerified}>{savingVerified ? "Saving…" : "Save"}</button></div></form></Modal>}
      {explainOpen && result && <Modal title="Why this result?" onClose={() => setExplainOpen(false)}><div className="modal-form"><p>{result.explanation}</p><div className="subheading"><h4>Source and model</h4></div><div className="check-list"><div><Database size={15} />{result.source?.name || selectedConnector?.name || "DataPilot local workspace"} / {result.dialect}</div><div><Bot size={15} />{result.provider.name} / {result.provider.model} ({result.provider.mode})</div><div><CircleGauge size={15} />Validation: {result.validation.status}; risk: {result.validation.risk_level}; row limit: {result.validation.row_limit}</div></div><div className="subheading"><h4>Grounding evidence</h4></div>{result.grounding?.catalog_matches?.slice(0, 5).map((item) => <div className="source-row" key={`${item.relation}-${item.match_type}`}><Layers3 size={15} /><span><strong>{item.relation}</strong><small>{item.match_type} catalog match / score {item.score}</small></span></div>)}{result.grounding?.semantic_matches?.slice(0, 5).map((item) => <div className="source-row" key={item.name}><Braces size={15} /><span><strong>{item.name}</strong><small>{item.formula} at {item.grain}</small></span></div>)}{result.grounding?.join_matches?.slice(0, 5).map((item) => <div className="source-row" key={`${item.left_relation}-${item.right_relation}`}><Network size={15} /><span><strong>{item.left_relation} {item.join_type} {item.right_relation}</strong><small>{item.left_column} = {item.right_column}</small></span></div>)}<div className="subheading"><h4>Safety checks</h4></div><div className="check-list">{result.validation.checks.map((check) => <div key={check}><Check size={15} />{check}</div>)}</div></div></Modal>}
    </div>
  );
}


const formatMs = (value: number | null | undefined) => (value === null || value === undefined ? "-" : value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value * 10) / 10} ms`);
const formatRows = (value: number | null | undefined) => (value === null || value === undefined ? "-" : Math.round(value).toLocaleString());

function PasteRunSummary({ run, onJump }: { run: PastedSqlRun; onJump: (line: number | null) => void }) {
  if (run.status === "error" && run.error) {
    const error = run.error;
    return (
      <section className="surface pst-run pst-run-error" role="alert">
        <div className="pst-run-head"><XCircle size={17} /><strong>{run.stage === "execution" ? "Query failed" : run.stage === "catalog" ? "Blocked: table outside the catalog" : "Blocked by the read-only guard"}</strong>{error.line ? <button type="button" className="pst-link" onClick={() => onJump(error.line)}>line {error.line}{error.column ? `, column ${error.column}` : ""}</button> : null}</div>
        <p className="pst-error-message">{error.message}</p>
        {error.snippet !== null && error.line ? <pre className="pst-snippet"><span className="pst-snippet-line">{error.line}</span>{error.snippet}{error.column ? `\n${" ".repeat(String(error.line).length + 1)}${" ".repeat(Math.max(0, error.column - 1))}^` : ""}</pre> : null}
      </section>
    );
  }
  return (
    <section className={`surface pst-run${run.slow ? " pst-run-slow" : ""}`}>
      <div className="pst-run-head">
        <Check size={17} /><strong>Ran read-only</strong>
        <span className="pst-metric"><Clock size={14} />{formatMs(run.duration_ms)}</span>
        <span className="pst-metric">{run.row_count.toLocaleString()}{run.truncated ? "+" : ""} rows{run.truncated ? ` (limit ${run.limit.toLocaleString()})` : ""}</span>
        <span className="pst-metric">{run.lines.toLocaleString()} lines</span>
        {run.slow ? <span className="pst-badge high"><AlertTriangle size={13} />Slower than {formatMs(run.slow_threshold_ms)}</span> : <span className="pst-badge ok">Under {formatMs(run.slow_threshold_ms)}</span>}
        {run.protected_columns?.length ? <span className="caption">PII masked: {run.protected_columns.join(", ")}</span> : null}
      </div>
    </section>
  );
}

function PerformancePanel({ report, onRewrite, rewriting, notify }: { report: SqlPerformanceReport; onRewrite: () => void; rewriting: boolean; notify: (message: string, tone?: "ok" | "error") => void }) {
  const copy = (text: string) => navigator.clipboard?.writeText(text).then(() => notify("Copied to the clipboard"), () => notify("Clipboard unavailable", "error"));
  return (
    <section className="surface pst-perf">
      <div className="section-heading compact">
        <div><span className="eyebrow">EXECUTION PLAN</span><h3>Performance analysis</h3></div>
        <div className="pst-perf-meta">
          <span className="caption">{report.engine} / {report.analyzed ? "EXPLAIN ANALYZE (actual rows and time)" : report.plan_format ? "estimated plan" : "no plan for this engine"}{report.execution_ms ? ` / plan execution ${formatMs(report.execution_ms)}` : ""}{report.total_cost ? ` / cost ${Math.round(report.total_cost).toLocaleString()}` : ""}</span>
          {report.recommend_rewrite && <button type="button" className="primary-button" onClick={onRewrite} disabled={rewriting}>{rewriting ? <RefreshCw size={16} className="spin" /> : <Zap size={16} />}Rewrite for speed</button>}
        </div>
      </div>
      {report.plan_error && <p className="caption">Plan unavailable: {report.plan_error}</p>}
      <div className="subheading"><h4>Detected issues</h4><span>{report.issues.length}</span></div>
      {report.issues.length ? <ul className="pst-issues">{report.issues.map((issue, index) => <li key={`${issue.kind}-${index}`} className={`pst-issue ${issue.severity}`}><span className={`pst-badge ${issue.severity}`}>{issue.severity}</span><div><strong>{issue.title}</strong><p>{issue.detail}</p></div></li>)}</ul> : <div className="inline-empty">No scans of large tables, spills, large nested loops, non-sargable predicates or repeated subqueries were found.</div>}
      {report.operators.length > 0 && <>
        <div className="subheading"><h4>Costliest operators</h4><span>{report.analyzed ? "by time" : "by cost"}</span></div>
        <div className="data-table-wrap pst-ops"><table><thead><tr><th>Operator</th><th>Relation</th><th>Est. rows</th><th>Actual rows</th><th>Loops</th><th>{report.analyzed ? "Time" : "Cost"}</th><th>Share</th></tr></thead><tbody>
          {report.operators.map((operator, index) => <tr key={index}><td>{operator.node}{operator.index ? <small> ({operator.index})</small> : null}</td><td>{operator.relation || "-"}</td><td>{formatRows(operator.est_rows)}</td><td className={operator.actual_rows !== null && operator.actual_rows !== undefined && operator.est_rows ? (operator.actual_rows > 10 * operator.est_rows || operator.est_rows > 10 * Math.max(1, operator.actual_rows) ? "pst-misestimate" : "") : ""}>{formatRows(operator.actual_rows)}</td><td>{formatRows(operator.loops)}</td><td>{report.analyzed ? formatMs(operator.time_ms) : formatRows(operator.exclusive_cost ?? operator.cost)}</td><td><span className="pst-share"><span style={{ width: `${Math.min(100, operator.share_pct || 0)}%` }} /></span>{operator.share_pct !== null && operator.share_pct !== undefined ? `${operator.share_pct}%` : "-"}</td></tr>)}
        </tbody></table></div>
      </>}
      {report.cte_costs.length > 1 && <>
        <div className="subheading"><h4>Cost by CTE</h4><span>{report.cte_costs[0].basis === "plan" ? "from the plan" : "by structure (no plan costs)"}</span></div>
        <div className="pst-ctes">{report.cte_costs.map((cte) => <div key={cte.name}><code>{cte.name}</code><span className="pst-share"><span style={{ width: `${Math.min(100, cte.share_pct)}%` }} /></span><small>{cte.share_pct}% / {cte.lines} lines</small></div>)}</div>
      </>}
      <div className="subheading"><h4>Index suggestions for this query</h4><span>{report.index_suggestions.length}</span></div>
      {report.index_suggestions.length ? <div className="pst-indexes">{report.index_suggestions.map((item) => <div key={`${item.relation}-${item.columns.join("-")}`} className="pst-index"><div><strong>{item.relation} ({item.columns.join(", ")})</strong>{item.exists ? <span className="pst-badge ok">already indexed</span> : item.full_scan ? <span className="pst-badge medium">table is scanned</span> : null}<small>{item.reason}{item.verify_note ? `. ${item.verify_note}` : ""}</small></div><code>{item.statement}</code><button type="button" className="icon-button" title="Copy DDL (advice only: DataPilot never runs it)" onClick={() => copy(item.statement)}><Copy size={15} /></button></div>)}</div> : <div className="inline-empty">No filter, join or sort columns on catalogued tables to index.</div>}
    </section>
  );
}

function TuningPanel({ detail, running, busy, canSave, onUse, onApprove, onSaveArtifact, onClose }: { detail: SqlTuningDetail; running: boolean; busy: boolean; canSave: boolean; onUse: () => void; onApprove: () => void; onSaveArtifact: () => void; onClose: () => void }) {
  const report = detail.report as (SqlTuningDetail["report"] & SqlTuningReportExtras) | null;
  const attempts = (report?.attempts || []) as NonNullable<SqlTuningReportExtras["attempts"]>;
  const improved = report?.status === "improved" && detail.status === "SUCCEEDED" && Boolean(report.winning_sql);
  const lastLog = detail.logs[detail.logs.length - 1]?.message;
  return (
    <section className="surface pst-tune">
      <div className="section-heading compact">
        <div><span className="eyebrow">REWRITE FOR SPEED</span><h3>{improved ? `${report?.speedup_pct}% faster, same result` : detail.status === "FAILED" ? "Tuning failed" : report?.status === "no_improvement" ? "No faster equivalent found" : "Searching for a faster equivalent rewrite"}</h3></div>
        <div className="pst-perf-meta">
          {report?.mode === "piecewise" && <span className="caption">Piece-wise: {report.lines?.toLocaleString()} lines, rewriting CTE {report.cte_targets?.join(", ")}; the whole query is re-verified each time</span>}
          <button type="button" className="icon-button" title="Close" onClick={onClose}><XCircle size={16} /></button>
        </div>
      </div>
      {!["SUCCEEDED", "FAILED", "CANCELLED"].includes(detail.status) && <div className="compose-progress"><div className="compose-progress-bar"><span style={{ width: `${detail.progress}%` }} /></div><small>{running ? <RefreshCw size={12} className="spin" /> : null} {detail.status.toLowerCase()} / {detail.progress}%{lastLog ? ` / ${lastLog}` : ""}</small></div>}
      {(report?.error || detail.error) && <div className="conversation-memory compact-memory execution-error"><span>Why</span><p>{report?.error || detail.error}</p></div>}
      {report?.baseline_ms !== undefined && <div className="pst-run-head"><span className="pst-metric"><Clock size={14} />Original {formatMs(report.baseline_ms)}</span>{report.best_ms !== null && report.best_ms !== undefined && <span className="pst-metric"><Zap size={14} />Best {formatMs(report.best_ms)}</span>}{report.baseline?.row_count !== undefined && <span className="pst-metric">{report.baseline.row_count.toLocaleString()} reference rows</span>}{report.model && <span className="caption">{report.model}</span>}</div>}
      {attempts.length > 0 && <div className="data-table-wrap pst-attempts"><table><thead><tr><th>#</th>{report?.mode === "piecewise" && <th>CTE</th>}<th>Time</th><th>Same result</th><th>Outcome</th></tr></thead><tbody>
        {attempts.map((attempt) => <tr key={attempt.attempt} className={attempt.improved ? "pst-winner" : ""}><td>{attempt.attempt}</td>{report?.mode === "piecewise" && <td><code>{attempt.part || "-"}</code></td>}<td>{formatMs(attempt.ms)}</td><td>{attempt.equivalent ? <Check size={15} className="compose-ok" aria-label="same result" /> : attempt.sql ? <XCircle size={15} className="compose-failed" aria-label="different result" /> : "-"}</td><td>{attempt.improved ? `Faster: new best${attempt.notes ? ` (${attempt.notes})` : ""}` : attempt.rejected_reason || attempt.notes || "-"}</td></tr>)}
      </tbody></table></div>}
      {improved && report?.winning_sql && <>
        {report.plan_diff?.length ? <div className="check-list">{report.plan_diff.slice(0, 8).map((line) => <div key={line}><CircleGauge size={15} />{line}</div>)}</div> : null}
        <div className="subheading"><h4>Rewritten query vs original</h4><span>{(report.winning_sql.match(/\n/g)?.length ?? 0) + 1} lines</span></div>
        <pre className="pst-diff">{(report.diff?.length ? report.diff : report.winning_sql.split("\n").map((line) => `+${line}`)).map((line, index) => <span key={index} className={line.startsWith("@@") ? "hunk" : line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "del" : ""}>{line}{"\n"}</span>)}</pre>
        <div className="code-actions">
          <button type="button" className="secondary-button" onClick={onSaveArtifact} disabled={busy || !canSave}><Archive size={16} />Save as artifact</button>
          <button type="button" className="secondary-button" onClick={onApprove} disabled={busy || !canSave || detail.approval?.status === "pending"} title="The rewrite becomes the verified query for its question after approval">{detail.approval?.status === "pending" ? "Approval pending" : <><Sparkles size={16} />Save as verified query via approval</>}</button>
          <button type="button" className="primary-button" onClick={onUse}><Code2 size={16} />Use rewritten SQL</button>
        </div>
      </>}
    </section>
  );
}
