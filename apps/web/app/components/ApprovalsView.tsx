import {
  AlertCircle,
  Check,
  ChevronRight,
  Search,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type {
  Approval,
} from "../types";
import { StatusPill, EmptyState } from "./shared";


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
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [selected, setSelected] = useState<Approval | null>(null);
  const [filter, setFilter] = useState<"pending" | "decided">("pending");
  const [search, setSearch] = useState("");
  const load = useCallback(() => api<Approval[]>("/approvals").then((data) => { setApprovals(data); setSelected((current) => data.find((item) => item.id === current?.id) || data[0] || null); }), []);
  useEffect(() => { load(); }, [load]);
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
      <div className="approval-layout"><section className="surface approval-list">{filtered.map((approval) => <button key={approval.id} className={selected?.id === approval.id ? "selected" : ""} onClick={() => setSelected(approval)}><span className={`risk-mark ${approval.risk_level}`}><ShieldCheck size={18} /></span><span><strong>{approval.title}</strong><small>{approval.action_type.replaceAll("_", " ")} / {new Date(approval.created_at).toLocaleDateString()}</small></span><StatusPill value={approval.status} /><ChevronRight size={16} /></button>)}</section>
        <aside className="surface approval-detail">{selected ? <><div className="section-heading compact"><div><span className="eyebrow">DECISION REQUIRED</span><h3>{selected.title}</h3></div><StatusPill value={selected.risk_level} /></div><div className="evidence-box"><h4>Action summary</h4><p>{selected.evidence.summary || selected.evidence.objective}</p></div>{!!selected.evidence.plan?.length && <FrozenPlan evidence={selected.evidence} />}<div className="subheading"><h4>Guardrails and checks</h4></div><div className="check-list">{(selected.evidence.checks || selected.evidence.guardrails || []).map((check) => <div key={check}><ShieldCheck size={15} />{check}</div>)}</div><div className="approval-actions"><button className="danger-button" disabled={selected.status !== "pending"} onClick={() => decide("rejected")}><XCircle size={17} />Reject</button><button className="primary-button" disabled={selected.status !== "pending"} onClick={() => decide("approved")}><Check size={17} />Approve action</button></div></> : <EmptyState icon={<ShieldCheck size={24} />} title="No approvals" body="Controlled agent actions will appear here." />}</aside>
      </div>
    </div>
  );
}
