import { ScreenVisibilityPanel } from "./ScreenVisibilityPanel";
import {
  AlertCircle,
  EyeOff,
  Archive,
  Bot,
  Check,
  Clock3,
  Database,
  Edit2,
  FlaskConical,
  Gauge,
  KeyRound,
  Layers3,
  Network,
  Play,
  Plus,
  RefreshCw,
  Search,
  Server,
  Settings,
  ShieldCheck,
  Sparkles,
  UserPlus,
  Users,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, SessionUser } from "../lib/api";
import { scopes, useConnectors, useDebouncedValue, useFacets, useInvalidate, useModelProviders, useModelRouting, useModelUsage, usePagedQuery, usePagination, useQueryErrorToast, useSchemaDrift, type Facet, type PageParams } from "../lib/queries";
import type {
  NavKey,
  Connector,
  ModelProvider,
  Project,
  Job,
  ExternalClient,
  QueryTool,
  QueryToolGrant,
  QueryToolDraft,
  QueryToolAiDraft,
  RelationOption,
  QueryToolRegistrySummary,
  PromptArtifact,
  RetentionPolicy,
  SchemaDrift,
  ModelUsage,
  ModelRouting,
} from "../types";
import {
  connectorLabels,
  providerCapability,
  providerTypeOptions,
} from "../lib/constants";
import { StatusPill, LoadingBlock, EmptyState, Modal, Metric, useConfirm, formatUsd, CollapsibleGroup, GroupBySelect, Pagination } from "./shared";
import { AuditLogPanel } from "./AuditLog";
import { useWorkspace } from "../lib/workspace";

/** GET /query-tools/{id}/analytics (admin-only). */
type QueryToolAnalytics = { invocation_count: number; success_count: number; failure_count: number; success_rate: number | null; median_latency_ms: number | null; rows_returned: number; last_invoked_at: string | null; client_usage: { client: string; invocations: number }[]; recent_errors: { at: string; error: string }[] };


export function AdminView({ currentUser, notify, setActive: setAppActive }: { currentUser: SessionUser; notify: (message: string, tone?: "ok" | "error") => void; setActive?: (key: NavKey) => void }) {
  const [tab, setTab] = useState<"users" | "projects" | "connectors" | "models" | "governance" | "audit" | "auth" | "screens">(() => (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("tab") === "screens" ? "screens" : "connectors"));
  return (
    <div className="view-stack">
      <div className="view-header"><div><h2>Administration</h2><p>Configure local access, data sources, model routing, and enterprise identity.</p></div><StatusPill value={currentUser.role} /></div>
      <div className="tabs"><button className={tab === "connectors" ? "active" : ""} onClick={() => setTab("connectors")}><Server size={16} />Connectors</button><button className={tab === "models" ? "active" : ""} onClick={() => setTab("models")}><Bot size={16} />Model providers</button><button className={tab === "governance" ? "active" : ""} onClick={() => setTab("governance")}><ShieldCheck size={16} />Governance</button><button className={tab === "projects" ? "active" : ""} onClick={() => setTab("projects")}><Layers3 size={16} />Projects</button><button className={tab === "users" ? "active" : ""} onClick={() => setTab("users")}><Users size={16} />Users</button><button className={tab === "audit" ? "active" : ""} onClick={() => setTab("audit")}><Clock3 size={16} />Audit log</button><button className={tab === "auth" ? "active" : ""} onClick={() => setTab("auth")}><KeyRound size={16} />Authentication</button><button className={tab === "screens" ? "active" : ""} onClick={() => setTab("screens")}><EyeOff size={16} />Screens</button></div>
      <p className="admin-hint">Looking for the query-tool / external-gateway registry or external agent call history? It's under <strong>Agents &amp; tools</strong> in the main navigation — External gateway / query tools and Invocation history tabs.</p>
      {tab === "connectors" && <ConnectorsAdmin notify={notify} />}
      {tab === "models" && <ModelsAdmin notify={notify} />}
      {tab === "governance" && <GovernanceAdmin notify={notify} setActive={setAppActive} />}
      {tab === "projects" && <ProjectsAdmin notify={notify} />}
      {tab === "users" && <UsersAdmin notify={notify} currentUser={currentUser} />}
      {tab === "audit" && <AuditLogPanel notify={notify} />}
      {tab === "auth" && <AuthAdmin notify={notify} />}
      {tab === "screens" && <ScreenVisibilityPanel notify={notify} />}
    </div>
  );
}

export function GatewayAdmin({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const emptyTool = { name: "", description: "", purpose: "", data_source: "", line_of_business: "", owner: "", tags: "", connector_id: "", upstream_tool_name: "", sql_template: "SELECT * FROM staging.example WHERE id = :id", parameter_schema: '{"type":"object","required":["id"],"properties":{"id":{"type":"integer"}},"additionalProperties":false}', allowed_relations: "staging.example", row_limit: 200, timeout_seconds: 15 };
  const [clients, setClients] = useState<ExternalClient[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [showTool, setShowTool] = useState(false);
  const [showClient, setShowClient] = useState(false);
  const [showWizard, setShowWizard] = useState(false);
  const [selected, setSelected] = useState<QueryTool | null>(null);
  const [toolForm, setToolForm] = useState(emptyTool);
  const [aiToolQuestion, setAiToolQuestion] = useState("");
  const [aiToolDrafting, setAiToolDrafting] = useState(false);
  async function draftToolWithAi() {
    setAiToolDrafting(true);
    try {
      const draft = await api<QueryToolAiDraft>("/query-tools/draft", { method: "POST", body: JSON.stringify({ sql: toolForm.sql_template, question: aiToolQuestion }) });
      setToolForm((current) => ({ ...current, name: draft.name, description: draft.description, purpose: draft.purpose, line_of_business: draft.line_of_business, tags: draft.tags.join(", "), parameter_schema: JSON.stringify(draft.parameter_schema, null, 2), allowed_relations: draft.allowed_relations.length ? draft.allowed_relations.join(", ") : current.allowed_relations }));
      notify(draft.by === "llm" ? `Drafted by ${draft.model ?? "the design model"}: review before saving` : "Drafted from the SQL (no design model routed): review before saving");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "The draft could not be created", "error");
    } finally {
      setAiToolDrafting(false);
    }
  }
  const [clientName, setClientName] = useState("");
  const [issuedToken, setIssuedToken] = useState("");
  const [grantClient, setGrantClient] = useState("");
  const [grantQuota, setGrantQuota] = useState("");
  const [grants, setGrants] = useState<QueryToolGrant[]>([]);
  const [clientExpiryDays, setClientExpiryDays] = useState("");
  const [rotating, setRotating] = useState<ExternalClient | null>(null);
  const [rotateExpiryDays, setRotateExpiryDays] = useState("");
  const [testParameters, setTestParameters] = useState("{}");
  const [confirmRetire, retireDialog] = useConfirm();
  const { user } = useWorkspace();
  // Retire and usage analytics are admin-only on the API; engineers see the buttons disabled.
  const isAdmin = user.role === "admin";
  const [analytics, setAnalytics] = useState<QueryToolAnalytics | null>(null);
  const [summary, setSummary] = useState<QueryToolRegistrySummary | null>(null);
  const [search, setSearch] = useState("");
  const [groupBy, setGroupBy] = useState<"none" | "data_source" | "line_of_business">("none");
  const query = useDebouncedValue(search.trim());
  const invalidate = useInvalidate();
  const facets = useFacets<{ total: number; data_source: Facet[]; line_of_business: Facet[] }>(scopes.queryTools, groupBy === "none" ? null : "/query-tools/facets", { q: query });
  const load = useCallback(async () => { const [clientData, connectorData, summaryData] = await Promise.all([api<ExternalClient[]>("/external-clients"), api<Connector[]>("/connectors"), api<QueryToolRegistrySummary>("/query-tools/summary"), invalidate(scopes.queryTools)]); setClients(clientData); setConnectors(connectorData); setSummary(summaryData); }, [invalidate]);
  useEffect(() => { load().catch((reason) => notify(reason instanceof Error ? reason.message : "Gateway configuration unavailable", "error")); }, [load, notify]);
  function chooseGrantClient(clientId: string, known: QueryToolGrant[] = grants) { setGrantClient(clientId); const existing = known.find((item) => item.external_client_id === clientId); setGrantQuota(existing?.daily_quota ? String(existing.daily_quota) : ""); }
  async function loadGrants(tool: QueryTool) { try { const data = await api<QueryToolGrant[]>(`/query-tools/${tool.id}/grants`); setGrants(data); chooseGrantClient(clients[0]?.id || "", data); } catch { setGrants([]); } }
  function openTool(tool?: QueryTool) { setAnalytics(null); setGrants([]); setGrantQuota(""); if (tool) void loadGrants(tool); setSelected(tool || null); setToolForm(tool ? { name: tool.name, description: tool.description, purpose: tool.purpose, data_source: tool.data_source, line_of_business: tool.line_of_business, owner: tool.owner, tags: tool.tags.join(", "), connector_id: tool.connector_id || "", upstream_tool_name: tool.upstream_tool_name || "", sql_template: tool.sql_template, parameter_schema: JSON.stringify(tool.parameter_schema, null, 2), allowed_relations: tool.allowed_relations.join(", "), row_limit: tool.row_limit, timeout_seconds: tool.timeout_seconds } : emptyTool); setTestParameters("{}"); setGrantClient(clients[0]?.id || ""); setShowTool(true); }
  function startFromTemplate(kind: "lookup" | "count") { const lookup = kind === "lookup"; setSelected(null); setToolForm({ ...emptyTool, name: lookup ? "record.lookup" : "records.count_by_filter", description: lookup ? "Look up one record by a governed identifier." : "Count governed records using an optional bounded status filter.", purpose: lookup ? "Support a read-only support lookup by identifier." : "Support a read-only operational count by status.", tags: lookup ? "lookup, read-only" : "count, read-only", sql_template: lookup ? "SELECT * FROM staging.example WHERE id = :id LIMIT 1" : "SELECT COUNT(*) AS total FROM staging.example WHERE status = :status", parameter_schema: lookup ? '{"type":"object","required":["id"],"properties":{"id":{"type":"integer"}},"additionalProperties":false}' : '{"type":"object","required":["status"],"properties":{"status":{"type":"string"}},"additionalProperties":false}', allowed_relations: "staging.example", row_limit: lookup ? 1 : 100 }); setTestParameters(lookup ? '{"id": 1}' : '{"status": "active"}'); setGrantClient(clients[0]?.id || ""); setShowTool(true); }
  async function saveTool(event: FormEvent) { event.preventDefault(); try { const payload = { ...toolForm, connector_id: toolForm.connector_id || null, upstream_tool_name: toolForm.upstream_tool_name || null, tags: toolForm.tags.split(",").map((item) => item.trim()).filter(Boolean), parameter_schema: JSON.parse(toolForm.parameter_schema), result_schema: { type: "object" }, allowed_relations: toolForm.allowed_relations.split(",").map((item) => item.trim()).filter(Boolean), requires_approval: false }; await api(selected ? `/query-tools/${selected.id}` : "/query-tools", { method: selected ? "PUT" : "POST", body: JSON.stringify(payload) }); setShowTool(false); setSelected(null); await load(); notify(selected ? "Query tool saved as a new draft version" : "Query tool draft created"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Query tool could not be saved", "error"); } }
  async function retire(tool: QueryTool) {
    if (!(await confirmRetire({ title: "Retire query tool", body: `Retire "${tool.name}" v${tool.version}? External agents and bound agents can no longer list or invoke it. The definition and its history are kept.`, confirmLabel: "Retire tool" }))) return;
    try { await api(`/query-tools/${tool.id}/retire`, { method: "POST" }); await load(); if (selected?.id === tool.id) setShowTool(false); notify("Query tool retired"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Query tool could not be retired", "error"); }
  }
  async function loadAnalytics(tool: QueryTool) { try { setAnalytics(await api<QueryToolAnalytics>(`/query-tools/${tool.id}/analytics`)); } catch (reason) { notify(reason instanceof Error ? reason.message : "Usage analytics unavailable", "error"); } }
  async function publish(tool: QueryTool) { try { await api(`/query-tools/${tool.id}/publish`, { method: "POST" }); await load(); notify("Query tool published"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Query tool could not be published", "error"); } }
  async function testTool() { if (!selected) return; try { const result = await api<{ row_count: number }>(`/query-tools/${selected.id}/test`, { method: "POST", body: JSON.stringify({ parameters: JSON.parse(testParameters) }) }); notify(`Query tool returned ${result.row_count} rows`); } catch (reason) { notify(reason instanceof Error ? reason.message : "Query tool test failed", "error"); } }
  async function grant() { if (!selected || !grantClient) return; const quota = grantQuota.trim() ? Number(grantQuota) : null; if (quota !== null && (!Number.isInteger(quota) || quota < 1)) { notify("Daily quota must be a whole number of at least 1, or empty for unlimited", "error"); return; } try { const saved = await api<QueryToolGrant>(`/query-tools/${selected.id}/grants`, { method: "POST", body: JSON.stringify({ external_client_id: grantClient, enabled: true, daily_quota: quota }) }); setGrants((current) => [...current.filter((item) => item.external_client_id !== saved.external_client_id), saved]); notify(quota ? `External client grant saved (${quota} calls/day)` : "External client grant saved (no daily quota)"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Grant could not be saved", "error"); } }
  async function createClient(event: FormEvent) { event.preventDefault(); try { const created = await api<ExternalClient>("/external-clients", { method: "POST", body: JSON.stringify({ name: clientName, scopes: ["tools:list", "tools:invoke"], ...(clientExpiryDays.trim() ? { expires_in_days: Number(clientExpiryDays) } : {}) }) }); setIssuedToken(created.token || ""); setClientName(""); setClientExpiryDays(""); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "External client could not be created", "error"); } }
  async function rotate(event: FormEvent) { event.preventDefault(); if (!rotating) return; const client = rotating; try { const updated = await api<ExternalClient>(`/external-clients/${client.id}/rotate`, { method: "POST", body: JSON.stringify(rotateExpiryDays.trim() ? { expires_in_days: Number(rotateExpiryDays) } : {}) }); setRotating(null); setRotateExpiryDays(""); setIssuedToken(updated.token || ""); setShowClient(true); await load(); notify("Client token rotated"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Token rotation failed", "error"); } }
  async function toggleClient(client: ExternalClient) { try { await api(`/external-clients/${client.id}`, { method: "PUT", body: JSON.stringify({ active: !client.active, scopes: client.scopes }) }); await load(); notify(`External client ${client.active ? "disabled" : "enabled"}`); } catch (reason) { notify(reason instanceof Error ? reason.message : "Client update failed", "error"); } }
  const selectedConnector = connectors.find((item) => item.id === toolForm.connector_id);
  if (showWizard) return <QueryToolWizard notify={notify} onCancel={() => setShowWizard(false)} onUse={(draft) => { setSelected(null); setToolForm({ name: draft.name, description: draft.description, purpose: draft.purpose, data_source: draft.data_source, line_of_business: draft.line_of_business, owner: draft.owner, tags: draft.tags.join(", "), connector_id: draft.connector_id || "", upstream_tool_name: draft.upstream_tool_name || "", sql_template: draft.sql_template, parameter_schema: JSON.stringify(draft.parameter_schema, null, 2), allowed_relations: draft.allowed_relations.join(", "), row_limit: draft.row_limit, timeout_seconds: draft.timeout_seconds }); setTestParameters("{}"); setGrantClient(clients[0]?.id || ""); setShowWizard(false); setShowTool(true); }} />;
  return <div className="view-stack">
    <section className="surface admin-surface">
      <div className="section-heading"><div><span className="eyebrow">EXTERNAL AGENT ACCESS</span><h3>Governed query gateway</h3><p>Published parameterized tools are searchable by purpose, source, LOB, owner, and tags over REST and MCP.</p></div><div className="row-actions"><div className="toolbar-search"><Search size={16} /><input placeholder="Search tools by name, owner, LOB, tag..." value={search} onChange={(event) => setSearch(event.target.value)} /></div><button className="secondary-button" onClick={() => setShowWizard(true)}><Database size={16} />Catalog wizard</button><button className="secondary-button" onClick={() => startFromTemplate("lookup")}><Database size={16} />Lookup template</button><button className="secondary-button" onClick={() => startFromTemplate("count")}><FlaskConical size={16} />Count template</button><button className="secondary-button" onClick={() => { setIssuedToken(""); setShowClient(true); }}><KeyRound size={16} />New client</button><button className="primary-button" onClick={() => openTool()}><Plus size={16} />New query tool</button></div></div>
      <div className="metric-grid three"><Metric label="Published" value={summary?.published ?? "-"} detail="Available to granted clients" icon={<Check size={18} />} tone="teal" /><Metric label="Invocations" value={summary?.tools.reduce((total, tool) => total + tool.invocation_count, 0) ?? "-"} detail="Audited external requests" icon={<Network size={18} />} tone="blue" /><Metric label="Never invoked" value={summary?.never_invoked ?? "-"} detail="Review for adoption or retirement" icon={<AlertCircle size={18} />} tone="amber" /></div>
      <div className="list-toolbar"><GroupBySelect value={groupBy} onChange={setGroupBy} options={[{ value: "none", label: "None" }, { value: "data_source", label: "Data source" }, { value: "line_of_business", label: "Line of business" }]} /></div>
      {groupBy === "none" ? <GatewayToolRows params={{ q: query }} connectors={connectors} searching={!!query} onOpen={openTool} onPublish={publish} onRetire={retire} canRetire={isAdmin} /> : facets.data ? (facets.data[groupBy].length ? facets.data[groupBy].map((facet) => <CollapsibleGroup key={facet.value} title={facet.value} count={facet.count} defaultOpen={facets.data!.total <= 20}><GatewayToolRows params={{ q: query, [groupBy]: facet.value }} connectors={connectors} searching={!!query} onOpen={openTool} onPublish={publish} onRetire={retire} canRetire={isAdmin} compact /></CollapsibleGroup>) : <div className="inline-empty">{query ? "No tools match your search." : "No query tools yet."}</div>) : <LoadingBlock label="Grouping tools" />}
    </section>
    <section className="surface admin-surface">
      <div className="section-heading compact"><div><span className="eyebrow">CLIENT CREDENTIALS</span><h3>External clients</h3></div><code>/mcp / external/v1/query-tools</code></div>
      <div className="table-header external-client-grid"><span>Client</span><span>Client ID</span><span>Scopes</span><span>Status</span><span /></div>
      {clients.map((client) => <div className="data-row external-client-grid" key={client.id}><span><strong>{client.name}</strong><small>Created {new Date(client.created_at).toLocaleDateString()} · {client.expires_at ? `${client.expired ? "Expired" : "Expires"} ${new Date(client.expires_at).toLocaleDateString()}` : "No expiry"} · {client.last_used_at ? `Last used ${new Date(client.last_used_at).toLocaleString()}` : "Never used"}</small></span><code>{client.client_id}</code><span>{client.scopes.join(", ")}</span><StatusPill value={!client.active ? "disabled" : client.expired ? "expired" : "active"} /><span className="row-actions"><button className="icon-button" title="Rotate token" onClick={() => { setRotateExpiryDays(""); setRotating(client); }}><RefreshCw size={16} /></button><button className="icon-button" title={client.active ? "Disable client" : "Enable client"} onClick={() => toggleClient(client)}>{client.active ? <XCircle size={16} /> : <Check size={16} />}</button></span></div>)}
    </section>
    {showTool && <Modal title={selected ? `Query tool v${selected.version}` : "Create query tool"} onClose={() => setShowTool(false)}><form className="modal-form" onSubmit={saveTool}>
      <div className="form-grid"><label>Name<input value={toolForm.name} onChange={(event) => setToolForm({ ...toolForm, name: event.target.value })} required /></label><label>Connector<select value={toolForm.connector_id} onChange={(event) => setToolForm({ ...toolForm, connector_id: event.target.value, upstream_tool_name: "" })}><option value="">Local PostgreSQL</option>{connectors.map((connector) => <option key={connector.id} value={connector.id}>{connector.name} / {connector.connection_mode}</option>)}</select></label></div>
      <label>Description<input value={toolForm.description} onChange={(event) => setToolForm({ ...toolForm, description: event.target.value })} required /></label>
      <label>Purpose<textarea rows={3} value={toolForm.purpose} onChange={(event) => setToolForm({ ...toolForm, purpose: event.target.value })} required /></label>
      <div className="form-grid"><label>Data source<input value={toolForm.data_source} onChange={(event) => setToolForm({ ...toolForm, data_source: event.target.value })} required /></label><label>Line of business<input value={toolForm.line_of_business} onChange={(event) => setToolForm({ ...toolForm, line_of_business: event.target.value })} required /></label></div>
      <div className="form-grid"><label>Owner<input value={toolForm.owner} onChange={(event) => setToolForm({ ...toolForm, owner: event.target.value })} required /></label><label>Tags<input value={toolForm.tags} onChange={(event) => setToolForm({ ...toolForm, tags: event.target.value })} placeholder="accounts, customer, read-only" /></label></div>
      {selectedConnector?.connection_mode === "mcp" && <label>Upstream MCP tool name<input value={toolForm.upstream_tool_name} onChange={(event) => setToolForm({ ...toolForm, upstream_tool_name: event.target.value })} placeholder="get_account" required /></label>}
      <label>Read-only SQL template<textarea rows={7} value={toolForm.sql_template} onChange={(event) => setToolForm({ ...toolForm, sql_template: event.target.value })} required /></label>
      {!selected && <div className="tool-ai-draft-row"><input value={aiToolQuestion} onChange={(event) => setAiToolQuestion(event.target.value)} placeholder="Optional: the business question this tool answers" aria-label="Question for AI draft" /><button type="button" className="secondary-button" onClick={() => void draftToolWithAi()} disabled={aiToolDrafting || (!toolForm.sql_template.trim() && !aiToolQuestion.trim())}>{aiToolDrafting ? <RefreshCw size={16} className="spin" /> : <Sparkles size={16} />}Draft with AI</button></div>}
      <label>Parameter JSON Schema<textarea rows={7} value={toolForm.parameter_schema} onChange={(event) => setToolForm({ ...toolForm, parameter_schema: event.target.value })} required /></label>
      <div className="form-grid"><label>Allowed relations<input value={toolForm.allowed_relations} onChange={(event) => setToolForm({ ...toolForm, allowed_relations: event.target.value })} /></label><label>Row limit<input type="number" min={1} max={1000} value={toolForm.row_limit} onChange={(event) => setToolForm({ ...toolForm, row_limit: Number(event.target.value) })} /></label></div>
      {selected && <><label>Test parameters<textarea rows={4} value={testParameters} onChange={(event) => setTestParameters(event.target.value)} /></label><div className="inline-admin-form"><select value={grantClient} onChange={(event) => chooseGrantClient(event.target.value)}><option value="">Select external client</option>{clients.map((client) => <option value={client.id} key={client.id}>{client.name}</option>)}</select><input type="number" min={1} max={1000000} placeholder="Daily quota (unlimited)" title="Maximum invocations per UTC day for this client; empty = unlimited" value={grantQuota} onChange={(event) => setGrantQuota(event.target.value)} /><button type="button" className="secondary-button" onClick={grant}><KeyRound size={16} />Grant</button><button type="button" className="secondary-button" onClick={testTool}><Play size={16} />Test</button><button type="button" className="secondary-button" onClick={() => void loadAnalytics(selected)} disabled={!isAdmin} title={isAdmin ? "Invocation analytics for this tool" : "Usage analytics are admin-only"}><Gauge size={16} />Usage</button><button type="button" className="secondary-button danger" onClick={() => void retire(selected)} disabled={!isAdmin || selected.status === "retired"} title={isAdmin ? "Retire this tool" : "Retiring tools is admin-only"}><XCircle size={16} />Retire</button></div>{analytics && <div className="policy-details query-tool-analytics"><div><span>Invocations</span><strong>{analytics.invocation_count} ({analytics.success_count} ok / {analytics.failure_count} failed)</strong></div><div><span>Success rate</span><strong>{analytics.success_rate == null ? "-" : `${analytics.success_rate}%`}</strong></div><div><span>Median latency</span><strong>{analytics.median_latency_ms == null ? "-" : `${analytics.median_latency_ms} ms`}</strong></div><div><span>Rows returned</span><strong>{analytics.rows_returned}</strong></div><div><span>Last invoked</span><strong>{analytics.last_invoked_at ? new Date(analytics.last_invoked_at).toLocaleString() : "Never"}</strong></div><div><span>Clients</span><strong>{analytics.client_usage.map((item) => `${item.client} (${item.invocations})`).join(", ") || "None"}</strong></div>{analytics.recent_errors.length > 0 && <div><span>Recent errors</span><strong>{analytics.recent_errors.map((item) => item.error).join(" · ")}</strong></div>}</div>}</>}
      <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowTool(false)}>Cancel</button><button className="primary-button"><Archive size={16} />Save draft</button></div>
    </form></Modal>}
    {rotating && <Modal title={`Rotate token: ${rotating.name}`} onClose={() => setRotating(null)}><form className="modal-form" onSubmit={rotate}><div className="policy-banner"><KeyRound size={18} /><span><strong>The current token stops working immediately</strong><small>{rotating.expires_at ? `${rotating.expired ? "Expired" : "Expires"} ${new Date(rotating.expires_at).toLocaleDateString()}` : "The current token never expires"}. Leave the field empty to keep the current expiry.</small></span></div><label>Expires in days<input type="number" min={1} max={365} placeholder="Keep current expiry" value={rotateExpiryDays} onChange={(event) => setRotateExpiryDays(event.target.value)} /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setRotating(null)}>Cancel</button><button className="primary-button"><RefreshCw size={16} />Rotate token</button></div></form></Modal>}
    {retireDialog}
    {showClient && <Modal title="External client" onClose={() => setShowClient(false)}>{issuedToken ? <div className="modal-form"><div className="policy-banner"><KeyRound size={18} /><span><strong>One-time client token</strong><small>This value is not available again after this dialog closes.</small></span></div><label>Bearer token<textarea readOnly rows={4} value={issuedToken} onFocus={(event) => event.currentTarget.select()} /></label><div className="modal-actions"><button className="primary-button" onClick={() => setShowClient(false)}><Check size={16} />Done</button></div></div> : <form className="modal-form" onSubmit={createClient}><label>Client name<input value={clientName} onChange={(event) => setClientName(event.target.value)} required /></label><label>Expires in days<input type="number" min={1} max={365} placeholder="Never expires" value={clientExpiryDays} onChange={(event) => setClientExpiryDays(event.target.value)} /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowClient(false)}>Cancel</button><button className="primary-button"><KeyRound size={16} />Issue token</button></div></form>}</Modal>}
  </div>;
}

function GatewayToolRows({ params, connectors, searching, onOpen, onPublish, onRetire, canRetire = false, compact = false }: { params: PageParams; connectors: Connector[]; searching: boolean; onOpen: (tool: QueryTool) => void; onPublish: (tool: QueryTool) => void; onRetire?: (tool: QueryTool) => void; canRetire?: boolean; compact?: boolean }) {
  const pagination = usePagination(params, compact ? 25 : 50);
  const page = usePagedQuery<QueryTool>(scopes.queryTools, "/query-tools", params, pagination);
  const items = page.data?.items ?? [];
  if (!items.length) return page.isPending ? <LoadingBlock label="Loading tools" /> : <div className="inline-empty">{searching ? "No tools match your search." : "No query tools yet."}</div>;
  return <>
    <div className="table-header gateway-tool-grid"><span>Tool</span><span>Connector</span><span>Version</span><span>Status</span><span /></div>
    {items.map((tool) => <div className="data-row gateway-tool-grid" key={tool.id}><button className="metric-main" onClick={() => onOpen(tool)}><strong>{tool.name}</strong><small>{tool.line_of_business} · {tool.purpose}</small></button><span>{connectors.find((item) => item.id === tool.connector_id)?.name || "Local PostgreSQL"}</span><span>v{tool.version}</span><StatusPill value={tool.status} /><span className="row-actions"><button className="icon-button" title={tool.status === "retired" ? "Publish again (un-retire)" : "Publish query tool"} disabled={tool.status === "published"} onClick={() => onPublish(tool)}><Check size={16} /></button>{onRetire && <button className="icon-button danger" title={canRetire ? "Retire query tool" : "Retiring tools is admin-only"} disabled={!canRetire || tool.status === "retired"} onClick={() => onRetire(tool)}><XCircle size={16} /></button>}</span></div>)}
    <Pagination state={pagination} total={page.data?.total ?? 0} count={items.length} busy={page.isFetching} label="tools" compact={compact} />
  </>;
}

export function QueryToolWizard({ notify, onCancel, onUse }: { notify: (message: string, tone?: "ok" | "error") => void; onCancel: () => void; onUse: (draft: QueryToolDraft) => void }) {
  const [relations, setRelations] = useState<RelationOption[]>([]);
  const [assetId, setAssetId] = useState("");
  const [template, setTemplate] = useState<"record_lookup" | "filtered_count" | "recent_records">("record_lookup");
  const [column, setColumn] = useState("");
  const [generating, setGenerating] = useState(false);
  useEffect(() => { api<RelationOption[]>("/query-tools/relation-options").then((items) => { const unique = items.filter((item, index, self) => index === self.findIndex((t) => t.relation === item.relation && t.connector_name === item.connector_name)); setRelations(unique); setAssetId(unique[0]?.asset_id || ""); setColumn(unique[0]?.columns[0]?.name || ""); }).catch((reason) => notify(reason instanceof Error ? reason.message : "Catalog relations unavailable", "error")); }, [notify]);
  const selected = relations.find((item) => item.asset_id === assetId);
  function chooseAsset(id: string) { const next = relations.find((item) => item.asset_id === id); setAssetId(id); setColumn(next?.columns[0]?.name || ""); }
  async function generate() { if (!selected || !column) return; setGenerating(true); try { const payload = template === "record_lookup" ? { asset_id: selected.asset_id, template, key_column: column } : template === "filtered_count" ? { asset_id: selected.asset_id, template, filter_column: column } : { asset_id: selected.asset_id, template, time_column: column }; const result = await api<{ suggested_tool: QueryToolDraft }>("/query-tools/wizard/preview", { method: "POST", body: JSON.stringify(payload) }); onUse(result.suggested_tool); notify("Catalog-grounded query tool draft generated"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not generate a query tool draft", "error"); } finally { setGenerating(false); } }
  const columnLabel = template === "record_lookup" ? "Identifier column" : template === "filtered_count" ? "Filter column" : "Time column";
  return <div className="view-stack"><div className="view-header"><div><h2>Catalog query-tool wizard</h2><p>Select a governed relation and column. The generated contract remains a draft for review, testing, publication, and grants.</p></div><button className="secondary-button" onClick={onCancel}>Back to gateway</button></div><section className="surface admin-surface"><form className="modal-form" onSubmit={(event) => { event.preventDefault(); void generate(); }}><label>Relation<select value={assetId} onChange={(event) => chooseAsset(event.target.value)} required>{relations.map((relation) => <option value={relation.asset_id} key={relation.asset_id}>{relation.relation} / {relation.connector_name}</option>)}</select></label>{selected && <div className="policy-banner"><Database size={18} /><span><strong>{selected.source_name}</strong><small>{selected.tags.join(", ") || "No catalog tags"}</small></span></div>}<div className="form-grid"><label>Contract template<select value={template} onChange={(event) => setTemplate(event.target.value as "record_lookup" | "filtered_count" | "recent_records")}><option value="record_lookup">Record lookup</option><option value="filtered_count">Count by filter</option><option value="recent_records">Recent records</option></select></label><label>{columnLabel}<select value={column} onChange={(event) => setColumn(event.target.value)} required>{selected?.columns.map((item) => <option key={item.name} value={item.name}>{item.name} / {item.type}</option>)}</select></label></div><div className="modal-actions"><button type="button" className="secondary-button" onClick={onCancel}>Cancel</button><button className="primary-button" disabled={!selected || !column || generating}>{generating ? <RefreshCw size={16} className="spin" /> : <Sparkles size={16} />}Generate draft</button></div></form></section></div>;
}

export function GovernanceAdmin({ notify, setActive }: { notify: (message: string, tone?: "ok" | "error") => void; setActive?: (key: NavKey) => void }) {
  const [confirm, confirmDialog] = useConfirm();
  const emptyPrompt = { name: "", system_prompt: "", template: "", variables: "" };
  const [prompts, setPrompts] = useState<PromptArtifact[]>([]);
  const [policies, setPolicies] = useState<RetentionPolicy[]>([]);
  const [showPrompt, setShowPrompt] = useState(false);
  const [editing, setEditing] = useState<PromptArtifact | null>(null);
  const [promptForm, setPromptForm] = useState(emptyPrompt);
  const [rollbackVersion, setRollbackVersion] = useState(1);
  const [retentionForm, setRetentionForm] = useState({ resource_type: "audit_events", retention_days: 365, enabled: true });
  // Learning-loop suggestions and router evaluation moved to Learning (docs/UX_CONSOLIDATION.md §4.2).
  const [govTab, setGovTab] = useState<"prompts" | "retention">("prompts");
  const load = useCallback(async () => { const [promptData, retentionData] = await Promise.all([api<PromptArtifact[]>("/prompts"), api<RetentionPolicy[]>("/retention-policies")]); setPrompts(promptData); setPolicies(retentionData); }, []);
  useEffect(() => { load().catch((reason) => notify(reason instanceof Error ? reason.message : "Governance configuration unavailable", "error")); }, [load, notify]);
  function openPrompt(prompt?: PromptArtifact) { setEditing(prompt || null); setPromptForm(prompt ? { name: prompt.name, system_prompt: prompt.content.system_prompt || "", template: prompt.content.template || "", variables: (prompt.content.variables || []).join(", ") } : emptyPrompt); setRollbackVersion(1); setShowPrompt(true); }
  async function savePrompt(event: FormEvent) { event.preventDefault(); try { await api("/prompts", { method: "POST", body: JSON.stringify({ ...promptForm, variables: promptForm.variables.split(",").map((item) => item.trim()).filter(Boolean), prompt_id: editing?.id || null, metadata: {} }) }); setShowPrompt(false); await load(); notify("Prompt draft version saved"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Prompt could not be saved", "error"); } }
  async function publishPrompt(prompt: PromptArtifact) { try { await api(`/artifacts/${prompt.id}/review`, { method: "POST", body: JSON.stringify({ decision: "approved", note: "Published from prompt governance" }) }); await load(); notify("Prompt approved"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Prompt could not be approved", "error"); } }
  async function rollbackPrompt() { if (!editing) return; try { await api(`/prompts/${editing.id}/rollback`, { method: "POST", body: JSON.stringify({ version: rollbackVersion }) }); setShowPrompt(false); await load(); notify(`Prompt rolled back from version ${rollbackVersion}`); } catch (reason) { notify(reason instanceof Error ? reason.message : "Prompt rollback failed", "error"); } }
  async function deletePrompt(prompt: PromptArtifact) { if (!(await confirm({ title: "Delete prompt", body: `Delete prompt "${prompt.name}" and its version history?` }))) return; try { await api(`/prompts/${prompt.id}`, { method: "DELETE" }); await load(); notify("Prompt deleted"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Prompt could not be deleted", "error"); } }
  async function saveRetention(event: FormEvent) { event.preventDefault(); try { await api("/retention-policies", { method: "POST", body: JSON.stringify(retentionForm) }); await load(); notify("Retention policy saved"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Retention policy could not be saved", "error"); } }
  async function runRetention(policy: RetentionPolicy) { try { const result = await api<{ candidate_count: number }>(`/retention-policies/${policy.id}/run`, { method: "POST" }); notify(`${result.candidate_count} expired records sent for approval`); } catch (reason) { notify(reason instanceof Error ? reason.message : "Retention preview failed", "error"); } }
  return <div className="view-stack">
    <div className="tabs"><button className={govTab === "prompts" ? "active" : ""} onClick={() => setGovTab("prompts")}><Archive size={16} />Prompts</button><button className={govTab === "retention" ? "active" : ""} onClick={() => setGovTab("retention")}><Clock3 size={16} />Retention</button></div>
    <p className="admin-hint">Learning-loop suggestions and router evaluation now live in <Link href="/learning?tab=suggestions">Learning → Suggestions</Link> and <Link href="/learning?tab=router">Learning → Router &amp; tool choice</Link>, next to verified queries and evaluations.</p>
    {govTab === "prompts" && <section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">PROMPT LIFECYCLE</span><h3>Versioned prompts</h3><p>Draft, review, approve, and roll back reusable model instructions.</p></div><button className="primary-button" onClick={() => openPrompt()}><Plus size={16} />New prompt</button></div><div className="table-header prompt-grid"><span>Prompt</span><span>Version</span><span>Status</span><span /></div>{prompts.map((prompt) => <div className="data-row prompt-grid" key={prompt.id}><button className="metric-main" onClick={() => openPrompt(prompt)}><strong>{prompt.name}</strong><small>{(prompt.content.variables || []).join(", ") || "No variables"}</small></button><span>v{prompt.version}</span><StatusPill value={prompt.status} /><span className="row-actions"><button className="icon-button" title="Approve prompt" disabled={prompt.status === "approved"} onClick={() => publishPrompt(prompt)}><Check size={16} /></button><button className="icon-button" title="Delete prompt and version history" onClick={() => deletePrompt(prompt)}><XCircle size={16} /></button></span></div>)}</section>}
    {govTab === "retention" && <section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">DATA LIFECYCLE</span><h3>Retention controls</h3><p>Preview expired operational records and route permanent deletion through approval.</p></div></div><form className="inline-admin-form retention-form" onSubmit={saveRetention}><select value={retentionForm.resource_type} onChange={(event) => setRetentionForm({ ...retentionForm, resource_type: event.target.value })}><option value="audit_events">Audit events</option><option value="model_call_logs">Model call logs</option><option value="external_invocations">External invocations</option><option value="user_feedback">User feedback</option></select><input type="number" min={1} max={3650} value={retentionForm.retention_days} onChange={(event) => setRetentionForm({ ...retentionForm, retention_days: Number(event.target.value) })} aria-label="Retention days" /><button className="primary-button"><Archive size={16} />Save</button></form><div className="table-header retention-grid"><span>Resource</span><span>Days</span><span>Status</span><span /></div>{policies.map((policy) => <div className="data-row retention-grid" key={policy.id}><strong>{policy.resource_type.replaceAll("_", " ")}</strong><span>{policy.retention_days}</span><StatusPill value={policy.enabled ? "enabled" : "disabled"} /><button className="secondary-button" onClick={() => runRetention(policy)}><Play size={15} />Preview and run</button></div>)}</section>}
    {showPrompt && <Modal title={editing ? `Edit ${editing.name}` : "Create prompt"} onClose={() => setShowPrompt(false)}><form className="modal-form" onSubmit={savePrompt}><label>Name<input value={promptForm.name} onChange={(event) => setPromptForm({ ...promptForm, name: event.target.value })} required /></label><label>System prompt<textarea rows={7} value={promptForm.system_prompt} onChange={(event) => setPromptForm({ ...promptForm, system_prompt: event.target.value })} required /></label><label>Template<textarea rows={7} value={promptForm.template} onChange={(event) => setPromptForm({ ...promptForm, template: event.target.value })} required /></label><label>Variables<input value={promptForm.variables} onChange={(event) => setPromptForm({ ...promptForm, variables: event.target.value })} placeholder="question, catalog_context" /></label>{editing && <div className="inline-admin-form prompt-rollback"><input type="number" min={1} max={editing.version} value={rollbackVersion} onChange={(event) => setRollbackVersion(Number(event.target.value))} aria-label="Rollback source version" /><button type="button" className="secondary-button" onClick={rollbackPrompt}><RefreshCw size={16} />Rollback</button></div>}<div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowPrompt(false)}>Cancel</button><button className="primary-button"><Archive size={16} />Save version</button></div></form></Modal>}{confirmDialog}</div>;
}

export function ProjectsAdmin({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  type AdminUser = SessionUser & { active: boolean };
  type Member = { id: string; user_id: string; role: string; is_current: boolean; user: AdminUser };
  const [projects, setProjects] = useState<Project[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [members, setMembers] = useState<Member[]>([]);
  const [form, setForm] = useState({ user_id: "", role: "member" });
  const load = useCallback(async () => { const [projectData, userData] = await Promise.all([api<Project[]>("/projects"), api<AdminUser[]>("/admin/users")]); setProjects(projectData); setUsers(userData); setSelectedId((current) => current || projectData[0]?.id || ""); }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (selectedId) api<Member[]>(`/projects/${selectedId}/members`).then(setMembers); }, [selectedId]);
  async function add(event: FormEvent) { event.preventDefault(); try { await api(`/projects/${selectedId}/members`, { method: "POST", body: JSON.stringify(form) }); setMembers(await api<Member[]>(`/projects/${selectedId}/members`)); notify("Project membership updated"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Membership update failed", "error"); } }
  return <section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">WORKSPACE ACCESS</span><h3>Projects and memberships</h3><p>Create projects from the sidebar switcher, then assign users and project roles here.</p></div><select value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>{projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select></div><div className="table-header project-member-grid"><span>User</span><span>Application role</span><span>Project role</span></div>{members.map((member) => <div className="data-row project-member-grid" key={member.id}><span><strong>{member.user.name}</strong><small>{member.user.email}</small></span><StatusPill value={member.user.role} /><StatusPill value={member.role} /></div>)}<form className="inline-admin-form" onSubmit={add}><select value={form.user_id} onChange={(event) => setForm({ ...form, user_id: event.target.value })} required><option value="">Select user</option>{users.map((user) => <option value={user.id} key={user.id}>{user.name} / {user.email}</option>)}</select><select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}><option value="owner">Owner</option><option value="maintainer">Maintainer</option><option value="member">Member</option><option value="viewer">Viewer</option></select><button className="primary-button"><UserPlus size={16} />Assign</button></form>{selectedId && <AutoApprovalPolicy projectId={selectedId} notify={notify} />}</section>;
}

type AutoApprovalPolicyState = { enabled: boolean; policy_version: number; auto_approvable_actions: string[]; manual_only: Record<string, string>; separation_of_duties: boolean };

/** Per-project switch for the auto-approval policy agent (low-risk, read-only requests only; every decision audited). */
function AutoApprovalPolicy({ projectId, notify }: { projectId: string; notify: (message: string, tone?: "ok" | "error") => void }) {
  const [policy, setPolicy] = useState<AutoApprovalPolicyState | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { setPolicy(null); api<AutoApprovalPolicyState>(`/projects/${projectId}/auto-approval`).then(setPolicy).catch(() => setPolicy(null)); }, [projectId]);
  async function toggle() {
    if (!policy) return;
    setSaving(true);
    try { setPolicy(await api<AutoApprovalPolicyState>(`/projects/${projectId}/auto-approval`, { method: "PUT", body: JSON.stringify({ enabled: !policy.enabled }) })); notify(`Auto-approval ${policy.enabled ? "disabled" : "enabled"} for this project`); }
    catch (reason) { notify(reason instanceof Error ? reason.message : "Auto-approval setting could not be saved", "error"); }
    finally { setSaving(false); }
  }
  if (!policy) return null;
  return (
    <div className="auth-config auto-approval-policy">
      <div className="toggle-row"><span><strong>Auto-approval policy agent</strong><small>Approves only {policy.auto_approvable_actions.map((item) => item.replaceAll("_", " ")).join(", ")} requests whose SQL re-passes the read-only guard, touches only catalogued tables and no PII columns. Each decision is recorded with its checks in the audit log.{policy.separation_of_duties ? " Separation of duties is on, so self-requested high-impact actions still need a second person." : ""}</small></span><button type="button" className={`toggle ${policy.enabled ? "on" : ""}`} onClick={() => void toggle()} disabled={saving} aria-pressed={policy.enabled} aria-label="Auto-approval policy"><span /></button></div>
      <p className="admin-hint">Always left for a person: {Object.entries(policy.manual_only).map(([action, reason]) => `${action.replaceAll("_", " ")} (${reason.toLowerCase()})`).join("; ")}.</p>
    </div>
  );
}

const NO_CONNECTORS: Connector[] = [];
const NO_DRIFT: SchemaDrift[] = [];
const NO_PROVIDERS: ModelProvider[] = [];

export function ConnectorsAdmin({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [confirm, confirmDialog] = useConfirm();
  const connectorsQuery = useConnectors();
  const driftQuery = useSchemaDrift();
  const connectors = connectorsQuery.data ?? NO_CONNECTORS;
  const drift = driftQuery.data ?? NO_DRIFT;
  useQueryErrorToast(connectorsQuery.error || driftQuery.error, notify, "Connectors could not be loaded");
  const invalidate = useInvalidate();
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Connector | null>(null);
  const [form, setForm] = useState({ name: "", connector_type: "sql_server", connection_mode: "direct" as "direct" | "mcp", description: "", host: "", database: "", mcp_server_url: "", secret_reference: "" });
  // Connector changes also change the catalog (datasets) that scans discover.
  const load = () => invalidate(scopes.connectors, scopes.schemaDrift, scopes.datasets);
  function openForm(connector?: Connector) {
    setEditing(connector || null);
    setForm(connector ? { name: connector.name, connector_type: connector.connector_type, connection_mode: connector.connection_mode || "direct", description: connector.description || "", host: connector.host || "", database: connector.database || "", mcp_server_url: connector.mcp_server_url || "", secret_reference: connector.secret_reference || "" } : { name: "", connector_type: "sql_server", connection_mode: "direct", description: "", host: "", database: "", mcp_server_url: "", secret_reference: "" });
    setShowForm(true);
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    try {
      await api(editing ? `/connectors/${editing.id}` : "/connectors", { method: editing ? "PUT" : "POST", body: JSON.stringify({ ...form, read_only: true }) });
      setShowForm(false);
      setEditing(null);
      setForm({ name: "", connector_type: "sql_server", connection_mode: "direct", description: "", host: "", database: "", mcp_server_url: "", secret_reference: "" });
      await load();
      notify(editing ? "Connector updated" : "Connector added in read-only mode");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not save connector", "error"); }
  }
  async function test(id: string) { try { const result = await api<{ message: string }>(`/connectors/${id}/test`, { method: "POST" }); notify(result.message); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Connection test failed", "error"); } }
  async function scan(id: string) { try { const result = await api<{ status: string; job_id: string; assets_discovered?: number }>(`/connectors/${id}/scan`, { method: "POST" }); if (result.status === "QUEUED") { notify("Metadata scan queued in Temporal"); for (let attempt = 0; attempt < 30; attempt += 1) { await new Promise((resolve) => window.setTimeout(resolve, 500)); const job = await api<Job>(`/jobs/${result.job_id}`); if (["SUCCEEDED", "FAILED"].includes(job.status)) { notify(job.status === "SUCCEEDED" ? job.logs.at(-1)?.message || "Metadata scan completed" : "Metadata scan failed", job.status === "SUCCEEDED" ? "ok" : "error"); break; } } } else { notify(`Metadata scan completed: ${result.assets_discovered || 0} assets`); } await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Scan failed", "error"); } }
  async function remove(connector: Connector) { if (!(await confirm({ title: "Delete connector", body: `Delete connector "${connector.name}"? Catalog entries discovered through it stop refreshing.` }))) return; try { await api(`/connectors/${connector.id}`, { method: "DELETE" }); await load(); notify("Connector deleted"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Connector could not be deleted", "error"); } }
  async function acknowledge(id: string) { try { await api(`/schema-drift/${id}/acknowledge`, { method: "POST" }); await load(); notify("Schema drift acknowledged"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Drift could not be acknowledged", "error"); } }
  return (
    <section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">DATA ACCESS</span><h3>Registered data sources</h3><p>Every connector starts read-only and stores only a secret reference.</p></div><button className="primary-button" onClick={() => openForm()}><Plus size={17} />Add connector</button></div>
      <div className="table-header connector-grid"><span>Connector</span><span>System</span><span>Connection type</span><span>Catalog</span><span>Status</span><span /></div>
      {connectors.map((connector) => <div className="data-row connector-grid" key={connector.id}><span><strong>{connector.name}</strong><small>{connector.description || `${connector.host || "Local service"} / ${connector.database || "-"}`}</small></span><span>{connectorLabels[connector.connector_type] || connector.connector_type}</span><span>{connector.connection_mode === "mcp" ? "Upstream MCP" : "Native driver"}</span><span>{connector.metadata_summary?.tables || 0} tables</span><StatusPill value={connector.status} /><span className="row-actions"><button className="icon-button" title="Edit connector" onClick={() => openForm(connector)}><Settings size={16} /></button><button className="icon-button" title="Test connection" onClick={() => test(connector.id)}><Gauge size={16} /></button><button className="icon-button" title="Scan metadata" onClick={() => scan(connector.id)}><RefreshCw size={16} /></button><button className="icon-button" title="Delete connector" onClick={() => remove(connector)}><XCircle size={16} /></button></span></div>)}
      {drift.length > 0 && <><div className="subheading"><h4>Schema drift</h4><span>{drift.filter((item) => item.status === "detected").length} open</span></div><div className="table-header drift-grid"><span>Relation</span><span>Changes</span><span>Status</span><span /></div>{drift.map((item) => <div className="data-row drift-grid" key={item.id}><span><strong>{item.relation}</strong><small>{new Date(item.detected_at).toLocaleString()}</small></span><span>{item.changes.map((change) => `${change.kind.replaceAll("_", " ")}: ${change.column}`).join(", ")}</span><StatusPill value={item.status} /><button className="icon-button" title="Acknowledge drift" disabled={item.status === "acknowledged"} onClick={() => acknowledge(item.id)}><Check size={16} /></button></div>)}</>}
      {showForm && <Modal title={editing ? "Edit data connector" : "Add data connector"} onClose={() => { setShowForm(false); setEditing(null); }}><form className="modal-form" onSubmit={save}><label>Name<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label><div className="form-grid"><label>System<select value={form.connector_type} onChange={(event) => setForm({ ...form, connector_type: event.target.value })}><option value="postgres">PostgreSQL</option><option value="sql_server">SQL Server</option><option value="oracle">Oracle</option><option value="teradata">Teradata</option><option value="bigquery">BigQuery</option><option value="local_files">Local files</option></select></label><label>Connection mode<select value={form.connection_mode} onChange={(event) => setForm({ ...form, connection_mode: event.target.value as "direct" | "mcp", mcp_server_url: event.target.value === "mcp" ? form.mcp_server_url : "" })}><option value="direct">Native driver</option><option value="mcp">Upstream MCP</option></select></label></div><label>Description<textarea rows={3} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="Owner, domain, sensitivity, and approved use." /></label>{form.connection_mode === "mcp" ? <label>MCP server URL<input value={form.mcp_server_url} onChange={(event) => setForm({ ...form, mcp_server_url: event.target.value })} placeholder="http://mcp-toolbox:5000/mcp" required /></label> : <div className="form-grid"><label>Host / project<input value={form.host} onChange={(event) => setForm({ ...form, host: event.target.value })} /></label><label>Database / dataset<input value={form.database} onChange={(event) => setForm({ ...form, database: event.target.value })} /></label></div>}<label>Secret reference<input value={form.secret_reference} onChange={(event) => setForm({ ...form, secret_reference: event.target.value })} placeholder={form.connection_mode === "mcp" ? "env:MCP_TOOLBOX_TOKEN" : form.connector_type === "sql_server" ? "env:SQLSERVER_CREDENTIALS" : "env:POSTGRES_CREDENTIALS"} /></label><div className="modal-note"><ShieldCheck size={16} />The connector is read-only. Credentials are stored only by reference and hidden from viewer roles.</div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => { setShowForm(false); setEditing(null); }}>Cancel</button><button className="primary-button">{editing ? "Save connector" : "Add connector"}</button></div></form></Modal>}
      {confirmDialog}
    </section>
  );
}

export function ModelsAdmin({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const providersQuery = useModelProviders();
  const usageQuery = useModelUsage();
  const providers = providersQuery.data ?? NO_PROVIDERS;
  const usage: ModelUsage | null = usageQuery.data ?? null;
  useQueryErrorToast(providersQuery.error || usageQuery.error, notify, "Model providers could not be loaded");
  const invalidate = useInvalidate();
  const [showForm, setShowForm] = useState(false);
  const emptyProviderForm = { name: "", provider_type: "company_gateway", base_url: "", default_model: "", embedding_model: "", secret_reference: "" };
  const [form, setForm] = useState(emptyProviderForm);
  const providerType = providerTypeOptions.find((option) => option.value === form.provider_type) || providerTypeOptions[0];
  // Switching type swaps pre-filled defaults, but never overwrites values the admin typed.
  function chooseProviderType(value: string) {
    const previous = providerType;
    const next = providerTypeOptions.find((option) => option.value === value) || providerTypeOptions[0];
    setForm((current) => ({
      ...current,
      provider_type: next.value,
      base_url: !current.base_url || current.base_url === previous.baseUrl ? next.baseUrl : current.base_url,
      secret_reference: !current.secret_reference || current.secret_reference === previous.secretReference ? next.secretReference : current.secret_reference,
      default_model: !current.default_model || current.default_model === (previous.defaultModel || "") ? next.defaultModel || "" : current.default_model,
    }));
  }
  const routingQuery = useModelRouting();
  const purposeLabels = Object.fromEntries((routingQuery.data?.purposes || []).map((item) => [item.purpose, item.label]));
  const decisionForm = (providerType.capability || "generation") === "decision";
  // Provider health and defaults feed the routing table and the top-bar model picker.
  const load = () => invalidate(scopes.modelProviders, scopes.modelUsage, scopes.modelRouting, scopes.projects);
  async function create(event: FormEvent) { event.preventDefault(); try { await api("/model-providers", { method: "POST", body: JSON.stringify({ ...form, enabled: true, is_default: false }) }); setShowForm(false); setForm(emptyProviderForm); await load(); notify("Model provider added"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not add provider", "error"); } }
  async function test(id: string) { try { const result = await api<{ message: string }>(`/model-providers/${id}/test`, { method: "POST" }); notify(result.message); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Provider test failed", "error"); } }
  async function setDefault(id: string) { try { await api(`/model-providers/${id}/default`, { method: "POST" }); notify("Default model provider updated"); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Provider could not be selected", "error"); } }
  const [reindexing, setReindexing] = useState(false);
  async function reindex() {
    setReindexing(true);
    try {
      const summary = await api<{ assets_indexed: number; assets_total: number; glossary_chunks_indexed: number; glossary_chunks_total: number }>("/model-providers/reindex-embeddings", { method: "POST" });
      notify(`Reindexed ${summary.assets_indexed}/${summary.assets_total} assets and ${summary.glossary_chunks_indexed}/${summary.glossary_chunks_total} glossary chunks`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Reindex failed", "error");
    } finally {
      setReindexing(false);
    }
  }
  return (
    <section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">MODEL ROUTING</span><h3>Provider registry</h3><p>Company gateway first, with Gemini, OpenAI, Claude, OpenRouter, compatible, and local providers.</p></div><div style={{ display: "flex", gap: 8 }}><button className="secondary-button" disabled={reindexing} onClick={reindex} title="Re-embed all catalog assets and glossary documents under the active embedding model">{reindexing ? "Reindexing…" : "Reindex embeddings"}</button><button className="primary-button" onClick={() => setShowForm(true)}><Plus size={17} />Add provider</button></div></div>
      <div className="provider-grid">{providers.map((provider) => {
        const decision = providerCapability(provider) === "decision";
        return <article className="provider-card" key={provider.id}><div className="provider-heading"><span className="provider-icon"><Bot size={20} /></span><span>{decision && <span className="tag tag-decision" title="Returns typed choices with probabilities, not text">decision model</span>}{provider.is_default && <span className="tag">default</span>}<StatusPill value={provider.status} /></span></div><h4>{provider.name}</h4><p>{provider.provider_type === "jev" ? "TypeSafe Jev via OpenRouter Decisions" : provider.provider_type.replaceAll("_", " ")}</p><dl><div><dt>{decision ? "Decision model" : "Chat model"}</dt><dd>{provider.default_model}</dd></div>{!decision && <div><dt>Embeddings</dt><dd>{provider.embedding_model || "Not configured"}</dd></div>}<div><dt>Secret</dt><dd>{provider.secret_reference || "Not required"}</dd></div></dl><div className="provider-actions"><button className="secondary-button" onClick={() => test(provider.id)}><Gauge size={16} />Test</button><button className="secondary-button" disabled={decision || provider.is_default || provider.status !== "healthy"} title={decision ? "A decision model cannot answer chat requests, so it cannot be the default" : undefined} onClick={() => setDefault(provider.id)}><Check size={16} />Set default</button></div></article>;
      })}</div>
      <ModelRoutingPanel notify={notify} />
      {usage && <section className="usage-strip"><div><span>Calls</span><strong>{usage.totals.calls}</strong></div><div><span>Input tokens</span><strong>{usage.totals.input_tokens.toLocaleString()}</strong></div><div><span>Output tokens</span><strong>{usage.totals.output_tokens.toLocaleString()}</strong></div><div><span>Estimated cost</span><strong title={`${usage.totals.estimated_cost_usd} USD`}>{usage.pricing_configured || usage.totals.estimated_cost_usd > 0 ? formatUsd(usage.totals.estimated_cost_usd) : "Rates not set"}</strong></div></section>}
      {usage && usage.items.length > 0 && (
        <div className="usage-table">
          <div className="subheading"><h4>Model usage</h4><span>Calls per purpose and provider in this project. Decision-model calls (Jev) are listed under routing, risk-check and SQL tie-breaker purposes.</span></div>
          <div className="table-header usage-grid"><span>Purpose</span><span>Provider / model</span><span>Calls</span><span>Tokens in / out</span><span>Cost</span><span>Avg latency</span></div>
          {[...usage.items].sort((a, b) => (a.purpose || "").localeCompare(b.purpose || "") || b.calls - a.calls).map((item, index) => {
            const decision = providerCapability({ capability: item.capability, provider_type: item.provider_type }) === "decision" || /jev/i.test(item.model);
            return (
              <div className="data-row usage-grid" key={`${item.provider_id}-${item.model}-${item.purpose || ""}-${index}`}>
                <span><strong>{item.purpose ? purposeLabels[item.purpose] || item.purpose.replaceAll("_", " ") : "Unattributed"}</strong>{item.purpose && <small className="mono">{item.purpose}</small>}</span>
                <span><strong>{item.provider_name}{decision && <span className="tag tag-decision">decision model</span>}</strong><small className="mono" title={item.model}>{item.model}</small></span>
                <span className="mono">{item.calls.toLocaleString()}</span>
                <span className="mono">{item.input_tokens.toLocaleString()} / {item.output_tokens.toLocaleString()}</span>
                <span className="mono" title={`${item.estimated_cost_usd} USD`}>{item.estimated_cost_usd > 0 || usage.pricing_configured ? formatUsd(item.estimated_cost_usd) : "-"}</span>
                <span className="mono">{Math.round(item.average_latency_ms).toLocaleString()} ms</span>
              </div>
            );
          })}
        </div>
      )}
      {showForm && <Modal title="Add model provider" onClose={() => setShowForm(false)}><form className="modal-form" onSubmit={create}><div className="form-grid"><label>Name<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label><label>Type<select value={form.provider_type} onChange={(event) => chooseProviderType(event.target.value)}>{providerTypeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label></div>{providerType.hint && <p className="modal-hint provider-type-hint"><span className="tag tag-decision">decision model</span>{providerType.hint}</p>}<label>Base URL<input value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} placeholder={providerType.baseUrl || "Provider default"} /></label><div className="form-grid"><label>{decisionForm ? "Decision model" : "Default chat model"}<input value={form.default_model} onChange={(event) => setForm({ ...form, default_model: event.target.value })} placeholder={providerType.modelPlaceholder} required /></label>{!decisionForm && <label>Embedding model<input value={form.embedding_model} onChange={(event) => setForm({ ...form, embedding_model: event.target.value })} /></label>}</div><label>Secret reference<input value={form.secret_reference} onChange={(event) => setForm({ ...form, secret_reference: event.target.value })} placeholder={providerType.secretPlaceholder} /></label>{form.provider_type === "jev" && <div className="modal-note"><ShieldCheck size={16} />Jev is served by the OpenRouter Decisions API and reads OPENROUTER_API_KEY. Assign it to decision purposes (decision routing, consequential-action check, SQL candidate tie-breaker) under Model routing; it can only escalate risk, never approve an action.</div>}{form.provider_type === "openrouter" && <div className="modal-note"><ShieldCheck size={16} />OpenRouter is OpenAI-compatible. Model names are namespaced by vendor, for example anthropic/claude-sonnet-5; the key is read from OPENROUTER_API_KEY.</div>}<div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary-button">Add provider</button></div></form></Modal>}
    </section>
  );
}

export function UsersAdmin({ notify, currentUser }: { notify: (message: string, tone?: "ok" | "error") => void; currentUser?: SessionUser }) {
  const [search, setSearch] = useState("");
  const query = useDebouncedValue(search.trim());
  const pagination = usePagination(query, 50);
  const usersPage = usePagedQuery<SessionUser & { active: boolean; created_at: string }>(scopes.users, "/admin/users", { q: query }, pagination);
  useQueryErrorToast(usersPage.error, notify, "Users could not be loaded");
  const users = usersPage.data?.items ?? [];
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", role: "analyst", temporary_password: "ChangeMe123!" });
  const [editingUser, setEditingUser] = useState<(typeof users)[number] | null>(null);
  const [editForm, setEditForm] = useState({ name: "", email: "" });
  const invalidate = useInvalidate();
  const load = useCallback(() => invalidate(scopes.users), [invalidate]);
  async function create(event: FormEvent) { event.preventDefault(); try { await api("/admin/users", { method: "POST", body: JSON.stringify(form) }); setShowForm(false); await load(); notify("Local user added"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not add user", "error"); } }
  async function update(user: (typeof users)[number], patch: { role?: string; active?: boolean; name?: string; email?: string }) { try { await api(`/admin/users/${user.id}`, { method: "PUT", body: JSON.stringify(patch) }); await load(); notify("User access updated"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not update user", "error"); } }
  const [confirm, confirmDialog] = useConfirm();
  async function toggleActive(user: (typeof users)[number]) {
    if (user.active && !(await confirm({ title: "Deactivate user", body: `Deactivate ${user.name}? They will immediately lose the ability to sign in until reactivated.`, confirmLabel: "Deactivate" }))) return;
    update(user, { active: !user.active });
  }
  function openEdit(user: (typeof users)[number]) { setEditingUser(user); setEditForm({ name: user.name, email: user.email }); }
  async function saveEdit(event: FormEvent) {
    event.preventDefault();
    if (!editingUser) return;
    await update(editingUser, { name: editForm.name.trim(), email: editForm.email.trim() });
    setEditingUser(null);
  }
  return (
    <section className="surface admin-surface">
      <div className="section-heading"><div><span className="eyebrow">LOCAL ACCESS</span><h3>Users and roles</h3><p>Admin-managed accounts remain available before and after PingFederate is enabled. Deactivating revokes sign-in immediately; accounts are never hard-deleted so audit history stays intact.</p></div><div className="row-actions"><div className="toolbar-search"><Search size={16} /><input placeholder="Search users..." value={search} onChange={(event) => setSearch(event.target.value)} /></div><button className="primary-button" onClick={() => setShowForm(true)}><UserPlus size={17} />Add user</button></div></div>
      {usersPage.isPending ? <LoadingBlock label="Loading users" /> : users.length ? <>
        <div className="table-header user-grid"><span>User</span><span>Role</span><span>Status</span><span>Created</span></div>
        {users.map((user) => <div className="data-row user-grid" key={user.id}><span className="person-cell"><span className="user-avatar">{user.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</span><span><strong>{user.name}</strong><small>{user.email}</small></span></span><select className="table-select" value={user.role} onChange={(event) => update(user, { role: event.target.value })} aria-label={`Role for ${user.name}`}><option value="admin">Admin</option><option value="engineer">Engineer</option><option value="analyst">Analyst</option><option value="viewer">Viewer</option></select><span className="row-actions"><button className="icon-button" title="Edit name and email" onClick={() => openEdit(user)}><Edit2 size={15} /></button><button className="status-action" onClick={() => toggleActive(user)} title={user.active ? "Deactivate user" : "Activate user"} disabled={currentUser?.id === user.id && user.active}><StatusPill value={user.active ? "active" : "inactive"} /></button></span><span>{new Date(user.created_at).toLocaleDateString()}</span></div>)}
        <Pagination state={pagination} total={usersPage.data?.total ?? 0} count={users.length} busy={usersPage.isFetching} label="users" />
      </> : <EmptyState icon={<UserPlus size={24} />} title={search ? "No matching users" : "No local users yet"} body={search ? "Try a different name or email." : "Add the first local account to get started."} />}
      {showForm && <Modal title="Add local user" onClose={() => setShowForm(false)}><form className="modal-form" onSubmit={create}><label>Full name<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label><label>Email<input type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} required /></label><div className="form-grid"><label>Role<select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}><option value="admin">Admin</option><option value="engineer">Engineer</option><option value="analyst">Analyst</option><option value="viewer">Viewer</option></select></label><label>Temporary password<input type="password" value={form.temporary_password} onChange={(event) => setForm({ ...form, temporary_password: event.target.value })} minLength={10} required /></label></div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary-button">Create user</button></div></form></Modal>}
      {editingUser && <Modal title={`Edit ${editingUser.name}`} onClose={() => setEditingUser(null)}><form className="modal-form" onSubmit={saveEdit}><label>Full name<input value={editForm.name} onChange={(event) => setEditForm({ ...editForm, name: event.target.value })} required /></label><label>Email<input type="email" value={editForm.email} onChange={(event) => setEditForm({ ...editForm, email: event.target.value })} required /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setEditingUser(null)}>Cancel</button><button className="primary-button"><Check size={16} />Save</button></div></form></Modal>}
      {confirmDialog}
    </section>
  );
}

/**
 * Per-purpose model assignment (GET/PUT /model-routing). `null` means the purpose
 * follows the project's pinned provider, then the global default.
 */
function ModelRoutingPanel({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const routingQuery = useModelRouting();
  const invalidate = useInvalidate();
  const routing: ModelRouting | null = routingQuery.data ?? null;
  const [draft, setDraft] = useState<Record<string, string | null>>({});
  const [saving, setSaving] = useState(false);
  useQueryErrorToast(routingQuery.error, notify, "Model routing could not be loaded", { ignoreUnavailable: true });
  const state: "loading" | "ready" | "unavailable" = routingQuery.isPending ? "loading" : routingQuery.isError ? "unavailable" : "ready";
  const reset = useCallback((data: ModelRouting) => setDraft(Object.fromEntries(data.purposes.map((item) => [item.purpose, item.provider_id ?? null]))), []);
  // Fresh server data (load, save, provider changes) resets the draft.
  useEffect(() => { if (routing) reset(routing); }, [routing, reset]);
  const purposes = routing?.purposes || [];
  const options = routing?.providers || [];
  const dirty = purposes.some((item) => (draft[item.purpose] ?? null) !== (item.provider_id ?? null));
  async function save() {
    setSaving(true);
    try {
      await api<ModelRouting>("/model-routing", { method: "PUT", body: JSON.stringify({ assignments: draft }) });
      await invalidate(scopes.modelRouting);
      notify("Model routing saved");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Model routing could not be saved", "error");
    } finally {
      setSaving(false);
    }
  }
  if (state === "unavailable") return <div className="routing-panel"><div className="subheading"><h4>Model routing</h4></div><p className="admin-hint">Per-purpose model routing is not available from this API version.</p></div>;
  return (
    <div className="routing-panel">
      <div className="subheading"><h4>Model routing</h4><span>Choose which provider answers each kind of request. &quot;Project/global default&quot; follows the project&apos;s pinned model, then the global default.</span></div>
      {state === "loading" ? <LoadingBlock label="Loading model routing" /> : <>
        <div className="table-header routing-grid"><span>Purpose</span><span>Provider</span><span>Effective model</span></div>
        {purposes.map((item) => {
          // kind: generation → text models only, decision → decision models (Jev) only, either → both.
          const kind = item.kind || "generation";
          const selectedId = draft[item.purpose] ?? "";
          const allowed = options.filter((provider) => kind === "either" || providerCapability(provider) === kind || provider.id === selectedId);
          const effective = item.effective_provider ? options.find((provider) => provider.id === item.effective_provider!.id) : undefined;
          return (
            <div className="data-row routing-grid" key={item.purpose}>
              <span><strong>{item.label}{kind !== "generation" && <span className={`tag ${kind === "decision" ? "tag-decision" : ""}`} title={kind === "decision" ? "Answered by a decision model" : "Text or decision model"}>{kind === "decision" ? "decision" : "text or decision"}</span>}</strong><small>{item.purpose}</small></span>
              <select className="table-select" aria-label={`Provider for ${item.label}`} value={selectedId} onChange={(event) => setDraft((current) => ({ ...current, [item.purpose]: event.target.value || null }))}>
                <option value="">{kind === "decision" ? "Not assigned (platform default)" : "Project/global default"}</option>
                {allowed.map((provider) => {
                  const capability = providerCapability(provider);
                  const mismatch = kind !== "either" && capability !== "local" && capability !== kind;
                  return <option key={provider.id} value={provider.id} disabled={!provider.enabled || mismatch}>{provider.name} / {provider.default_model}{capability === "decision" ? " · decision model" : ""}{capability === "local" && kind !== "generation" ? " · on-prem, no external call" : ""}{provider.status !== "healthy" ? ` (${provider.status.replaceAll("_", " ")})` : ""}{mismatch ? " (incompatible)" : ""}</option>;
                })}
              </select>
              <span>{item.effective_provider ? <>{item.effective_provider.name} / {item.effective_provider.model}{effective && providerCapability(effective) === "decision" && <span className="tag tag-decision">decision model</span>}</> : "No provider resolved"}{item.scope && <small>via {item.scope}</small>}</span>
            </div>
          );
        })}
        {!purposes.length && <p className="admin-hint">The API reported no routable purposes.</p>}
        <div className="form-end">
          <button type="button" className="secondary-button" disabled={!dirty || saving} onClick={() => routing && reset(routing)}>Reset</button>
          <button type="button" className="primary-button" disabled={!dirty || saving} onClick={() => void save()}>{saving ? <RefreshCw size={16} className="spin" /> : <Check size={16} />}Save routing</button>
        </div>
      </>}
    </div>
  );
}

export function AuthAdmin({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [provider, setProvider] = useState<{ id: string; enabled: boolean; issuer_url: string; client_id: string; scopes: string; group_claim: string } | null>(null);
  useEffect(() => { api<(typeof provider)[]>("/auth-providers").then((data) => setProvider(data[0])); }, []);
  async function save(event: FormEvent) { event.preventDefault(); if (!provider) return; try { const updated = await api<typeof provider>(`/auth-providers/${provider.id}`, { method: "PUT", body: JSON.stringify(provider) }); setProvider(updated); notify("PingFederate configuration saved"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not save configuration", "error"); } }
  return (
    <section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">ENTERPRISE IDENTITY</span><h3>PingFederate</h3><p>OIDC is the default integration path. Local admin login remains available as a controlled fallback.</p></div>{provider && <StatusPill value={provider.enabled ? "enabled" : "disabled"} />}</div>
      {!provider ? <LoadingBlock /> : <form className="auth-config" onSubmit={save}><div className="toggle-row"><span><strong>Enable PingFederate OIDC</strong><small>Show enterprise sign-in after issuer validation succeeds.</small></span><button type="button" className={`toggle ${provider.enabled ? "on" : ""}`} onClick={() => setProvider({ ...provider, enabled: !provider.enabled })} aria-label="Enable PingFederate"><span /></button></div><label>Issuer URL<input value={provider.issuer_url || ""} onChange={(event) => setProvider({ ...provider, issuer_url: event.target.value })} placeholder="https://sso.company.example" /></label><div className="form-grid"><label>Client ID<input value={provider.client_id || ""} onChange={(event) => setProvider({ ...provider, client_id: event.target.value })} /></label><label>Group claim<input value={provider.group_claim} onChange={(event) => setProvider({ ...provider, group_claim: event.target.value })} /></label></div><label>Scopes<input value={provider.scopes} onChange={(event) => setProvider({ ...provider, scopes: event.target.value })} /></label><div className="policy-banner"><ShieldCheck size={18} /><span><strong>Server-side authorization remains authoritative.</strong><small>PingFederate groups map to DataPilot roles; a successful login alone does not grant project access.</small></span></div><div className="form-end"><button className="primary-button"><Check size={17} />Save configuration</button></div></form>}
    </section>
  );
}
