import {
  Activity,
  AlertCircle,
  Archive,
  Bot,
  BookOpen,
  Boxes,
  Braces,
  Check,
  ChevronDown,
  ChevronRight,
  CircleGauge,
  Clock3,
  CalendarClock,
  Code2,
  Database,
  FileSpreadsheet,
  FileUp,
  FlaskConical,
  Gauge,
  GitBranch,
  GitCompare,
  KeyRound,
  Layers3,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  Network,
  PanelLeftClose,
  Play,
  Plus,
  RefreshCw,
  Search,
  Send,
  Server,
  Settings,
  ShieldCheck,
  Sparkles,
  UserPlus,
  Users,
  X,
  XCircle,
} from "lucide-react";
import { embedDashboard, EmbeddedDashboard } from "@superset-ui/embedded-sdk";
import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, SessionUser } from "../lib/api";
import type {
  NavKey,
  Overview,
  Recommendation,
  SecurityCategoryKey,
  SecurityOverview,
  Dataset,
  Connector,
  ModelProvider,
  Project,
  AgentVersion,
  AgentDefinition,
  ToolVersion,
  ToolDefinition,
  SemanticMetric,
  SemanticJoinPolicy,
  PipelineDefinition,
  Incident,
  Job,
  Approval,
  IngestedFile,
  MappingColumn,
  LoadMode,
  IngestionMapping,
  QualityRun,
  QualityRule,
  SQLResult,
  SQLExecutionResult,
  SearchResult,
  Artifact,
  ArtifactVersion,
  IngestionSchedule,
  MappingOption,
  ArtifactComment,
  EvaluationSet,
  NotebookCellData,
  Notebook,
  Conversation,
  ConversationMessage,
  ExternalClient,
  QueryTool,
  QueryToolDraft,
  RelationOption,
  QueryToolUsage,
  QueryToolRegistrySummary,
  PromptArtifact,
  RetentionPolicy,
  SchemaDrift,
  ModelUsage,
} from "../types";
import {
  navItems,
  TOUR_STORAGE_KEY,
  defaultTourSteps,
  connectorLabels,
  connectorDialectForType,
  statusTone,
} from "../lib/constants";
import { StatusPill, LoadingBlock, EmptyState, Modal, Metric, ControlItem, AnalysisChart, SecurityOverviewPanel } from "./shared";


export function ConversationsView({ notify, currentUser }: { notify: (message: string, tone?: "ok" | "error") => void; currentUser: SessionUser }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [dialect, setDialect] = useState("postgres");
  const [connectorId, setConnectorId] = useState("");
  const [busy, setBusy] = useState(false);
  const [reportName, setReportName] = useState("");
  const [showReport, setShowReport] = useState(false);
  const canEditConversations = ["admin", "engineer", "analyst"].includes(currentUser.role);

  const loadConversations = useCallback(async () => {
    const data = await api<Conversation[]>("/conversations");
    setConversations(data);
    setSelectedId((current) => current || data[0]?.id || "");
  }, []);
  useEffect(() => {
    Promise.all([loadConversations(), api<Connector[]>("/connectors").then(setConnectors)])
      .catch((reason) => notify(reason instanceof Error ? reason.message : "Conversations unavailable", "error"));
  }, [loadConversations, notify]);
  useEffect(() => {
    if (!selectedId) { setMessages([]); return; }
    api<ConversationMessage[]>(`/conversations/${selectedId}/messages`).then(setMessages).catch((reason) => notify(reason instanceof Error ? reason.message : "Conversation unavailable", "error"));
  }, [selectedId, notify]);

  async function createConversation() {
    if (!canEditConversations) {
      notify("Your role can view conversations but cannot create analyses", "error");
      return;
    }
    try {
      const created = await api<Conversation>("/conversations", { method: "POST", body: JSON.stringify({ title: "New analysis" }) });
      setConversations((items) => [created, ...items]);
      setSelectedId(created.id);
      setMessages([]);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Conversation could not be created", "error"); }
  }
  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!canEditConversations) {
      notify("Your role can view analyses but cannot send questions", "error");
      return;
    }
    if (!question.trim()) return;
    setBusy(true);
    try {
      let conversationId = selectedId;
      if (!conversationId) {
        const created = await api<Conversation>("/conversations", { method: "POST", body: JSON.stringify({ title: "New analysis" }) });
        conversationId = created.id;
        setSelectedId(created.id);
      }
      const pending: ConversationMessage = { id: `pending-${Date.now()}`, conversation_id: conversationId, role: "user", content: question, structured: {}, created_at: new Date().toISOString() };
      setMessages((items) => [...items, pending]);
      const response = await api<ConversationMessage>(`/conversations/${conversationId}/messages`, { method: "POST", body: JSON.stringify({ content: question, dialect, connector_id: connectorId || null }) });
      setMessages((items) => [...items, response]);
      setQuestion("");
      await loadConversations();
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Analysis failed", "error"); }
    finally { setBusy(false); }
  }
  async function saveReport(event: FormEvent) {
    event.preventDefault();
    if (!canEditConversations) {
      notify("Your role cannot save conversation reports", "error");
      return;
    }
    try {
      await api(`/conversations/${selectedId}/report`, { method: "POST", body: JSON.stringify({ name: reportName }) });
      setShowReport(false); setReportName(""); notify("Conversation saved as a versioned report");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Report could not be saved", "error"); }
  }
  async function remove() {
    if (!selectedId) return;
    const selectedConversation = conversations.find((item) => item.id === selectedId);
    if (!canEditConversations || (currentUser.role === "analyst" && selectedConversation?.created_by !== currentUser.id)) {
      notify("Your role cannot delete this conversation", "error");
      return;
    }
    try { await api(`/conversations/${selectedId}`, { method: "DELETE" }); setSelectedId(""); setMessages([]); await loadConversations(); notify("Conversation deleted"); }
    catch (reason) { notify(reason instanceof Error ? reason.message : "Conversation could not be deleted", "error"); }
  }
  const latestAnalysis = [...messages].reverse().find((message) => message.role === "assistant" && message.structured?.sql);
  const selectedConnector = connectors.find((connector) => connector.id === connectorId);
  const selectedConversation = conversations.find((item) => item.id === selectedId);
  const canDeleteSelected = canEditConversations && !!selectedId && !(currentUser.role === "analyst" && selectedConversation?.created_by !== currentUser.id);

  return (
    <div className="analysis-layout">
      <aside className="surface conversation-list">
        <div className="section-heading compact"><div><span className="eyebrow">HISTORY</span><h3>Analyses</h3></div><button className="icon-button" title={canEditConversations ? "New analysis" : "Viewer role is read-only"} disabled={!canEditConversations} onClick={createConversation}><Plus size={17} /></button></div>
        <div className="conversation-items">{conversations.map((item) => <button key={item.id} className={selectedId === item.id ? "selected" : ""} onClick={() => setSelectedId(item.id)}><MessageSquare size={16} /><span><strong>{item.title}</strong><small>{item.message_count} messages / {new Date(item.updated_at).toLocaleDateString()}</small></span></button>)}</div>
      </aside>
      <section className="surface conversation-thread">
        <div className="section-heading compact"><div><span className="eyebrow">GROUNDED ANALYSIS</span><h3>{selectedConversation?.title || "New analysis"}</h3></div><span className="row-actions"><button className="icon-button" title={canEditConversations ? "Save report" : "Viewer role is read-only"} disabled={!messages.length || !canEditConversations} onClick={() => { setReportName(selectedConversation?.title || "Analysis report"); setShowReport(true); }}><Archive size={17} /></button><button className="icon-button" title={canDeleteSelected ? "Delete conversation" : "Insufficient permission"} disabled={!canDeleteSelected} onClick={remove}><XCircle size={17} /></button></span></div>
        <div className="message-list">{messages.length ? messages.map((message) => <div className={`message ${message.role}`} key={message.id}><span className="message-avatar">{message.role === "user" ? "You" : <Bot size={16} />}</span><div><p>{message.content}</p>{message.structured?.sql && <><div className="message-meta"><StatusPill value={message.structured.validation?.status || "validated"} /><span>{message.structured.source ? `${message.structured.source.name} / ${connectorLabels[message.structured.source.connector_type] || message.structured.source.connector_type}` : `${message.structured.provider?.name} / ${message.structured.provider?.model}`}</span>{message.structured.cache?.hit ? <span>Reused saved query</span> : null}{message.structured.memory?.prior_messages_used ? <span>Context: {message.structured.memory.prior_messages_used} earlier messages</span> : null}</div><pre>{message.structured.sql}</pre></>}</div></div>) : <EmptyState icon={<MessageSquare size={24} />} title="Start an analysis" body="Each topic is a persistent conversation. Ask a follow-up here and its earlier context stays available." />}{busy && <div className="message assistant"><span className="message-avatar"><Bot size={16} /></span><div><p><RefreshCw size={15} className="spin" /> Continuing grounded analysis</p></div></div>}</div>
        <form className="analysis-composer" onSubmit={ask}><select value={connectorId} onChange={(event) => setConnectorId(event.target.value)} aria-label="Registered data source" disabled={!canEditConversations}><option value="">DataPilot local workspace / PostgreSQL</option>{connectors.map((connector) => <option key={connector.id} value={connector.id}>{connector.name} / {connector.database || connector.host || "default"} / {connectorLabels[connector.connector_type] || connector.connector_type}</option>)}</select><span className="analysis-dialect">{connectorId ? `${connectorLabels[selectedConnector?.connector_type || ""] || selectedConnector?.connector_type} SQL` : `${dialect} SQL`}</span><textarea rows={2} value={question} onChange={(event) => setQuestion(event.target.value)} disabled={!canEditConversations} placeholder={canEditConversations ? "Ask a question or continue this topic" : "Read-only role: conversations can be viewed but not changed"} /><button className="send-button" disabled={busy || !question.trim() || !canEditConversations} aria-label="Send analysis question">{busy ? <RefreshCw size={18} className="spin" /> : <Send size={18} />}</button></form>
      </section>
        <aside className="surface insight-panel"><div className="section-heading compact"><div><span className="eyebrow">CONVERSATION CONTEXT</span><h3>Source and result</h3></div></div>{latestAnalysis ? <><div className="source-summary"><span>Registered source</span><strong>{latestAnalysis.structured.source?.name || "DataPilot local workspace"}</strong><small>{latestAnalysis.structured.source?.database || "PostgreSQL staging"} / {connectorLabels[latestAnalysis.structured.source?.connector_type || "local_files"] || latestAnalysis.structured.source?.connector_type}</small></div>{latestAnalysis.structured.cache?.hit && <div className="conversation-memory"><span>Reuse</span><p>Reused a saved governed query for the same normalized question and source context.</p></div>}{latestAnalysis.structured.memory?.summary && <div className="conversation-memory"><span>Durable memory</span><p>{latestAnalysis.structured.memory.summary.replace("Earlier conversation summary:\n", "")}</p></div>}<AnalysisChart chart={latestAnalysis.structured.chart} /><div className="insight-facts"><div><span>Rows</span><strong>{latestAnalysis.structured.execution?.row_count ?? "-"}</strong></div><div><span>SQL type</span><strong>{latestAnalysis.structured.dialect}</strong></div><div><span>Memory</span><strong>{latestAnalysis.structured.memory?.prior_messages_used || 0} prior</strong></div></div>{latestAnalysis.structured.grounding?.semantic_matches?.length ? <div className="conversation-memory"><span>Semantic grounding</span><p>{latestAnalysis.structured.grounding.semantic_matches.map((item) => `${item.name}: ${item.formula}`).join(" | ")}</p></div> : null}{latestAnalysis.structured.grounding?.join_matches?.length ? <div className="conversation-memory"><span>Approved joins</span><p>{latestAnalysis.structured.grounding.join_matches.map((item) => `${item.left_relation} ${item.join_type} ${item.right_relation}`).join(" | ")}</p></div> : null}<div className="check-list">{latestAnalysis.structured.validation?.checks?.map((check) => <div key={check}><Check size={15} />{check}</div>)}</div></> : <EmptyState icon={<CircleGauge size={24} />} title="No result yet" body="Select a registered source, then start a persistent analysis topic." />}</aside>
      {showReport && <Modal title="Save analysis report" onClose={() => setShowReport(false)}><form className="modal-form" onSubmit={saveReport}><label>Report name<input value={reportName} onChange={(event) => setReportName(event.target.value)} required /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowReport(false)}>Cancel</button><button className="primary-button"><Archive size={16} />Save report</button></div></form></Modal>}
    </div>
  );
}
