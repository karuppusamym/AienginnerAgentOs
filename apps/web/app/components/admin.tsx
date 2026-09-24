import {
  AlertCircle,
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
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError, SessionUser } from "../lib/api";
import type {
  NavKey,
  Connector,
  ModelProvider,
  Project,
  Job,
  ExternalClient,
  QueryTool,
  QueryToolDraft,
  RelationOption,
  QueryToolRegistrySummary,
  PromptArtifact,
  RetentionPolicy,
  SchemaDrift,
  ModelUsage,
  LearningSuggestion,
  ModelRouting,
} from "../types";
import {
  connectorLabels,
  providerTypeOptions,
} from "../lib/constants";
import { StatusPill, LoadingBlock, EmptyState, Modal, Metric, useConfirm } from "./shared";


export function AdminView({ currentUser, notify, setActive: setAppActive }: { currentUser: SessionUser; notify: (message: string, tone?: "ok" | "error") => void; setActive?: (key: NavKey) => void }) {
  const [tab, setTab] = useState<"users" | "projects" | "connectors" | "models" | "governance" | "auth">("connectors");
  return (
    <div className="view-stack">
      <div className="view-header"><div><h2>Administration</h2><p>Configure local access, data sources, model routing, and enterprise identity.</p></div><StatusPill value={currentUser.role} /></div>
      <div className="tabs"><button className={tab === "connectors" ? "active" : ""} onClick={() => setTab("connectors")}><Server size={16} />Connectors</button><button className={tab === "models" ? "active" : ""} onClick={() => setTab("models")}><Bot size={16} />Model providers</button><button className={tab === "governance" ? "active" : ""} onClick={() => setTab("governance")}><ShieldCheck size={16} />Governance</button><button className={tab === "projects" ? "active" : ""} onClick={() => setTab("projects")}><Layers3 size={16} />Projects</button><button className={tab === "users" ? "active" : ""} onClick={() => setTab("users")}><Users size={16} />Users</button><button className={tab === "auth" ? "active" : ""} onClick={() => setTab("auth")}><KeyRound size={16} />Authentication</button></div>
      <p className="admin-hint">Looking for the query-tool / external-gateway registry? It's under <strong>Tool registry</strong> in the main navigation — External data tools tab.</p>
      {tab === "connectors" && <ConnectorsAdmin notify={notify} />}
      {tab === "models" && <ModelsAdmin notify={notify} />}
      {tab === "governance" && <GovernanceAdmin notify={notify} setActive={setAppActive} />}
      {tab === "projects" && <ProjectsAdmin notify={notify} />}
      {tab === "users" && <UsersAdmin notify={notify} currentUser={currentUser} />}
      {tab === "auth" && <AuthAdmin notify={notify} />}
    </div>
  );
}

export function GatewayAdmin({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const emptyTool = { name: "", description: "", purpose: "", data_source: "", line_of_business: "", owner: "", tags: "", connector_id: "", upstream_tool_name: "", sql_template: "SELECT * FROM staging.example WHERE id = :id", parameter_schema: '{"type":"object","required":["id"],"properties":{"id":{"type":"integer"}},"additionalProperties":false}', allowed_relations: "staging.example", row_limit: 200, timeout_seconds: 15 };
  const [tools, setTools] = useState<QueryTool[]>([]);
  const [clients, setClients] = useState<ExternalClient[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [showTool, setShowTool] = useState(false);
  const [showClient, setShowClient] = useState(false);
  const [showWizard, setShowWizard] = useState(false);
  const [selected, setSelected] = useState<QueryTool | null>(null);
  const [toolForm, setToolForm] = useState(emptyTool);
  const [clientName, setClientName] = useState("");
  const [issuedToken, setIssuedToken] = useState("");
  const [grantClient, setGrantClient] = useState("");
  const [testParameters, setTestParameters] = useState("{}");
  const [summary, setSummary] = useState<QueryToolRegistrySummary | null>(null);
  const [search, setSearch] = useState("");
  const load = useCallback(async () => { const [toolData, clientData, connectorData, summaryData] = await Promise.all([api<QueryTool[]>("/query-tools"), api<ExternalClient[]>("/external-clients"), api<Connector[]>("/connectors"), api<QueryToolRegistrySummary>("/query-tools/summary")]); setTools(toolData); setClients(clientData); setConnectors(connectorData); setSummary(summaryData); }, []);
  useEffect(() => { load().catch((reason) => notify(reason instanceof Error ? reason.message : "Gateway configuration unavailable", "error")); }, [load, notify]);
  function openTool(tool?: QueryTool) { setSelected(tool || null); setToolForm(tool ? { name: tool.name, description: tool.description, purpose: tool.purpose, data_source: tool.data_source, line_of_business: tool.line_of_business, owner: tool.owner, tags: tool.tags.join(", "), connector_id: tool.connector_id || "", upstream_tool_name: tool.upstream_tool_name || "", sql_template: tool.sql_template, parameter_schema: JSON.stringify(tool.parameter_schema, null, 2), allowed_relations: tool.allowed_relations.join(", "), row_limit: tool.row_limit, timeout_seconds: tool.timeout_seconds } : emptyTool); setTestParameters("{}"); setGrantClient(clients[0]?.id || ""); setShowTool(true); }
  function startFromTemplate(kind: "lookup" | "count") { const lookup = kind === "lookup"; setSelected(null); setToolForm({ ...emptyTool, name: lookup ? "record.lookup" : "records.count_by_filter", description: lookup ? "Look up one record by a governed identifier." : "Count governed records using an optional bounded status filter.", purpose: lookup ? "Support a read-only support lookup by identifier." : "Support a read-only operational count by status.", tags: lookup ? "lookup, read-only" : "count, read-only", sql_template: lookup ? "SELECT * FROM staging.example WHERE id = :id LIMIT 1" : "SELECT COUNT(*) AS total FROM staging.example WHERE status = :status", parameter_schema: lookup ? '{"type":"object","required":["id"],"properties":{"id":{"type":"integer"}},"additionalProperties":false}' : '{"type":"object","required":["status"],"properties":{"status":{"type":"string"}},"additionalProperties":false}', allowed_relations: "staging.example", row_limit: lookup ? 1 : 100 }); setTestParameters(lookup ? '{"id": 1}' : '{"status": "active"}'); setGrantClient(clients[0]?.id || ""); setShowTool(true); }
  async function saveTool(event: FormEvent) { event.preventDefault(); try { const payload = { ...toolForm, connector_id: toolForm.connector_id || null, upstream_tool_name: toolForm.upstream_tool_name || null, tags: toolForm.tags.split(",").map((item) => item.trim()).filter(Boolean), parameter_schema: JSON.parse(toolForm.parameter_schema), result_schema: { type: "object" }, allowed_relations: toolForm.allowed_relations.split(",").map((item) => item.trim()).filter(Boolean), requires_approval: false }; await api(selected ? `/query-tools/${selected.id}` : "/query-tools", { method: selected ? "PUT" : "POST", body: JSON.stringify(payload) }); setShowTool(false); setSelected(null); await load(); notify(selected ? "Query tool saved as a new draft version" : "Query tool draft created"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Query tool could not be saved", "error"); } }
  async function publish(tool: QueryTool) { try { await api(`/query-tools/${tool.id}/publish`, { method: "POST" }); await load(); notify("Query tool published"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Query tool could not be published", "error"); } }
  async function testTool() { if (!selected) return; try { const result = await api<{ row_count: number }>(`/query-tools/${selected.id}/test`, { method: "POST", body: JSON.stringify({ parameters: JSON.parse(testParameters) }) }); notify(`Query tool returned ${result.row_count} rows`); } catch (reason) { notify(reason instanceof Error ? reason.message : "Query tool test failed", "error"); } }
  async function grant() { if (!selected || !grantClient) return; try { await api(`/query-tools/${selected.id}/grants`, { method: "POST", body: JSON.stringify({ external_client_id: grantClient, enabled: true }) }); notify("External client grant saved"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Grant could not be saved", "error"); } }
  async function createClient(event: FormEvent) { event.preventDefault(); try { const created = await api<ExternalClient>("/external-clients", { method: "POST", body: JSON.stringify({ name: clientName, scopes: ["tools:list", "tools:invoke"] }) }); setIssuedToken(created.token || ""); setClientName(""); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "External client could not be created", "error"); } }
  async function rotate(client: ExternalClient) { try { const updated = await api<ExternalClient>(`/external-clients/${client.id}/rotate`, { method: "POST" }); setIssuedToken(updated.token || ""); setShowClient(true); notify("Client token rotated"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Token rotation failed", "error"); } }
  async function toggleClient(client: ExternalClient) { try { await api(`/external-clients/${client.id}`, { method: "PUT", body: JSON.stringify({ active: !client.active, scopes: client.scopes }) }); await load(); notify(`External client ${client.active ? "disabled" : "enabled"}`); } catch (reason) { notify(reason instanceof Error ? reason.message : "Client update failed", "error"); } }
  const selectedConnector = connectors.find((item) => item.id === toolForm.connector_id);
  const filteredTools = tools.filter((tool) => search ? [tool.name, tool.purpose, tool.owner, tool.line_of_business, tool.data_source, ...tool.tags].some((field) => field.toLowerCase().includes(search.toLowerCase())) : true);
  if (showWizard) return <QueryToolWizard notify={notify} onCancel={() => setShowWizard(false)} onUse={(draft) => { setSelected(null); setToolForm({ name: draft.name, description: draft.description, purpose: draft.purpose, data_source: draft.data_source, line_of_business: draft.line_of_business, owner: draft.owner, tags: draft.tags.join(", "), connector_id: draft.connector_id || "", upstream_tool_name: draft.upstream_tool_name || "", sql_template: draft.sql_template, parameter_schema: JSON.stringify(draft.parameter_schema, null, 2), allowed_relations: draft.allowed_relations.join(", "), row_limit: draft.row_limit, timeout_seconds: draft.timeout_seconds }); setTestParameters("{}"); setGrantClient(clients[0]?.id || ""); setShowWizard(false); setShowTool(true); }} />;
  return <div className="view-stack">
    <section className="surface admin-surface">
      <div className="section-heading"><div><span className="eyebrow">EXTERNAL AGENT ACCESS</span><h3>Governed query gateway</h3><p>Published parameterized tools are searchable by purpose, source, LOB, owner, and tags over REST and MCP.</p></div><div className="row-actions"><div className="toolbar-search"><Search size={16} /><input placeholder="Search tools by name, owner, LOB, tag..." value={search} onChange={(event) => setSearch(event.target.value)} /></div><button className="secondary-button" onClick={() => setShowWizard(true)}><Database size={16} />Catalog wizard</button><button className="secondary-button" onClick={() => startFromTemplate("lookup")}><Database size={16} />Lookup template</button><button className="secondary-button" onClick={() => startFromTemplate("count")}><FlaskConical size={16} />Count template</button><button className="secondary-button" onClick={() => { setIssuedToken(""); setShowClient(true); }}><KeyRound size={16} />New client</button><button className="primary-button" onClick={() => openTool()}><Plus size={16} />New query tool</button></div></div>
      <div className="metric-grid three"><Metric label="Published" value={summary?.published ?? "-"} detail="Available to granted clients" icon={<Check size={18} />} tone="teal" /><Metric label="Invocations" value={summary?.tools.reduce((total, tool) => total + tool.invocation_count, 0) ?? "-"} detail="Audited external requests" icon={<Network size={18} />} tone="blue" /><Metric label="Never invoked" value={summary?.never_invoked ?? "-"} detail="Review for adoption or retirement" icon={<AlertCircle size={18} />} tone="amber" /></div>
      {filteredTools.length ? <><div className="table-header gateway-tool-grid"><span>Tool</span><span>Connector</span><span>Version</span><span>Status</span><span /></div>
      {filteredTools.map((tool) => <div className="data-row gateway-tool-grid" key={tool.id}><button className="metric-main" onClick={() => openTool(tool)}><strong>{tool.name}</strong><small>{tool.line_of_business} · {tool.purpose}</small></button><span>{connectors.find((item) => item.id === tool.connector_id)?.name || "Local PostgreSQL"}</span><span>v{tool.version}</span><StatusPill value={tool.status} /><button className="icon-button" title="Publish query tool" disabled={tool.status === "published"} onClick={() => publish(tool)}><Check size={16} /></button></div>)}</> : <div className="inline-empty">{search ? "No tools match your search." : "No query tools yet."}</div>}
    </section>
    <section className="surface admin-surface">
      <div className="section-heading compact"><div><span className="eyebrow">CLIENT CREDENTIALS</span><h3>External clients</h3></div><code>/mcp / external/v1/query-tools</code></div>
      <div className="table-header external-client-grid"><span>Client</span><span>Client ID</span><span>Scopes</span><span>Status</span><span /></div>
      {clients.map((client) => <div className="data-row external-client-grid" key={client.id}><span><strong>{client.name}</strong><small>{new Date(client.created_at).toLocaleDateString()}</small></span><code>{client.client_id}</code><span>{client.scopes.join(", ")}</span><StatusPill value={client.active ? "active" : "disabled"} /><span className="row-actions"><button className="icon-button" title="Rotate token" onClick={() => rotate(client)}><RefreshCw size={16} /></button><button className="icon-button" title={client.active ? "Disable client" : "Enable client"} onClick={() => toggleClient(client)}>{client.active ? <XCircle size={16} /> : <Check size={16} />}</button></span></div>)}
    </section>
    {showTool && <Modal title={selected ? `Query tool v${selected.version}` : "Create query tool"} onClose={() => setShowTool(false)}><form className="modal-form" onSubmit={saveTool}>
      <div className="form-grid"><label>Name<input value={toolForm.name} onChange={(event) => setToolForm({ ...toolForm, name: event.target.value })} required /></label><label>Connector<select value={toolForm.connector_id} onChange={(event) => setToolForm({ ...toolForm, connector_id: event.target.value, upstream_tool_name: "" })}><option value="">Local PostgreSQL</option>{connectors.map((connector) => <option key={connector.id} value={connector.id}>{connector.name} / {connector.connection_mode}</option>)}</select></label></div>
      <label>Description<input value={toolForm.description} onChange={(event) => setToolForm({ ...toolForm, description: event.target.value })} required /></label>
      <label>Purpose<textarea rows={3} value={toolForm.purpose} onChange={(event) => setToolForm({ ...toolForm, purpose: event.target.value })} required /></label>
      <div className="form-grid"><label>Data source<input value={toolForm.data_source} onChange={(event) => setToolForm({ ...toolForm, data_source: event.target.value })} required /></label><label>Line of business<input value={toolForm.line_of_business} onChange={(event) => setToolForm({ ...toolForm, line_of_business: event.target.value })} required /></label></div>
      <div className="form-grid"><label>Owner<input value={toolForm.owner} onChange={(event) => setToolForm({ ...toolForm, owner: event.target.value })} required /></label><label>Tags<input value={toolForm.tags} onChange={(event) => setToolForm({ ...toolForm, tags: event.target.value })} placeholder="accounts, customer, read-only" /></label></div>
      {selectedConnector?.connection_mode === "mcp" && <label>Upstream MCP tool name<input value={toolForm.upstream_tool_name} onChange={(event) => setToolForm({ ...toolForm, upstream_tool_name: event.target.value })} placeholder="get_account" required /></label>}
      <label>Read-only SQL template<textarea rows={7} value={toolForm.sql_template} onChange={(event) => setToolForm({ ...toolForm, sql_template: event.target.value })} required /></label>
      <label>Parameter JSON Schema<textarea rows={7} value={toolForm.parameter_schema} onChange={(event) => setToolForm({ ...toolForm, parameter_schema: event.target.value })} required /></label>
      <div className="form-grid"><label>Allowed relations<input value={toolForm.allowed_relations} onChange={(event) => setToolForm({ ...toolForm, allowed_relations: event.target.value })} /></label><label>Row limit<input type="number" min={1} max={1000} value={toolForm.row_limit} onChange={(event) => setToolForm({ ...toolForm, row_limit: Number(event.target.value) })} /></label></div>
      {selected && <><label>Test parameters<textarea rows={4} value={testParameters} onChange={(event) => setTestParameters(event.target.value)} /></label><div className="inline-admin-form"><select value={grantClient} onChange={(event) => setGrantClient(event.target.value)}><option value="">Select external client</option>{clients.map((client) => <option value={client.id} key={client.id}>{client.name}</option>)}</select><button type="button" className="secondary-button" onClick={grant}><KeyRound size={16} />Grant</button><button type="button" className="secondary-button" onClick={testTool}><Play size={16} />Test</button></div></>}
      <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowTool(false)}>Cancel</button><button className="primary-button"><Archive size={16} />Save draft</button></div>
    </form></Modal>}
    {showClient && <Modal title="External client" onClose={() => setShowClient(false)}>{issuedToken ? <div className="modal-form"><div className="policy-banner"><KeyRound size={18} /><span><strong>One-time client token</strong><small>This value is not available again after this dialog closes.</small></span></div><label>Bearer token<textarea readOnly rows={4} value={issuedToken} onFocus={(event) => event.currentTarget.select()} /></label><div className="modal-actions"><button className="primary-button" onClick={() => setShowClient(false)}><Check size={16} />Done</button></div></div> : <form className="modal-form" onSubmit={createClient}><label>Client name<input value={clientName} onChange={(event) => setClientName(event.target.value)} required /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowClient(false)}>Cancel</button><button className="primary-button"><KeyRound size={16} />Issue token</button></div></form>}</Modal>}
  </div>;
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
  const [suggestions, setSuggestions] = useState<LearningSuggestion[]>([]);
  const [suggestionFilter, setSuggestionFilter] = useState<"open" | "accepted" | "dismissed">("open");
  const [reviewingSuggestion, setReviewingSuggestion] = useState<LearningSuggestion | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [govTab, setGovTab] = useState<"prompts" | "retention" | "learning" | "router">("prompts");
  const load = useCallback(async () => { const [promptData, retentionData] = await Promise.all([api<PromptArtifact[]>("/prompts"), api<RetentionPolicy[]>("/retention-policies")]); setPrompts(promptData); setPolicies(retentionData); }, []);
  const loadSuggestions = useCallback(async (status: "open" | "accepted" | "dismissed") => { try { setSuggestions(await api<LearningSuggestion[]>(`/learning-suggestions?status=${status}`)); } catch (reason) { notify(reason instanceof Error ? reason.message : "Learning suggestions unavailable", "error"); } }, [notify]);
  useEffect(() => { load().catch((reason) => notify(reason instanceof Error ? reason.message : "Governance configuration unavailable", "error")); }, [load, notify]);
  useEffect(() => { loadSuggestions(suggestionFilter); }, [loadSuggestions, suggestionFilter]);
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
  function openPrompt(prompt?: PromptArtifact) { setEditing(prompt || null); setPromptForm(prompt ? { name: prompt.name, system_prompt: prompt.content.system_prompt || "", template: prompt.content.template || "", variables: (prompt.content.variables || []).join(", ") } : emptyPrompt); setRollbackVersion(1); setShowPrompt(true); }
  async function savePrompt(event: FormEvent) { event.preventDefault(); try { await api("/prompts", { method: "POST", body: JSON.stringify({ ...promptForm, variables: promptForm.variables.split(",").map((item) => item.trim()).filter(Boolean), prompt_id: editing?.id || null, metadata: {} }) }); setShowPrompt(false); await load(); notify("Prompt draft version saved"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Prompt could not be saved", "error"); } }
  async function publishPrompt(prompt: PromptArtifact) { try { await api(`/artifacts/${prompt.id}/review`, { method: "POST", body: JSON.stringify({ decision: "approved", note: "Published from prompt governance" }) }); await load(); notify("Prompt approved"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Prompt could not be approved", "error"); } }
  async function rollbackPrompt() { if (!editing) return; try { await api(`/prompts/${editing.id}/rollback`, { method: "POST", body: JSON.stringify({ version: rollbackVersion }) }); setShowPrompt(false); await load(); notify(`Prompt rolled back from version ${rollbackVersion}`); } catch (reason) { notify(reason instanceof Error ? reason.message : "Prompt rollback failed", "error"); } }
  async function deletePrompt(prompt: PromptArtifact) { if (!(await confirm({ title: "Delete prompt", body: `Delete prompt "${prompt.name}" and its version history?` }))) return; try { await api(`/prompts/${prompt.id}`, { method: "DELETE" }); await load(); notify("Prompt deleted"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Prompt could not be deleted", "error"); } }
  async function saveRetention(event: FormEvent) { event.preventDefault(); try { await api("/retention-policies", { method: "POST", body: JSON.stringify(retentionForm) }); await load(); notify("Retention policy saved"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Retention policy could not be saved", "error"); } }
  async function runRetention(policy: RetentionPolicy) { try { const result = await api<{ candidate_count: number }>(`/retention-policies/${policy.id}/run`, { method: "POST" }); notify(`${result.candidate_count} expired records sent for approval`); } catch (reason) { notify(reason instanceof Error ? reason.message : "Retention preview failed", "error"); } }
  return <div className="view-stack">
    <div className="tabs"><button className={govTab === "prompts" ? "active" : ""} onClick={() => setGovTab("prompts")}><Archive size={16} />Prompts</button><button className={govTab === "retention" ? "active" : ""} onClick={() => setGovTab("retention")}><Clock3 size={16} />Retention</button><button className={govTab === "learning" ? "active" : ""} onClick={() => setGovTab("learning")}><Sparkles size={16} />Learning loop{suggestions.length > 0 && suggestionFilter === "open" ? <span className="nav-count">{suggestions.length}</span> : null}</button><button className={govTab === "router" ? "active" : ""} onClick={() => setGovTab("router")}><Network size={16} />Router evaluation</button></div>
    {govTab === "router" && <RouterEvaluationPanel notify={notify} />}
    {govTab === "prompts" && <section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">PROMPT LIFECYCLE</span><h3>Versioned prompts</h3><p>Draft, review, approve, and roll back reusable model instructions.</p></div><button className="primary-button" onClick={() => openPrompt()}><Plus size={16} />New prompt</button></div><div className="table-header prompt-grid"><span>Prompt</span><span>Version</span><span>Status</span><span /></div>{prompts.map((prompt) => <div className="data-row prompt-grid" key={prompt.id}><button className="metric-main" onClick={() => openPrompt(prompt)}><strong>{prompt.name}</strong><small>{(prompt.content.variables || []).join(", ") || "No variables"}</small></button><span>v{prompt.version}</span><StatusPill value={prompt.status} /><span className="row-actions"><button className="icon-button" title="Approve prompt" disabled={prompt.status === "approved"} onClick={() => publishPrompt(prompt)}><Check size={16} /></button><button className="icon-button" title="Delete prompt and version history" onClick={() => deletePrompt(prompt)}><XCircle size={16} /></button></span></div>)}</section>}
    {govTab === "retention" && <section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">DATA LIFECYCLE</span><h3>Retention controls</h3><p>Preview expired operational records and route permanent deletion through approval.</p></div></div><form className="inline-admin-form retention-form" onSubmit={saveRetention}><select value={retentionForm.resource_type} onChange={(event) => setRetentionForm({ ...retentionForm, resource_type: event.target.value })}><option value="audit_events">Audit events</option><option value="model_call_logs">Model call logs</option><option value="external_invocations">External invocations</option><option value="user_feedback">User feedback</option></select><input type="number" min={1} max={3650} value={retentionForm.retention_days} onChange={(event) => setRetentionForm({ ...retentionForm, retention_days: Number(event.target.value) })} aria-label="Retention days" /><button className="primary-button"><Archive size={16} />Save</button></form><div className="table-header retention-grid"><span>Resource</span><span>Days</span><span>Status</span><span /></div>{policies.map((policy) => <div className="data-row retention-grid" key={policy.id}><strong>{policy.resource_type.replaceAll("_", " ")}</strong><span>{policy.retention_days}</span><StatusPill value={policy.enabled ? "enabled" : "disabled"} /><button className="secondary-button" onClick={() => runRetention(policy)}><Play size={15} />Preview and run</button></div>)}</section>}
    {govTab === "learning" && <section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">LEARNING LOOP</span><h3>Feedback-derived suggestions</h3><p>Repeated not-helpful feedback in the same area is grouped into one suggestion with escalating severity. Nothing here changes runtime behavior automatically — review and apply changes yourself.</p></div><select value={suggestionFilter} onChange={(event) => setSuggestionFilter(event.target.value as typeof suggestionFilter)} aria-label="Filter suggestions by status"><option value="open">Open</option><option value="accepted">Accepted</option><option value="dismissed">Dismissed</option></select></div>{suggestions.length ? <div className="table-header suggestion-grid"><span>Signal</span><span>Category</span><span>Occurrences</span><span>Severity</span><span /></div> : <div className="inline-empty">No {suggestionFilter} suggestions for this project.</div>}{suggestions.map((suggestion) => <div className="data-row suggestion-grid" key={suggestion.id}><span><strong>{suggestion.title}</strong><small>{suggestion.rationale}</small></span><span>{suggestion.category.replaceAll("_", " ")}</span><span className="mono">{suggestion.occurrence_count}</span><StatusPill value={suggestion.severity} />{suggestion.status === "open" ? <button className="secondary-button" onClick={() => openReview(suggestion)}><Check size={15} />Review</button> : <span className="caption">{suggestion.status} {suggestion.review_note ? `— ${suggestion.review_note}` : ""}</span>}</div>)}</section>}
    {showPrompt && <Modal title={editing ? `Edit ${editing.name}` : "Create prompt"} onClose={() => setShowPrompt(false)}><form className="modal-form" onSubmit={savePrompt}><label>Name<input value={promptForm.name} onChange={(event) => setPromptForm({ ...promptForm, name: event.target.value })} required /></label><label>System prompt<textarea rows={7} value={promptForm.system_prompt} onChange={(event) => setPromptForm({ ...promptForm, system_prompt: event.target.value })} required /></label><label>Template<textarea rows={7} value={promptForm.template} onChange={(event) => setPromptForm({ ...promptForm, template: event.target.value })} required /></label><label>Variables<input value={promptForm.variables} onChange={(event) => setPromptForm({ ...promptForm, variables: event.target.value })} placeholder="question, catalog_context" /></label>{editing && <div className="inline-admin-form prompt-rollback"><input type="number" min={1} max={editing.version} value={rollbackVersion} onChange={(event) => setRollbackVersion(Number(event.target.value))} aria-label="Rollback source version" /><button type="button" className="secondary-button" onClick={rollbackPrompt}><RefreshCw size={16} />Rollback</button></div>}<div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowPrompt(false)}>Cancel</button><button className="primary-button"><Archive size={16} />Save version</button></div></form></Modal>}{reviewingSuggestion && <Modal title={reviewingSuggestion.title} onClose={() => setReviewingSuggestion(null)}><p className="modal-description">{reviewingSuggestion.rationale}</p><div className="policy-details"><div><span>Category</span><strong>{reviewingSuggestion.category.replaceAll("_", " ")}</strong></div><div><span>Occurrences</span><strong>{reviewingSuggestion.occurrence_count}</strong></div><div><span>Severity</span><strong>{reviewingSuggestion.severity}</strong></div></div>{reviewingSuggestion.proposed_change.recent_signals?.length ? <div className="tool-list">{reviewingSuggestion.proposed_change.recent_signals.map((signal, index) => <div key={signal.feedback_id || index}><span><small>{signal.comment || "No comment provided"}</small></span></div>)}</div> : null}
{setActive && reviewingSuggestion.proposed_change.review_target && REVIEW_TARGET_NAV[reviewingSuggestion.proposed_change.review_target] && (
  <div className="modal-note">
    <ShieldCheck size={16} />
    <span>
      Accepting only records your decision — it never changes a prompt, tool, or policy by itself. To make the actual fix, go review it yourself.
      <button type="button" className="link-button" onClick={() => setActive!(REVIEW_TARGET_NAV[reviewingSuggestion.proposed_change.review_target!].key)}>
        {REVIEW_TARGET_NAV[reviewingSuggestion.proposed_change.review_target!].label} →
      </button>
    </span>
  </div>
)}
<label>Review note<textarea rows={4} value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="What you decided and why, for the audit trail" /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => submitReview("dismissed")}><XCircle size={16} />Dismiss</button><button className="primary-button" onClick={() => submitReview("accepted")}><Check size={16} />Accept</button></div></Modal>}{confirmDialog}</div>;
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
  return <section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">WORKSPACE ACCESS</span><h3>Projects and memberships</h3><p>Create projects from the sidebar switcher, then assign users and project roles here.</p></div><select value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>{projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select></div><div className="table-header project-member-grid"><span>User</span><span>Application role</span><span>Project role</span></div>{members.map((member) => <div className="data-row project-member-grid" key={member.id}><span><strong>{member.user.name}</strong><small>{member.user.email}</small></span><StatusPill value={member.user.role} /><StatusPill value={member.role} /></div>)}<form className="inline-admin-form" onSubmit={add}><select value={form.user_id} onChange={(event) => setForm({ ...form, user_id: event.target.value })} required><option value="">Select user</option>{users.map((user) => <option value={user.id} key={user.id}>{user.name} / {user.email}</option>)}</select><select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}><option value="owner">Owner</option><option value="maintainer">Maintainer</option><option value="member">Member</option><option value="viewer">Viewer</option></select><button className="primary-button"><UserPlus size={16} />Assign</button></form></section>;
}

export function ConnectorsAdmin({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [confirm, confirmDialog] = useConfirm();
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [drift, setDrift] = useState<SchemaDrift[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Connector | null>(null);
  const [form, setForm] = useState({ name: "", connector_type: "sql_server", connection_mode: "direct" as "direct" | "mcp", description: "", host: "", database: "", mcp_server_url: "", secret_reference: "" });
  const load = useCallback(() => Promise.all([api<Connector[]>("/connectors"), api<SchemaDrift[]>("/schema-drift")]).then(([connectorData, driftData]) => { setConnectors(connectorData); setDrift(driftData); }), []);
  useEffect(() => { load(); }, [load]);
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
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [usage, setUsage] = useState<ModelUsage | null>(null);
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
    }));
  }
  const load = useCallback(() => Promise.all([api<ModelProvider[]>("/model-providers"), api<ModelUsage>("/model-usage")]).then(([providerData, usageData]) => { setProviders(providerData); setUsage(usageData); }), []);
  useEffect(() => { load(); }, [load]);
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
      <div className="provider-grid">{providers.map((provider) => <article className="provider-card" key={provider.id}><div className="provider-heading"><span className="provider-icon"><Bot size={20} /></span><span>{provider.is_default && <span className="tag">default</span>}<StatusPill value={provider.status} /></span></div><h4>{provider.name}</h4><p>{provider.provider_type.replaceAll("_", " ")}</p><dl><div><dt>Chat model</dt><dd>{provider.default_model}</dd></div><div><dt>Embeddings</dt><dd>{provider.embedding_model || "Not configured"}</dd></div><div><dt>Secret</dt><dd>{provider.secret_reference || "Not required"}</dd></div></dl><div className="provider-actions"><button className="secondary-button" onClick={() => test(provider.id)}><Gauge size={16} />Test</button><button className="secondary-button" disabled={provider.is_default || provider.status !== "healthy"} onClick={() => setDefault(provider.id)}><Check size={16} />Set default</button></div></article>)}</div>
      <ModelRoutingPanel notify={notify} providers={providers} />
      {usage && <section className="usage-strip"><div><span>Calls</span><strong>{usage.totals.calls}</strong></div><div><span>Input tokens</span><strong>{usage.totals.input_tokens.toLocaleString()}</strong></div><div><span>Output tokens</span><strong>{usage.totals.output_tokens.toLocaleString()}</strong></div><div><span>Estimated cost</span><strong>{usage.pricing_configured ? `$${usage.totals.estimated_cost_usd.toFixed(4)}` : "Rates not set"}</strong></div></section>}
      {showForm && <Modal title="Add model provider" onClose={() => setShowForm(false)}><form className="modal-form" onSubmit={create}><div className="form-grid"><label>Name<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label><label>Type<select value={form.provider_type} onChange={(event) => chooseProviderType(event.target.value)}>{providerTypeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label></div><label>Base URL<input value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} placeholder={providerType.baseUrl || "Provider default"} /></label><div className="form-grid"><label>Default chat model<input value={form.default_model} onChange={(event) => setForm({ ...form, default_model: event.target.value })} placeholder={providerType.modelPlaceholder} required /></label><label>Embedding model<input value={form.embedding_model} onChange={(event) => setForm({ ...form, embedding_model: event.target.value })} /></label></div><label>Secret reference<input value={form.secret_reference} onChange={(event) => setForm({ ...form, secret_reference: event.target.value })} placeholder={providerType.secretPlaceholder} /></label>{form.provider_type === "openrouter" && <div className="modal-note"><ShieldCheck size={16} />OpenRouter is OpenAI-compatible. Model names are namespaced by vendor, for example anthropic/claude-sonnet-5; the key is read from OPENROUTER_API_KEY.</div>}<div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary-button">Add provider</button></div></form></Modal>}
    </section>
  );
}

export function UsersAdmin({ notify, currentUser }: { notify: (message: string, tone?: "ok" | "error") => void; currentUser?: SessionUser }) {
  const [users, setUsers] = useState<(SessionUser & { active: boolean; created_at: string })[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", role: "analyst", temporary_password: "ChangeMe123!" });
  const [editingUser, setEditingUser] = useState<(typeof users)[number] | null>(null);
  const [editForm, setEditForm] = useState({ name: "", email: "" });
  const load = useCallback(() => api<typeof users>("/admin/users").then(setUsers).finally(() => setLoading(false)), []);
  useEffect(() => { load(); }, [load]);
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
  const filtered = users.filter((user) => search ? user.name.toLowerCase().includes(search.toLowerCase()) || user.email.toLowerCase().includes(search.toLowerCase()) : true);
  return (
    <section className="surface admin-surface">
      <div className="section-heading"><div><span className="eyebrow">LOCAL ACCESS</span><h3>Users and roles</h3><p>Admin-managed accounts remain available before and after PingFederate is enabled. Deactivating revokes sign-in immediately; accounts are never hard-deleted so audit history stays intact.</p></div><div className="row-actions"><div className="toolbar-search"><Search size={16} /><input placeholder="Search users..." value={search} onChange={(event) => setSearch(event.target.value)} /></div><button className="primary-button" onClick={() => setShowForm(true)}><UserPlus size={17} />Add user</button></div></div>
      {loading ? <LoadingBlock label="Loading users" /> : filtered.length ? <>
        <div className="table-header user-grid"><span>User</span><span>Role</span><span>Status</span><span>Created</span></div>
        {filtered.map((user) => <div className="data-row user-grid" key={user.id}><span className="person-cell"><span className="user-avatar">{user.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</span><span><strong>{user.name}</strong><small>{user.email}</small></span></span><select className="table-select" value={user.role} onChange={(event) => update(user, { role: event.target.value })} aria-label={`Role for ${user.name}`}><option value="admin">Admin</option><option value="engineer">Engineer</option><option value="analyst">Analyst</option><option value="viewer">Viewer</option></select><span className="row-actions"><button className="icon-button" title="Edit name and email" onClick={() => openEdit(user)}><Edit2 size={15} /></button><button className="status-action" onClick={() => toggleActive(user)} title={user.active ? "Deactivate user" : "Activate user"} disabled={currentUser?.id === user.id && user.active}><StatusPill value={user.active ? "active" : "inactive"} /></button></span><span>{new Date(user.created_at).toLocaleDateString()}</span></div>)}
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
function ModelRoutingPanel({ notify, providers: registry }: { notify: (message: string, tone?: "ok" | "error") => void; providers: ModelProvider[] }) {
  const [routing, setRouting] = useState<ModelRouting | null>(null);
  const [draft, setDraft] = useState<Record<string, string | null>>({});
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");
  const [saving, setSaving] = useState(false);
  const apply = useCallback((data: ModelRouting) => {
    setRouting(data);
    setDraft(Object.fromEntries(data.purposes.map((item) => [item.purpose, item.provider_id ?? null])));
    setState("ready");
  }, []);
  useEffect(() => {
    let active = true;
    api<ModelRouting>("/model-routing")
      .then((data) => { if (active) apply(data); })
      .catch((reason) => {
        if (!active) return;
        setState("unavailable");
        if (!(reason instanceof ApiError && (reason.status === 404 || reason.status === 405))) notify(reason instanceof Error ? reason.message : "Model routing could not be loaded", "error");
      });
    return () => { active = false; };
  }, [apply, notify, registry]);
  const purposes = routing?.purposes || [];
  const options = routing?.providers || [];
  const dirty = purposes.some((item) => (draft[item.purpose] ?? null) !== (item.provider_id ?? null));
  async function save() {
    setSaving(true);
    try {
      apply(await api<ModelRouting>("/model-routing", { method: "PUT", body: JSON.stringify({ assignments: draft }) }));
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
        {purposes.map((item) => (
          <div className="data-row routing-grid" key={item.purpose}>
            <span><strong>{item.label}</strong><small>{item.purpose}</small></span>
            <select className="table-select" aria-label={`Provider for ${item.label}`} value={draft[item.purpose] ?? ""} onChange={(event) => setDraft((current) => ({ ...current, [item.purpose]: event.target.value || null }))}>
              <option value="">Project/global default</option>
              {options.map((provider) => <option key={provider.id} value={provider.id} disabled={!provider.enabled}>{provider.name} / {provider.default_model}{provider.status !== "healthy" ? ` (${provider.status.replaceAll("_", " ")})` : ""}</option>)}
            </select>
            <span>{item.effective_provider ? `${item.effective_provider.name} / ${item.effective_provider.model}` : "No provider resolved"}{item.scope && <small>via {item.scope}</small>}</span>
          </div>
        ))}
        {!purposes.length && <p className="admin-hint">The API reported no routable purposes.</p>}
        <div className="form-end">
          <button type="button" className="secondary-button" disabled={!dirty || saving} onClick={() => routing && apply(routing)}>Reset</button>
          <button type="button" className="primary-button" disabled={!dirty || saving} onClick={() => void save()}>{saving ? <RefreshCw size={16} className="spin" /> : <Check size={16} />}Save routing</button>
        </div>
      </>}
    </div>
  );
}

type RouterEvaluation = {
  cases: number;
  backends: Record<string, { accuracy: number | null; avg_latency_ms: number | null; effective_backend: string | null; results: { question: string; expected: string; got: string; confidence: number; backend: string; correct: boolean }[] }>;
};
const ROUTER_BACKENDS = ["local", "llm", "jev"] as const;
const ROUTER_SAMPLE_CASES = "How many orders were placed per month? | sql_analysis\nRun the monthly revenue reconciliation agent | agent_run\nWhat does it mean? | clarify";

/** Replays labelled questions through each decision-router backend (POST /router/evaluate). */
function RouterEvaluationPanel({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [casesText, setCasesText] = useState(ROUTER_SAMPLE_CASES);
  const [backends, setBackends] = useState<Record<string, boolean>>({ local: true, llm: true, jev: false });
  const [includeFeedback, setIncludeFeedback] = useState(true);
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<RouterEvaluation | null>(null);
  const [openBackend, setOpenBackend] = useState("");
  async function run(event: FormEvent) {
    event.preventDefault();
    const cases = casesText.split("\n").map((line) => line.split("|").map((part) => part.trim())).filter(([question, route]) => question && route).map(([question, route]) => ({ question, expected_route: route }));
    const selected = ROUTER_BACKENDS.filter((name) => backends[name]);
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
  return (
    <section className="surface admin-surface">
      <div className="section-heading"><div><span className="eyebrow">DECISION ROUTER</span><h3>Router evaluation</h3><p>Replay labelled questions, plus answers users rated, through each routing backend. Enable a backend only if it wins on your own data.</p></div></div>
      <form className="modal-form router-eval-form" onSubmit={run}>
        <label>Labelled cases (one per line: question | expected_route)<textarea rows={4} value={casesText} onChange={(event) => setCasesText(event.target.value)} placeholder="How many orders per month? | sql_analysis" /></label>
        <div className="router-eval-options">
          {ROUTER_BACKENDS.map((name) => <label key={name} className="check-option"><input type="checkbox" checked={!!backends[name]} onChange={(event) => setBackends((current) => ({ ...current, [name]: event.target.checked }))} />{name}</label>)}
          <label className="check-option"><input type="checkbox" checked={includeFeedback} onChange={(event) => setIncludeFeedback(event.target.checked)} />Include rated answers</label>
          <button className="primary-button" disabled={running}>{running ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}Run evaluation</button>
        </div>
      </form>
      {report && <>
        <div className="subheading"><h4>Results</h4><span>{report.cases} case{report.cases === 1 ? "" : "s"}</span></div>
        <div className="table-header router-eval-grid"><span>Backend</span><span>Effective</span><span>Accuracy</span><span>Avg latency</span><span /></div>
        {rows.map(([name, item]) => (
          <div key={name}>
            <div className="data-row router-eval-grid">
              <span><strong>{name}</strong></span>
              <span>{item.effective_backend || "-"}{item.effective_backend && item.effective_backend !== name ? " (fallback)" : ""}</span>
              <span>{item.accuracy == null ? "-" : `${Math.round(item.accuracy * 100)}%`}</span>
              <span>{item.avg_latency_ms == null ? "-" : `${item.avg_latency_ms} ms`}</span>
              <button type="button" className="text-button" onClick={() => setOpenBackend(openBackend === name ? "" : name)} aria-expanded={openBackend === name}>{openBackend === name ? "Hide cases" : "Cases"}</button>
            </div>
            {openBackend === name && <div className="router-eval-cases">{item.results.map((result, index) => <div key={index} className={result.correct ? "" : "miss"}>{result.correct ? <Check size={13} /> : <XCircle size={13} />}<span><strong>{result.question}</strong><small>expected {result.expected} · got {result.got} ({Math.round(result.confidence * 100)}%)</small></span></div>)}</div>}
          </div>
        ))}
      </>}
    </section>
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
