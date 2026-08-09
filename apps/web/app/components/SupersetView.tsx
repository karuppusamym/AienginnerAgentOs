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


export function SupersetView({ isAdmin, projectName }: { isAdmin: boolean; projectName: string }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const dashboardRef = useRef<EmbeddedDashboard | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [openingEditor, setOpeningEditor] = useState(false);
  const [dashboardLabel, setDashboardLabel] = useState("Project analytics");
  const [datasetRelation, setDatasetRelation] = useState("");
  const [accessMode, setAccessMode] = useState("dashboard scope");
  const [chartCount, setChartCount] = useState<number | null>(null);
  const [mappedAt, setMappedAt] = useState("");
  const [attempt, setAttempt] = useState(0);

  async function openEditor() {
    const editorWindow = window.open("about:blank", "datapilot-superset-editor");
    setOpeningEditor(true);
    try {
      const session = await api<{ url: string }>("/analytics/editor-session", { method: "POST" });
      if (editorWindow) {
        editorWindow.location.replace(session.url);
      } else {
        window.location.assign(session.url);
      }
    } catch (reason) {
      editorWindow?.close();
      setError(reason instanceof Error ? reason.message : "Could not open the analytics editor");
      setState("error");
    } finally {
      setOpeningEditor(false);
    }
  }

  useEffect(() => {
    let active = true;
    async function mount() {
      if (!mountRef.current) return;
      try {
        const config = await api<{ embedded_id: string; superset_domain: string; dashboard_title?: string; dataset_relation?: string; access_mode?: string; chart_count?: number; mapped_at?: string }>("/analytics/config");
        const embedded = await embedDashboard({
          id: config.embedded_id,
          supersetDomain: config.superset_domain,
          mountPoint: mountRef.current,
          fetchGuestToken: async () => {
            const result = await api<{ token: string }>("/analytics/guest-token", { method: "POST" });
            return result.token;
          },
          dashboardUiConfig: {
            hideTitle: false,
            hideTab: true,
            hideChartControls: false,
            filters: { visible: true, expanded: false },
            urlParams: { standalone: 2 },
          },
          iframeTitle: "DataPilot governed analytics",
          referrerPolicy: "strict-origin-when-cross-origin",
        });
        if (!active) {
          embedded.unmount();
          return;
        }
        dashboardRef.current = embedded;
        setDashboardLabel(config.dashboard_title || "Project analytics");
        setDatasetRelation(config.dataset_relation || "");
        setAccessMode((config.access_mode || "dashboard_scope").replaceAll("_", " "));
        setChartCount(typeof config.chart_count === "number" ? config.chart_count : null);
        setMappedAt(config.mapped_at || "");
        setState("ready");
      } catch (reason) {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "Embedded analytics could not be loaded");
        setState("error");
      }
    }
    mount();
    return () => {
      active = false;
      dashboardRef.current?.unmount();
      dashboardRef.current = null;
    };
  }, [attempt]);

  return (
    <div className="view-stack"><div className="view-header"><div><h2>Governed analytics</h2><p>Explore the current project's mapped DataPilot dataset through embedded Apache Superset without another login.{mappedAt ? ` Last synced ${new Date(mappedAt).toLocaleString()}.` : ""}</p></div><div className="analytics-header-actions"><StatusPill value={state === "ready" ? "connected" : state} />{isAdmin && <button className="secondary-button" onClick={openEditor} disabled={openingEditor}>{openingEditor ? <RefreshCw size={17} className="spin" /> : <Settings size={17} />}{openingEditor ? "Opening" : "Open editor"}</button>}</div></div>
      <section className="surface analytics-embed-shell">
        {state === "loading" && <div className="analytics-overlay"><RefreshCw size={20} className="spin" /><strong>Connecting analytics</strong></div>}
        {state === "error" && <div className="analytics-overlay error"><AlertCircle size={22} /><strong>Analytics unavailable</strong><span>{error}</span><button className="secondary-button" onClick={() => { setState("loading"); setError(""); setAttempt((current) => current + 1); }}><RefreshCw size={16} />Retry</button></div>}
        <div ref={mountRef} className="analytics-mount" />
      </section>
      <div className="three-column compact-cards"><ControlItem icon={<Database size={17} />} label="Project" value={projectName} status="current" /><ControlItem icon={<LayoutDashboard size={17} />} label="Dashboard" value={chartCount ? `${dashboardLabel} / ${chartCount} charts` : dashboardLabel} status={state === "ready" ? "ready" : state} /><ControlItem icon={<ShieldCheck size={17} />} label="Dataset" value={datasetRelation || "Waiting for mapping"} status={datasetRelation ? "mapped" : state} /><ControlItem icon={<ShieldCheck size={17} />} label="Access" value={accessMode} status={state === "ready" ? "enforced" : state} /></div>
    </div>
  );
}
