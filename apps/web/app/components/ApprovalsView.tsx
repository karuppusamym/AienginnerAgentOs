import {
  AlertCircle,
  Check,
  ChevronRight,
  Search,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { api } from "../lib/api";
import type {
  Approval,
} from "../types";
import { scopes, useApprovals, useInvalidate, useQueryErrorToast } from "../lib/queries";
import { StatusPill, EmptyState, LoadingBlock, formatScore } from "./shared";

const NO_APPROVALS: Approval[] = [];
const ACTION_LABELS: Record<string, string> = { prompt_activation: "Prompt activation", create_index: "Create index" };

/** GEPA-optimised prompt waiting to become the active version. */
function PromptActivationEvidence({ evidence }: { evidence: Approval["evidence"] }) {
  const delta = evidence.best_score != null && evidence.baseline_score != null ? evidence.best_score - evidence.baseline_score : null;
  return (
    <div className="approval-evidence-block">
      <div className="subheading"><h4>Prompt activation</h4>{evidence.optimization_id && <Link className="text-button" href={`/learning?tab=optimization&run=${encodeURIComponent(evidence.optimization_id)}`}>Open optimization run</Link>}</div>
      <dl className="plan-facts">
        <div><dt>Prompt</dt><dd>{evidence.prompt_name || "-"}</dd></div>
        <div><dt>Version</dt><dd>{evidence.version != null ? `v${evidence.version}` : "-"}</dd></div>
        <div><dt>Baseline</dt><dd>{formatScore(evidence.baseline_score)}</dd></div>
        <div><dt>Optimised</dt><dd>{formatScore(evidence.best_score)}{delta != null && <small className={delta >= 0 ? "score-up" : "score-down"}> ({delta >= 0 ? "+" : ""}{formatScore(delta, true)})</small>}</dd></div>
      </dl>
      {evidence.instructions && <details className="plan-objective" open><summary>Instructions to activate</summary><pre className="evidence-pre">{evidence.instructions}</pre></details>}
      <p className="plan-binding bound"><ShieldCheck size={14} />Approving activates exactly this version for SQL generation; it can be rolled back from Admin / Governance / Prompts.</p>
    </div>
  );
}

/** Index DDL recommended from observed query predicates; it runs only after approval. */
function CreateIndexEvidence({ evidence }: { evidence: Approval["evidence"] }) {
  return (
    <div className="approval-evidence-block">
      <div className="subheading"><h4>Create index</h4></div>
      <dl className="plan-facts">
        <div><dt>Relation</dt><dd>{evidence.relation || "-"}</dd></div>
        <div><dt>Columns</dt><dd>{evidence.columns?.join(", ") || "-"}</dd></div>
        <div><dt>Seen in</dt><dd>{evidence.occurrences ?? "-"} quer{evidence.occurrences === 1 ? "y" : "ies"}</dd></div>
      </dl>
      {evidence.statement && <pre className="evidence-pre">{evidence.statement}</pre>}
      <p className="plan-binding unbound"><AlertCircle size={14} />This DDL runs against the database only after approval.</p>
    </div>
  );
}


/** Why an agent run was held for approval; "jev:consequential" means the Jev decision model escalated it. */
function RiskTriggers({ evidence }: { evidence: Approval["evidence"] }) {
  const triggers = evidence.risk_triggers || [];
  const byJev = triggers.includes("jev:consequential") || evidence.jev?.consequential != null;
  if (!triggers.length && !byJev) return null;
  const others = triggers.filter((trigger) => trigger !== "jev:consequential");
  return (
    <div className="approval-evidence-block risk-triggers">
      {byJev && (
        <p className="plan-binding unbound jev-escalation">
          <AlertCircle size={14} />
          <span>Escalated by Jev{evidence.jev?.consequential != null ? ` (p=${evidence.jev.consequential.toFixed(2)})` : ""}{evidence.jev?.model ? <> · <code>{evidence.jev.model}</code></> : null}. The decision model can only add an approval step, never remove one.</span>
        </p>
      )}
      {others.length > 0 && <p className="approval-trigger-list"><strong>Approval triggers:</strong> {others.map((trigger) => trigger.replaceAll("_", " ")).join(", ")}</p>}
    </div>
  );
}

/** The exact plan an agent-run approval authorises, with its binding hash. */
function FrozenPlan({ evidence }: { evidence: Approval["evidence"] }) {
  const plan = evidence.plan || [];
  const bound = evidence.plan_bound === true;
  return (
    <div className="frozen-plan">
      <div className="subheading"><h4>Frozen plan</h4><span>{plan.length} step{plan.length === 1 ? "" : "s"}{evidence.plan_hash ? <> · <code title={evidence.plan_hash}>{evidence.plan_hash.slice(0, 12)}</code></> : null}</span></div>
      <ol className="frozen-plan-steps">
        {plan.map((step, index) => <li key={`${step.agent}-${index}`}><span>{index + 1}</span><span><strong>{step.agent}</strong><small>{step.action}</small></span></li>)}
      </ol>
      <p className={`plan-binding ${bound ? "bound" : "unbound"}`}>
        {bound ? <ShieldCheck size={14} /> : <AlertCircle size={14} />}
        {bound ? "Plan-bound: approving runs exactly these steps." : evidence.plan_binding_note || "Not plan-bound: the run may re-plan from the objective after approval."}
      </p>
      <dl className="plan-facts">
        {evidence.hold && <div><dt>Held on</dt><dd>{evidence.hold}</dd></div>}
        {evidence.autonomy_level !== undefined && <div><dt>Autonomy</dt><dd>Level {evidence.autonomy_level}</dd></div>}
        {evidence.planner && <div><dt>Planner</dt><dd>{evidence.planner}</dd></div>}
      </dl>
      {evidence.objective && evidence.summary && <details className="plan-objective"><summary>Full objective</summary><p>{evidence.objective}</p></details>}
    </div>
  );
}

export function ApprovalsView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const approvalsQuery = useApprovals();
  const approvals = approvalsQuery.data ?? NO_APPROVALS;
  useQueryErrorToast(approvalsQuery.error, notify, "Approvals could not be loaded");
  const invalidate = useInvalidate();
  // Deciding changes job state and may activate a prompt or create an index.
  const load = () => invalidate(scopes.approvals, scopes.jobs, scopes.promptOptimizations, scopes.indexRecommendations);
  // undefined = follow the first item; null = nothing selected (filter switched to an empty list).
  const [selectedId, setSelectedId] = useState<string | null | undefined>(undefined);
  const selected = selectedId === null ? null : approvals.find((item) => item.id === selectedId) || (selectedId === undefined ? approvals[0] || null : null);
  const setSelected = (approval: Approval | null) => setSelectedId(approval ? approval.id : null);
  const [filter, setFilter] = useState<"pending" | "decided">("pending");
  const [search, setSearch] = useState("");
  const filtered = approvals.filter((approval) => (filter === "pending" ? approval.status === "pending" : approval.status !== "pending") && (search ? approval.title.toLowerCase().includes(search.toLowerCase()) || approval.action_type.toLowerCase().includes(search.toLowerCase()) : true));
  async function decide(decision: "approved" | "rejected") {
    if (!selected) return;
    try {
      await api(`/approvals/${selected.id}/decision`, { method: "POST", body: JSON.stringify({ decision, note: decision === "approved" ? "Reviewed in local workspace" : "Returned for revision" }) });
      notify(`Action ${decision}`);
      await load();
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Decision failed", "error"); }
  }
  return (
    <div className="view-stack"><div className="view-header"><div><h2>Approval inbox</h2><p>Review evidence and decide every controlled write, schedule, or external action.</p></div><div className="row-actions"><div className="toolbar-search"><Search size={16} /><input placeholder="Search approvals..." value={search} onChange={(e) => setSearch(e.target.value)} /></div><div className="segmented"><button className={filter === "pending" ? "active" : ""} onClick={() => { setFilter("pending"); setSelected(approvals.find((item) => item.status === "pending") || null); }}>Pending</button><button className={filter === "decided" ? "active" : ""} onClick={() => { setFilter("decided"); setSelected(approvals.find((item) => item.status !== "pending") || null); }}>Decided</button></div></div></div>
      <div className="approval-layout"><section className="surface approval-list">{filtered.map((approval) => <button key={approval.id} className={selected?.id === approval.id ? "selected" : ""} onClick={() => setSelected(approval)}><span className={`risk-mark ${approval.risk_level}`}><ShieldCheck size={18} /></span><span><strong>{approval.title}</strong><small>{ACTION_LABELS[approval.action_type] || approval.action_type.replaceAll("_", " ")} / {new Date(approval.created_at).toLocaleDateString()}</small></span><StatusPill value={approval.status} /><ChevronRight size={16} /></button>)}</section>
        <aside className="surface approval-detail">{selected ? <><div className="section-heading compact"><div><span className="eyebrow">DECISION REQUIRED</span><h3>{selected.title}</h3></div><StatusPill value={selected.risk_level} /></div><div className="evidence-box"><h4>Action summary</h4><p>{selected.evidence.summary || selected.evidence.objective || (selected.action_type === "prompt_activation" ? `Activate ${selected.evidence.prompt_name || "prompt"} v${selected.evidence.version ?? "?"}` : selected.action_type === "create_index" ? `Create index on ${selected.evidence.relation || "relation"} (${selected.evidence.columns?.join(", ") || ""})` : "")}</p></div><RiskTriggers evidence={selected.evidence} />{!!selected.evidence.plan?.length && <FrozenPlan evidence={selected.evidence} />}{selected.action_type === "prompt_activation" && <PromptActivationEvidence evidence={selected.evidence} />}{selected.action_type === "create_index" && <CreateIndexEvidence evidence={selected.evidence} />}<div className="subheading"><h4>Guardrails and checks</h4></div><div className="check-list">{(selected.evidence.checks || selected.evidence.guardrails || []).map((check) => <div key={check}><ShieldCheck size={15} />{check}</div>)}</div><div className="approval-actions"><button className="danger-button" disabled={selected.status !== "pending"} onClick={() => decide("rejected")}><XCircle size={17} />Reject</button><button className="primary-button" disabled={selected.status !== "pending"} onClick={() => decide("approved")}><Check size={17} />Approve action</button></div></> : approvalsQuery.isPending ? <LoadingBlock label="Loading approvals" /> : <EmptyState icon={<ShieldCheck size={24} />} title="No approvals" body="Controlled agent actions will appear here." />}</aside>
      </div>
    </div>
  );
}
