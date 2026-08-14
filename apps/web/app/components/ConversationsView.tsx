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
  Edit2,
  FileSpreadsheet,
  FileUp,
  FlaskConical,
  Gauge,
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
  ThumbsDown,
  ThumbsUp,
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


export function ConversationsView({ notify, currentUser, seed }: { notify: (message: string, tone?: "ok" | "error") => void; currentUser: SessionUser; seed?: { question: string; connector_id: string } | null }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [connectorId, setConnectorId] = useState("");
  const [busy, setBusy] = useState(false);
  const [reportName, setReportName] = useState("");
  const [showReport, setShowReport] = useState(false);
  const [toolSql, setToolSql] = useState("");
  const [showToolModal, setShowToolModal] = useState(false);
  const [notebookSql, setNotebookSql] = useState("");
  const [showNotebookModal, setShowNotebookModal] = useState(false);
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
  useEffect(() => {
    if (!seed) return;
    setQuestion(seed.question);
    setConnectorId(seed.connector_id);
    setSelectedId(""); // Force a new conversation
  }, [seed]);

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
      const effectiveDialect = resolvedConnector ? connectorDialectForType(resolvedConnector.connector_type) : "postgres";
      const response = await api<ConversationMessage>(`/conversations/${conversationId}/messages`, { method: "POST", body: JSON.stringify({ content: question, dialect: effectiveDialect, connector_id: resolvedConnector?.id || null }) });
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

  async function publishTool(event: FormEvent) {
    event.preventDefault();
    const slug = ("tool_" + reportName.toLowerCase().replace(/[^a-z0-9_.-]+/g, "_")).slice(0, 120);
    try {
      await api("/query-tools", { method: "POST", body: JSON.stringify({
        name: slug,
        description: `Published from a conversation analysis: ${reportName}`,
        purpose: question || reportName,
        data_source: selectedConnector?.name || "DataPilot workspace",
        line_of_business: "general",
        owner: currentUser.email || currentUser.name,
        sql_template: toolSql,
        parameter_schema: { type: "object", properties: {}, additionalProperties: false },
        requires_approval: true,
      }) });
      setShowToolModal(false); setReportName(""); notify("Tool publication requested and sent to Approvals");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not publish tool", "error"); }
  }

  async function ejectNotebook(event: FormEvent) {
    event.preventDefault();
    try {
      await api("/notebooks", { method: "POST", body: JSON.stringify({ name: reportName, cells: [{ id: `cell-${Date.now()}`, type: "sql", source: notebookSql }] }) });
      setShowNotebookModal(false); setReportName(""); notify("Notebook created");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not create notebook", "error"); }
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
  async function renameConversation() {
    if (!selectedConversation || !canEditConversations) return;
    const newTitle = window.prompt("Rename analysis:", selectedConversation.title);
    if (newTitle && newTitle.trim() && newTitle.trim() !== selectedConversation.title) {
      try {
        await api(`/conversations/${selectedId}`, { method: "PUT", body: JSON.stringify({ title: newTitle.trim() }) });
        await loadConversations();
        notify("Analysis renamed");
      } catch (reason) { notify("Rename failed", "error"); }
    }
  }
  async function sendFeedback(messageId: string, rating: "positive" | "negative") {
    try {
      await api("/feedback", { method: "POST", body: JSON.stringify({ context_type: "sql", context_id: messageId, rating: rating === "positive" ? "helpful" : "not_helpful" }) });
      notify("Feedback saved");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not save feedback", "error"); }
  }
  const latestAnalysis = [...messages].reverse().find((message) => message.role === "assistant" && message.structured?.sql);
  const localConnector = connectors.find((connector) => connector.connector_type === "local_files");
  const externalConnectors = connectors.filter((connector) => connector.connector_type !== "local_files");
  const selectedConnector = connectors.find((connector) => connector.id === connectorId);
  const resolvedConnector = selectedConnector || localConnector || null;
  const latestExecutionTarget = latestAnalysis?.structured.source
    ? `${latestAnalysis.structured.source.name} / ${latestAnalysis.structured.source.database || latestAnalysis.structured.source.dialect}`
    : "DataPilot local workspace / PostgreSQL staging";
  const selectedConversation = conversations.find((item) => item.id === selectedId);
  const canDeleteSelected = canEditConversations && !!selectedId && !(currentUser.role === "analyst" && selectedConversation?.created_by !== currentUser.id);

  return (
    <div className="analysis-layout">
      <aside className="surface conversation-list">
        <div className="section-heading compact"><div><span className="eyebrow">HISTORY</span><h3>Analyses</h3></div><button className="icon-button" title={canEditConversations ? "New analysis" : "Viewer role is read-only"} disabled={!canEditConversations} onClick={createConversation}><Plus size={17} /></button></div>
        <div className="conversation-items">{conversations.map((item) => <button key={item.id} className={selectedId === item.id ? "selected" : ""} onClick={() => setSelectedId(item.id)}><MessageSquare size={16} /><span><strong>{item.title}</strong><small>{item.message_count} messages / {new Date(item.updated_at).toLocaleDateString()}</small></span></button>)}</div>
      </aside>
      <section className="surface conversation-thread">
        <div className="section-heading compact"><div><span className="eyebrow">GROUNDED ANALYSIS</span><h3>{selectedConversation?.title || "New analysis"}</h3></div><span className="row-actions"><button className="icon-button" title={canEditConversations ? "Rename analysis" : "Viewer role is read-only"} disabled={!selectedId || !canEditConversations} onClick={renameConversation}><Edit2 size={17} /></button><button className="icon-button" title={canEditConversations ? "Save report" : "Viewer role is read-only"} disabled={!messages.length || !canEditConversations} onClick={() => { setReportName(selectedConversation?.title || "Analysis report"); setShowReport(true); }}><Archive size={17} /></button><button className="icon-button" title={canDeleteSelected ? "Delete conversation" : "Insufficient permission"} disabled={!canDeleteSelected} onClick={remove}><XCircle size={17} /></button></span></div>
        <div className="message-list">{messages.length ? messages.map((message) => <div className={`message ${message.role}`} key={message.id}><span className="message-avatar">{message.role === "user" ? "You" : <Bot size={16} />}</span><div><p>{message.content}</p>{message.structured?.sql && <><div className="message-meta"><StatusPill value={message.structured.validation?.status || "validated"} /><span>{message.structured.source ? `${message.structured.source.name} / ${connectorLabels[message.structured.source.connector_type] || message.structured.source.connector_type}` : `${message.structured.provider?.name} / ${message.structured.provider?.model}`}</span>{message.structured.cache?.hit ? <span>Reused saved query</span> : null}{message.structured.memory?.prior_messages_used ? <span>Context: {message.structured.memory.prior_messages_used} earlier messages</span> : null}</div><pre>{message.structured.sql}</pre><div className="row-actions" style={{marginTop: "8px", justifyContent: "flex-end"}}><button className="icon-button" onClick={() => { setToolSql(message.structured.sql || ""); setShowToolModal(true); setReportName(selectedConversation?.title || "Tool API"); }} title="Publish as Tool"><Network size={15} /></button><button className="icon-button" onClick={() => { setNotebookSql(message.structured.sql || ""); setShowNotebookModal(true); setReportName(selectedConversation?.title || "Analysis Notebook"); }} title="Eject to Notebook"><FileSpreadsheet size={15} /></button><button className="icon-button" onClick={() => sendFeedback(message.id, "positive")} title="Helpful"><ThumbsUp size={15} /></button><button className="icon-button" onClick={() => sendFeedback(message.id, "negative")} title="Not helpful"><ThumbsDown size={15} /></button></div></>}</div></div>) : <EmptyState icon={<MessageSquare size={24} />} title="Start an analysis" body="Each topic is a persistent conversation. Ask a follow-up here and its earlier context stays available." />}{busy && <div className="message assistant"><span className="message-avatar"><Bot size={16} /></span><div><p><RefreshCw size={15} className="spin" /> Continuing grounded analysis</p></div></div>}</div>
        <form className="analysis-composer" onSubmit={ask}><select value={connectorId} onChange={(event) => setConnectorId(event.target.value)} aria-label="Registered data source" disabled={!canEditConversations}><option value="">DataPilot local workspace / PostgreSQL staging</option>{externalConnectors.map((connector) => <option key={connector.id} value={connector.id}>{connector.name} / {connector.database || connector.host || "default"} / {connectorLabels[connector.connector_type] || connector.connector_type}</option>)}</select><span className="analysis-dialect">{selectedConnector ? `${connectorLabels[selectedConnector.connector_type] || selectedConnector.connector_type} source` : "PostgreSQL local source"}</span><textarea rows={2} value={question} onChange={(event) => setQuestion(event.target.value)} disabled={!canEditConversations} placeholder={canEditConversations ? "Ask a question or continue this topic" : "Read-only role: conversations can be viewed but not changed"} /><button className="send-button" disabled={busy || !question.trim() || !canEditConversations} aria-label="Send analysis question">{busy ? <RefreshCw size={18} className="spin" /> : <Send size={18} />}</button></form>
      </section>
        <aside className="surface insight-panel"><div className="section-heading compact"><div><span className="eyebrow">CONVERSATION CONTEXT</span><h3>Source and result</h3></div></div>{latestAnalysis ? <><div className="source-summary"><span>Selected source</span><strong>{latestAnalysis.structured.source?.name || "DataPilot local workspace"}</strong><small>{latestAnalysis.structured.source?.database || "PostgreSQL staging"} / {connectorLabels[latestAnalysis.structured.source?.connector_type || "local_files"] || latestAnalysis.structured.source?.connector_type}</small></div><div className="conversation-memory"><span>Execution target</span><p>{latestExecutionTarget}</p></div>{latestAnalysis.structured.cache?.hit && <div className="conversation-memory"><span>Reuse</span><p>Reused a saved governed query for the same normalized question and source context.</p></div>}{latestAnalysis.structured.execution?.error ? <div className="conversation-memory execution-error"><span>Execution error</span><p>{latestAnalysis.structured.execution.error}</p></div> : null}{latestAnalysis.structured.memory?.summary && <div className="conversation-memory"><span>Durable memory</span><p>{latestAnalysis.structured.memory.summary.replace("Earlier conversation summary:\n", "")}</p></div>}{latestAnalysis.structured.execution?.error ? <div className="chart-empty">Query execution failed. Review the error details above.</div> : <AnalysisChart chart={latestAnalysis.structured.chart} />}<div className="insight-facts"><div><span>Rows</span><strong>{latestAnalysis.structured.execution?.row_count ?? "-"}</strong></div><div><span>Source dialect</span><strong>{latestAnalysis.structured.dialect}</strong></div><div><span>Memory</span><strong>{latestAnalysis.structured.memory?.prior_messages_used || 0} prior</strong></div></div>{latestAnalysis.structured.grounding?.semantic_matches?.length ? <div className="conversation-memory"><span>Semantic grounding</span><p>{latestAnalysis.structured.grounding.semantic_matches.map((item) => `${item.name}: ${item.formula}`).join(" | ")}</p></div> : null}{latestAnalysis.structured.grounding?.join_matches?.length ? <div className="conversation-memory"><span>Approved joins</span><p>{latestAnalysis.structured.grounding.join_matches.map((item) => `${item.left_relation} ${item.join_type} ${item.right_relation}`).join(" | ")}</p></div> : null}<div className="check-list">{latestAnalysis.structured.validation?.checks?.map((check) => <div key={check}><Check size={15} />{check}</div>)}</div></> : <EmptyState icon={<CircleGauge size={24} />} title="No result yet" body="Choose a source or use the local workspace, then start a persistent analysis topic." />}</aside>
      {showReport && <Modal title="Save analysis report" onClose={() => setShowReport(false)}><form className="modal-form" onSubmit={saveReport}><label>Report name<input value={reportName} onChange={(event) => setReportName(event.target.value)} required /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowReport(false)}>Cancel</button><button className="primary-button"><Archive size={16} />Save report</button></div></form></Modal>}
      {showToolModal && <Modal title="Publish as API Tool" onClose={() => setShowToolModal(false)}><form className="modal-form" onSubmit={publishTool}><label>Tool name<input value={reportName} onChange={(event) => setReportName(event.target.value)} required /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowToolModal(false)}>Cancel</button><button className="primary-button"><Network size={16} />Request Approval</button></div></form></Modal>}
      {showNotebookModal && <Modal title="Eject to Notebook" onClose={() => setShowNotebookModal(false)}><form className="modal-form" onSubmit={ejectNotebook}><label>Notebook title<input value={reportName} onChange={(event) => setReportName(event.target.value)} required /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowNotebookModal(false)}>Cancel</button><button className="primary-button"><FileSpreadsheet size={16} />Create Notebook</button></div></form></Modal>}
    </div>
  );
}
