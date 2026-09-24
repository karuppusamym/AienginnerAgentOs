import {
  AlertCircle,
  Archive,
  ArrowDown,
  ArrowUp,
  Bot,
  ChevronLeft,
  ChevronRight,
  CircleGauge,
  Copy,
  Download,
  Edit2,
  FileSpreadsheet,
  GitBranch,
  MessageSquare,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Send,
  ShieldCheck,
  Square,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  XCircle,
} from "lucide-react";
import { FormEvent, KeyboardEvent, ReactNode, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError, apiStream, SessionUser } from "../lib/api";
import type { AnswerEnsemble, AnswerLearning, AnswerStage, ChartType, Connector, Conversation, ConversationMessage, JevDecision, RouteCandidate, RouteDecision, SQLExecutionResult } from "../types";
import { projectKey, scopes, useConnectors, useConversationMessages, useConversations, useInvalidate, useQueryErrorToast, type MessagePages } from "../lib/queries";
import { useWorkspace } from "../lib/workspace";
import { connectorLabels, connectorDialectForType } from "../lib/constants";
import { StatusPill, EmptyState, Modal, formatProbability, formatUsd } from "./shared";
import { AnalysisChart, ChartTypeSwitcher, chartAlternatives } from "./charts";

type Notify = (message: string, tone?: "ok" | "error") => void;
type InspectorTab = "result" | "sql" | "context" | "decision";
type Dialog =
  | { kind: "rename"; name: string }
  | { kind: "delete" }
  | { kind: "report"; name: string }
  | { kind: "tool"; name: string; sql: string; purpose: string; source: string }
  | { kind: "notebook"; name: string; sql: string }
  | { kind: "feedback"; messageId: string; comment: string };

const PANEL_STORAGE_KEY = "datapilot.analysis.panels";
const NO_CONVERSATIONS: Conversation[] = [];
const NO_CONNECTORS: Connector[] = [];
const NO_MESSAGES: ConversationMessage[] = [];
// Server-sent stages of one answer, in pipeline order (see POST /conversations/{id}/messages/stream).
const ANSWER_STAGES: { key: string; label: string }[] = [
  { key: "grounding", label: "Ground" },
  { key: "generating_sql", label: "Draft SQL" },
  { key: "executing", label: "Run preview" },
  { key: "routing", label: "Route" },
  { key: "answering", label: "Answer" },
];
const ROUTE_ICONS: Record<string, ReactNode> = {
  sql_analysis: <Sparkles size={13} />,
  query_tool: <Network size={13} />,
  agent_run: <GitBranch size={13} />,
  clarify: <AlertCircle size={13} />,
};

function readPanels(): { left: boolean; right: boolean } {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(PANEL_STORAGE_KEY) || "{}");
    return { left: parsed.left !== false, right: parsed.right !== false };
  } catch {
    return { left: true, right: true };
  }
}

function relativeTime(value: string) {
  const seconds = Math.round((Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 7 * 86400) return `${Math.floor(seconds / 86400)}d ago`;
  return new Date(value).toLocaleDateString();
}

function historyGroup(value: string) {
  const date = new Date(value);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diffDays = Math.floor((today.getTime() - new Date(date).setHours(0, 0, 0, 0)) / 86400000);
  if (diffDays <= 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return "Previous 7 days";
  return "Older";
}

// Answers saved before the API trimmed driver errors embed the full statement
// and a docs link; the inspector shows the complete error, the thread does not need it.
function displayText(content: string) {
  return content
    .replace(/\n?\[SQL:[\s\S]*?\]\s*(\(Background on this error at: [^)]*\))?/g, "")
    .replace(/\(Background on this error at: [^)]*\)/g, "")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

const CLAMP_CHARS = 420;

function toCsv(result: SQLExecutionResult) {
  const escape = (value: unknown) => {
    const text = value === null || value === undefined ? "" : String(value);
    return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  return [result.columns.map(escape).join(","), ...result.rows.map((row) => result.columns.map((column) => escape(row[column])).join(","))].join("\n");
}

function ScoreBar({ value, tone = "brand", label }: { value: number; tone?: "brand" | "blue" | "muted"; label?: string }) {
  const width = Math.max(2, Math.min(100, Math.round(value * 100)));
  return <span className={`score-bar score-bar--${tone}`} role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={width}><i style={{ width: `${width}%` }} /></span>;
}

function ResultTable({ result }: { result: SQLExecutionResult }) {
  const [page, setPage] = useState(0);
  const pageSize = 25;
  const pages = Math.max(1, Math.ceil(result.rows.length / pageSize));
  const rows = result.rows.slice(page * pageSize, page * pageSize + pageSize);
  useEffect(() => setPage(0), [result]);
  if (!result.columns.length) return <div className="chart-empty">No columns returned</div>;
  return (
    <div className="inspector-table-wrap">
      <div className="inspector-table-scroll">
        <table className="inspector-table">
          <thead><tr>{result.columns.map((column) => <th key={column} scope="col">{column}{result.protected_columns?.includes(column) && <ShieldCheck size={11} aria-label="masked" />}</th>)}</tr></thead>
          <tbody>{rows.map((row, index) => <tr key={index}>{result.columns.map((column) => <td key={column} title={String(row[column] ?? "")}>{String(row[column] ?? "")}</td>)}</tr>)}</tbody>
        </table>
      </div>
      <div className="inspector-table-footer">
        <span>{result.row_count} row{result.row_count === 1 ? "" : "s"}{result.truncated ? ` (truncated at ${result.limit})` : ""}</span>
        {pages > 1 && <span className="row-actions"><button className="icon-button" aria-label="Previous page" disabled={page === 0} onClick={() => setPage(page - 1)}><ChevronLeft size={14} /></button><span>{page + 1}/{pages}</span><button className="icon-button" aria-label="Next page" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}><ChevronRight size={14} /></button></span>}
      </div>
    </div>
  );
}

function RouteBadge({ route }: { route: RouteDecision }) {
  return <span className={`route-badge route-${route.route}`} title={`${route.label} · confidence ${Math.round(route.confidence * 100)}% · ${route.backend}`}>{ROUTE_ICONS[route.route]}{route.label}<b>{Math.round(route.confidence * 100)}%</b></span>;
}

export function ConversationsView({ notify, currentUser, seed, onSeedConsumed, routeConversationId, routeMessageId, onRouteChange }: {
  notify: Notify;
  currentUser: SessionUser;
  seed?: { question: string; connector_id: string } | null;
  onSeedConsumed?: () => void;
  /** `?c=` from the URL; "" means a fresh analysis / latest thread. */
  routeConversationId?: string;
  /** `?m=` from the URL: the answer shown in the inspector. */
  routeMessageId?: string;
  /** Reports thread / inspected answer so the shell can sync the URL (push = new history entry). */
  onRouteChange?: (conversationId: string, messageId: string, push: boolean) => void;
}) {
  const { projectId } = useWorkspace();
  const queryClient = useQueryClient();
  const invalidate = useInvalidate();
  const conversationsQuery = useConversations();
  const connectorsQuery = useConnectors();
  const conversations = conversationsQuery.data ?? NO_CONVERSATIONS;
  const connectors = connectorsQuery.data ?? NO_CONNECTORS;
  useQueryErrorToast(conversationsQuery.error || connectorsQuery.error, notify, "Conversations unavailable");
  const [selectedId, setSelectedId] = useState(routeConversationId || "");
  const messagesQuery = useConversationMessages(selectedId);
  useQueryErrorToast(messagesQuery.error, notify, "Conversation unavailable");
  // Client-only turns not (yet) confirmed by the server: the optimistic question
  // while it is answered, and failed / stopped questions offering Retry.
  const [localMessages, setLocalMessages] = useState<ConversationMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [connectorId, setConnectorId] = useState("");
  const [busy, setBusy] = useState(false);
  const [historyQuery, setHistoryQuery] = useState("");
  const [inspectId, setInspectId] = useState("");
  const [tab, setTab] = useState<InspectorTab>("result");
  const [panels, setPanels] = useState({ left: true, right: true });
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [feedback, setFeedback] = useState<Record<string, "positive" | "negative">>({});
  const [toolResults, setToolResults] = useState<Record<string, { tool: string; result: SQLExecutionResult }>>({});
  // Chart type the user picked per answer (inspector Result tab); unset = the API's choice.
  const [chartTypes, setChartTypes] = useState<Record<string, ChartType>>({});
  const [showJump, setShowJump] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [stage, setStage] = useState<AnswerStage | null>(null);
  const activeIdRef = useRef("");
  const abortRef = useRef<AbortController | null>(null);
  const streamSupportRef = useRef<boolean | null>(null);
  const preserveScrollRef = useRef<{ height: number; top: number } | null>(null);
  const skipAutoScrollRef = useRef(false);
  const pendingInspectRef = useRef(routeMessageId || "");
  const pushRouteRef = useRef(false);
  const unmountedRef = useRef(false);
  const prevRouteRef = useRef(routeConversationId || "");
  const prevRouteMessageRef = useRef(routeMessageId || "");
  const seededRef = useRef(false);
  const listRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const canEdit = ["admin", "engineer", "analyst"].includes(currentUser.role);
  const serverMessages = useMemo(() => (messagesQuery.data ? [...messagesQuery.data.pages].reverse().flatMap((page) => page.items) : NO_MESSAGES), [messagesQuery.data]);
  const messages = useMemo(() => {
    const local = localMessages.filter((item) => item.conversation_id === selectedId);
    return local.length ? [...serverMessages, ...local] : serverMessages;
  }, [serverMessages, localMessages, selectedId]);
  const loadingMessages = !!selectedId && messagesQuery.isPending;
  const hasMore = !!messagesQuery.hasNextPage;
  const loadingEarlier = messagesQuery.isFetchingNextPage;
  const messagesKey = useCallback((conversationId: string) => projectKey(projectId, ...scopes.messages(conversationId)), [projectId]);

  const localConnector = connectors.find((connector) => connector.connector_type === "local_files");
  const externalConnectors = connectors.filter((connector) => connector.connector_type !== "local_files");
  const selectedConnector = connectors.find((connector) => connector.id === connectorId);
  const resolvedConnector = selectedConnector || localConnector || null;
  const selectedConversation = conversations.find((item) => item.id === selectedId);
  const ownsSelected = !(currentUser.role === "analyst" && selectedConversation?.created_by !== currentUser.id);
  const canManageSelected = canEdit && !!selectedId && ownsSelected;
  const results = useMemo(() => messages.filter((message) => message.role === "assistant"), [messages]);
  const inspected = results.find((message) => message.id === inspectId) || results[results.length - 1];
  const inspectedIndex = inspected ? results.indexOf(inspected) : -1;

  useEffect(() => { setPanels(readPanels()); }, []);
  function togglePanel(side: "left" | "right") {
    setPanels((current) => {
      const next = { ...current, [side]: !current[side] };
      try { window.localStorage.setItem(PANEL_STORAGE_KEY, JSON.stringify(next)); } catch { /* storage unavailable */ }
      return next;
    });
  }

  const refreshConversations = useCallback(() => invalidate(scopes.conversations), [invalidate]);

  // A seeded question must start a fresh analysis, not land in the newest thread.
  // A deep-linked id that is not in this project's list falls back to the newest thread.
  const conversationList = conversationsQuery.data;
  useEffect(() => {
    if (!conversationList || seededRef.current) return;
    setSelectedId((current) => (current && conversationList.some((item) => item.id === current) ? current : conversationList[0]?.id || ""));
  }, [conversationList]);

  useEffect(() => {
    activeIdRef.current = selectedId;
    setInspectId("");
  }, [selectedId]);

  // A deep-linked `?m=` is applied once the thread's messages are available.
  const messagePages = messagesQuery.data;
  const messagesFetching = messagesQuery.isFetching;
  useEffect(() => {
    const pending = pendingInspectRef.current;
    if (!pending || !messagePages) return;
    if (messagePages.pages.some((page) => page.items.some((item) => item.id === pending && item.role === "assistant"))) {
      pendingInspectRef.current = "";
      setInspectId(pending);
    } else if (!messagesFetching) {
      pendingInspectRef.current = "";
    }
  }, [messagePages, messagesFetching]);

  useEffect(() => {
    if (!seed) return;
    seededRef.current = true;
    setQuestion(seed.question);
    setConnectorId(seed.connector_id);
    setSelectedId("");
    composerRef.current?.focus();
    // Consumed: clear it in the shell so returning to Analysis does not re-seed.
    onSeedConsumed?.();
  }, [seed, onSeedConsumed]);

  // URL -> state: back/forward (or a new deep link) switches thread / inspected answer.
  useEffect(() => {
    const next = routeConversationId || "";
    if (prevRouteRef.current === next) return;
    prevRouteRef.current = next;
    if (next === activeIdRef.current) return;
    seededRef.current = !next;
    pendingInspectRef.current = routeMessageId || "";
    setSelectedId(next);
  }, [routeConversationId, routeMessageId]);
  useEffect(() => {
    const next = routeMessageId || "";
    if (prevRouteMessageRef.current === next) return;
    prevRouteMessageRef.current = next;
    if (next && messages.some((item) => item.id === next && item.role === "assistant")) setInspectId(next);
  }, [routeMessageId, messages]);

  // State -> URL. Only explicit thread changes add a history entry; auto-selection replaces.
  // Only an answer of the open thread belongs in `?m=`: right after a thread switch
  // inspectId still holds the previous thread's answer until the reset effect runs.
  const routeInspectId = inspectId && results.some((item) => item.id === inspectId) ? inspectId : "";
  useEffect(() => {
    if (!onRouteChange) return;
    const push = pushRouteRef.current;
    pushRouteRef.current = false;
    prevRouteRef.current = selectedId;
    prevRouteMessageRef.current = routeInspectId;
    onRouteChange(selectedId, routeInspectId, push);
  }, [selectedId, routeInspectId, onRouteChange]);

  // Abort an in-flight answer if the view unmounts (navigation, project switch).
  useEffect(() => { unmountedRef.current = false; return () => { unmountedRef.current = true; abortRef.current?.abort(); }; }, []);

  const scrollToBottom = useCallback(() => {
    const node = listRef.current;
    if (node) node.scrollTop = node.scrollHeight;
    setShowJump(false);
  }, []);
  useLayoutEffect(() => {
    const node = listRef.current;
    const previous = preserveScrollRef.current;
    if (!node || !previous) return;
    preserveScrollRef.current = null;
    skipAutoScrollRef.current = true;
    node.scrollTop = node.scrollHeight - previous.height + previous.top;
  }, [messages]);
  useEffect(() => {
    const node = listRef.current;
    if (!node) return;
    if (skipAutoScrollRef.current) { skipAutoScrollRef.current = false; return; }
    const nearBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 160;
    if (nearBottom || busy) scrollToBottom(); else setShowJump(true);
  }, [messages, busy, scrollToBottom]);

  function newAnalysis() {
    // Created lazily on first send, so "+" no longer leaves empty threads behind.
    seededRef.current = true;
    pushRouteRef.current = true;
    setSelectedId("");
    setQuestion("");
    composerRef.current?.focus();
  }

  async function loadEarlier() {
    if (!selectedId || !hasMore || loadingEarlier) return;
    const node = listRef.current;
    // Keep the reader's position when older messages are prepended above.
    preserveScrollRef.current = { height: node?.scrollHeight ?? 0, top: node?.scrollTop ?? 0 };
    const result = await messagesQuery.fetchNextPage();
    if (result.isError) {
      preserveScrollRef.current = null;
      notify(result.error instanceof Error ? result.error.message : "Earlier messages could not be loaded", "error");
    }
  }

  // Streams stage events when the API supports it; falls back to the blocking endpoint on 404/405.
  async function requestAnswer(conversationId: string, body: string, signal: AbortSignal): Promise<ConversationMessage> {
    if (streamSupportRef.current !== false) {
      const outcome: { message?: ConversationMessage; error?: ApiError } = {};
      try {
        await apiStream(`/conversations/${conversationId}/messages/stream`, { method: "POST", body, signal }, (event, data) => {
          const payload = (data && typeof data === "object" ? data : {}) as { stage?: string; label?: string; message?: ConversationMessage; detail?: string; status?: number };
          if (event === "stage" && payload.stage) {
            if (activeIdRef.current === conversationId) setStage({ stage: payload.stage, label: payload.label || payload.stage.replaceAll("_", " ") });
          } else if (event === "done" && payload.message) {
            outcome.message = payload.message;
          } else if (event === "error") {
            outcome.error = new ApiError(payload.detail || "Analysis failed", payload.status || 500);
          }
        });
      } catch (reason) {
        if (!(reason instanceof ApiError) || (reason.status !== 404 && reason.status !== 405)) throw reason;
        const fallback = await api<ConversationMessage>(`/conversations/${conversationId}/messages`, { method: "POST", body, signal });
        streamSupportRef.current = false;
        return fallback;
      }
      streamSupportRef.current = true;
      if (outcome.error) throw outcome.error;
      if (!outcome.message) throw new ApiError("The answer stream ended before a result arrived. Retry the question.", 0);
      return outcome.message;
    }
    return api<ConversationMessage>(`/conversations/${conversationId}/messages`, { method: "POST", body, signal });
  }

  function stopAnswer() {
    abortRef.current?.abort();
  }

  async function ask(text: string) {
    if (!canEdit) { notify("Your role can view analyses but cannot send questions", "error"); return; }
    const content = text.trim();
    if (!content || busy) return;
    setBusy(true);
    setStage(null);
    setLocalMessages((items) => items.filter((item) => !item.failed));
    const pendingId = `pending-${Date.now()}`;
    let conversationId = selectedId;
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      if (!conversationId) {
        const created = await api<Conversation>("/conversations", { method: "POST", body: JSON.stringify({ title: "New analysis" }) });
        conversationId = created.id;
        // A brand-new thread has no messages: seed the cache instead of fetching.
        queryClient.setQueryData<MessagePages>(messagesKey(created.id), { pages: [{ items: [], hasMore: false }], pageParams: [""] });
        queryClient.setQueryData<Conversation[]>(projectKey(projectId, ...scopes.conversations), (items) => [created, ...(items || [])]);
        pushRouteRef.current = true;
        setSelectedId(created.id);
        activeIdRef.current = created.id;
      }
      const userTurn: ConversationMessage = { id: pendingId, conversation_id: conversationId, role: "user", content, structured: {}, created_at: new Date().toISOString() };
      setLocalMessages((items) => [...items, userTurn]);
      setQuestion("");
      const dialect = resolvedConnector ? connectorDialectForType(resolvedConnector.connector_type) : "postgres";
      const response = await requestAnswer(conversationId, JSON.stringify({ content, dialect, connector_id: resolvedConnector?.id || null }), controller.signal);
      // Move the confirmed turn and its answer into the thread's cached newest page;
      // the thread is marked stale so the next visit refetches the server copy.
      const key = messagesKey(conversationId);
      queryClient.setQueryData<MessagePages>(key, (current) => {
        if (!current?.pages.length) return { pages: [{ items: [userTurn, response], hasMore: false }], pageParams: [""] };
        const [newest, ...older] = current.pages;
        return { ...current, pages: [{ ...newest, items: [...newest.items, userTurn, response] }, ...older] };
      });
      void queryClient.invalidateQueries({ queryKey: key, refetchType: "none" });
      setLocalMessages((items) => items.filter((item) => item.id !== pendingId));
      if (activeIdRef.current === conversationId) {
        setInspectId(response.id);
        setTab(response.structured.execution?.error ? "sql" : "result");
      }
      seededRef.current = false;
      await refreshConversations();
    } catch (reason) {
      const stopped = controller.signal.aborted;
      setLocalMessages((items) => items.map((item) => item.id === pendingId ? { ...item, failed: true, stopped } : item));
      if (activeIdRef.current === conversationId) setQuestion(content);
      if (stopped && unmountedRef.current) {
        // Navigated away mid-answer: nothing to report.
      } else if (stopped) {
        notify("Stopped. The question was not answered; use Retry to ask it again.");
        void refreshConversations().catch(() => undefined);
      } else {
        notify(reason instanceof Error ? reason.message : "Analysis failed", "error");
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setBusy(false);
      setStage(null);
    }
  }

  function submit(event: FormEvent) { event.preventDefault(); void ask(question); }
  function onComposerKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void ask(question); }
    if (event.key === "ArrowUp" && !question) {
      const last = [...messages].reverse().find((item) => item.role === "user");
      if (last) { event.preventDefault(); setQuestion(last.content); }
    }
  }

  async function confirmDialog(event: FormEvent) {
    event.preventDefault();
    if (!dialog) return;
    try {
      if (dialog.kind === "rename") {
        await api(`/conversations/${selectedId}`, { method: "PUT", body: JSON.stringify({ title: dialog.name.trim() }) });
        await refreshConversations();
        notify("Analysis renamed");
      } else if (dialog.kind === "delete") {
        const deletedId = selectedId;
        await api(`/conversations/${deletedId}`, { method: "DELETE" });
        setSelectedId("");
        setLocalMessages((items) => items.filter((item) => item.conversation_id !== deletedId));
        queryClient.removeQueries({ queryKey: messagesKey(deletedId) });
        seededRef.current = false;
        await refreshConversations();
        notify("Conversation deleted");
      } else if (dialog.kind === "report") {
        await api(`/conversations/${selectedId}/report`, { method: "POST", body: JSON.stringify({ name: dialog.name }) });
        notify("Conversation saved as a versioned report");
      } else if (dialog.kind === "tool") {
        const slug = ("tool_" + dialog.name.toLowerCase().replace(/[^a-z0-9_.-]+/g, "_")).slice(0, 120);
        await api("/query-tools", { method: "POST", body: JSON.stringify({
          name: slug,
          description: `Published from a conversation analysis: ${dialog.name}`,
          purpose: dialog.purpose,
          data_source: dialog.source,
          line_of_business: "general",
          owner: currentUser.email || currentUser.name,
          sql_template: dialog.sql,
          parameter_schema: { type: "object", properties: {}, additionalProperties: false },
          requires_approval: true,
        }) });
        await invalidate(scopes.approvals);
        notify("Tool publication requested and sent to Approvals");
      } else if (dialog.kind === "notebook") {
        await api("/notebooks", { method: "POST", body: JSON.stringify({ name: dialog.name, cells: [{ id: `cell-${Date.now()}`, type: "sql", source: dialog.sql }] }) });
        notify("Notebook created");
      } else if (dialog.kind === "feedback") {
        await submitFeedback(dialog.messageId, "negative", dialog.comment);
        notify("Thanks, your feedback was recorded");
      }
      setDialog(null);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Action failed", "error");
    }
  }

  async function submitFeedback(messageId: string, rating: "positive" | "negative", comment = "") {
    const note = comment.trim();
    await api("/feedback", { method: "POST", body: JSON.stringify({ context_type: "sql", context_id: messageId, rating: rating === "positive" ? "helpful" : "not_helpful", ...(note ? { comment: note } : {}) }) });
    setFeedback((current) => ({ ...current, [messageId]: rating }));
  }

  // Thumbs-up is sent at once; thumbs-down first asks for an optional comment.
  async function sendFeedback(messageId: string, rating: "positive" | "negative") {
    if (feedback[messageId] === rating) return;
    if (rating === "negative") { setDialog({ kind: "feedback", messageId, comment: "" }); return; }
    try { await submitFeedback(messageId, rating); } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not save feedback", "error"); }
  }

  async function runSuggestion(message: ConversationMessage, action: RouteCandidate) {
    try {
      if (action.route === "agent_run") {
        const run = await api<{ job_id: string; status: string; approval_id?: string; plan_hash?: string; plan_bound?: boolean }>("/agents/runs", { method: "POST", body: JSON.stringify({ objective: message.structured.question || "", autonomy_level: 2, ...(action.target?.id ? { agent_id: action.target.id } : {}) }) });
        void invalidate(scopes.approvals, scopes.jobs);
        notify(run.approval_id ? (run.plan_bound && run.plan_hash ? `Plan ${run.plan_hash.slice(0, 12)} is waiting in Approvals` : "Agent run is waiting in Approvals") : `Agent run ${run.status.toLowerCase()}`);
      } else if (action.route === "query_tool" && action.target) {
        try {
          const result = await api<SQLExecutionResult>(`/query-tools/${action.target.id}/test`, { method: "POST", body: JSON.stringify({ parameters: {} }) });
          setToolResults((current) => ({ ...current, [message.id]: { tool: action.target!.name, result } }));
          setInspectId(message.id); setTab("result");
          notify(`${action.target.name} returned ${result.row_count} rows`);
        } catch (reason) {
          // Running a query tool needs the query-runner permission (viewers are read-only).
          if (reason instanceof ApiError && reason.status === 403) { notify(`You do not have permission to run ${action.target.name}. Ask a project maintainer for query access.`, "error"); return; }
          throw reason;
        }
      }
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Action failed", "error"); }
  }

  async function copySql(sql: string) {
    try { await navigator.clipboard.writeText(sql); notify("SQL copied"); } catch { notify("Clipboard unavailable", "error"); }
  }

  function downloadCsv(result: SQLExecutionResult, name: string) {
    const url = URL.createObjectURL(new Blob([toCsv(result)], { type: "text/csv" }));
    const link = document.createElement("a");
    link.href = url; link.download = `${name.replace(/[^a-z0-9_-]+/gi, "_").slice(0, 60) || "result"}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const filtered = useMemo(() => {
    const needle = historyQuery.trim().toLowerCase();
    const matches = needle ? conversations.filter((item) => [item.title, item.summary, item.last_message].some((text) => text?.toLowerCase().includes(needle))) : conversations;
    const groups: { label: string; items: Conversation[] }[] = [];
    for (const item of matches) {
      const label = historyGroup(item.updated_at);
      const group = groups.find((entry) => entry.label === label);
      if (group) group.items.push(item); else groups.push({ label, items: [item] });
    }
    return groups;
  }, [conversations, historyQuery]);

  const latestAssistantId = results[results.length - 1]?.id;
  const layoutClass = `analysis-layout${panels.left ? "" : " left-collapsed"}${panels.right ? "" : " right-collapsed"}`;

  return (
    <div className={layoutClass}>
      {panels.left ? (
        <aside className="surface conversation-list" aria-label="Analysis history">
          <div className="panel-header">
            <div><span className="eyebrow">HISTORY</span><h3>Analyses</h3></div>
            <span className="row-actions">
              <button className="icon-button" title={canEdit ? "New analysis" : "Viewer role is read-only"} aria-label="New analysis" disabled={!canEdit} onClick={newAnalysis}><Plus size={17} /></button>
              <button className="icon-button" title="Collapse history" aria-label="Collapse history" onClick={() => togglePanel("left")}><PanelLeftClose size={17} /></button>
            </span>
          </div>
          <label className="history-search"><Search size={14} /><input value={historyQuery} onChange={(event) => setHistoryQuery(event.target.value)} placeholder="Search analyses" aria-label="Search analyses" /></label>
          <div className="conversation-items">
            {filtered.length ? filtered.map((group) => (
              <div key={group.label} className="history-group">
                <span className="history-group-label">{group.label}</span>
                {group.items.map((item) => (
                  <button key={item.id} className={selectedId === item.id ? "selected" : ""} aria-current={selectedId === item.id ? "true" : undefined} onClick={() => { if (item.id === selectedId) return; seededRef.current = false; pushRouteRef.current = true; setSelectedId(item.id); }}>
                    <MessageSquare size={15} />
                    <span>
                      <strong>{item.title}</strong>
                      {item.last_message && <em>{displayText(item.last_message)}</em>}
                      <small>{Math.floor(item.message_count / 2)} question{item.message_count === 2 ? "" : "s"} · {relativeTime(item.updated_at)}</small>
                    </span>
                  </button>
                ))}
              </div>
            )) : <p className="history-empty">{historyQuery ? "No analyses match your search." : "No analyses yet."}</p>}
          </div>
        </aside>
      ) : (
        <button className="panel-rail" onClick={() => togglePanel("left")} aria-label="Show history" title="Show history"><PanelLeftOpen size={17} /></button>
      )}

      <section className="surface conversation-thread" aria-label="Conversation">
        <div className="panel-header">
          <div><span className="eyebrow">GROUNDED ANALYSIS</span><h3>{selectedConversation?.title || "New analysis"}</h3></div>
          <span className="row-actions">
            <button className="icon-button" title={canManageSelected ? "Rename analysis" : "Insufficient permission"} aria-label="Rename analysis" disabled={!canManageSelected} onClick={() => setDialog({ kind: "rename", name: selectedConversation?.title || "" })}><Edit2 size={16} /></button>
            <button className="icon-button" title="Save as report" aria-label="Save as report" disabled={!messages.length || !canEdit} onClick={() => setDialog({ kind: "report", name: selectedConversation?.title || "Analysis report" })}><Archive size={16} /></button>
            <button className="icon-button danger" title={canManageSelected ? "Delete conversation" : "Insufficient permission"} aria-label="Delete conversation" disabled={!canManageSelected} onClick={() => setDialog({ kind: "delete" })}><XCircle size={16} /></button>
          </span>
        </div>

        <div className="message-list" ref={listRef} onScroll={(event) => { const node = event.currentTarget; if (node.scrollHeight - node.scrollTop - node.clientHeight < 40) setShowJump(false); }} aria-live="polite">
          {hasMore && !!messages.length && <div className="load-earlier"><button type="button" className="secondary-button compact" onClick={() => void loadEarlier()} disabled={loadingEarlier}>{loadingEarlier ? <RefreshCw size={13} className="spin" /> : <ArrowUp size={13} />}Load earlier messages</button></div>}
          {loadingMessages && !messages.length ? <div className="message assistant"><span className="message-avatar"><Bot size={16} /></span><div><p><RefreshCw size={15} className="spin" /> Loading conversation…</p></div></div> : null}
          {!loadingMessages && !messages.length && !busy && (
            <EmptyState icon={<MessageSquare size={24} />} title="Start an analysis" body="Ask a question about your catalogued data. Follow-ups keep the context of this conversation, and every answer shows the SQL, sources and routing decision behind it." />
          )}
          {messages.map((message) => {
            if (message.role === "user") {
              return (
                <div className={`message user${message.failed ? " failed" : ""}`} key={message.id}>
                  <span className="message-avatar">You</span>
                  <div>
                    <p className="message-text">{message.content}</p>
                    {message.failed && <div className="message-failed"><AlertCircle size={13} /> {message.stopped ? "Stopped, not answered" : "Not answered"} <button className="link-button" onClick={() => void ask(message.content)} disabled={busy}><RotateCcw size={12} /> Retry</button></div>}
                  </div>
                </div>
              );
            }
            const s = message.structured;
            const isInspected = inspected?.id === message.id;
            const execution = s.execution;
            const text = displayText(message.content);
            const long = text.length > CLAMP_CHARS || text.split("\n").length > 8;
            const open = !!expanded[message.id];
            return (
              <div className={`message assistant${isInspected ? " inspected" : ""}`} key={message.id}>
                <span className="message-avatar"><Bot size={16} /></span>
                <div>
                  <p className={`message-text${long && !open ? " clamped" : ""}`}>{text}</p>
                  {long && <button type="button" className="link-button show-more" aria-expanded={open} onClick={() => setExpanded((current) => ({ ...current, [message.id]: !open }))}>{open ? "Show less" : "Show more"}</button>}
                  {s.sql && (
                    <button type="button" className="result-card" onClick={() => { setInspectId(message.id); if (!panels.right) togglePanel("right"); }} aria-pressed={isInspected} aria-label="Inspect this result">
                      <StatusPill value={execution?.error ? "failed" : s.validation?.status || "validated"} />
                      <span>{s.source?.name || "DataPilot workspace"}</span>
                      {execution && !execution.error && <span><b>{execution.row_count}</b> row{execution.row_count === 1 ? "" : "s"}{execution.truncated ? "+" : ""}</span>}
                      {s.cache?.hit && <span className="chip">cached</span>}
                      {s.route && <RouteBadge route={s.route} />}
                      <ChevronRight size={14} className="result-card-arrow" />
                    </button>
                  )}
                  {s.route?.suggested_actions?.length ? (
                    <div className="suggested-actions">
                      {s.route.suggested_actions.map((action, index) => {
                        const runnable = action.route === "agent_run" || (action.route === "query_tool" && !action.target?.required_parameters?.length && !action.target?.requires_approval);
                        return (
                          <div className="suggested-action" key={`${action.route}-${index}`}>
                            <span>{ROUTE_ICONS[action.route]}<strong>{action.target?.name || action.label}</strong><small>{action.reasons[0]}</small></span>
                            {runnable && canEdit && <button className="secondary-button compact" onClick={() => void runSuggestion(message, action)}><Play size={12} />{action.route === "agent_run" ? (action.target?.name ? `Start ${action.target.name} agent` : "Start agent run") : "Run tool"}</button>}
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                  <div className="message-toolbar">
                    <time dateTime={message.created_at}>{new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>
                    <button className={`icon-button${feedback[message.id] === "positive" ? " active" : ""}`} onClick={() => void sendFeedback(message.id, "positive")} title="Helpful" aria-label="Helpful" aria-pressed={feedback[message.id] === "positive"}><ThumbsUp size={14} /></button>
                    <button className={`icon-button${feedback[message.id] === "negative" ? " active" : ""}`} onClick={() => void sendFeedback(message.id, "negative")} title="Not helpful" aria-label="Not helpful" aria-pressed={feedback[message.id] === "negative"}><ThumbsDown size={14} /></button>
                  </div>
                  {message.id === latestAssistantId && !!s.follow_ups?.length && canEdit && (
                    <div className="follow-ups" aria-label="Suggested follow-ups">
                      {s.follow_ups.map((item) => <button key={item} className="follow-up-chip" disabled={busy} onClick={() => void ask(item)}>{item}</button>)}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
          {busy && <ThinkingBubble stage={stage} onStop={stopAnswer} />}
        </div>
        {showJump && <button className="jump-latest" onClick={scrollToBottom}><ArrowDown size={14} /> Latest</button>}

        <form className="analysis-composer" onSubmit={submit}>
          <select value={connectorId} onChange={(event) => setConnectorId(event.target.value)} aria-label="Data source" disabled={!canEdit}>
            <option value="">DataPilot workspace</option>
            {externalConnectors.map((connector) => <option key={connector.id} value={connector.id}>{connector.name} / {connector.database || connector.host || "default"} / {connectorLabels[connector.connector_type] || connector.connector_type}</option>)}
          </select>
          <textarea ref={composerRef} rows={2} value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={onComposerKey} disabled={!canEdit} aria-label="Question" placeholder={canEdit ? "Ask a question or follow up…  (Enter to send, Shift+Enter for a new line)" : "Read-only role: conversations can be viewed but not changed"} />
          {busy
            ? <button type="button" className="send-button stop" onClick={stopAnswer} aria-label="Stop answering" title="Stop answering"><Square size={15} fill="currentColor" /></button>
            : <button className="send-button" disabled={!question.trim() || !canEdit} aria-label="Send question"><Send size={18} /></button>}
        </form>
      </section>

      {panels.right ? (
        <aside className="surface insight-panel" aria-label="Result inspector">
          <div className="panel-header">
            <div><span className="eyebrow">INSPECTOR</span><h3>{inspected ? `Result ${inspectedIndex + 1} of ${results.length}` : "Results"}</h3></div>
            <span className="row-actions">
              <button className="icon-button" aria-label="Previous result" disabled={inspectedIndex <= 0} onClick={() => setInspectId(results[inspectedIndex - 1].id)}><ChevronLeft size={16} /></button>
              <button className="icon-button" aria-label="Next result" disabled={inspectedIndex < 0 || inspectedIndex >= results.length - 1} onClick={() => setInspectId(results[inspectedIndex + 1].id)}><ChevronRight size={16} /></button>
              <button className="icon-button" title="Collapse inspector" aria-label="Collapse inspector" onClick={() => togglePanel("right")}><PanelRightClose size={16} /></button>
            </span>
          </div>
          {inspected ? (
            <Inspector
              message={inspected}
              tab={tab}
              onTab={setTab}
              toolResult={toolResults[inspected.id]}
              chartType={chartTypes[inspected.id]}
              onChartType={(type) => setChartTypes((current) => ({ ...current, [inspected.id]: type }))}
              canEdit={canEdit}
              onCopy={copySql}
              onCsv={downloadCsv}
              onPublish={(sql) => setDialog({ kind: "tool", name: selectedConversation?.title || "Tool API", sql, purpose: inspected.structured.question || selectedConversation?.title || "", source: inspected.structured.source?.name || "DataPilot workspace" })}
              onNotebook={(sql) => setDialog({ kind: "notebook", name: selectedConversation?.title || "Analysis Notebook", sql })}
            />
          ) : <EmptyState icon={<CircleGauge size={24} />} title="No results yet" body="The result table, chart, SQL, grounding sources and routing decision for the selected answer appear here." />}
        </aside>
      ) : (
        <button className="panel-rail" onClick={() => togglePanel("right")} aria-label="Show inspector" title="Show inspector"><PanelRightOpen size={17} /></button>
      )}

      {dialog && (
        <Modal
          title={{ rename: "Rename analysis", delete: "Delete analysis", report: "Save analysis report", tool: "Publish as API tool", notebook: "Eject to notebook", feedback: "What went wrong?" }[dialog.kind]}
          onClose={() => setDialog(null)}
        >
          <form className="modal-form" onSubmit={confirmDialog}>
            {dialog.kind === "delete" ? (
              <p>Delete <strong>{selectedConversation?.title}</strong> and its {selectedConversation?.message_count ?? 0} messages? Saved reports and artifacts are kept.</p>
            ) : dialog.kind === "feedback" ? (
              <label>Comment (optional)
                <textarea autoFocus rows={4} maxLength={5000} value={dialog.comment} onChange={(event) => setDialog({ ...dialog, comment: event.target.value })} placeholder="Wrong table, wrong numbers, misunderstood the question…" />
              </label>
            ) : (
              <label>{dialog.kind === "notebook" ? "Notebook title" : dialog.kind === "tool" ? "Tool name" : dialog.kind === "report" ? "Report name" : "Title"}
                <input autoFocus value={dialog.name} maxLength={200} onChange={(event) => setDialog({ ...dialog, name: event.target.value })} required />
              </label>
            )}
            {dialog.kind === "tool" && <p className="modal-hint">The tool is created with requires-approval on and no parameters; literal values in the SQL stay fixed until you parameterise it in Tools.</p>}
            <div className="modal-actions">
              <button type="button" className="secondary-button" onClick={() => setDialog(null)}>Cancel</button>
              <button className={dialog.kind === "delete" ? "primary-button danger" : "primary-button"}>{dialog.kind === "delete" ? "Delete" : dialog.kind === "tool" ? "Request approval" : dialog.kind === "feedback" ? "Send feedback" : "Save"}</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

function ThinkingBubble({ stage, onStop }: { stage: AnswerStage | null; onStop: () => void }) {
  const current = stage ? ANSWER_STAGES.findIndex((item) => item.key === stage.stage) : -1;
  return (
    <div className="message assistant">
      <span className="message-avatar"><Bot size={16} /></span>
      <div className="thinking-bubble">
        <p className="thinking" role="status"><RefreshCw size={15} className="spin" /> {stage?.label || "Grounding in the catalog, drafting governed SQL and running a preview…"}</p>
        {current >= 0 && (
          <ol className="stage-steps" aria-label={`Step ${current + 1} of ${ANSWER_STAGES.length}`}>
            {ANSWER_STAGES.map((item, index) => <li key={item.key} className={index < current ? "done" : index === current ? "current" : ""} aria-current={index === current ? "step" : undefined}><i />{item.label}</li>)}
          </ol>
        )}
        <button type="button" className="link-button stop-link" onClick={onStop}><Square size={11} fill="currentColor" /> Stop</button>
      </div>
    </div>
  );
}

function Inspector({ message, tab, onTab, toolResult, chartType, onChartType, canEdit, onCopy, onCsv, onPublish, onNotebook }: {
  message: ConversationMessage;
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  toolResult?: { tool: string; result: SQLExecutionResult };
  chartType?: ChartType;
  onChartType: (type: ChartType) => void;
  canEdit: boolean;
  onCopy: (sql: string) => void;
  onCsv: (result: SQLExecutionResult, name: string) => void;
  onPublish: (sql: string) => void;
  onNotebook: (sql: string) => void;
}) {
  const s = message.structured;
  const execution = toolResult?.result || s.execution;
  const chartOptions = useMemo(() => chartAlternatives(s.chart), [s.chart]);
  const shownChart: ChartType | undefined = chartType && chartOptions.includes(chartType) ? chartType : chartOptions[0];
  const tabs: { key: InspectorTab; label: string }[] = [
    { key: "result", label: "Result" },
    { key: "sql", label: "SQL" },
    { key: "context", label: "Context" },
    { key: "decision", label: "Decision" },
  ];
  return (
    <>
      <div className="inspector-tabs" role="tablist">
        {tabs.map((item) => <button key={item.key} role="tab" aria-selected={tab === item.key} className={tab === item.key ? "active" : ""} onClick={() => onTab(item.key)}>{item.label}</button>)}
      </div>
      <div className="inspector-body" role="tabpanel">
        {tab === "result" && (
          <>
            {toolResult && <div className="inspector-note"><Network size={13} /> Showing governed tool <strong>{toolResult.tool}</strong></div>}
            {execution?.error ? (
              <div className="conversation-memory execution-error"><span>Query error</span><p>{execution.error}</p></div>
            ) : execution ? (
              <>
                {!toolResult && (s.chart?.data?.length && shownChart ? (
                  <>
                    <ChartTypeSwitcher options={chartOptions} value={shownChart} onChange={onChartType} reason={s.chart.reason} />
                    {shownChart !== "table" && <AnalysisChart chart={s.chart} type={shownChart} />}
                  </>
                ) : <AnalysisChart chart={s.chart} />)}
                <ResultTable result={execution} />
                <div className="inspector-actions"><button className="secondary-button compact" onClick={() => onCsv(execution, s.question || "result")}><Download size={13} />CSV</button></div>
              </>
            ) : <div className="chart-empty">This source was not executed from DataPilot. Open the SQL tab to run it through the governed connector path.</div>}
          </>
        )}
        {tab === "sql" && (
          <>
            <pre className="inspector-sql">{s.sql || "No SQL generated"}</pre>
            {s.sql && (
              <div className="inspector-actions">
                <button className="secondary-button compact" onClick={() => onCopy(s.sql!)}><Copy size={13} />Copy</button>
                {canEdit && <button className="secondary-button compact" onClick={() => onNotebook(s.sql!)}><FileSpreadsheet size={13} />Notebook</button>}
                {canEdit && <button className="secondary-button compact" onClick={() => onPublish(s.sql!)}><Network size={13} />Publish tool</button>}
              </div>
            )}
            <dl className="fact-grid">
              <div><dt>Dialect</dt><dd>{s.dialect || "-"}</dd></div>
              <div><dt>Model</dt><dd>{s.provider ? `${s.provider.name} / ${s.provider.model}` : "-"}</dd></div>
              <div><dt>Mode</dt><dd>{s.provider?.mode || "-"}</dd></div>
              <div><dt>Latency</dt><dd>{s.provider?.latency_ms != null ? `${s.provider.latency_ms} ms` : "-"}</dd></div>
              <div><dt>Cache</dt><dd>{s.cache?.hit ? "hit" : "miss"}</dd></div>
              <div><dt>Rows</dt><dd>{s.execution?.row_count ?? "-"}</dd></div>
            </dl>
          </>
        )}
        {tab === "context" && (
          <>
            <section className="inspector-section">
              <h4>Execution target</h4>
              <p className="inspector-strong">{s.source ? `${s.source.name} / ${s.source.database || s.source.dialect}` : "DataPilot local workspace / PostgreSQL staging"}</p>
              <small>{s.source ? `${connectorLabels[s.source.connector_type] || s.source.connector_type} · ${s.source.dialect}` : "Local staging"}</small>
            </section>
            <section className="inspector-section">
              <h4>Catalog grounding</h4>
              {s.grounding?.catalog_matches?.length ? s.grounding.catalog_matches.map((item) => (
                <div className="score-row" key={item.relation}><span className="score-label" title={item.relation}>{item.relation}</span><small>{item.match_type}</small><ScoreBar value={item.match_type === "keyword" ? Math.min(1, item.score / 3) : item.score} tone="blue" /></div>
              )) : <p className="inspector-muted">No catalog tables matched this question.</p>}
            </section>
            {!!s.grounding?.semantic_matches?.length && (
              <section className="inspector-section">
                <h4>Semantic metrics</h4>
                {s.grounding.semantic_matches.map((item) => <p key={item.name} className="inspector-line"><strong>{item.name}</strong> <code>{item.formula}</code> <small>@ {item.grain}</small></p>)}
              </section>
            )}
            {!!s.grounding?.join_matches?.length && (
              <section className="inspector-section">
                <h4>Approved joins</h4>
                {s.grounding.join_matches.map((item, index) => <p key={index} className="inspector-line"><code>{item.left_relation}.{item.left_column} {item.join_type.toUpperCase()} {item.right_relation}.{item.right_column}</code></p>)}
              </section>
            )}
            <section className="inspector-section">
              <h4>Validation</h4>
              <ul className="inspector-checks">{(s.validation?.checks || []).map((check) => <li key={check}><ShieldCheck size={12} />{check}</li>)}</ul>
            </section>
            <LearningSection learning={s.learning} />
            <section className="inspector-section">
              <h4>CONVERSATION CONTEXT</h4>
              <p className="inspector-muted">{s.memory?.prior_messages_used ? `${s.memory.prior_messages_used} earlier message(s) used as context.` : "First question in this thread."}</p>
              {s.memory?.summary && <p className="inspector-summary">{s.memory.summary}</p>}
            </section>
          </>
        )}
        {tab === "decision" && (
          <>
            {s.route ? <DecisionPanel route={s.route} /> : <p className="inspector-muted inspector-pad">This answer predates the decision router.</p>}
            {s.route?.jev && <JevSection jev={s.route.jev} />}
            <EnsembleSection ensemble={s.ensemble} />
          </>
        )}
      </div>
    </>
  );
}

function DecisionPanel({ route }: { route: RouteDecision }) {
  const max = Math.max(...route.candidates.map((item) => item.score), 0.0001);
  return (
    <>
      <section className="inspector-section">
        <h4>Chosen route</h4>
        <p className="inspector-strong">{ROUTE_ICONS[route.route]} {route.label}{route.target?.name ? `: ${route.target.name}` : ""}</p>
        <div className="score-row"><span className="score-label">Confidence</span><small>{Math.round(route.confidence * 100)}%</small><ScoreBar value={route.confidence} /></div>
        <dl className="fact-grid">
          <div><dt>Backend</dt><dd title={route.backend}>{backendLabel(route.backend)}</dd></div>
          <div><dt>Policy</dt><dd>{route.policy_version}</dd></div>
          <div><dt>Latency</dt><dd>{route.latency_ms} ms</dd></div>
          <div><dt>Risk</dt><dd className={`risk-${route.risk.level}`}>{route.risk.level}</dd></div>
        </dl>
        {route.backend.startsWith("jev:") && <p className="inspector-muted">Routed by Jev model <code>{route.backend.slice(4)}</code>.</p>}
        {route.risk.escalated_by && <p className="inspector-muted escalated-note"><ShieldCheck size={12} /> Risk escalated by {route.risk.escalated_by === "jev" ? "Jev" : route.risk.escalated_by}.</p>}
        {!!route.risk.triggers.length && <p className="inspector-muted">Approval triggers: {route.risk.triggers.join(", ")}</p>}
      </section>
      <section className="inspector-section">
        <h4>Candidates</h4>
        {route.candidates.map((item, index) => (
          <div className="candidate" key={`${item.route}-${item.target?.id || index}`}>
            <div className="score-row"><span className="score-label">{ROUTE_ICONS[item.route]} {item.target?.name || item.route.replace("_", " ")}</span><small>{item.score.toFixed(2)}</small><ScoreBar value={item.score / max} tone={index === 0 ? "brand" : "muted"} /></div>
            <small className="candidate-reasons">{item.reasons.join(" · ")}</small>
          </div>
        ))}
      </section>
    </>
  );
}

const ROUTE_OPTION_LABELS: Record<string, string> = { sql_analysis: "SQL analysis", query_tool: "Query tool", agent_run: "Agent run", clarify: "Clarify" };

/** What the Jev decision model (typed choices with probabilities, not text) said about this question. */
function JevSection({ jev }: { jev: JevDecision }) {
  const options = Object.entries(jev.probabilities || {}).filter(([, value]) => Number.isFinite(value)).sort((a, b) => b[1] - a[1]);
  return (
    <section className="inspector-section jev-section">
      <h4>Jev decision</h4>
      <p className="inspector-line">Decision model <code>{jev.model || "typesafe/jev"}</code></p>
      {options.length ? options.map(([option, probability], index) => (
        <div className="score-row" key={option}>
          <span className="score-label" title={option}>{ROUTE_ICONS[option]} {ROUTE_OPTION_LABELS[option] || option.replaceAll("_", " ")}</span>
          <small>{formatProbability(probability)}</small>
          <ScoreBar value={probability} tone={index === 0 ? "brand" : "muted"} label={`${option} probability`} />
        </div>
      )) : <p className="inspector-muted">No option probabilities were returned.</p>}
      {jev.consequential != null && (
        <>
          <div className="score-row jev-consequential">
            <span className="score-label"><ShieldCheck size={13} /> Consequential action</span>
            <small>{formatProbability(jev.consequential)}</small>
            <ScoreBar value={jev.consequential} tone="blue" label="Consequential action probability" />
          </div>
          <p className="inspector-muted">Jev can only escalate risk: a high probability sends the action to approval; a low one never removes an approval the rules require.</p>
        </>
      )}
      <dl className="fact-grid">
        <div><dt>Latency</dt><dd>{jev.latency_ms != null ? `${Math.round(jev.latency_ms)} ms` : "-"}</dd></div>
        <div><dt>Cost</dt><dd title={jev.cost_usd != null ? `${jev.cost_usd} USD` : undefined}>{formatUsd(jev.cost_usd)}</dd></div>
      </dl>
    </section>
  );
}

/** "jev:typesafe/jev-1.13-…" → "Jev (typesafe/jev-1.13-…)"; other backends unchanged. */
function backendLabel(backend: string) {
  return backend.startsWith("jev:") ? `Jev (${backend.slice(4)})` : backend;
}

const ENSEMBLE_STRATEGY_LABELS: Record<string, string> = {
  result_majority: "Majority of identical results",
  cascade_agreed: "Two models agreed (third not needed)",
  sql_majority: "Majority of equivalent SQL",
  jev_tie_break: "No majority: Jev picked",
  single: "Only one candidate ran successfully",
};

/** Examples, reused verified query and prompt version the learning loop contributed to this answer. */
function LearningSection({ learning }: { learning?: AnswerLearning }) {
  if (!learning) return null;
  const examples = learning.verified_examples || [];
  const reused = learning.reused_verified_query;
  return (
    <section className="inspector-section">
      <h4>Learning</h4>
      {reused ? (
        <p className="inspector-line"><ShieldCheck size={12} /> Reused verified query <strong>{reused.question}</strong> <small>#{reused.id.slice(0, 8)}</small></p>
      ) : <p className="inspector-muted">No verified query was reused verbatim.</p>}
      {examples.length ? (
        <>
          <small>{examples.length} verified example{examples.length === 1 ? "" : "s"} used as few-shot context</small>
          <ul className="inspector-examples">{examples.map((item) => <li key={item.id} title={item.id}>{item.question}</li>)}</ul>
        </>
      ) : <p className="inspector-muted">No verified examples were used.</p>}
      <dl className="fact-grid">
        <div><dt>Prompt version</dt><dd>{learning.prompt_version != null ? `v${learning.prompt_version}` : "Default"}</dd></div>
      </dl>
    </section>
  );
}

/** Multi-model SQL candidates and how the answer was chosen. */
function EnsembleSection({ ensemble }: { ensemble?: AnswerEnsemble }) {
  if (!ensemble) return null;
  const candidates = ensemble.candidates || [];
  const tieBreak = ensemble.tie_break;
  const tieOptions = Object.entries(tieBreak?.probabilities || {}).filter(([, value]) => Number.isFinite(value)).sort((a, b) => b[1] - a[1]);
  const chosenProbability = tieBreak?.chosen != null ? tieBreak.probabilities?.[tieBreak.chosen] : undefined;
  return (
    <section className="inspector-section">
      <h4>Ensemble</h4>
      <dl className="fact-grid">
        <div><dt>Agreement</dt><dd>{ensemble.agreement || "-"}</dd></div>
        <div><dt>Strategy</dt><dd title={ensemble.strategy}>{ensemble.strategy ? ENSEMBLE_STRATEGY_LABELS[ensemble.strategy] || ensemble.strategy : "-"}</dd></div>
      </dl>
      {ensemble.not_needed?.length ? <p className="inspector-muted">Not called (first two models agreed): {ensemble.not_needed.join(", ")}</p> : null}
      {ensemble.escalated ? <p className="inspector-muted">The first two candidates disagreed or failed, so the third model was asked.</p> : null}
      {tieBreak && (
        <div className="tie-break">
          <p className="inspector-line"><Sparkles size={12} /> No majority — {tieBreak.by === "jev" || !tieBreak.by ? "Jev" : tieBreak.by} picked <strong>{tieBreak.chosen || "-"}</strong>{chosenProbability != null ? ` (${formatProbability(chosenProbability)})` : ""}{tieBreak.model && <small> · <code>{tieBreak.model}</code></small>}</p>
          {tieOptions.map(([model, probability]) => (
            <div className="score-row" key={model}><span className="score-label" title={model}>{model}</span><small>{formatProbability(probability)}</small><ScoreBar value={probability} tone={model === tieBreak.chosen ? "brand" : "muted"} label={`${model} probability`} /></div>
          ))}
        </div>
      )}
      {candidates.length ? (
        <table className="ensemble-table">
          <thead><tr><th scope="col">Model</th><th scope="col">Result</th><th scope="col">Rows</th><th scope="col">Fingerprint</th></tr></thead>
          <tbody>
            {candidates.map((item, index) => (
              <tr key={`${item.model}-${index}`} className={item.chosen ? "chosen" : undefined} aria-current={item.chosen ? "true" : undefined}>
                <td title={item.model}>{item.chosen && <span className="chosen-mark" aria-label="chosen">✓</span>}{item.model}</td>
                <td>{item.ok ? <span className="ensemble-ok">ok</span> : <span className="ensemble-error" title={item.error || undefined}>failed</span>}</td>
                <td>{item.row_count ?? "-"}</td>
                <td><code title={item.fingerprint || undefined}>{item.fingerprint ? item.fingerprint.slice(0, 10) : "-"}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="inspector-muted">No candidates were recorded.</p>}
      {candidates.filter((item) => !item.ok && item.error).map((item, index) => <p key={index} className="inspector-muted ensemble-error-line"><strong>{item.model}:</strong> {item.error}</p>)}
    </section>
  );
}
