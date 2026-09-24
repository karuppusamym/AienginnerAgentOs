import {
  Activity,
  Bot,
  Boxes,
  Check,
  ChevronRight,
  Database,
  FileUp,
  GitBranch,
  RefreshCw,
  Send,
  Server,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type {
  NavKey,
  Overview,
  Recommendation,
  SecurityOverview,
  Job,
} from "../types";
import { StatusPill, Metric, ControlItem, SecurityOverviewPanel } from "./shared";


export function WorkspaceView({
  setActive,
  notify,
}: {
  setActive: (key: NavKey) => void;
  notify: (message: string, tone?: "ok" | "error") => void;
}) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [security, setSecurity] = useState<SecurityOverview | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [objective, setObjective] = useState("");
  const [running, setRunning] = useState(false);
  const [plan, setPlan] = useState<Job["plan"]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);

  const load = useCallback(() => {
    Promise.all([api<Overview>("/overview"), api<Job[]>("/jobs"), api<SecurityOverview>("/security-overview"), api<{ suggestions: Recommendation[] }>("/recommendations")])
      .then(([overviewData, jobsData, securityData, recommendationData]) => {
        setOverview(overviewData);
        setJobs(jobsData);
        setSecurity(securityData);
        setRecommendations(recommendationData.suggestions);
      })
      .catch(() => notify("The API is not available yet", "error"));
  }, [notify]);

  useEffect(load, [load]);

  async function runObjective(event: FormEvent) {
    event.preventDefault();
    if (!objective.trim()) return;
    setRunning(true);
    try {
      const result = await api<{ status: string; plan: Job["plan"]; approval_id?: string; plan_hash?: string; plan_bound?: boolean }>("/agents/runs", {
        method: "POST",
        body: JSON.stringify({ objective, autonomy_level: 2 }),
      });
      setPlan(result.plan);
      notify(
        result.approval_id ? (result.plan_bound && result.plan_hash ? `Plan ${result.plan_hash.slice(0, 12)} frozen and sent for approval` : "Draft complete and sent for approval") : "Bounded agent run completed",
      );
      load();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Agent run failed", "error");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="view-stack">
      <section className="command-surface">
        <div className="command-heading">
          <div>
            <span className="eyebrow">AUTONOMY LEVEL 2 / BOUNDED DRAFT</span>
            <h2>What do you want to build or understand?</h2>
            <p>DataPilot will inspect metadata, select specialists, and return a reviewable plan with evidence.</p>
          </div>
          <div className="command-model">
            <span className="status-dot" />
            <span>
              <small>Active model</small>
              <strong>{overview?.system.model || "Loading"}</strong>
            </span>
            <Bot size={16} />
          </div>
        </div>
        <form className="command-input" onSubmit={runObjective}>
          <Sparkles size={20} />
          <textarea
            value={objective}
            onChange={(event) => setObjective(event.target.value)}
            placeholder="Ask about your data, generate SQL, or draft a pipeline..."
            rows={2}
          />
          <button className="send-button" disabled={running || !objective.trim()} aria-label="Run request">
            {running ? <RefreshCw size={19} className="spin" /> : <Send size={19} />}
          </button>
        </form>
        <div className="quick-prompts" aria-label="Catalog-based recommended questions">
          {recommendations.map((recommendation, index) => <button key={`${recommendation.relation}-${index}`} title={recommendation.basis} onClick={() => setObjective(recommendation.question)}>{recommendation.question}</button>)}
        </div>
        <small className="recommendation-basis">Recommended from this project&apos;s catalog metadata.</small>
      </section>

      {plan.length > 0 && (
        <section className="plan-strip">
          <div className="section-heading compact">
            <div>
              <span className="eyebrow">LATEST RUN</span>
              <h3>Agent plan and trace</h3>
            </div>
            <button type="button" className="text-button" onClick={() => setActive("jobs")}>Open full trace <ChevronRight size={16} /></button>
          </div>
          <div className="plan-steps">
            {plan.map((step, index) => (
              <div className="plan-step" key={`${step.agent}-${index}`}>
                <span className={step.status === "complete" ? "step-index complete" : "step-index"}>{step.status === "complete" ? <Check size={14} /> : index + 1}</span>
                <div><strong>{step.agent}</strong><span>{step.action}</span></div>
                {index < plan.length - 1 && <span className="step-line" />}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="metric-grid">
        <Metric label="Catalog assets" value={overview?.counts.data_assets ?? "-"} detail="Grounded for agent use" icon={<Database size={19} />} tone="teal" />
        <Metric label="Connected sources" value={overview?.counts.connectors ?? "-"} detail="Read-only by default" icon={<Server size={19} />} tone="blue" />
        <Metric label="Active jobs" value={overview?.counts.jobs ?? "-"} detail="Tracked end to end" icon={<Activity size={19} />} tone="amber" />
        <Metric label="Needs approval" value={overview?.counts.pending_approvals ?? "-"} detail="Human decision required" icon={<ShieldCheck size={19} />} tone="rose" />
      </section>

      <section className="surface starter-surface">
        <div className="section-heading compact">
          <div>
            <span className="eyebrow">TRY THIS FIRST</span>
            <h3>Recommended sample workflow</h3>
          </div>
          <button type="button" className="secondary-button" onClick={() => setActive("files")}>
            <FileUp size={16} />
            Start with files
          </button>
        </div>
        <div className="starter-grid">
          <div className="starter-step">
            <span>1</span>
            <div>
              <strong>Upload a local file</strong>
              <small>Profile CSV, Excel, JSON, Parquet, or PDF and confirm the source shape.</small>
            </div>
            <button type="button" className="text-button" onClick={() => setActive("files")}>Open Files</button>
          </div>
          <div className="starter-step">
            <span>2</span>
            <div>
              <strong>Ask a grounded question</strong>
              <small>Use Analysis for a persistent topic that keeps context, SQL, and preview results together.</small>
            </div>
            <button type="button" className="text-button" onClick={() => setActive("conversations")}>Open Analysis</button>
          </div>
          <div className="starter-step">
            <span>3</span>
            <div>
              <strong>Inspect generated SQL</strong>
              <small>Review catalog grounding, semantic terms, validation checks, and reuse status before saving.</small>
            </div>
            <button type="button" className="text-button" onClick={() => setActive("sql")}>Open SQL</button>
          </div>
          <div className="starter-step">
            <span>4</span>
            <div>
              <strong>Review the run trace</strong>
              <small>Open Jobs to see plan steps, evidence, outputs, approvals, and operational logs.</small>
            </div>
            <button type="button" className="text-button" onClick={() => setActive("jobs")}>Open Jobs</button>
          </div>
        </div>
      </section>

      <SecurityOverviewPanel data={security} onOpenIncidents={() => setActive("jobs")} />

      <div className="two-column">
        <section className="surface">
          <div className="section-heading compact">
            <div>
              <span className="eyebrow">OPERATIONS</span>
              <h3>Recent work</h3>
            </div>
            <button className="icon-button" onClick={load} title="Refresh" aria-label="Refresh jobs"><RefreshCw size={17} /></button>
          </div>
          <div className="job-list">
            {jobs.slice(0, 4).map((job) => (
              <button className="job-row" key={job.id} onClick={() => setActive("jobs")}>
                <span className="job-icon"><Activity size={17} /></span>
                <span className="job-main"><strong>{job.title}</strong><small>{job.job_type.replaceAll("_", " ")}</small></span>
                <StatusPill value={job.status} />
                <span className="job-time">{new Date(job.created_at).toLocaleDateString()}</span>
                <ChevronRight size={16} />
              </button>
            ))}
          </div>
        </section>
        <section className="surface">
          <div className="section-heading compact">
            <div>
              <span className="eyebrow">LOCAL STACK</span>
              <h3>Control plane</h3>
            </div>
          </div>
          <div className="control-list">
            <ControlItem icon={<Bot size={17} />} label="Model routing" value={overview?.system.model || "Loading"} status="healthy" />
            <ControlItem icon={<Boxes size={17} />} label="Vector search" value={overview?.system.vector_store || "Qdrant"} status="healthy" />
            <ControlItem icon={<GitBranch size={17} />} label="Workflow engine" value={overview?.system.workflow_engine || "Temporal"} status="ready" />
            <ControlItem icon={<ShieldCheck size={17} />} label="Autonomy policy" value={`Level ${overview?.system.autonomy_level ?? 2}`} status="enforced" />
          </div>
        </section>
      </div>
    </div>
  );
}
