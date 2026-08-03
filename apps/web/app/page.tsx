"use client";

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
import { api, ApiError, login, logout, SessionUser } from "./lib/api";

type NavKey =
  | "workspace"
  | "conversations"
  | "datasets"
  | "files"
  | "sql"
  | "notebooks"
  | "pipelines"
  | "jobs"
  | "artifacts"
  | "quality"
  | "superset"
  | "approvals"
  | "tools"
  | "agents"
  | "semantic"
  | "evaluations"
  | "admin";

type Overview = {
  counts: { data_assets: number; connectors: number; jobs: number; pending_approvals: number };
  system: { model: string; vector_store: string; workflow_engine: string; autonomy_level: number };
};

type Recommendation = { question: string; basis: string; relation: string };

type SecurityCategoryKey = "prompt_injection" | "pii_exposure" | "toxic_content";

type SecurityOverview = {
  period: { key: string; label: string; started_at: string; ended_at: string };
  overview: {
    overall_security_score: number;
    posture: string;
    score_delta_pp: number;
    total_security_events: number;
    blocked_requests: number;
    critical_incidents: number;
  };
  event_series: {
    label: string;
    start_at: string;
    end_at: string;
    counts: Record<SecurityCategoryKey, number>;
  }[];
  top_security_risks: {
    key: SecurityCategoryKey;
    category: string;
    count: number;
    share_percent: number;
  }[];
  events_by_category: {
    key: SecurityCategoryKey;
    category: string;
    count: number;
  }[];
  incidents_by_severity: { severity: string; count: number }[];
  recent_incidents: {
    id: string;
    title: string;
    severity: string;
    status: string;
    category: string;
    created_at: string;
  }[];
};

type Dataset = {
  id: string;
  source_name: string;
  schema_name: string;
  table_name: string;
  asset_type: string;
  category: string;
  row_count: number | null;
  columns: { name: string; type: string; nullable: boolean }[];
  tags: string[];
  description: string;
  connector_id?: string | null;
  source?: { id?: string | null; name: string; database: string; connector_type: string; dialect: string };
};

type Connector = {
  id: string;
  name: string;
  connector_type: string;
  connection_mode: "direct" | "mcp";
  description?: string | null;
  host: string | null;
  database: string | null;
  mcp_server_url?: string | null;
  secret_reference?: string | null;
  status: string;
  read_only: boolean;
  metadata_summary: Record<string, number>;
  last_scanned_at?: string;
};

type ModelProvider = {
  id: string;
  name: string;
  provider_type: string;
  base_url?: string;
  default_model: string;
  embedding_model?: string;
  secret_reference?: string;
  enabled: boolean;
  is_default: boolean;
  status: string;
};

type Project = {
  id: string;
  name: string;
  slug: string;
  description?: string;
  environment: string;
  active: boolean;
  default_model_provider_id?: string;
  membership_role?: string;
  is_current: boolean;
  model_provider?: { id: string; name: string; provider_type: string; default_model: string; status: string };
};

type AgentVersion = { id: string; version: number; instructions: string; model_provider_id?: string; tool_names: string[]; input_schema: Record<string, unknown>; config: Record<string, unknown>; status: string; evaluation_score?: number; created_at: string };
type AgentDefinition = { id: string; name: string; purpose: string; autonomy_level: number; enabled: boolean; tool_names: string[]; policy: Record<string, unknown>; current_version?: number; version_status?: string; model_provider_id?: string; evaluation_score?: number; versions?: AgentVersion[] };
type ToolVersion = { id: string; version: number; implementation_type: string; handler_name: string; endpoint?: string; http_method: string; parameter_schema: { type?: string; required?: string[]; properties?: Record<string, { type?: string; description?: string }> }; result_schema: Record<string, unknown>; permissions: string[]; timeout_seconds: number; max_retries: number; retry_backoff_seconds: number; cost_class: string; environment: string; status: string; created_at: string };
type ToolDefinition = { id: string; name: string; category: string; description: string; risk_level: string; enabled: boolean; requires_approval: boolean; current_version?: number; version_status?: string; implementation_type?: string; parameter_schema?: ToolVersion["parameter_schema"]; versions?: ToolVersion[] };
type SemanticMetric = { id: string; project_id: string; name: string; description?: string; formula: string; grain: string; owner: string; dimensions: string[]; synonyms: string[]; status: string };
type SemanticJoinPolicy = { id: string; project_id: string; left_asset_id: string; right_asset_id: string; left_column: string; right_column: string; join_type: "inner" | "left"; description?: string; status: string };
type PipelineDefinition = { id: string; name: string; objective: string; status: string; current_version: number; generated_code: string; definition: { sources?: { asset_id: string; relation: string }[]; target?: { relation: string }; nodes?: { id: string; type: string; label: string }[]; edges?: { source: string; target: string }[]; checks?: string[] }; updated_at: string };
type Incident = { id: string; job_id: string; title: string; severity: string; status: string; root_cause: string; evidence: Record<string, unknown>[]; remediation: string[]; retry_job_id?: string; created_at: string };

type Job = {
  id: string;
  title: string;
  job_type: string;
  status: string;
  progress: number;
  plan: { agent: string; action: string; status: string }[];
  evidence: { type: string; label: string }[];
  logs: { at: string; level: string; message: string }[];
  outputs: { type: string; agent?: string; tool?: string; title?: string; summary?: string; data?: unknown; at?: string }[];
  created_at: string;
};

type Approval = {
  id: string;
  job_id: string;
  title: string;
  action_type: string;
  risk_level: string;
  status: string;
  evidence: { summary?: string; checks?: string[]; objective?: string; guardrails?: string[] };
  created_at: string;
};

type IngestedFile = {
  id: string;
  filename: string;
  size_bytes: number;
  status: string;
  row_count?: number;
  profile: {
    kind: string;
    row_count?: number;
    column_count?: number;
    columns?: { name: string; inferred_type: string; null_count: number; distinct_count: number }[];
    sample_rows?: Record<string, unknown>[];
    preview?: string;
    staged_table?: { schema_name: string; table_name: string; relation: string; row_count: number; loaded_rows: number; replaced_rows: number; load_mode: LoadMode };
    confirmed_mapping?: {
      id: string;
      name: string;
      target_table: string;
      columns: MappingColumn[];
      load_mode?: LoadMode;
      key_columns?: string[];
    };
  };
  created_at: string;
};

type MappingColumn = {
  source_name: string;
  target_name: string;
  target_type: "string" | "integer" | "number" | "boolean";
  nullable: boolean;
};

type LoadMode = "versioned" | "replace" | "append" | "upsert";

type IngestionMapping = {
  id: string;
  name: string;
  target_table: string;
  columns: MappingColumn[];
  latest_relation?: string;
  run_count: number;
  artifact_id: string;
};

type QualityRun = {
  id: string;
  rule_id: string;
  rule_name: string;
  dataset: string;
  status: string;
  checked_rows: number;
  failed_rows: number;
  pass_rate: number;
  quarantine_relation?: string;
  error?: string;
  created_at: string;
};

type QualityRule = {
  id: string;
  asset_id: string;
  name: string;
  rule_type: string;
  column_name: string;
  severity: string;
  dataset: string;
  latest_run?: QualityRun;
};

type SQLResult = {
  sql: string;
  dialect: string;
  explanation: string;
  cache?: { hit: boolean; cache_key?: string; normalized_question?: string; hit_count?: number };
  grounding?: {
    catalog_matches?: { relation: string; match_type: string; score: number }[];
    semantic_matches?: { name: string; formula: string; grain: string }[];
    join_matches?: { left_relation: string; right_relation: string; join_type: string; left_column: string; right_column: string }[];
  };
  validation: {
    status: string;
    read_only: boolean;
    row_limit: number;
    risk_level: string;
    checks: string[];
  };
  sources: { asset?: string; columns?: string[]; term?: string; definition?: string }[];
  preview: Record<string, string | number>[];
  execution?: SQLExecutionResult | null;
  provider: { id: string; name: string; model: string; mode: string; latency_ms: number };
};

type SQLExecutionResult = {
  columns: string[];
  rows: Record<string, string | number>[];
  row_count: number;
  truncated: boolean;
  limit: number;
  error?: string;
};

type SearchResult = {
  source_id: string;
  source_type: string;
  title: string;
  text: string;
  score: number;
  relation?: string;
};

type Artifact = {
  id: string;
  name: string;
  artifact_type: string;
  status: string;
  latest_version: number;
  metadata: Record<string, unknown>;
  updated_at: string;
};

type ArtifactVersion = {
  id: string;
  artifact_id: string;
  version: number;
  content: string;
  artifact_metadata: Record<string, unknown>;
  created_at: string;
};

type IngestionSchedule = {
  id: string;
  name: string;
  mapping_id: string;
  mapping_name: string;
  filename: string;
  target_table?: string;
  cron: string;
  load_mode: string;
  watermark_column?: string;
  last_watermark?: string;
  enabled: boolean;
  next_run_at?: string;
  last_run_at?: string;
};

type MappingOption = IngestionMapping & { filename: string };

type ArtifactComment = { id: string; body: string; version?: number; author: string; created_at: string };

type EvaluationSet = {
  id: string;
  name: string;
  description?: string;
  cases: { name: string; question: string; case_type?: "sql_generation" | "agent_run"; dialect: string; expected_tables: string[]; required_sql_tokens: string[]; expected_agents?: string[]; expected_tools?: string[]; expects_approval?: boolean | null }[];
  latest_run?: { id: string; status: string; score: number; created_at: string };
};

type NotebookCellData = { id: string; type: "markdown" | "sql" | "python"; source: string };
type Notebook = { id: string; name: string; status: string; version: number; cells: NotebookCellData[]; outputs: { cell_id: string; status: string; output?: unknown; error?: string }[]; job_id?: string | null };

type Conversation = { id: string; title: string; summary?: string; message_count: number; last_message?: string; created_by: string; created_at: string; updated_at: string };
type ConversationMessage = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  structured: {
    sql?: string;
    dialect?: string;
    provider?: { name: string; model: string };
    cache?: { hit: boolean; cache_key?: string; normalized_question?: string; hit_count?: number };
    grounding?: {
      catalog_matches?: { relation: string; match_type: string; score: number }[];
      semantic_matches?: { name: string; formula: string; grain: string }[];
      join_matches?: { left_relation: string; right_relation: string; join_type: string; left_column: string; right_column: string }[];
    };
    validation?: { status: string; checks: string[] };
    sources?: { asset?: string; term?: string }[];
    execution?: SQLExecutionResult;
    chart?: { type: "bar" | "line" | "table"; title: string; x?: string; y?: string; data: Record<string, string | number>[] };
    source?: { id?: string | null; name: string; database: string; connector_type: string; dialect: string };
    memory?: { prior_messages_used: number; persisted: boolean; summary?: string | null };
  };
};
type ExternalClient = { id: string; name: string; client_id: string; active: boolean; scopes: string[]; created_at: string; token?: string };
type QueryTool = { id: string; name: string; description: string; purpose: string; data_source: string; line_of_business: string; owner: string; tags: string[]; connector_id?: string; upstream_tool_name?: string | null; sql_template: string; parameter_schema: Record<string, unknown>; result_schema: Record<string, unknown>; allowed_relations: string[]; row_limit: number; timeout_seconds: number; requires_approval: boolean; status: string; version: number; updated_at: string };
type QueryToolDraft = Omit<QueryTool, "id" | "status" | "version" | "updated_at">;
type RelationOption = { asset_id: string; relation: string; source_name: string; connector_id?: string | null; connector_name: string; columns: Dataset["columns"]; tags: string[] };
type QueryToolUsage = { invocation_count: number; success_count: number; failure_count: number; success_rate: number | null; median_latency_ms: number | null; rows_returned: number; last_invoked_at: string | null };
type QueryToolRegistrySummary = { total: number; published: number; draft: number; never_invoked: number; tools: (QueryTool & QueryToolUsage)[] };
type PromptArtifact = { id: string; name: string; status: string; version: number; content: { system_prompt?: string; template?: string; variables?: string[] }; metadata: Record<string, unknown>; updated_at: string };
type RetentionPolicy = { id: string; resource_type: string; retention_days: number; enabled: boolean; updated_at: string };
type SchemaDrift = { id: string; connector_id: string; relation: string; changes: { kind: string; column: string; from?: string; to?: string; type?: string }[]; status: string; detected_at: string };
type ModelUsage = { pricing_configured: boolean; totals: { calls: number; input_tokens: number; output_tokens: number; estimated_cost_usd: number }; items: { provider_id: string; provider_name: string; model: string; calls: number; input_tokens: number; output_tokens: number; estimated_cost_usd: number; average_latency_ms: number }[] };

const navItems: { key: NavKey; label: string; icon: typeof LayoutDashboard }[] = [
  { key: "workspace", label: "Workspace", icon: LayoutDashboard },
  { key: "conversations", label: "Analysis", icon: MessageSquare },
  { key: "datasets", label: "Datasets", icon: Database },
  { key: "files", label: "Files", icon: FileUp },
  { key: "sql", label: "SQL", icon: Code2 },
  { key: "notebooks", label: "Notebooks", icon: BookOpen },
  { key: "pipelines", label: "Pipelines", icon: GitBranch },
  { key: "jobs", label: "Jobs", icon: Activity },
  { key: "artifacts", label: "Artifacts", icon: Archive },
  { key: "quality", label: "Quality", icon: ShieldCheck },
  { key: "superset", label: "Superset", icon: Gauge },
  { key: "approvals", label: "Approvals", icon: Check },
  { key: "tools", label: "Tool registry", icon: Network },
  { key: "agents", label: "Agents", icon: Bot },
  { key: "semantic", label: "Semantic layer", icon: Braces },
  { key: "evaluations", label: "Evaluations", icon: FlaskConical },
  { key: "admin", label: "Admin", icon: Settings },
];

const TOUR_STORAGE_KEY = "datapilot_tour_completed_v1";

const defaultTourSteps: { key: NavKey; title: string; body: string }[] = [
  {
    key: "workspace",
    title: "Workspace overview",
    body: "Start here for system health, recent jobs, recommendations, and a quick way to launch a governed objective.",
  },
  {
    key: "conversations",
    title: "Persistent analysis",
    body: "Use Analysis for question-driven work. Each topic keeps its earlier context, generated SQL, preview, and saved memory.",
  },
  {
    key: "files",
    title: "File ingestion",
    body: "Profile local files, confirm schema mappings, stage them into governed PostgreSQL tables, and keep an audit trail.",
  },
  {
    key: "sql",
    title: "Grounded SQL workspace",
    body: "Generate read-only SQL from catalog and semantic context, reuse matching saved queries, preview results, and save reviewed artifacts.",
  },
  {
    key: "jobs",
    title: "Run trace and outputs",
    body: "Inspect plans, evidence, step outputs, logs, approvals, and retries for agent runs, scans, and operational workflows.",
  },
];

const connectorLabels: Record<string, string> = {
  postgres: "PostgreSQL",
  sql_server: "SQL Server",
  oracle: "Oracle",
  teradata: "Teradata",
  bigquery: "BigQuery",
  local_files: "Local files",
};

const connectorDialectForType = (connectorType: string) => {
  if (connectorType === "postgres") return "postgres";
  if (connectorType === "sql_server") return "sqlserver";
  if (connectorType === "bigquery") return "bigquery";
  if (connectorType === "oracle") return "oracle";
  if (connectorType === "teradata") return "teradata";
  return "postgres";
};

const statusTone = (status: string) => {
  const normalized = status.toLowerCase();
  if (["healthy", "succeeded", "approved", "passed", "reachable", "staged"].includes(normalized)) {
    return "positive";
  }
  if (["failed", "rejected", "cancelled"].includes(normalized)) return "negative";
  if (["pending", "waiting_for_approval", "retrying", "configuration_required"].includes(normalized)) {
    return "warning";
  }
  return "neutral";
};

function StatusPill({ value }: { value: string }) {
  return <span className={`status-pill ${statusTone(value)}`}>{value.replaceAll("_", " ")}</span>;
}

function LoadingBlock({ label = "Loading workspace" }: { label?: string }) {
  return (
    <div className="loading-block">
      <RefreshCw size={18} className="spin" />
      <span>{label}</span>
    </div>
  );
}

function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon: ReactNode;
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{body}</p>
      {action}
    </div>
  );
}

export default function Home() {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [active, setActive] = useState<NavKey>("workspace");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [mobileNav, setMobileNav] = useState(false);
  const [tourOpen, setTourOpen] = useState(false);
  const [tourStep, setTourStep] = useState(0);
  const [toast, setToast] = useState<{ tone: "ok" | "error"; message: string } | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [passwordForm, setPasswordForm] = useState({ current_password: "", new_password: "" });
  const [passwordDialog, setPasswordDialog] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [projectDialog, setProjectDialog] = useState(false);
  const [projectForm, setProjectForm] = useState({ name: "", description: "", environment: "local" });
  const [sqlSeed, setSqlSeed] = useState<{ question: string; dialect: string } | null>(null);
  const [pendingApprovalCount, setPendingApprovalCount] = useState(0);

  const notify = useCallback((message: string, tone: "ok" | "error" = "ok") => {
    setToast({ message, tone });
    window.setTimeout(() => setToast(null), 3600);
  }, []);

  useEffect(() => {
    const token = window.localStorage.getItem("datapilot_token");
    if (!token) {
      setAuthChecked(true);
      return;
    }
    api<SessionUser>("/auth/me")
      .then(setUser)
      .catch(() => logout())
      .finally(() => setAuthChecked(true));
  }, []);

  useEffect(() => {
    if (searchQuery.trim().length < 2 || !user) {
      setSearchResults([]);
      return;
    }
    const timer = window.setTimeout(() => {
      setSearching(true);
      api<{ results: SearchResult[] }>(`/search?q=${encodeURIComponent(searchQuery.trim())}`)
        .then((result) => setSearchResults(result.results))
        .catch(() => setSearchResults([]))
        .finally(() => setSearching(false));
    }, 220);
    return () => window.clearTimeout(timer);
  }, [searchQuery, user]);

  useEffect(() => {
    if (user?.must_change_password) setPasswordDialog(true);
  }, [user?.must_change_password]);

  const loadControlPlane = useCallback(async () => {
    if (!user) return;
    try {
      const [projectData, providerData, approvalData] = await Promise.all([api<Project[]>("/projects"), api<ModelProvider[]>("/model-providers"), api<Approval[]>("/approvals?status=pending")]);
      setProjects(projectData);
      setProviders(providerData);
      setPendingApprovalCount(approvalData.length);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Workspace configuration could not be loaded", "error");
    }
  }, [notify, user]);

  useEffect(() => { loadControlPlane(); }, [loadControlPlane]);

  if (!authChecked) {
    return (
      <main className="auth-page">
        <LoadingBlock label="Opening local workspace" />
      </main>
    );
  }

  if (!user) {
    return <LoginScreen onLogin={setUser} />;
  }

  const activeLabel = navItems.find((item) => item.key === active)?.label || "Workspace";
  const currentProject = projects.find((project) => project.is_current) || projects.find((project) => project.id === user.current_project_id) || projects[0];
  const healthyProviders = providers.filter((provider) => provider.enabled && provider.status === "healthy");
  const visibleNavItems = navItems.filter((item) => (item.key !== "admin" || user.role === "admin") && (item.key !== "tools" || ["admin", "engineer"].includes(user.role)));
  const tourSteps = defaultTourSteps.filter((step) => visibleNavItems.some((item) => item.key === step.key));
  const currentTourStep = tourSteps[tourStep] || tourSteps[0];

  useEffect(() => {
    if (!user || user.must_change_password || passwordDialog || tourOpen || !tourSteps.length) return;
    const completed = window.localStorage.getItem(TOUR_STORAGE_KEY);
    if (completed) return;
    setTourStep(0);
    setActive(tourSteps[0].key);
    setTourOpen(true);
  }, [passwordDialog, tourOpen, tourSteps, user]);

  useEffect(() => {
    if (!tourOpen || !currentTourStep) return;
    setActive(currentTourStep.key);
  }, [currentTourStep, tourOpen]);

  function openTour(stepIndex = 0) {
    if (!tourSteps.length) return;
    const nextStep = Math.min(Math.max(stepIndex, 0), tourSteps.length - 1);
    setTourStep(nextStep);
    setMobileNav(false);
    setTourOpen(true);
    setActive(tourSteps[nextStep].key);
  }

  function closeTour(markComplete: boolean) {
    setTourOpen(false);
    if (markComplete) {
      window.localStorage.setItem(TOUR_STORAGE_KEY, "true");
    }
  }

  async function switchProject(project: Project) {
    try {
      await api(`/projects/${project.id}/select`, { method: "POST" });
      setUser((current) => current ? { ...current, current_project_id: project.id, current_project_name: project.name } : current);
      await loadControlPlane();
      setProjectDialog(false);
      notify(`Project switched to ${project.name}`);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Project switch failed", "error"); }
  }
  async function createProject(event: FormEvent) {
    event.preventDefault();
    try {
      const project = await api<Project>("/projects", { method: "POST", body: JSON.stringify(projectForm) });
      setProjectForm({ name: "", description: "", environment: "local" });
      await switchProject(project);
      notify("Project created and selected");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Project creation failed", "error"); }
  }
  async function selectModel(providerId: string) {
    if (!currentProject) return;
    try {
      await api(`/projects/${currentProject.id}/model-provider`, { method: "PUT", body: JSON.stringify({ provider_id: providerId }) });
      await loadControlPlane();
      notify("Project model updated");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Model selection failed", "error"); }
  }
  async function changePassword(event: FormEvent) {
    event.preventDefault();
    try {
      await api("/auth/change-password", { method: "POST", body: JSON.stringify(passwordForm) });
      setUser((current) => current ? { ...current, must_change_password: false } : current);
      setPasswordForm({ current_password: "", new_password: "" });
      setPasswordDialog(false);
      notify("Password changed");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Password change failed", "error"); }
  }
  return (
    <div className={`app-shell ${sidebarOpen ? "" : "sidebar-collapsed"}`}>
      <aside className={`sidebar ${mobileNav ? "mobile-open" : ""}`}>
        <div className="brand">
          <div className="brand-mark">DP</div>
          <div className="brand-copy">
            <strong>DataPilot</strong>
            <span>Agent OS</span>
          </div>
          <button className="icon-button sidebar-close" onClick={() => setMobileNav(false)} aria-label="Close menu">
            <X size={19} />
          </button>
        </div>
        <div className="project-switcher">
          <span className="project-label">Project</span>
          <button onClick={() => setProjectDialog(true)} title="Switch or create project">
            <span className="project-avatar">RB</span>
            <span>
              <strong>{currentProject?.name || user.current_project_name || "Select project"}</strong>
              <small>{currentProject?.environment || "local"} environment</small>
            </span>
            <ChevronDown size={16} />
          </button>
        </div>
        <nav className="main-nav" aria-label="Product navigation">
          {visibleNavItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                className={active === item.key ? "active" : ""}
                onClick={() => {
                  setActive(item.key);
                  setMobileNav(false);
                }}
                title={item.label}
              >
                <Icon size={18} strokeWidth={1.8} />
                <span>{item.label}</span>
                {item.key === "approvals" && pendingApprovalCount > 0 && <span className="nav-count">{pendingApprovalCount}</span>}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <div className="local-status">
            <span className="status-dot" />
            <span>
              <strong>Local stack</strong>
              <small>Private workspace</small>
            </span>
          </div>
          <button className="user-menu" onClick={() => setPasswordDialog(true)} title="Account and password">
            <span className="user-avatar">{user.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</span>
            <span>
              <strong>{user.name}</strong>
              <small>{user.role}</small>
            </span>
            <KeyRound size={16} />
          </button>
        </div>
      </aside>

      <div className="app-body">
        <header className="topbar">
          <div className="topbar-left">
            <button className="icon-button mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open menu">
              <Menu size={20} />
            </button>
            <button
              className="icon-button desktop-collapse"
              onClick={() => setSidebarOpen((value) => !value)}
              aria-label={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
              title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
            >
              <PanelLeftClose size={19} />
            </button>
            <div>
              <h1>{activeLabel}</h1>
              <p>{currentProject?.name || "Local workspace"} / {currentProject?.environment || "local"}</p>
            </div>
          </div>
          <div className="topbar-actions">
            <select className="topbar-model-select" value={currentProject?.default_model_provider_id || ""} onChange={(event) => selectModel(event.target.value)} disabled={!currentProject || !healthyProviders.length || !["admin", "engineer"].includes(user.role)} aria-label="Active project model" title="Active project model">
              {!healthyProviders.length && <option value="">No tested models</option>}
              {healthyProviders.map((provider) => <option key={provider.id} value={provider.id}>{provider.name} / {provider.default_model}</option>)}
            </select>
            <div className="global-search">
              <div className="search-box">
                {searching ? <RefreshCw size={17} className="spin" /> : <Search size={17} />}
                <input aria-label="Search workspace" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Search datasets, files, knowledge" />
              </div>
              {searchQuery.trim().length >= 2 && (
                <div className="search-results">
                  {searchResults.length ? searchResults.map((result) => (
                    <button key={result.source_id} onClick={() => { setActive(result.source_type === "file" ? "files" : "datasets"); setSearchQuery(""); }}>
                      <span className="search-result-icon">{result.source_type === "file" ? <FileSpreadsheet size={16} /> : <Database size={16} />}</span>
                      <span><strong>{result.title}</strong><small>{result.text}</small></span>
                      <StatusPill value={result.source_type} />
                    </button>
                  )) : <div className="search-empty">{searching ? "Searching grounded knowledge" : "No grounded results"}</div>}
                </div>
              )}
            </div>
            <button
              className="icon-button"
              onClick={() => openTour(0)}
              aria-label="Open product tour"
              title="Open product tour"
            >
              <BookOpen size={18} />
            </button>
            <button
              className="icon-button"
              onClick={() => {
                logout();
                setUser(null);
              }}
              aria-label="Sign out"
              title="Sign out"
            >
              <LogOut size={18} />
            </button>
          </div>
        </header>

        <main className="content">
          {active === "workspace" && <WorkspaceView setActive={setActive} notify={notify} />}
          {active === "conversations" && <ConversationsView notify={notify} currentUser={user} />}
          {active === "datasets" && <DatasetsView onOpenSQL={(dataset) => { setSqlSeed({ question: `Analyze ${dataset.schema_name}.${dataset.table_name} using its approved metadata`, dialect: dataset.source_name === "Local files" ? "postgres" : "sqlserver" }); setActive("sql"); }} />}
          {active === "files" && <FilesView notify={notify} currentUser={user} />}
          {active === "sql" && <SQLView notify={notify} seed={sqlSeed} currentUser={user} />}
          {active === "notebooks" && <NotebooksView notify={notify} />}
          {active === "pipelines" && <PipelinesView notify={notify} />}
          {active === "jobs" && <JobsView notify={notify} />}
          {active === "artifacts" && <ArtifactsView notify={notify} />}
          {active === "quality" && <QualityView notify={notify} />}
          {active === "superset" && <SupersetView isAdmin={user.role === "admin"} projectName={currentProject?.name || user.current_project_name || "Current project"} />}
          {active === "approvals" && <ApprovalsView notify={notify} />}
          {active === "tools" && <ToolsView notify={notify} />}
          {active === "agents" && <AgentsView notify={notify} />}
          {active === "semantic" && <SemanticView notify={notify} />}
          {active === "evaluations" && <EvaluationsView notify={notify} />}
          {active === "admin" && <AdminView currentUser={user} notify={notify} />}
        </main>
      </div>
      {mobileNav && <button className="nav-backdrop" aria-label="Close menu" onClick={() => setMobileNav(false)} />}
      {toast && (
        <div className={`toast ${toast.tone}`} role="status">
          {toast.tone === "ok" ? <Check size={18} /> : <AlertCircle size={18} />}
          {toast.message}
        </div>
      )}
      {tourOpen && currentTourStep && (
        <Modal title="Product tour" onClose={() => closeTour(false)}>
          <div className="tour-body">
            <div className="tour-progress">
              <span>Step {tourStep + 1} of {tourSteps.length}</span>
              <strong>{currentTourStep.title}</strong>
            </div>
            <p className="tour-copy">{currentTourStep.body}</p>
            <div className="tour-step-list">
              {tourSteps.map((step, index) => (
                <button
                  key={step.key}
                  className={index === tourStep ? "active" : ""}
                  onClick={() => openTour(index)}
                  type="button"
                >
                  <span>{index + 1}</span>
                  <strong>{visibleNavItems.find((item) => item.key === step.key)?.label || step.title}</strong>
                </button>
              ))}
            </div>
            <div className="modal-actions">
              <button type="button" className="secondary-button" onClick={() => closeTour(true)}>Skip tour</button>
              <button type="button" className="secondary-button" onClick={() => setTourStep((value) => Math.max(0, value - 1))} disabled={tourStep === 0}>Back</button>
              {tourStep < tourSteps.length - 1 ? (
                <button type="button" className="primary-button" onClick={() => setTourStep((value) => Math.min(tourSteps.length - 1, value + 1))}>
                  Next
                </button>
              ) : (
                <button type="button" className="primary-button" onClick={() => closeTour(true)}>
                  Finish
                </button>
              )}
            </div>
          </div>
        </Modal>
      )}
      {passwordDialog && <Modal title={user.must_change_password ? "Change temporary password" : "Change password"} onClose={() => setPasswordDialog(false)}><form className="modal-form" onSubmit={changePassword}><label>Current password<input type="password" value={passwordForm.current_password} onChange={(event) => setPasswordForm({ ...passwordForm, current_password: event.target.value })} required /></label><label>New password<input type="password" value={passwordForm.new_password} onChange={(event) => setPasswordForm({ ...passwordForm, new_password: event.target.value })} minLength={10} required /></label><div className="modal-actions"><button className="primary-button"><KeyRound size={17} />Change password</button></div></form></Modal>}
      {projectDialog && <Modal title="Projects" onClose={() => setProjectDialog(false)}><div className="project-dialog-list">{projects.map((project) => <button key={project.id} className={project.is_current ? "selected" : ""} onClick={() => switchProject(project)}><span className="project-avatar">{project.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</span><span><strong>{project.name}</strong><small>{project.environment} / {project.membership_role || "admin"}</small></span>{project.is_current ? <Check size={17} /> : <ChevronRight size={17} />}</button>)}</div>{["admin", "engineer"].includes(user.role) && <form className="modal-form project-create-form" onSubmit={createProject}><div className="subheading"><h4>New project</h4></div><label>Name<input value={projectForm.name} onChange={(event) => setProjectForm({ ...projectForm, name: event.target.value })} required /></label><label>Description<input value={projectForm.description} onChange={(event) => setProjectForm({ ...projectForm, description: event.target.value })} /></label><div className="modal-actions"><button className="primary-button"><Plus size={17} />Create project</button></div></form>}</Modal>}
    </div>
  );
}

function LoginScreen({ onLogin }: { onLogin: (user: SessionUser) => void }) {
  const [email, setEmail] = useState("admin@datapilot.local");
  const [password, setPassword] = useState("ChangeMe123!");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(await login(email, password));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to sign in");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="login-panel">
        <div className="login-brand">
          <div className="brand-mark large">DP</div>
          <div>
            <strong>DataPilot</strong>
            <span>Agent OS</span>
          </div>
        </div>
        <div className="login-copy">
          <h1>Open your data workspace</h1>
          <p>Sign in with a local administrator account. PingFederate can be enabled from Admin after initial setup.</p>
        </div>
        <form onSubmit={submit}>
          <label>
            Email
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
          </label>
          {error && <div className="form-error"><AlertCircle size={16} />{error}</div>}
          <button className="primary-button wide" disabled={busy}>
            {busy ? <RefreshCw size={17} className="spin" /> : <KeyRound size={17} />}
            Sign in
          </button>
        </form>
        <div className="login-foot">
          <ShieldCheck size={16} />
          Credentials and data remain within this local environment.
        </div>
      </section>
      <section className="auth-context">
        <div className="context-copy">
          <span className="eyebrow">GOVERNED AGENT WORKSPACE</span>
          <h2>From source systems to trusted data products.</h2>
          <p>Connect enterprise databases, profile local files, generate grounded SQL, and run controlled multi-agent workflows with a complete approval trail.</p>
        </div>
        <div className="context-flow" aria-label="Data workflow">
          <div><Database size={18} /><span>Sources</span></div>
          <ChevronRight size={16} />
          <div><Bot size={18} /><span>Agents</span></div>
          <ChevronRight size={16} />
          <div><ShieldCheck size={18} /><span>Controls</span></div>
          <ChevronRight size={16} />
          <div><LayoutDashboard size={18} /><span>Outcomes</span></div>
        </div>
      </section>
    </main>
  );
}

function WorkspaceView({
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
      const result = await api<{ status: string; plan: Job["plan"]; approval_id?: string }>("/agents/runs", {
        method: "POST",
        body: JSON.stringify({ objective, autonomy_level: 2 }),
      });
      setPlan(result.plan);
      notify(
        result.approval_id ? "Draft complete and sent for approval" : "Bounded agent run completed",
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
          {recommendations.map((recommendation) => <button key={recommendation.question} title={recommendation.basis} onClick={() => setObjective(recommendation.question)}>{recommendation.question}</button>)}
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
            <button className="text-button" onClick={() => setActive("jobs")}>Open full trace <ChevronRight size={16} /></button>
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
          <button className="secondary-button" onClick={() => setActive("files")}>
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
            <button className="text-button" onClick={() => setActive("files")}>Open Files</button>
          </div>
          <div className="starter-step">
            <span>2</span>
            <div>
              <strong>Ask a grounded question</strong>
              <small>Use Analysis for a persistent topic that keeps context, SQL, and preview results together.</small>
            </div>
            <button className="text-button" onClick={() => setActive("conversations")}>Open Analysis</button>
          </div>
          <div className="starter-step">
            <span>3</span>
            <div>
              <strong>Inspect generated SQL</strong>
              <small>Review catalog grounding, semantic terms, validation checks, and reuse status before saving.</small>
            </div>
            <button className="text-button" onClick={() => setActive("sql")}>Open SQL</button>
          </div>
          <div className="starter-step">
            <span>4</span>
            <div>
              <strong>Review the run trace</strong>
              <small>Open Jobs to see plan steps, evidence, outputs, approvals, and operational logs.</small>
            </div>
            <button className="text-button" onClick={() => setActive("jobs")}>Open Jobs</button>
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

function ConversationsView({ notify, currentUser }: { notify: (message: string, tone?: "ok" | "error") => void; currentUser: SessionUser }) {
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

function AnalysisChart({ chart }: { chart?: ConversationMessage["structured"]["chart"] }) {
  if (!chart?.data?.length || !chart.x || !chart.y) return <div className="chart-empty">No chartable result</div>;
  const values = chart.data.map((row) => Number(row[chart.y!] || 0));
  const maximum = Math.max(...values.map((value) => Math.abs(value)), 1);
  return <div className="result-chart"><h4>{chart.title}</h4>{chart.data.slice(0, 12).map((row, index) => <div className="chart-row" key={`${String(row[chart.x!])}-${index}`}><span title={String(row[chart.x!])}>{String(row[chart.x!])}</span><i><b style={{ width: `${Math.max(2, Math.abs(Number(row[chart.y!] || 0)) / maximum * 100)}%` }} /></i><strong>{String(row[chart.y!])}</strong></div>)}</div>;
}

function Metric({ label, value, detail, icon, tone }: { label: string; value: ReactNode; detail: string; icon: ReactNode; tone: string }) {
  return (
    <div className="metric">
      <span className={`metric-icon ${tone}`}>{icon}</span>
      <div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
    </div>
  );
}

function ControlItem({ icon, label, value, status }: { icon: ReactNode; label: string; value: string; status: string }) {
  return (
    <div className="control-item">
      <span className="control-icon">{icon}</span>
      <span><small>{label}</small><strong>{value}</strong></span>
      <StatusPill value={status} />
    </div>
  );
}

function SecurityOverviewPanel({
  data,
  onOpenIncidents,
}: {
  data: SecurityOverview | null;
  onOpenIncidents: () => void;
}) {
  const categoryStyles: Record<SecurityCategoryKey, { label: string; tone: string }> = {
    prompt_injection: { label: "Prompt Injection", tone: "amber" },
    pii_exposure: { label: "PII Exposure", tone: "blue" },
    toxic_content: { label: "Toxic Content", tone: "rose" },
  };
  const maxBucketTotal = useMemo(
    () => Math.max(...(data?.event_series.map((bucket) => Object.values(bucket.counts).reduce((sum, count) => sum + count, 0)) || [1]), 1),
    [data],
  );

  if (!data) {
    return (
      <section className="surface security-overview">
        <div className="section-heading">
          <div>
            <span className="eyebrow">GUARDRAILS</span>
            <h3>Security Overview</h3>
            <p>Real-time summary of security posture and key risk indicators across your AI applications.</p>
          </div>
          <StatusPill value="loading" />
        </div>
        <div className="security-loading">
          <LoadingBlock label="Loading security posture" />
        </div>
      </section>
    );
  }

  const delta = data.overview.score_delta_pp;
  const deltaPrefix = delta > 0 ? "+" : "";
  const deltaTone = delta > 0 ? "positive" : delta < 0 ? "negative" : "neutral";
  const totalIncidentCount = data.incidents_by_severity.reduce((sum, item) => sum + item.count, 0);

  return (
    <section className="surface security-overview">
      <div className="section-heading">
        <div>
          <span className="eyebrow">GUARDRAILS</span>
          <h3>Security Overview</h3>
          <p>Real-time summary of security posture and key risk indicators across your AI applications.</p>
        </div>
        <div className="security-range">
          <strong>{data.period.key}</strong>
          <span>{data.period.label}</span>
        </div>
      </div>

      <div className="security-summary-grid">
        <article className="security-score-card">
          <span className="security-card-label">Overall Security Score</span>
          <strong>{data.overview.overall_security_score}%</strong>
          <div className="security-score-meta">
            <StatusPill value={data.overview.posture} />
            <small className={`security-delta ${deltaTone}`}>{deltaPrefix}{delta}pp vs last period</small>
          </div>
        </article>
        <article className="security-stat-card">
          <span>Total Security Events</span>
          <strong>{data.overview.total_security_events}</strong>
          <small>{data.overview.total_security_events ? "Needs review" : "No events detected"}</small>
        </article>
        <article className="security-stat-card">
          <span>Blocked Requests</span>
          <strong>{data.overview.blocked_requests}</strong>
          <small>{data.overview.blocked_requests ? "Guardrails intervened" : "No blocked requests"}</small>
        </article>
        <article className="security-stat-card">
          <span>Critical Incidents</span>
          <strong>{data.overview.critical_incidents}</strong>
          <small>{data.overview.critical_incidents ? "Immediate action needed" : "No critical incidents"}</small>
        </article>
      </div>

      <div className="security-layout">
        <div className="security-main">
          <section className="security-panel">
            <div className="security-panel-head">
              <div>
                <h4>Security Events Over Time</h4>
                <p>{data.period.label}</p>
              </div>
              <div className="security-legend">
                {Object.entries(categoryStyles).map(([key, item]) => (
                  <span key={key}><i className={`security-tone ${item.tone}`} />{item.label}</span>
                ))}
              </div>
            </div>
            <div className="security-chart">
              {data.event_series.map((bucket) => {
                const bucketTotal = Object.values(bucket.counts).reduce((sum, count) => sum + count, 0);
                return (
                  <div className="security-chart-group" key={`${bucket.label}-${bucket.start_at}`}>
                    <div className="security-chart-stack" title={`${bucket.label}: ${bucketTotal} events`}>
                      {(Object.keys(categoryStyles) as SecurityCategoryKey[]).map((key) => {
                        const count = bucket.counts[key];
                        const height = count ? `${Math.max(12, (count / maxBucketTotal) * 100)}%` : "0%";
                        return <i key={key} className={`security-segment ${categoryStyles[key].tone}`} style={{ height }} />;
                      })}
                      {!bucketTotal && <b className="security-chart-empty-line" />}
                    </div>
                    <span>{bucket.label}</span>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="security-panel">
            <div className="security-panel-head">
              <div>
                <h4>Top Security Risks</h4>
                <p>{data.overview.total_security_events} total</p>
              </div>
              <button className="text-button" onClick={onOpenIncidents}>View incidents <ChevronRight size={16} /></button>
            </div>
            <div className="security-risk-list">
              {data.top_security_risks.map((risk) => (
                <div className="security-risk-row" key={risk.key}>
                  <div>
                    <strong>{risk.category}</strong>
                    <small>{risk.count} events</small>
                  </div>
                  <div className="security-risk-meter">
                    <span style={{ width: `${risk.share_percent}%` }} className={categoryStyles[risk.key].tone} />
                  </div>
                  <strong>{risk.share_percent}%</strong>
                </div>
              ))}
            </div>
          </section>
        </div>

        <div className="security-side">
          <section className="security-panel">
            <div className="security-panel-head">
              <div>
                <h4>Security Events by Category</h4>
              </div>
            </div>
            <div className="security-category-list">
              {data.events_by_category.map((item) => (
                <div className="security-category-row" key={item.key}>
                  <span><i className={`security-tone ${categoryStyles[item.key].tone}`} />{item.category}</span>
                  <strong>{item.count}</strong>
                </div>
              ))}
            </div>
          </section>

          <section className="security-panel">
            <div className="security-panel-head">
              <div>
                <h4>Incidents by Severity</h4>
              </div>
            </div>
            {totalIncidentCount ? (
              <div className="security-severity-list">
                {data.incidents_by_severity.map((item) => (
                  <div className="security-severity-row" key={item.severity}>
                    <span>{item.severity}</span>
                    <strong>{item.count}</strong>
                  </div>
                ))}
              </div>
            ) : (
              <div className="security-empty">No guardrail incidents in this range</div>
            )}
          </section>

          <section className="security-panel">
            <div className="security-panel-head">
              <div>
                <h4>Recent Security Incidents</h4>
              </div>
              <button className="text-button" onClick={onOpenIncidents}>View all <ChevronRight size={16} /></button>
            </div>
            {data.recent_incidents.length ? (
              <div className="security-incident-list">
                {data.recent_incidents.map((incident) => (
                  <button className="security-incident-row" key={incident.id} onClick={onOpenIncidents}>
                    <span className="security-incident-icon"><AlertCircle size={16} /></span>
                    <span>
                      <strong>{incident.title}</strong>
                      <small>{incident.category} / {new Date(incident.created_at).toLocaleString()}</small>
                    </span>
                    <StatusPill value={incident.severity} />
                  </button>
                ))}
              </div>
            ) : (
              <div className="security-empty">No guardrail incidents in this range</div>
            )}
          </section>
        </div>
      </div>
    </section>
  );
}

function DatasetsView({ onOpenSQL }: { onOpenSQL: (dataset: Dataset) => void }) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [selected, setSelected] = useState<Dataset | null>(null);
  useEffect(() => {
    api<Dataset[]>("/datasets").then((data) => {
      setDatasets(data);
      setSelected(data[0] || null);
    });
  }, []);
  const sources = Array.from(new Set(datasets.map((dataset) => dataset.source?.name || dataset.source_name))).sort();
  const categories = Array.from(new Set(datasets.map((dataset) => dataset.category))).sort();
  const filtered = datasets.filter((dataset) => {
    const sourceName = dataset.source?.name || dataset.source_name;
    const matchesText = `${dataset.schema_name}.${dataset.table_name} ${dataset.description} ${sourceName} ${dataset.category}`.toLowerCase().includes(query.toLowerCase());
    const matchesSource = sourceFilter === "all" || sourceName === sourceFilter;
    const matchesCategory = categoryFilter === "all" || dataset.category === categoryFilter;
    return matchesText && matchesSource && matchesCategory;
  });
  return (
    <div className="view-stack">
      <div className="view-header">
        <div><h2>Dataset explorer</h2><p>Browse metadata, profile signals, and business context available to agents.</p></div>
        <div className="dataset-toolbar">
          <select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)} aria-label="Filter by source"><option value="all">All sources</option>{sources.map((source) => <option key={source} value={source}>{source}</option>)}</select>
          <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)} aria-label="Filter by category"><option value="all">All categories</option>{categories.map((category) => <option key={category} value={category}>{category}</option>)}</select>
          <div className="toolbar-search"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter datasets" /></div>
        </div>
      </div>
      <div className="dataset-layout">
        <section className="surface dataset-list">
          <div className="table-header dataset-grid"><span>Dataset</span><span>Rows</span><span>Category</span><span /></div>
          {filtered.map((dataset) => (
            <button className={`data-row dataset-grid ${selected?.id === dataset.id ? "selected" : ""}`} key={dataset.id} onClick={() => setSelected(dataset)}>
              <span className="dataset-name"><Database size={17} /><span><strong>{dataset.schema_name}.{dataset.table_name}</strong><small>{dataset.source?.name || dataset.source_name} / {connectorLabels[dataset.source?.connector_type || ""] || dataset.source?.connector_type || "registered source"}</small></span></span>
              <span className="mono">{dataset.row_count?.toLocaleString() || "-"}</span>
              <span className="tag-list"><span className="tag">{dataset.category}</span>{dataset.tags.slice(0, 2).map((tag) => <span className="tag" key={tag}>{tag}</span>)}</span>
              <ChevronRight size={16} />
            </button>
          ))}
        </section>
        <aside className="surface detail-panel">
          {selected ? (
            <>
              <div className="detail-title"><span className="dataset-icon"><Database size={21} /></span><div><span>{selected.schema_name}</span><h3>{selected.table_name}</h3></div></div>
              <p className="detail-description">{selected.description}</p>
              <div className="detail-stats"><div><span>Rows</span><strong>{selected.row_count?.toLocaleString()}</strong></div><div><span>Category</span><strong>{selected.category}</strong></div><div><span>System</span><strong>{connectorLabels[selected.source?.connector_type || ""] || selected.source?.connector_type || selected.asset_type}</strong></div></div>
              <div className="subheading"><h4>Columns</h4><span>{selected.columns.length}</span></div>
              <div className="column-list">
                {selected.columns.map((column) => (
                  <div key={column.name}><span><strong>{column.name}</strong><small>{column.type}</small></span><span>{column.nullable ? "nullable" : "required"}</span></div>
                ))}
              </div>
              <button className="secondary-button wide" onClick={() => onOpenSQL(selected)}><Code2 size={17} />Open in SQL workspace</button>
            </>
          ) : <LoadingBlock label="Loading catalog" />}
        </aside>
      </div>
    </div>
  );
}

function FilesView({ notify, currentUser }: { notify: (message: string, tone?: "ok" | "error") => void; currentUser: SessionUser }) {
  const [files, setFiles] = useState<IngestedFile[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [selected, setSelected] = useState<IngestedFile | null>(null);
  const [uploading, setUploading] = useState(false);
  const [staging, setStaging] = useState(false);
  const [showConnector, setShowConnector] = useState(false);
  const [editingConnector, setEditingConnector] = useState<Connector | null>(null);
  const emptyConnectorForm = { name: "", connector_type: "sql_server", description: "", host: "", database: "", secret_reference: "env:SQLSERVER_CREDENTIALS" };
  const [connectorForm, setConnectorForm] = useState(emptyConnectorForm);
  const [targetTable, setTargetTable] = useState("");
  const [mappingColumns, setMappingColumns] = useState<MappingColumn[]>([]);
  const [loadMode, setLoadMode] = useState<LoadMode>("versioned");
  const [keyColumn, setKeyColumn] = useState("");
  const canManageConnections = ["admin", "engineer"].includes(currentUser.role);
  const connectorTypeHelp: Record<string, string> = {
    postgres: "PostgreSQL read-only metadata and parameterized query access.",
    sql_server: "SQL Server read-only metadata and parameterized query access.",
    oracle: "Oracle read-only metadata and parameterized query access.",
    teradata: "Teradata read-only metadata and parameterized query access.",
    bigquery: "BigQuery dataset metadata and read-only query access.",
    local_files: "Local file source registered for catalog context.",
  };
  const load = useCallback(() => Promise.all([api<IngestedFile[]>("/files"), api<Connector[]>("/connectors")]).then(([fileData, connectorData]) => { setFiles(fileData); setConnectors(connectorData); }), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!selected || selected.profile.kind !== "structured") {
      setMappingColumns([]);
      setTargetTable("");
      setLoadMode("versioned");
      setKeyColumn("");
      return;
    }
    const confirmed = selected.profile.confirmed_mapping;
    setMappingColumns(confirmed?.columns || (selected.profile.columns || []).map((column) => ({
      source_name: column.name,
      target_name: column.name.toLowerCase().replace(/[^a-z0-9_]+/g, "_"),
      target_type: column.inferred_type as MappingColumn["target_type"],
      nullable: column.null_count > 0,
    })));
    setTargetTable(confirmed?.target_table || selected.filename.replace(/\.[^.]+$/, "").toLowerCase().replace(/[^a-z0-9_]+/g, "_"));
    setLoadMode(confirmed?.load_mode || "versioned");
    setKeyColumn(confirmed?.key_columns?.[0] || "");
  }, [selected]);

  async function uploadFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    const data = new FormData();
    data.append("file", file);
    data.append("stage_to_postgres", "false");
    try {
      const item = await api<IngestedFile>("/files/ingest", { method: "POST", body: data });
      setSelected(item);
      await load();
      notify(`${file.name} profiled and ready for schema confirmation`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "File ingestion failed", "error");
    } finally {
      setUploading(false);
      event.target.value = "";
    }
  }

  function updateMapping(index: number, patch: Partial<MappingColumn>) {
    setMappingColumns((current) => current.map((column, columnIndex) => columnIndex === index ? { ...column, ...patch } : column));
  }

  function openConnector(connector?: Connector) {
    setEditingConnector(connector || null);
    setConnectorForm(connector ? {
      name: connector.name,
      connector_type: connector.connector_type,
      description: connector.description || "",
      host: connector.host || "",
      database: connector.database || "",
      secret_reference: connector.secret_reference || "",
    } : emptyConnectorForm);
    setShowConnector(true);
  }

  async function saveConnector(event: FormEvent) {
    event.preventDefault();
    try {
      const payload = { ...connectorForm, read_only: true };
      await api(editingConnector ? `/connectors/${editingConnector.id}` : "/connectors", {
        method: editingConnector ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      setShowConnector(false);
      setEditingConnector(null);
      await load();
      notify(editingConnector ? "Connection updated" : "Connection added");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Connection could not be saved", "error");
    }
  }

  async function testConnector(id: string) {
    try {
      const result = await api<{ message: string }>(`/connectors/${id}/test`, { method: "POST" });
      await load();
      notify(result.message);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Connection test failed", "error");
    }
  }

  async function scanConnector(id: string) {
    try {
      const result = await api<{ status: string; assets_discovered?: number }>(`/connectors/${id}/scan`, { method: "POST" });
      await load();
      notify(result.status === "QUEUED" ? "Metadata scan queued" : `Metadata scan completed: ${result.assets_discovered || 0} assets`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Metadata scan failed", "error");
    }
  }

  async function deleteConnector(id: string) {
    try {
      await api(`/connectors/${id}`, { method: "DELETE" });
      await load();
      notify("Connection deleted");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Connection could not be deleted", "error");
    }
  }

  async function saveAndStage() {
    if (!selected || !targetTable.trim() || !mappingColumns.length) return;
    setStaging(true);
    try {
      const mapping = await api<IngestionMapping>(`/files/${selected.id}/schema`, {
        method: "POST",
        body: JSON.stringify({
          mapping_id: selected.profile.confirmed_mapping?.id,
          name: `${selected.filename} staging mapping`,
          target_table: targetTable,
          columns: mappingColumns,
        }),
      });
      const staged = await api<IngestedFile & { mapping: IngestionMapping; job_id: string }>(`/files/${selected.id}/stage`, {
        method: "POST",
        body: JSON.stringify({ mapping_id: mapping.id, load_mode: loadMode, key_columns: loadMode === "upsert" ? [keyColumn] : [] }),
      });
      setSelected(staged);
      await load();
      notify(`${staged.profile.staged_table?.loaded_rows || 0} rows loaded to ${staged.profile.staged_table?.relation}`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Mapped staging failed", "error");
    } finally {
      setStaging(false);
    }
  }

  return (
    <div className="view-stack">
      <div className="view-header">
        <div><h2>Local file ingestion</h2><p>Profile files before staging them as governed local datasets.</p></div>
        <label className="primary-button file-button">
          {uploading ? <RefreshCw size={17} className="spin" /> : <FileUp size={17} />}
          {uploading ? "Profiling" : "Upload file"}
          <input type="file" accept=".csv,.json,.xlsx,.parquet,.pdf" onChange={uploadFile} disabled={uploading} />
        </label>
      </div>
      <section className="surface connection-surface">
        <div className="section-heading compact">
          <div><span className="eyebrow">CONNECTIONS</span><h3>Registered data sources</h3></div>
          {canManageConnections && <button className="primary-button" onClick={() => openConnector()}><Plus size={17} />Add connection</button>}
        </div>
        {connectors.length ? (
          <div className="connection-list">
            {connectors.map((connector) => (
              <div className="connection-row" key={connector.id}>
                <span className="connection-icon"><Database size={17} /></span>
                <span><strong>{connector.name}</strong><small>{connectorLabels[connector.connector_type] || connector.connector_type} / {connector.database || connector.host || "not configured"}</small>{connector.description && <small>{connector.description}</small>}</span>
                <StatusPill value={connector.status} />
                {canManageConnections && <span className="row-actions"><button className="icon-button" title="Test connection" onClick={() => testConnector(connector.id)}><Gauge size={16} /></button><button className="icon-button" title="Scan metadata" onClick={() => scanConnector(connector.id)}><RefreshCw size={16} /></button><button className="icon-button" title="Edit connection" onClick={() => openConnector(connector)}><Settings size={16} /></button><button className="icon-button" title="Delete connection" onClick={() => deleteConnector(connector.id)}><XCircle size={16} /></button></span>}
              </div>
            ))}
          </div>
        ) : (
          <div className="inline-empty">No external connections are registered for this project.</div>
        )}
      </section>
      <div className="two-column file-columns">
        <section className="surface">
          <div className="section-heading compact"><div><span className="eyebrow">INGESTED FILES</span><h3>Recent uploads</h3></div></div>
          {files.length === 0 ? (
            <EmptyState icon={<FileSpreadsheet size={24} />} title="No local files yet" body="Upload CSV, Excel, Parquet, JSON, or PDF to create a profile." />
          ) : (
            <div className="file-list">
              {files.map((file) => (
                <button key={file.id} className={selected?.id === file.id ? "selected" : ""} onClick={() => setSelected(file)}>
                  <span className="file-type">{file.filename.split(".").pop()?.toUpperCase()}</span>
                  <span><strong>{file.filename}</strong><small>{(file.size_bytes / 1024).toFixed(1)} KB / {file.row_count ?? "document"} {file.row_count ? "rows" : ""}</small></span>
                  <StatusPill value={file.status} />
                  <ChevronRight size={16} />
                </button>
              ))}
            </div>
          )}
        </section>
        <section className="surface profile-panel">
          {selected ? (
            <>
              <div className="section-heading compact"><div><span className="eyebrow">PROFILE</span><h3>{selected.filename}</h3></div><StatusPill value={selected.status} /></div>
              {selected.profile.kind === "structured" ? (
                <>
                  <div className="detail-stats"><div><span>Rows</span><strong>{selected.profile.row_count?.toLocaleString()}</strong></div><div><span>Columns</span><strong>{selected.profile.column_count}</strong></div><div><span>Stage</span><strong>PostgreSQL</strong></div></div>
                  {selected.profile.staged_table && (
                    <div className="staging-relation"><Database size={17} /><span><small>Physical relation</small><strong>{selected.profile.staged_table.relation}</strong></span><StatusPill value="queryable" /></div>
                  )}
                  <div className="mapping-target">
                    <label>Target table<input value={targetTable} onChange={(event) => setTargetTable(event.target.value)} /></label>
                    <span><small>Workflow runs</small><strong>{selected.profile.confirmed_mapping ? "versioned" : "draft"}</strong></span>
                  </div>
                  <div className="ingestion-controls">
                    <div className="segmented" aria-label="Load mode">
                      {(["versioned", "replace", "append", "upsert"] as LoadMode[]).map((mode) => <button type="button" className={loadMode === mode ? "active" : ""} key={mode} onClick={() => setLoadMode(mode)}>{mode === "upsert" ? "Merge" : mode === "replace" ? "Replace" : mode === "append" ? "Append" : "Versioned"}</button>)}
                    </div>
                    {loadMode === "upsert" && <label>Merge key<select value={keyColumn} onChange={(event) => setKeyColumn(event.target.value)} required><option value="">Select column</option>{mappingColumns.map((column) => <option value={column.target_name} key={column.source_name}>{column.target_name}</option>)}</select></label>}
                  </div>
                  <div className="subheading"><h4>Schema mapping</h4><span>{mappingColumns.length} fields</span></div>
                  <div className="mapping-grid mapping-header"><span>Source</span><span>Target</span><span>Type</span><span>Nullable</span></div>
                  <div className="mapping-list">
                    {mappingColumns.map((column, index) => (
                      <div className="mapping-grid" key={column.source_name}>
                        <strong>{column.source_name}</strong>
                        <input value={column.target_name} onChange={(event) => updateMapping(index, { target_name: event.target.value })} aria-label={`Target name for ${column.source_name}`} />
                        <select value={column.target_type} onChange={(event) => updateMapping(index, { target_type: event.target.value as MappingColumn["target_type"] })} aria-label={`Target type for ${column.source_name}`}><option value="string">string</option><option value="integer">integer</option><option value="number">number</option><option value="boolean">boolean</option></select>
                        <input type="checkbox" checked={column.nullable} onChange={(event) => updateMapping(index, { nullable: event.target.checked })} aria-label={`${column.source_name} nullable`} />
                      </div>
                    ))}
                  </div>
                  <div className="mapping-actions"><button className="primary-button" onClick={saveAndStage} disabled={staging || !targetTable.trim() || (loadMode === "upsert" && !keyColumn)}>{staging ? <RefreshCw size={17} className="spin" /> : <Database size={17} />}{staging ? "Staging" : selected.profile.staged_table ? "Run mapping again" : "Confirm and stage"}</button></div>
                </>
              ) : (
                <div className="document-preview"><pre>{selected.profile.preview || "Metadata indexed."}</pre></div>
              )}
            </>
          ) : (
            <EmptyState icon={<CircleGauge size={24} />} title="Select a file profile" body="Schema, null counts, distinct values, and a safe sample appear here." />
          )}
        </section>
      </div>
      {showConnector && <Modal title={editingConnector ? "Edit connection" : "Add connection"} onClose={() => setShowConnector(false)}><form className="modal-form" onSubmit={saveConnector}><div className="form-grid"><label>Name<input value={connectorForm.name} onChange={(event) => setConnectorForm({ ...connectorForm, name: event.target.value })} required /></label><label>Connection type<select value={connectorForm.connector_type} onChange={(event) => setConnectorForm({ ...connectorForm, connector_type: event.target.value })}><option value="postgres">PostgreSQL</option><option value="sql_server">SQL Server</option><option value="oracle">Oracle</option><option value="teradata">Teradata</option><option value="bigquery">BigQuery</option><option value="local_files">Local files</option></select></label></div><div className="connector-type-note"><ShieldCheck size={16} />{connectorTypeHelp[connectorForm.connector_type]}</div><label>Description<textarea value={connectorForm.description} onChange={(event) => setConnectorForm({ ...connectorForm, description: event.target.value })} rows={3} placeholder="Business owner, domain, allowed use, and data sensitivity." /></label><div className="form-grid"><label>Host / project<input value={connectorForm.host} onChange={(event) => setConnectorForm({ ...connectorForm, host: event.target.value })} /></label><label>Database / dataset<input value={connectorForm.database} onChange={(event) => setConnectorForm({ ...connectorForm, database: event.target.value })} /></label></div><label>Secret reference<input value={connectorForm.secret_reference} onChange={(event) => setConnectorForm({ ...connectorForm, secret_reference: event.target.value })} placeholder="env:POSTGRES_CREDENTIALS" /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowConnector(false)}>Cancel</button><button className="primary-button"><Check size={17} />{editingConnector ? "Save connection" : "Add connection"}</button></div></form></Modal>}
    </div>
  );
}

function SQLView({ notify, seed, currentUser }: { notify: (message: string, tone?: "ok" | "error") => void; seed?: { question: string; dialect: string } | null; currentUser: SessionUser }) {
  const [question, setQuestion] = useState("Show monthly deposit-account growth and explain unusual changes");
  const [dialect, setDialect] = useState("postgres");
  const [connectorId, setConnectorId] = useState("");
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [sqlArtifacts, setSqlArtifacts] = useState<Artifact[]>([]);
  const [result, setResult] = useState<SQLResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [artifactId, setArtifactId] = useState<string | null>(null);
  const canSaveSql = ["admin", "engineer", "analyst"].includes(currentUser.role);
  const selectedConnector = connectors.find((connector) => connector.id === connectorId);
  const effectiveDialect = selectedConnector ? connectorDialectForType(selectedConnector.connector_type) : dialect;
  const loadSqlHistory = useCallback(() => api<Artifact[]>("/artifacts").then((items) => setSqlArtifacts(items.filter((item) => item.artifact_type === "sql"))), []);
  useEffect(() => {
    Promise.all([api<Connector[]>("/connectors").then(setConnectors), loadSqlHistory()]).catch(() => undefined);
  }, [loadSqlHistory]);
  useEffect(() => {
    if (!seed) return;
    setQuestion(seed.question);
    setDialect(seed.dialect);
    setConnectorId("");
    setResult(null);
    setArtifactId(null);
  }, [seed]);

  async function generate(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      setResult(await api<SQLResult>("/sql/generate", {
        method: "POST",
        body: JSON.stringify({ question, dialect: effectiveDialect, connector_id: connectorId || null }),
      }));
      notify("SQL draft generated and validated");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "SQL generation failed", "error");
    } finally {
      setLoading(false);
    }
  }
  async function runPreview() {
    if (!result) return;
    if (effectiveDialect !== "postgres") {
      notify("Local execution currently supports PostgreSQL; use the matching enterprise connector for this dialect", "error");
      return;
    }
    setExecuting(true);
    try {
      const execution = await api<SQLExecutionResult>("/sql/execute", {
        method: "POST",
        body: JSON.stringify({ sql: result.sql, dialect: "postgres", limit: 500 }),
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
    setSaving(true);
    try {
      const artifact = await api<{ id: string; version: number }>("/artifacts", {
        method: "POST",
        body: JSON.stringify({
          artifact_id: artifactId,
          name: question.slice(0, 120),
          artifact_type: "sql",
          content: result.sql,
          metadata: { dialect: effectiveDialect, question, connector_id: connectorId || null, validation: result.validation, sources: result.sources },
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
          <select value={connectorId} onChange={(event) => setConnectorId(event.target.value)} aria-label="SQL source connection"><option value="">Local PostgreSQL catalog</option>{connectors.map((connector) => <option key={connector.id} value={connector.id}>{connector.name} / {connectorLabels[connector.connector_type] || connector.connector_type}</option>)}</select>
          <select value={dialect} onChange={(event) => setDialect(event.target.value)} disabled={Boolean(connectorId)} aria-label="SQL dialect">
            <option value="sqlserver">SQL Server</option><option value="oracle">Oracle</option><option value="teradata">Teradata</option><option value="bigquery">BigQuery</option><option value="postgres">PostgreSQL</option>
          </select>
        </div>
      </div>
      <form className="sql-question surface" onSubmit={generate}>
        <Sparkles size={19} />
        <input value={question} onChange={(event) => setQuestion(event.target.value)} aria-label="Business question" />
        <button className="primary-button" disabled={loading}>{loading ? <RefreshCw size={17} className="spin" /> : <Play size={17} />}Generate</button>
      </form>
      {!result ? (
        <EmptyState icon={<Code2 size={26} />} title="Ready for a business question" body="The agent will show its SQL, evidence, validation checks, and a limited preview before anything can be saved." />
      ) : (
        <div className="sql-layout">
          <section className="surface code-panel">
            <div className="panel-toolbar"><span><Code2 size={16} />{result.dialect} | {selectedConnector?.name || result.provider.name}</span><StatusPill value={result.validation.status} /></div>
            <pre><code>{result.sql}</code></pre>
            <div className="code-actions"><button className="icon-button" onClick={() => sendFeedback("helpful")} title="Helpful result"><Check size={16} /></button><button className="icon-button" onClick={() => sendFeedback("not_helpful")} title="Result needs improvement"><XCircle size={16} /></button><button className="secondary-button" onClick={saveArtifact} disabled={saving || !canSaveSql}>{saving ? <RefreshCw size={16} className="spin" /> : <Archive size={16} />}Save artifact</button><button className="primary-button" onClick={runPreview} disabled={executing}>{executing ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}Run read-only preview</button></div>
          </section>
          <aside className="surface validation-panel">
            <div className="section-heading compact"><div><span className="eyebrow">EVIDENCE</span><h3>Validation</h3></div><StatusPill value={result.validation.risk_level} /></div>
            <p>{result.explanation}</p>
            {result.cache?.hit ? <div className="conversation-memory compact-memory"><span>Reuse</span><p>Reused a saved governed query for the same normalized question and source context.</p></div> : null}
            <div className="check-list">{result.validation.checks.map((check) => <div key={check}><Check size={15} />{check}</div>)}</div>
            <div className="subheading"><h4>Sources used</h4><span>{result.sources.length}</span></div>
            {result.sources.map((source, index) => <div className="source-row" key={index}><Database size={15} /><span><strong>{source.asset || source.term}</strong><small>{source.columns?.join(", ") || source.definition}</small></span></div>)}
            {result.grounding?.catalog_matches?.length ? <><div className="subheading"><h4>Catalog grounding</h4><span>{result.grounding.catalog_matches.length}</span></div>{result.grounding.catalog_matches.slice(0, 4).map((item) => <div className="source-row" key={`${item.relation}-${item.match_type}`}><Layers3 size={15} /><span><strong>{item.relation}</strong><small>{item.match_type} match / score {item.score}</small></span></div>)}</> : null}
            {result.grounding?.semantic_matches?.length ? <><div className="subheading"><h4>Semantic terms</h4><span>{result.grounding.semantic_matches.length}</span></div>{result.grounding.semantic_matches.slice(0, 3).map((item) => <div className="source-row" key={item.name}><Braces size={15} /><span><strong>{item.name}</strong><small>{item.formula} / {item.grain}</small></span></div>)}</> : null}
          </aside>
          <section className="surface preview-panel">
            <div className="section-heading compact"><div><span className="eyebrow">LIMITED PREVIEW</span><h3>Query result</h3></div><span className="caption">Maximum {result.validation.row_limit} rows</span></div>
            {result.preview.length ? <div className="data-table-wrap">
              <table><thead><tr>{Object.keys(result.preview[0] || {}).map((key) => <th key={key}>{key.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{result.preview.map((row, index) => <tr key={index}>{Object.values(row).map((value, valueIndex) => <td key={valueIndex}>{typeof value === "number" ? value.toLocaleString() : value}</td>)}</tr>)}</tbody></table>
            </div> : <div className="inline-empty">No local preview is available for this dialect.</div>}
          </section>
        </div>
      )}
      <section className="surface sql-history-surface">
        <div className="section-heading compact"><div><span className="eyebrow">SQL HISTORY</span><h3>Saved SQL artifacts</h3></div><StatusPill value={`${sqlArtifacts.length} saved`} /></div>
        {sqlArtifacts.length ? <div className="sql-history-list">{sqlArtifacts.slice(0, 8).map((artifact) => <button key={artifact.id} onClick={() => openSqlArtifact(artifact)}><Archive size={16} /><span><strong>{artifact.name}</strong><small>{String(artifact.metadata?.dialect || artifact.artifact_type)} / v{artifact.latest_version} / {new Date(artifact.updated_at).toLocaleString()}</small></span><ChevronRight size={16} /></button>)}</div> : <div className="inline-empty">Saved SQL from this project appears here. Conversation SQL stays inside each analysis thread until it is saved as a report or artifact.</div>}
      </section>
    </div>
  );
}

function PipelinesView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [objective, setObjective] = useState("Ingest daily transaction files, validate schema, and publish a clean local table");
  const [steps, setSteps] = useState<Job["plan"]>([]);
  const [busy, setBusy] = useState(false);
  const [schedules, setSchedules] = useState<IngestionSchedule[]>([]);
  const [mappings, setMappings] = useState<MappingOption[]>([]);
  const [showSchedule, setShowSchedule] = useState(false);
  const [showGenerator, setShowGenerator] = useState(false);
  const [pipelines, setPipelines] = useState<PipelineDefinition[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selectedPipeline, setSelectedPipeline] = useState<PipelineDefinition | null>(null);
  const [editingPipeline, setEditingPipeline] = useState<PipelineDefinition | null>(null);
  const [pipelineForm, setPipelineForm] = useState({ name: "", source_asset_id: "", target_schema: "curated", target_table: "" });
  const [scheduleForm, setScheduleForm] = useState({ name: "", mapping_id: "", cron: "0 6 * * *", load_mode: "append", key_column: "", watermark_column: "" });
  const loadSchedules = useCallback(() => Promise.all([api<IngestionSchedule[]>("/schedules"), api<MappingOption[]>("/ingestion-mappings"), api<PipelineDefinition[]>("/pipelines"), api<Dataset[]>("/datasets")]).then(([scheduleData, mappingData, pipelineData, datasetData]) => { setSchedules(scheduleData); setMappings(mappingData); setPipelines(pipelineData); setDatasets(datasetData); setSelectedPipeline((current) => pipelineData.find((item) => item.id === current?.id) || pipelineData[0] || null); setScheduleForm((current) => ({ ...current, mapping_id: current.mapping_id || mappingData[0]?.id || "" })); setPipelineForm((current) => ({ ...current, source_asset_id: current.source_asset_id || datasetData.find((item) => item.asset_type === "staged_file")?.id || datasetData[0]?.id || "" })); }), []);
  useEffect(() => { loadSchedules(); }, [loadSchedules]);
  const selectedMapping = mappings.find((mapping) => mapping.id === scheduleForm.mapping_id);
  async function draft() {
    setBusy(true);
    try {
      const result = await api<{ plan: Job["plan"]; approval_id?: string }>("/agents/runs", { method: "POST", body: JSON.stringify({ objective, autonomy_level: 3 }) });
      setSteps(result.plan);
      notify(result.approval_id ? "Pipeline draft is waiting for approval" : "Pipeline draft completed");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Could not draft pipeline", "error");
    } finally { setBusy(false); }
  }
  async function createSchedule(event: FormEvent) {
    event.preventDefault();
    try {
      const result = await api<{ approval_id: string }>("/schedules", { method: "POST", body: JSON.stringify({ name: scheduleForm.name, mapping_id: scheduleForm.mapping_id, cron: scheduleForm.cron, timezone: "UTC", load_mode: scheduleForm.load_mode, key_columns: scheduleForm.load_mode === "upsert" ? [scheduleForm.key_column] : [], watermark_column: scheduleForm.watermark_column || null }) });
      setShowSchedule(false);
      await loadSchedules();
      notify(`Schedule submitted for approval: ${result.approval_id.slice(0, 8)}`);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not create schedule", "error"); }
  }
  async function runSchedule(id: string) {
    try { const result = await api<{ status: string }>(`/schedules/${id}/run`, { method: "POST" }); notify(`Schedule run ${result.status.toLowerCase()}`); window.setTimeout(loadSchedules, 800); } catch (reason) { notify(reason instanceof Error ? reason.message : "Schedule run failed", "error"); }
  }
  function openPipelineGenerator(pipeline?: PipelineDefinition) {
    setEditingPipeline(pipeline || null);
    if (pipeline) {
      setPipelineForm((current) => ({ ...current, name: pipeline.name }));
      setObjective(pipeline.objective);
    } else {
      setPipelineForm((current) => ({ ...current, name: "", target_table: "" }));
    }
    setShowGenerator(true);
  }
  async function generatePipeline(event: FormEvent) {
    event.preventDefault();
    try {
      const saved = editingPipeline
        ? await api<PipelineDefinition>(`/pipelines/${editingPipeline.id}`, { method: "PUT", body: JSON.stringify({ name: pipelineForm.name, objective }) })
        : await api<PipelineDefinition>("/pipelines/generate", { method: "POST", body: JSON.stringify({ name: pipelineForm.name, objective, source_asset_ids: [pipelineForm.source_asset_id], target_schema: pipelineForm.target_schema, target_table: pipelineForm.target_table }) });
      setShowGenerator(false);
      setEditingPipeline(null);
      await loadSchedules();
      setSelectedPipeline(saved);
      notify(editingPipeline ? "Pipeline saved as a new draft version" : "Executable pipeline draft and lineage created");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Pipeline generation failed", "error"); }
  }
  async function deployPipeline(id: string) {
    try { await api(`/pipelines/${id}/deploy`, { method: "POST" }); await loadSchedules(); notify("Pipeline deployment submitted for approval"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Deployment request failed", "error"); }
  }
  async function deletePipeline(pipeline: PipelineDefinition) {
    if (!window.confirm(`Delete pipeline "${pipeline.name}" from the registry?`)) return;
    try {
      await api(`/pipelines/${pipeline.id}`, { method: "DELETE" });
      await loadSchedules();
      setSelectedPipeline((current) => current?.id === pipeline.id ? null : current);
      notify("Pipeline deleted from registry");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Pipeline could not be deleted", "error"); }
  }
  return (
    <div className="view-stack">
      <div className="view-header"><div><h2>Pipeline designer</h2><p>Generate versioned transformations from catalog datasets, review lineage, approve deployment, and schedule refreshes.</p></div><div className="row-actions"><button className="secondary-button" onClick={draft} disabled={busy}>{busy ? <RefreshCw className="spin" size={17} /> : <Sparkles size={17} />}Plan with agents</button><button className="primary-button" onClick={() => openPipelineGenerator()} disabled={!datasets.length}><Plus size={17} />New pipeline</button></div></div>
      <section className="surface pipeline-command"><label>Pipeline objective<textarea value={objective} onChange={(event) => setObjective(event.target.value)} rows={3} /></label></section>
      <section className="pipeline-canvas">
        {(selectedPipeline?.definition.nodes?.map((node) => ({ agent: node.type, action: node.label, status: selectedPipeline.status === "active" ? "complete" : "waiting" })) || (steps.length ? steps : [
          { agent: "Source", action: "Local file drop", status: "complete" },
          { agent: "Profile", action: "Infer and validate schema", status: "complete" },
          { agent: "Quality", action: "Run null and uniqueness checks", status: "waiting" },
          { agent: "Publish", action: "Write governed staging table", status: "waiting" },
        ])).map((step, index, all) => (
          <div className="pipeline-node-wrap" key={`${step.agent}-${index}`}>
            <div className={`pipeline-node ${step.status}`}><span className="node-icon">{index === 0 ? <FileUp size={18} /> : index === all.length - 1 ? <Database size={18} /> : <Bot size={18} />}</span><span><small>{step.agent}</small><strong>{step.action}</strong></span><StatusPill value={step.status} /></div>
            {index < all.length - 1 && <div className="pipeline-edge"><ChevronRight size={18} /></div>}
          </div>
        ))}
      </section>
      <section className="surface schedule-surface"><div className="section-heading"><div><span className="eyebrow">VERSIONED DEFINITIONS</span><h3>Generated pipelines</h3><p>Each draft contains executable local SQL, validation checks, and persisted source-to-target lineage.</p></div></div><div className="table-header pipeline-registry-grid"><span>Pipeline</span><span>Source to target</span><span>Version</span><span>Status</span><span /></div>{pipelines.map((pipeline) => <div className={`data-row pipeline-registry-grid ${selectedPipeline?.id === pipeline.id ? "selected" : ""}`} key={pipeline.id} onClick={() => setSelectedPipeline(pipeline)}><span><strong>{pipeline.name}</strong><small>{pipeline.objective}</small></span><span><strong>{pipeline.definition.target?.relation || "-"}</strong><small>{pipeline.definition.sources?.map((source) => source.relation).join(", ")}</small></span><span>v{pipeline.current_version}</span><StatusPill value={pipeline.status} /><span className="row-actions"><button className="icon-button" title="Edit pipeline" onClick={(event) => { event.stopPropagation(); openPipelineGenerator(pipeline); }}><Settings size={16} /></button>{pipeline.status === "draft" && <button className="icon-button" title="Request deployment approval" onClick={(event) => { event.stopPropagation(); deployPipeline(pipeline.id); }}><Play size={16} /></button>}<button className="icon-button" title="Delete pipeline" onClick={(event) => { event.stopPropagation(); deletePipeline(pipeline); }}><XCircle size={16} /></button></span></div>)}{!pipelines.length && <div className="inline-empty">Generate a pipeline from a real catalog dataset.</div>}{selectedPipeline?.generated_code && <pre className="registry-code"><code>{selectedPipeline.generated_code}</code></pre>}</section>
      <div className="policy-banner"><ShieldCheck size={19} /><span><strong>Controlled execution</strong><small>Writes, schedules, and external publication require an approval before the runner receives them.</small></span></div>
      <section className="surface schedule-surface">
        <div className="section-heading"><div><span className="eyebrow">DURABLE AUTOMATION</span><h3>Ingestion schedules</h3><p>Approved mappings run through the local worker with optional incremental watermarks.</p></div><button className="primary-button" onClick={() => setShowSchedule(true)} disabled={!mappings.length}><CalendarClock size={17} />Add schedule</button></div>
        <div className="table-header schedule-grid"><span>Schedule</span><span>Mapping</span><span>Mode</span><span>Next run</span><span /></div>
        {schedules.map((schedule) => <div className="data-row schedule-grid" key={schedule.id}><span><strong>{schedule.name}</strong><small>{schedule.cron} / UTC</small></span><span><strong>{schedule.target_table}</strong><small>{schedule.filename}</small></span><span><StatusPill value={schedule.enabled ? schedule.load_mode : "awaiting_approval"} />{schedule.last_watermark && <small>{schedule.last_watermark}</small>}</span><span>{schedule.next_run_at ? new Date(schedule.next_run_at).toLocaleString() : "-"}</span><button className="icon-button" title="Run now" disabled={!schedule.enabled} onClick={() => runSchedule(schedule.id)}><Play size={16} /></button></div>)}
        {!schedules.length && <div className="inline-empty">No ingestion schedules have been requested.</div>}
      </section>
      {showSchedule && <Modal title="Schedule ingestion" onClose={() => setShowSchedule(false)}><form className="modal-form" onSubmit={createSchedule}><label>Name<input value={scheduleForm.name} onChange={(event) => setScheduleForm({ ...scheduleForm, name: event.target.value })} required /></label><label>Mapping<select value={scheduleForm.mapping_id} onChange={(event) => setScheduleForm({ ...scheduleForm, mapping_id: event.target.value, key_column: "", watermark_column: "" })} required>{mappings.map((mapping) => <option value={mapping.id} key={mapping.id}>{mapping.filename} / {mapping.target_table}</option>)}</select></label><div className="form-grid"><label>Cron<input value={scheduleForm.cron} onChange={(event) => setScheduleForm({ ...scheduleForm, cron: event.target.value })} required /></label><label>Load mode<select value={scheduleForm.load_mode} onChange={(event) => setScheduleForm({ ...scheduleForm, load_mode: event.target.value })}><option value="append">Append</option><option value="upsert">Merge</option></select></label></div><div className="form-grid"><label>Watermark<select value={scheduleForm.watermark_column} onChange={(event) => setScheduleForm({ ...scheduleForm, watermark_column: event.target.value })}><option value="">None</option>{selectedMapping?.columns.map((column) => <option value={column.target_name} key={column.target_name}>{column.target_name}</option>)}</select></label>{scheduleForm.load_mode === "upsert" && <label>Merge key<select value={scheduleForm.key_column} onChange={(event) => setScheduleForm({ ...scheduleForm, key_column: event.target.value })} required><option value="">Select key</option>{selectedMapping?.columns.map((column) => <option value={column.target_name} key={column.target_name}>{column.target_name}</option>)}</select></label>}</div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowSchedule(false)}>Cancel</button><button className="primary-button"><CalendarClock size={17} />Request approval</button></div></form></Modal>}
      {showGenerator && <Modal title={editingPipeline ? "Edit pipeline" : "Generate executable pipeline"} onClose={() => { setShowGenerator(false); setEditingPipeline(null); }}><form className="modal-form" onSubmit={generatePipeline}><label>Name<input value={pipelineForm.name} onChange={(event) => setPipelineForm({ ...pipelineForm, name: event.target.value })} required /></label>{!editingPipeline && <><label>Source dataset<select value={pipelineForm.source_asset_id} onChange={(event) => setPipelineForm({ ...pipelineForm, source_asset_id: event.target.value })} required>{datasets.map((dataset) => <option value={dataset.id} key={dataset.id}>{dataset.schema_name}.{dataset.table_name} / {dataset.row_count ?? "unknown"} rows</option>)}</select></label><div className="form-grid"><label>Target schema<input value={pipelineForm.target_schema} onChange={(event) => setPipelineForm({ ...pipelineForm, target_schema: event.target.value })} required /></label><label>Target table<input value={pipelineForm.target_table} onChange={(event) => setPipelineForm({ ...pipelineForm, target_table: event.target.value })} required /></label></div></>}<label>Objective<textarea value={objective} onChange={(event) => setObjective(event.target.value)} rows={4} required /></label>{editingPipeline && <div className="modal-note"><GitBranch size={16} />Saving creates the next draft version and deployment must be requested again.</div>}<div className="modal-actions"><button type="button" className="secondary-button" onClick={() => { setShowGenerator(false); setEditingPipeline(null); }}>Cancel</button><button className="primary-button"><Sparkles size={16} />{editingPipeline ? "Save version" : "Generate"}</button></div></form></Modal>}
    </div>
  );
}

function JobsView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selected, setSelected] = useState<Job | null>(null);
  const [filter, setFilter] = useState<"all" | "running" | "action">("all");
  const load = useCallback(() => Promise.all([api<Job[]>("/jobs"), api<Incident[]>("/incidents")]).then(([data, incidentData]) => { setJobs(data); setIncidents(incidentData); setSelected((current) => data.find((item) => item.id === current?.id) || data[0] || null); }), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { const timer = window.setInterval(() => { if (jobs.some((job) => ["RUNNING", "QUEUED", "PLANNING", "RETRYING"].includes(job.status))) load(); }, 2000); return () => window.clearInterval(timer); }, [jobs, load]);
  const filtered = jobs.filter((job) => filter === "all" || (filter === "running" ? ["RUNNING", "QUEUED", "PLANNING"].includes(job.status) : ["WAITING_FOR_APPROVAL", "FAILED"].includes(job.status)));
  async function cancelSelected() {
    if (!selected) return;
    try { await api(`/jobs/${selected.id}/cancel`, { method: "POST" }); notify("Job cancelled"); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Job could not be cancelled", "error"); }
  }
  async function retrySelected() { if (!selected) return; try { const result = await api<{ status: string }>(`/jobs/${selected.id}/retry`, { method: "POST" }); notify(`Retry ${result.status.toLowerCase()}`); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Retry failed", "error"); } }
  async function diagnoseSelected() { if (!selected) return; try { await api(`/jobs/${selected.id}/diagnose`, { method: "POST" }); notify("Incident diagnosis recorded"); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Diagnosis failed", "error"); } }
  return (
    <div className="view-stack">
      <div className="view-header"><div><h2>Job operations</h2><p>Inspect state, progress, evidence, and every specialist handoff.</p></div><div className="segmented"><button className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>All</button><button className={filter === "running" ? "active" : ""} onClick={() => setFilter("running")}>Running</button><button className={filter === "action" ? "active" : ""} onClick={() => setFilter("action")}>Needs action</button></div></div>
      <div className="jobs-layout">
        <section className="surface jobs-table">
          <div className="table-header job-grid"><span>Job</span><span>Status</span><span>Progress</span><span>Created</span></div>
          {filtered.map((job) => (
            <button key={job.id} className={`data-row job-grid ${selected?.id === job.id ? "selected" : ""}`} onClick={() => setSelected(job)}>
              <span><strong>{job.title}</strong><small>{job.job_type.replaceAll("_", " ")}</small></span><StatusPill value={job.status} /><span className="progress-cell"><span><i style={{ width: `${job.progress}%` }} /></span><small>{job.progress}%</small></span><span>{new Date(job.created_at).toLocaleString()}</span>
            </button>
          ))}
        </section>
        <aside className="surface trace-panel">
          {selected ? <><div className="section-heading compact"><div><span className="eyebrow">RUN TRACE</span><h3>{selected.title}</h3></div><StatusPill value={selected.status} /></div>{["DRAFT", "PLANNING", "QUEUED", "RUNNING", "WAITING_FOR_APPROVAL", "RETRYING"].includes(selected.status) && <div className="trace-actions"><button className="danger-button" onClick={cancelSelected}><XCircle size={16} />Cancel job</button></div>}{["FAILED", "CANCELLED", "PARTIALLY_SUCCEEDED"].includes(selected.status) && <div className="trace-actions"><button className="secondary-button" onClick={diagnoseSelected}><AlertCircle size={16} />Diagnose</button><button className="primary-button" onClick={retrySelected}><RefreshCw size={16} />Retry</button></div>}<div className="trace-list">{selected.plan.map((step, index) => <div key={index}><span className={`trace-dot ${step.status}`} /> <span><strong>{step.agent}</strong><small>{step.action}</small></span><StatusPill value={step.status} /></div>)}</div><div className="subheading"><h4>Evidence</h4><span>{selected.evidence.length}</span></div><div className="evidence-list">{selected.evidence.map((item, index) => <span key={index}><Layers3 size={15} />{item.label}</span>)}</div><div className="subheading"><h4>Step outputs</h4><span>{selected.outputs?.length || 0}</span></div>{selected.outputs?.length ? <div className="log-list">{(selected.outputs || []).map((output, index) => <div key={`${output.at || output.title || output.type}-${index}`}><Layers3 size={14} /><span><strong>{output.title || output.type}</strong><small>{[output.agent, output.tool, output.summary, output.at ? new Date(output.at).toLocaleString() : ""].filter(Boolean).join(" / ")}</small>{output.data ? <pre className="trace-output-data">{JSON.stringify(output.data, null, 2)}</pre> : null}</span></div>)}</div> : <div className="inline-empty trace-empty">No step outputs were captured for this run.</div>}<div className="subheading"><h4>Execution log</h4><span>{selected.logs?.length || 0}</span></div><div className="log-list">{(selected.logs || []).map((entry, index) => <div key={`${entry.at}-${index}`}><Clock3 size={14} /><span><strong>{entry.message}</strong><small>{new Date(entry.at).toLocaleString()} / {entry.level}</small></span></div>)}</div>{incidents.filter((incident) => incident.job_id === selected.id).map((incident) => <div className="incident-box" key={incident.id}><div><AlertCircle size={17} /><strong>{incident.title}</strong><StatusPill value={incident.status} /></div><p>{incident.root_cause}</p>{incident.remediation.map((item) => <small key={item}>{item}</small>)}</div>)}</> : <LoadingBlock />}
        </aside>
      </div>
    </div>
  );
}

function ArtifactsView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [selected, setSelected] = useState<Artifact | null>(null);
  const [versions, setVersions] = useState<ArtifactVersion[]>([]);
  const [comments, setComments] = useState<ArtifactComment[]>([]);
  const [comment, setComment] = useState("");
  const [diff, setDiff] = useState("");

  useEffect(() => {
    api<Artifact[]>("/artifacts").then((data) => {
      setArtifacts(data);
      setSelected(data[0] || null);
    });
  }, []);

  useEffect(() => {
    if (!selected) {
      setVersions([]);
      return;
    }
    Promise.all([api<ArtifactVersion[]>(`/artifacts/${selected.id}/versions`), api<ArtifactComment[]>(`/artifacts/${selected.id}/comments`)]).then(([versionData, commentData]) => { setVersions(versionData); setComments(commentData); setDiff(""); });
  }, [selected]);

  async function comparePrevious() {
    if (!selected || versions.length < 2) return;
    const result = await api<{ diff: string }>(`/artifacts/${selected.id}/diff?from_version=${versions[1].version}&to_version=${versions[0].version}`);
    setDiff(result.diff || "No content changes");
  }
  async function addComment() {
    if (!selected || !comment.trim()) return;
    await api(`/artifacts/${selected.id}/comments`, { method: "POST", body: JSON.stringify({ body: comment, version: versions[0]?.version }) });
    setComment("");
    setComments(await api<ArtifactComment[]>(`/artifacts/${selected.id}/comments`));
    notify("Review comment added");
  }
  async function review(decision: "approved" | "changes_requested") {
    if (!selected) return;
    await api(`/artifacts/${selected.id}/review`, { method: "POST", body: JSON.stringify({ decision }) });
    setArtifacts((current) => current.map((artifact) => artifact.id === selected.id ? { ...artifact, status: decision } : artifact));
    setSelected({ ...selected, status: decision });
    notify(`Artifact ${decision.replaceAll("_", " ")}`);
  }

  return (
    <div className="view-stack">
      <div className="view-header"><div><h2>Artifact repository</h2><p>Versioned SQL, workflows, quality rules, prompts, and runbooks produced in the workspace.</p></div><StatusPill value={`${artifacts.length} artifacts`} /></div>
      {!artifacts.length ? <section className="surface"><EmptyState icon={<Archive size={26} />} title="No saved artifacts" body="Save an approved SQL draft or workflow to create its first durable version." /></section> : (
        <div className="artifact-layout">
          <section className="surface artifact-list">
            <div className="table-header artifact-grid"><span>Artifact</span><span>Type</span><span>Version</span><span>Updated</span></div>
            {artifacts.map((artifact) => <button key={artifact.id} className={`data-row artifact-grid ${selected?.id === artifact.id ? "selected" : ""}`} onClick={() => setSelected(artifact)}><span><strong>{artifact.name}</strong><small>{artifact.status}</small></span><StatusPill value={artifact.artifact_type} /><span className="mono">v{artifact.latest_version}</span><span>{new Date(artifact.updated_at).toLocaleString()}</span></button>)}
          </section>
          <aside className="surface artifact-detail">
            {selected && versions[0] ? <><div className="section-heading compact"><div><span className="eyebrow">LATEST VERSION</span><h3>{selected.name}</h3></div><StatusPill value={selected.status} /></div><pre><code>{diff || versions[0].content}</code></pre><div className="artifact-review-actions"><button className="secondary-button" disabled={versions.length < 2} onClick={comparePrevious}><GitCompare size={16} />Compare previous</button><button className="secondary-button" onClick={() => review("changes_requested")}><MessageSquare size={16} />Request changes</button><button className="primary-button" onClick={() => review("approved")}><Check size={16} />Approve</button></div><div className="subheading"><h4>Version history</h4><span>{versions.length}</span></div><div className="version-list">{versions.map((version) => <div key={version.id}><span className="version-number">v{version.version}</span><span><strong>{String(version.artifact_metadata.dialect || selected.artifact_type)}</strong><small>{new Date(version.created_at).toLocaleString()}</small></span></div>)}</div><div className="subheading"><h4>Review comments</h4><span>{comments.length}</span></div><div className="comment-composer"><input value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Add review comment" /><button className="icon-button" onClick={addComment} disabled={!comment.trim()} title="Add comment"><Send size={16} /></button></div><div className="comment-list">{comments.map((item) => <div key={item.id}><MessageSquare size={14} /><span><strong>{item.author}</strong><small>{item.body} / {new Date(item.created_at).toLocaleString()}</small></span></div>)}</div></> : <LoadingBlock label="Loading artifact" />}
          </aside>
        </div>
      )}
    </div>
  );
}

function NotebooksView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [selected, setSelected] = useState<Notebook | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api<Notebook[]>("/notebooks").then((data) => { setNotebooks(data); setSelected((current) => data.find((item) => item.id === current?.id) || data[0] || null); }), []);
  useEffect(() => { load(); }, [load]);
  async function createNotebook() {
    const result = await api<Notebook>("/notebooks", { method: "POST", body: JSON.stringify({ name: `Analysis ${new Date().toLocaleDateString()}`, cells: [{ id: "notes", type: "markdown", source: "# Analysis" }, { id: "query", type: "sql", source: "SELECT account_type, COUNT(*) AS account_count FROM core.accounts GROUP BY account_type ORDER BY account_count DESC" }, { id: "calculation", type: "python", source: "row_count = len(last_rows)\nrow_count" }] }) });
    await load();
    setSelected(result);
    notify("Notebook created");
  }
  function updateCell(id: string, source: string) { setSelected((current) => current ? { ...current, cells: current.cells.map((cell) => cell.id === id ? { ...cell, source } : cell) } : current); }
  function addCell(type: NotebookCellData["type"]) { setSelected((current) => current ? { ...current, cells: [...current.cells, { id: `cell-${Date.now()}`, type, source: type === "sql" ? "SELECT 1 AS value" : type === "python" ? "sum([1, 2, 3])" : "## Notes" }] } : current); }
  async function save(runAfter = false) {
    if (!selected) return;
    setBusy(true);
    try {
      const saved = await api<{ id: string }>("/notebooks", { method: "POST", body: JSON.stringify({ notebook_id: selected.id, name: selected.name, cells: selected.cells }) });
      if (runAfter) {
        const result = await api<{ status: string; outputs: Notebook["outputs"]; job_id: string }>(`/notebooks/${saved.id}/run`, { method: "POST" });
        notify(`Notebook ${result.status}; trace ${result.job_id.slice(0, 8)}`);
      } else notify("Notebook version saved");
      await load();
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Notebook operation failed", "error"); } finally { setBusy(false); }
  }
  async function remove() {
    if (!selected || !window.confirm(`Delete notebook "${selected.name}" and its version history?`)) return;
    try { await api(`/notebooks/${selected.id}`, { method: "DELETE" }); await load(); notify("Notebook deleted"); }
    catch (reason) { notify(reason instanceof Error ? reason.message : "Notebook could not be deleted", "error"); }
  }
  return <div className="view-stack"><div className="view-header"><div><h2>Governed notebooks</h2><p>Versioned SQL, notes, safe calculations, outputs, and review history.</p></div><button className="primary-button" onClick={createNotebook}><Plus size={17} />New notebook</button></div><div className="notebook-layout"><section className="surface notebook-list">{notebooks.map((notebook) => <button key={notebook.id} className={selected?.id === notebook.id ? "selected" : ""} onClick={() => setSelected(notebook)}><BookOpen size={17} /><span><strong>{notebook.name}</strong><small>v{notebook.version} / {notebook.status}</small></span><ChevronRight size={16} /></button>)}</section><section className="surface notebook-editor">{selected ? <><div className="section-heading compact"><div><span className="eyebrow">NOTEBOOK</span><input className="notebook-name" value={selected.name} onChange={(event) => setSelected({ ...selected, name: event.target.value })} aria-label="Notebook name" />{selected.job_id && <small className="notebook-run-link">Last run trace: <code>{selected.job_id}</code></small>}</div><div className="row-actions"><button className="icon-button" title="Delete notebook" onClick={remove} disabled={busy}><XCircle size={16} /></button><button className="secondary-button" onClick={() => save(false)} disabled={busy}><Archive size={16} />Save</button><button className="primary-button" onClick={() => save(true)} disabled={busy}>{busy ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}Run all</button></div></div><div className="notebook-toolbar"><button onClick={() => addCell("sql")}><Database size={15} />SQL</button><button onClick={() => addCell("python")}><Code2 size={15} />Python</button><button onClick={() => addCell("markdown")}><MessageSquare size={15} />Notes</button></div><div className="notebook-cells">{selected.cells.map((cell, index) => <div className="notebook-cell" key={cell.id}><div><span>{index + 1}</span><StatusPill value={cell.type} /></div><textarea value={cell.source} onChange={(event) => updateCell(cell.id, event.target.value)} rows={cell.type === "markdown" ? 3 : 5} aria-label={`${cell.type} cell ${index + 1}`} />{selected.outputs.find((output) => output.cell_id === cell.id) && <pre>{JSON.stringify(selected.outputs.find((output) => output.cell_id === cell.id), null, 2)}</pre>}</div>)}</div></> : <EmptyState icon={<BookOpen size={24} />} title="No notebook selected" body="Create a notebook to begin a governed local analysis." />}</section></div></div>;
}

function EvaluationsView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [sets, setSets] = useState<EvaluationSet[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<EvaluationSet | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "SQL grounding baseline", description: "Regression checks for governed SQL generation", case_name: "Account growth", question: "Show monthly deposit account growth", case_type: "sql_generation" as "sql_generation" | "agent_run", dialect: "postgres", expected_tables: "core.accounts", required_tokens: "select, limit", expected_agents: "Planner, Metadata, Policy", expected_tools: "catalog.search", expects_approval: "auto" });
  const load = useCallback(() => api<EvaluationSet[]>("/evaluations").then(setSets), []);
  useEffect(() => { load(); }, [load]);
  function openForm(item?: EvaluationSet) { const first = item?.cases[0]; setEditing(item || null); setForm(item ? { name: item.name, description: item.description || "", case_name: first?.name || "Case", question: first?.question || "", case_type: first?.case_type || "sql_generation", dialect: first?.dialect || "postgres", expected_tables: first?.expected_tables.join(", ") || "", required_tokens: first?.required_sql_tokens.join(", ") || "", expected_agents: first?.expected_agents?.join(", ") || "Planner, Metadata, Policy", expected_tools: first?.expected_tools?.join(", ") || "", expects_approval: first?.expects_approval === true ? "yes" : first?.expects_approval === false ? "no" : "auto" } : { name: "SQL grounding baseline", description: "Regression checks for governed SQL generation", case_name: "Account growth", question: "Show monthly deposit account growth", case_type: "sql_generation", dialect: "postgres", expected_tables: "core.accounts", required_tokens: "select, limit", expected_agents: "Planner, Metadata, Policy", expected_tools: "catalog.search", expects_approval: "auto" }); setShowForm(true); }
  async function create(event: FormEvent) { event.preventDefault(); try { await api(editing ? `/evaluations/${editing.id}` : "/evaluations", { method: editing ? "PUT" : "POST", body: JSON.stringify({ name: form.name, description: form.description, cases: [{ name: form.case_name, question: form.question, case_type: form.case_type, dialect: form.dialect, expected_tables: form.expected_tables.split(",").map((item) => item.trim()).filter(Boolean), required_sql_tokens: form.required_tokens.split(",").map((item) => item.trim()).filter(Boolean), expected_agents: form.expected_agents.split(",").map((item) => item.trim()).filter(Boolean), expected_tools: form.expected_tools.split(",").map((item) => item.trim()).filter(Boolean), expects_approval: form.expects_approval === "auto" ? null : form.expects_approval === "yes" }] }) }); setShowForm(false); setEditing(null); await load(); notify(editing ? "Evaluation version updated" : "Evaluation set created"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not save evaluation", "error"); } }
  async function run(id: string) { setRunning(id); try { const result = await api<{ score: number; status: string }>(`/evaluations/${id}/run`, { method: "POST", body: JSON.stringify({}) }); await load(); notify(`Evaluation ${result.status}: ${result.score}%`); } catch (reason) { notify(reason instanceof Error ? reason.message : "Evaluation failed", "error"); } finally { setRunning(null); } }
  async function remove(item: EvaluationSet) { if (!window.confirm(`Delete evaluation "${item.name}" and all replay results?`)) return; try { await api(`/evaluations/${item.id}`, { method: "DELETE" }); await load(); notify("Evaluation deleted"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Evaluation could not be deleted", "error"); } }
  return <div className="view-stack"><div className="view-header"><div><h2>Evaluation and replay</h2><p>Measure SQL grounding against expected sources and required query traits.</p></div><button className="primary-button" onClick={() => openForm()}><Plus size={17} />New evaluation</button></div><section className="surface evaluation-list"><div className="table-header evaluation-grid"><span>Evaluation</span><span>Cases</span><span>Latest score</span><span>Status</span><span /></div>{sets.map((item) => <div className="data-row evaluation-grid" key={item.id}><span><strong>{item.name}</strong><small>{item.description}</small></span><span>{item.cases.length}</span><strong>{item.latest_run ? `${item.latest_run.score}%` : "-"}</strong><StatusPill value={item.latest_run?.status || "not_run"} /><span className="row-actions"><button className="icon-button" title="Edit evaluation" onClick={() => openForm(item)}><Settings size={16} /></button><button className="secondary-button" onClick={() => run(item.id)} disabled={running === item.id}>{running === item.id ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}Replay</button><button className="icon-button" title="Delete evaluation" onClick={() => remove(item)}><XCircle size={16} /></button></span></div>)}</section>{showForm && <Modal title={editing ? "Edit evaluation" : "Create evaluation"} onClose={() => { setShowForm(false); setEditing(null); }}><form className="modal-form" onSubmit={create}><label>Name<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label><label>Description<input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label><label>Case name<input value={form.case_name} onChange={(event) => setForm({ ...form, case_name: event.target.value })} required /></label><label>Question<textarea value={form.question} onChange={(event) => setForm({ ...form, question: event.target.value })} rows={3} required /></label><div className="form-grid"><label>Dialect<select value={form.dialect} onChange={(event) => setForm({ ...form, dialect: event.target.value })}><option value="postgres">PostgreSQL</option><option value="sqlserver">SQL Server</option><option value="oracle">Oracle</option><option value="teradata">Teradata</option><option value="bigquery">BigQuery</option></select></label><label>Expected tables<input value={form.expected_tables} onChange={(event) => setForm({ ...form, expected_tables: event.target.value })} /></label></div><label>Required SQL tokens<input value={form.required_tokens} onChange={(event) => setForm({ ...form, required_tokens: event.target.value })} /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => { setShowForm(false); setEditing(null); }}>Cancel</button><button className="primary-button"><FlaskConical size={17} />{editing ? "Save" : "Create"}</button></div></form></Modal>}</div>;
}

function QualityView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [rules, setRules] = useState<QualityRule[]>([]);
  const [runs, setRuns] = useState<QualityRun[]>([]);
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [busyRuleId, setBusyRuleId] = useState<string | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [ruleForm, setRuleForm] = useState({ name: "", rule_type: "not_null", column_name: "", severity: "error", values: "", min: "", max: "" });
  const load = useCallback(() => Promise.all([
    api<Dataset[]>("/datasets"),
    api<QualityRule[]>("/quality/rules"),
    api<QualityRun[]>("/quality/runs"),
  ]).then(([datasetData, ruleData, runData]) => {
    setDatasets(datasetData);
    setRules(ruleData);
    setRuns(runData);
    setSelectedAssetId((current) => current || datasetData[0]?.id || "");
  }), []);
  useEffect(() => { load(); }, [load]);
  const selectedDataset = datasets.find((dataset) => dataset.id === selectedAssetId);

  async function suggest() {
    if (!selectedAssetId) return;
    setSuggesting(true);
    try {
      const created = await api<QualityRule[]>(`/quality/assets/${selectedAssetId}/suggest`, { method: "POST" });
      await load();
      notify(created.length ? `${created.length} grounded quality rules created` : "Suggested rules already exist");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Quality suggestions failed", "error");
    } finally { setSuggesting(false); }
  }

  async function createRule(event: FormEvent) {
    event.preventDefault();
    if (!selectedAssetId) return;
    const config = ruleForm.rule_type === "accepted_values"
      ? { values: ruleForm.values.split(",").map((value) => value.trim()).filter(Boolean) }
      : ruleForm.rule_type === "range"
        ? { min: ruleForm.min === "" ? null : Number(ruleForm.min), max: ruleForm.max === "" ? null : Number(ruleForm.max), allow_null: true }
        : {};
    try {
      await api("/quality/rules", { method: "POST", body: JSON.stringify({ asset_id: selectedAssetId, name: ruleForm.name, rule_type: ruleForm.rule_type, column_name: ruleForm.column_name, severity: ruleForm.severity, config }) });
      setShowForm(false);
      setRuleForm({ name: "", rule_type: "not_null", column_name: "", severity: "error", values: "", min: "", max: "" });
      await load();
      notify("Quality rule created and versioned");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Quality rule could not be created", "error"); }
  }

  async function runRule(rule: QualityRule) {
    setBusyRuleId(rule.id);
    try {
      const result = await api<QualityRun>(`/quality/rules/${rule.id}/run`, { method: "POST" });
      await load();
      notify(result.failed_rows ? `${result.failed_rows} rows written to quarantine` : `${result.checked_rows} rows passed`);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Quality execution failed", "error"); }
    finally { setBusyRuleId(null); }
  }

  const passing = runs.filter((run) => run.status === "passed").length;
  const failed = runs.filter((run) => run.status === "failed" || run.status === "error").length;
  const coveredAssets = new Set(rules.map((rule) => rule.asset_id)).size;
  return (
    <div className="view-stack">
      <div className="view-header"><div><h2>Data quality</h2><p>Execute governed checks against local datasets and isolate failed rows.</p></div><div className="quality-actions"><select value={selectedAssetId} onChange={(event) => setSelectedAssetId(event.target.value)} aria-label="Quality dataset">{datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.schema_name}.{dataset.table_name}</option>)}</select><button className="secondary-button" onClick={() => { setRuleForm((current) => ({ ...current, column_name: selectedDataset?.columns[0]?.name || "" })); setShowForm(true); }} disabled={!selectedDataset}><Plus size={17} />Add rule</button><button className="primary-button" onClick={suggest} disabled={suggesting || !selectedAssetId}>{suggesting ? <RefreshCw className="spin" size={17} /> : <Sparkles size={17} />}Suggest checks</button></div></div>
      <section className="metric-grid three"><Metric label="Coverage" value={`${coveredAssets}/${datasets.length}`} detail="Datasets with active rules" icon={<ShieldCheck size={19} />} tone="teal" /><Metric label="Passing runs" value={passing} detail="Real local evaluations" icon={<Check size={19} />} tone="blue" /><Metric label="Needs review" value={failed} detail="Failed or errored runs" icon={<AlertCircle size={19} />} tone="amber" /></section>
      <section className="surface"><div className="table-header quality-grid"><span>Dataset</span><span>Rule</span><span>Pass rate</span><span>Status</span><span /></div>{rules.length ? rules.map((rule) => <div className="data-row quality-grid" key={rule.id}><strong>{rule.dataset}</strong><span><strong>{rule.name}</strong><small>{rule.rule_type.replaceAll("_", " ")} / {rule.column_name}</small></span><span className="mono">{rule.latest_run ? `${rule.latest_run.pass_rate}%` : "Not run"}</span><StatusPill value={rule.latest_run?.status || "ready"} /><button className="icon-button" title="Run quality check" onClick={() => runRule(rule)} disabled={busyRuleId === rule.id}>{busyRuleId === rule.id ? <RefreshCw className="spin" size={16} /> : <Play size={16} />}</button></div>) : <EmptyState icon={<ShieldCheck size={24} />} title="No quality rules" body="Select a dataset and create or suggest its first executable check." />}</section>
      {runs.length > 0 && <section className="surface"><div className="section-heading compact"><div><span className="eyebrow">RUN HISTORY</span><h3>Recent evaluations</h3></div><StatusPill value={`${runs.length} runs`} /></div><div className="quality-run-list">{runs.slice(0, 8).map((run) => <div key={run.id}><span><strong>{run.rule_name}</strong><small>{run.dataset}</small></span><span className="mono">{run.failed_rows}/{run.checked_rows} failed</span><StatusPill value={run.status} /><span><small>Quarantine</small><strong>{run.quarantine_relation || "None"}</strong></span></div>)}</div></section>}
      {showForm && <Modal title="Add quality rule" onClose={() => setShowForm(false)}><form className="modal-form" onSubmit={createRule}><label>Name<input value={ruleForm.name} onChange={(event) => setRuleForm({ ...ruleForm, name: event.target.value })} required /></label><div className="form-grid"><label>Column<select value={ruleForm.column_name} onChange={(event) => setRuleForm({ ...ruleForm, column_name: event.target.value })} required>{selectedDataset?.columns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}</select></label><label>Rule type<select value={ruleForm.rule_type} onChange={(event) => setRuleForm({ ...ruleForm, rule_type: event.target.value })}><option value="not_null">Not null</option><option value="unique">Unique</option><option value="accepted_values">Accepted values</option><option value="range">Numeric range</option></select></label></div>{ruleForm.rule_type === "accepted_values" && <label>Accepted values<input value={ruleForm.values} onChange={(event) => setRuleForm({ ...ruleForm, values: event.target.value })} placeholder="active, closed, pending" required /></label>}{ruleForm.rule_type === "range" && <div className="form-grid"><label>Minimum<input type="number" value={ruleForm.min} onChange={(event) => setRuleForm({ ...ruleForm, min: event.target.value })} /></label><label>Maximum<input type="number" value={ruleForm.max} onChange={(event) => setRuleForm({ ...ruleForm, max: event.target.value })} /></label></div>}<label>Severity<select value={ruleForm.severity} onChange={(event) => setRuleForm({ ...ruleForm, severity: event.target.value })}><option value="error">Error</option><option value="warning">Warning</option></select></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary-button">Create rule</button></div></form></Modal>}
    </div>
  );
}

function SupersetView({ isAdmin, projectName }: { isAdmin: boolean; projectName: string }) {
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

function ApprovalsView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [selected, setSelected] = useState<Approval | null>(null);
  const [filter, setFilter] = useState<"pending" | "decided">("pending");
  const load = useCallback(() => api<Approval[]>("/approvals").then((data) => { setApprovals(data); setSelected((current) => data.find((item) => item.id === current?.id) || data[0] || null); }), []);
  useEffect(() => { load(); }, [load]);
  const filtered = approvals.filter((approval) => filter === "pending" ? approval.status === "pending" : approval.status !== "pending");
  async function decide(decision: "approved" | "rejected") {
    if (!selected) return;
    try {
      await api(`/approvals/${selected.id}/decision`, { method: "POST", body: JSON.stringify({ decision, note: decision === "approved" ? "Reviewed in local workspace" : "Returned for revision" }) });
      notify(`Action ${decision}`);
      await load();
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Decision failed", "error"); }
  }
  return (
    <div className="view-stack"><div className="view-header"><div><h2>Approval inbox</h2><p>Review evidence and decide every controlled write, schedule, or external action.</p></div><div className="segmented"><button className={filter === "pending" ? "active" : ""} onClick={() => { setFilter("pending"); setSelected(approvals.find((item) => item.status === "pending") || null); }}>Pending</button><button className={filter === "decided" ? "active" : ""} onClick={() => { setFilter("decided"); setSelected(approvals.find((item) => item.status !== "pending") || null); }}>Decided</button></div></div>
      <div className="approval-layout"><section className="surface approval-list">{filtered.map((approval) => <button key={approval.id} className={selected?.id === approval.id ? "selected" : ""} onClick={() => setSelected(approval)}><span className={`risk-mark ${approval.risk_level}`}><ShieldCheck size={18} /></span><span><strong>{approval.title}</strong><small>{approval.action_type.replaceAll("_", " ")} / {new Date(approval.created_at).toLocaleDateString()}</small></span><StatusPill value={approval.status} /><ChevronRight size={16} /></button>)}</section>
        <aside className="surface approval-detail">{selected ? <><div className="section-heading compact"><div><span className="eyebrow">DECISION REQUIRED</span><h3>{selected.title}</h3></div><StatusPill value={selected.risk_level} /></div><div className="evidence-box"><h4>Action summary</h4><p>{selected.evidence.summary || selected.evidence.objective}</p></div><div className="subheading"><h4>Guardrails and checks</h4></div><div className="check-list">{(selected.evidence.checks || selected.evidence.guardrails || []).map((check) => <div key={check}><ShieldCheck size={15} />{check}</div>)}</div><div className="approval-actions"><button className="danger-button" disabled={selected.status !== "pending"} onClick={() => decide("rejected")}><XCircle size={17} />Reject</button><button className="primary-button" disabled={selected.status !== "pending"} onClick={() => decide("approved")}><Check size={17} />Approve action</button></div></> : <EmptyState icon={<ShieldCheck size={24} />} title="No approvals" body="Controlled agent actions will appear here." />}</aside>
      </div>
    </div>
  );
}

function ToolsView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [kind, setKind] = useState<"internal" | "external">("internal");
  return <div className="view-stack"><div className="view-header"><div><h2>Tool registry</h2><p>Create reviewed internal integrations or publish controlled customer-data tools for external agents. Every path remains versioned and routed through DataPilot.</p></div></div><div className="tabs"><button className={kind === "internal" ? "active" : ""} onClick={() => setKind("internal")}><Boxes size={16} />Internal integrations</button><button className={kind === "external" ? "active" : ""} onClick={() => setKind("external")}><Network size={16} />External data tools</button></div>{kind === "internal" ? <AgentsView notify={notify} registryOnly /> : <GatewayAdmin notify={notify} />}</div>;
}

function AgentsView({ notify, registryOnly = false }: { notify: (message: string, tone?: "ok" | "error") => void; registryOnly?: boolean }) {
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [selected, setSelected] = useState<(AgentDefinition & { tools: ToolDefinition[] }) | null>(null);
  const [tools, setTools] = useState<ToolDefinition[]>([]);
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [selectedTool, setSelectedTool] = useState<ToolDefinition | null>(null);
  const [showAgentForm, setShowAgentForm] = useState(false);
  const [showToolForm, setShowToolForm] = useState(false);
  const [agentForm, setAgentForm] = useState({ name: "", purpose: "", instructions: "", autonomy_level: 2, tool_names: "catalog.search" });
  const [toolForm, setToolForm] = useState({ name: "", category: "integration", description: "", endpoint: "http://superset:8088/health", parameter_schema: '{"type":"object","properties":{},"additionalProperties":false}' });
  const [instructions, setInstructions] = useState("");
  const [agentTools, setAgentTools] = useState("");
  const [agentModel, setAgentModel] = useState("");
  const [toolParameters, setToolParameters] = useState("{}");
  const [toolVersionForm, setToolVersionForm] = useState({ endpoint: "", http_method: "POST", parameter_schema: "{}", timeout_seconds: 30, max_retries: 0, retry_backoff_seconds: 1 });
  const [policy, setPolicy] = useState<Record<string, unknown> | null>(null);
  const [agentMetadata, setAgentMetadata] = useState({ name: "", purpose: "", autonomy_level: 2, enabled: true, policy: "{}" });
  const [toolMetadata, setToolMetadata] = useState({ category: "", description: "", risk_level: "low", enabled: true, requires_approval: false });
  const [toolExecutions, setToolExecutions] = useState<{ id: string; tool_id: string; status: string; parameters: Record<string, unknown>; result: Record<string, unknown>; error?: string; duration_ms?: number; created_at: string }[]>([]);
  const loadRegistry = useCallback(() => Promise.all([api<AgentDefinition[]>("/agents"), api<ToolDefinition[]>("/tools"), api<ModelProvider[]>("/model-providers")]).then(([agentData, toolData, providerData]) => { setAgents(agentData); setTools(toolData); setProviders(providerData); }), []);
  useEffect(() => { loadRegistry().catch((reason) => notify(reason instanceof Error ? reason.message : "Registry unavailable", "error")); }, [loadRegistry, notify]);
  async function inspect(id: string) { try { const detail = await api<AgentDefinition & { tools: ToolDefinition[]; versions: AgentVersion[] }>(`/agents/${id}`); setSelectedTool(null); setSelected(detail); setAgentMetadata({ name: detail.name, purpose: detail.purpose, autonomy_level: detail.autonomy_level, enabled: detail.enabled, policy: JSON.stringify(detail.policy, null, 2) }); setInstructions(detail.versions?.[0]?.instructions || ""); setAgentTools((detail.versions?.[0]?.tool_names || detail.tool_names).join(", ")); setAgentModel(detail.versions?.[0]?.model_provider_id || ""); } catch (reason) { notify(reason instanceof Error ? reason.message : "Agent could not be loaded", "error"); } }
  async function inspectTool(id: string) { try { const [detail, executions] = await Promise.all([api<ToolDefinition>(`/tools/${id}`), api<typeof toolExecutions>("/tools/executions")]); setSelected(null); setSelectedTool(detail); setToolExecutions(executions.filter((item) => item.tool_id === id)); setToolMetadata({ category: detail.category, description: detail.description, risk_level: detail.risk_level, enabled: detail.enabled, requires_approval: detail.requires_approval }); setToolParameters("{}"); const version = detail.versions?.[0]; if (version) setToolVersionForm({ endpoint: version.endpoint || "", http_method: version.http_method, parameter_schema: JSON.stringify(version.parameter_schema, null, 2), timeout_seconds: version.timeout_seconds, max_retries: version.max_retries, retry_backoff_seconds: version.retry_backoff_seconds }); } catch (reason) { notify(reason instanceof Error ? reason.message : "Tool could not be loaded", "error"); } }
  async function loadPolicy() { try { setPolicy(await api<Record<string, unknown>>("/policies/effective")); } catch (reason) { notify(reason instanceof Error ? reason.message : "Policy could not be loaded", "error"); } }
  async function createAgent(event: FormEvent) { event.preventDefault(); try { await api("/agents", { method: "POST", body: JSON.stringify({ ...agentForm, tool_names: agentForm.tool_names.split(",").map((item) => item.trim()).filter(Boolean), enabled: true, policy: { writes_require_approval: true }, model_provider_id: null, input_schema: { type: "object", required: ["objective"], properties: { objective: { type: "string" } } }, config: { max_iterations: 4, max_tool_calls: 12 } }) }); setShowAgentForm(false); await loadRegistry(); notify("Agent draft created"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Agent could not be created", "error"); } }
  async function saveAgentVersion() { if (!selected) return; try { const created = await api<AgentVersion>(`/agents/${selected.id}/versions`, { method: "POST", body: JSON.stringify({ instructions, model_provider_id: agentModel || null, tool_names: agentTools.split(",").map((item) => item.trim()).filter(Boolean), input_schema: selected.versions?.[0]?.input_schema || { type: "object" }, config: selected.versions?.[0]?.config || {} }) }); await inspect(selected.id); await loadRegistry(); notify(`Agent version ${created.version} saved as draft`); } catch (reason) { notify(reason instanceof Error ? reason.message : "Agent version could not be saved", "error"); } }
  async function publishAgentVersion() { if (!selected?.versions?.[0]) return; try { await api(`/agents/${selected.id}/versions/${selected.versions[0].version}/publish`, { method: "POST" }); await inspect(selected.id); await loadRegistry(); notify("Agent version published"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Agent version could not be published", "error"); } }
  async function createTool(event: FormEvent) { event.preventDefault(); try { await api("/tools", { method: "POST", body: JSON.stringify({ ...toolForm, implementation_type: "http", http_method: "POST", parameter_schema: JSON.parse(toolForm.parameter_schema), result_schema: { type: "object" }, permissions: ["integration:invoke"], timeout_seconds: 30, max_retries: 1, retry_backoff_seconds: 1, cost_class: "low", environment: "local", risk_level: "medium", enabled: true, requires_approval: true, handler_name: "" }) }); setShowToolForm(false); await loadRegistry(); notify("Tool draft created; admin publication is required"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Tool could not be created", "error"); } }
  async function publishToolVersion() { const latest = selectedTool?.versions?.[0]; if (!selectedTool || !latest) return; try { await api(`/tools/${selectedTool.id}/versions/${latest.version}/publish`, { method: "POST" }); await inspectTool(selectedTool.id); await loadRegistry(); notify("Tool version published"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Tool version could not be published", "error"); } }
  async function saveToolVersion() { const latest = selectedTool?.versions?.[0]; if (!selectedTool || !latest) return; try { const created = await api<ToolVersion>(`/tools/${selectedTool.id}/versions`, { method: "POST", body: JSON.stringify({ implementation_type: latest.implementation_type, handler_name: latest.handler_name, endpoint: toolVersionForm.endpoint || null, http_method: toolVersionForm.http_method, parameter_schema: JSON.parse(toolVersionForm.parameter_schema), result_schema: latest.result_schema, permissions: latest.permissions, timeout_seconds: toolVersionForm.timeout_seconds, max_retries: toolVersionForm.max_retries, retry_backoff_seconds: toolVersionForm.retry_backoff_seconds, cost_class: latest.cost_class, environment: latest.environment }) }); await inspectTool(selectedTool.id); await loadRegistry(); notify(`Tool version ${created.version} saved as draft`); } catch (reason) { notify(reason instanceof Error ? reason.message : "Tool version could not be saved", "error"); } }
  async function executeSelectedTool() { if (!selectedTool) return; try { const result = await api<{ status: string; approval_id?: string; result?: unknown }>(`/tools/${selectedTool.id}/execute`, { method: "POST", body: JSON.stringify({ parameters: JSON.parse(toolParameters) }) }); notify(result.approval_id ? "Tool execution is waiting for approval" : `Tool execution ${result.status.toLowerCase()}`); await inspectTool(selectedTool.id); } catch (reason) { notify(reason instanceof Error ? reason.message : "Tool execution failed", "error"); } }
  async function saveAgentMetadata() { if (!selected) return; try { await api(`/agents/${selected.id}`, { method: "PUT", body: JSON.stringify({ ...agentMetadata, policy: JSON.parse(agentMetadata.policy) }) }); await inspect(selected.id); await loadRegistry(); notify("Agent metadata updated"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Agent metadata could not be updated", "error"); } }
  async function saveToolMetadata() { if (!selectedTool) return; try { await api(`/tools/${selectedTool.id}`, { method: "PUT", body: JSON.stringify(toolMetadata) }); await inspectTool(selectedTool.id); await loadRegistry(); notify("Tool metadata updated"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Tool metadata could not be updated", "error"); } }
  const iconFor = (name: string) => name === "Planner" ? Network : name === "Metadata" ? Database : name === "SQL Analyst" ? Code2 : name === "Pipeline" ? GitBranch : name === "Quality" ? ShieldCheck : Activity;
  if (selected && typeof window !== "undefined") {
    return <div className="view-stack registry-editor-page"><div className="view-header"><div className="registry-title"><button className="icon-button" title="Back to registry" onClick={() => setSelected(null)}><ChevronRight className="back-icon" size={18} /></button><span><span className="eyebrow">AGENT / {selected.versions?.[0]?.status || "UNVERSIONED"}</span><h2>{selected.name}</h2><p>Identity, run policy, model binding, allowed tools, and immutable instruction versions.</p></span></div><div className="row-actions"><button className="secondary-button" onClick={saveAgentMetadata}><Archive size={16} />Save metadata</button><button className="primary-button" onClick={saveAgentVersion}><Plus size={16} />New version</button></div></div><div className="registry-editor-layout"><section className="surface registry-form-section"><div className="section-heading compact"><div><span className="eyebrow">IDENTITY</span><h3>Agent definition</h3></div><StatusPill value={agentMetadata.enabled ? "enabled" : "disabled"} /></div><div className="registry-form-body"><label>Name<input value={agentMetadata.name} onChange={(event) => setAgentMetadata({ ...agentMetadata, name: event.target.value })} /></label><label>Purpose<textarea rows={5} value={agentMetadata.purpose} onChange={(event) => setAgentMetadata({ ...agentMetadata, purpose: event.target.value })} /></label><div className="form-grid"><label>Autonomy level<select value={agentMetadata.autonomy_level} onChange={(event) => setAgentMetadata({ ...agentMetadata, autonomy_level: Number(event.target.value) })}><option value={0}>0 / explain</option><option value={1}>1 / recommend</option><option value={2}>2 / read only</option><option value={3}>3 / approval gated</option></select></label><label>State<select value={agentMetadata.enabled ? "enabled" : "disabled"} onChange={(event) => setAgentMetadata({ ...agentMetadata, enabled: event.target.value === "enabled" })}><option value="enabled">Enabled</option><option value="disabled">Disabled</option></select></label></div><label>Policy JSON<textarea className="mono-input" rows={7} value={agentMetadata.policy} onChange={(event) => setAgentMetadata({ ...agentMetadata, policy: event.target.value })} /></label></div></section><section className="surface registry-form-section"><div className="section-heading compact"><div><span className="eyebrow">RUNTIME</span><h3>Published binding</h3></div><StatusPill value={`level_${agentMetadata.autonomy_level}`} /></div><div className="registry-form-body"><label>Model provider<select value={agentModel} onChange={(event) => setAgentModel(event.target.value)}><option value="">Use project model</option>{providers.filter((provider) => provider.enabled).map((provider) => <option value={provider.id} key={provider.id}>{provider.name} / {provider.default_model}</option>)}</select></label><label>Allowed tool names<textarea rows={4} value={agentTools} onChange={(event) => setAgentTools(event.target.value)} /></label><div className="resolved-tools">{selected.tools.map((tool) => <div key={tool.id}><Boxes size={15} /><span><strong>{tool.name}</strong><small>{tool.category} / {tool.risk_level}</small></span><StatusPill value={tool.requires_approval ? "approval_required" : "allowed"} /></div>)}</div></div></section></div><section className="surface registry-form-section"><div className="section-heading compact"><div><span className="eyebrow">INSTRUCTIONS</span><h3>Draft next version</h3></div><span className="mono">v{(selected.versions?.[0]?.version || 0) + 1}</span></div><div className="registry-form-body"><textarea className="code-editor" rows={18} value={instructions} onChange={(event) => setInstructions(event.target.value)} /><div className="form-end"><button className="primary-button" onClick={saveAgentVersion}><Archive size={16} />Save immutable version</button></div></div></section><section className="surface"><div className="section-heading compact"><div><span className="eyebrow">HISTORY</span><h3>Agent versions</h3></div></div><div className="table-header registry-version-grid"><span>Version</span><span>Model</span><span>Tools</span><span>Created</span><span>Status</span><span /></div>{selected.versions?.map((version) => <div className="data-row registry-version-grid" key={version.id}><strong>v{version.version}</strong><span>{providers.find((provider) => provider.id === version.model_provider_id)?.name || "Project model"}</span><span>{version.tool_names.length}</span><span>{new Date(version.created_at).toLocaleString()}</span><StatusPill value={version.status} /><button className="icon-button" title="Publish version" disabled={version.status === "published"} onClick={async () => { await api(`/agents/${selected.id}/versions/${version.version}/publish`, { method: "POST" }); await inspect(selected.id); await loadRegistry(); notify(`Agent version ${version.version} published`); }}><Check size={16} /></button></div>)}</section></div>;
  }
  if (selectedTool && typeof window !== "undefined") {
    const latest = selectedTool.versions?.[0];
    return <div className="view-stack registry-editor-page"><div className="view-header"><div className="registry-title"><button className="icon-button" title="Back to registry" onClick={() => setSelectedTool(null)}><ChevronRight className="back-icon" size={18} /></button><span><span className="eyebrow">TOOL / {latest?.implementation_type || "DEFINITION"}</span><h2>{selectedTool.name}</h2><p>Metadata, executable contract, validated parameters, publication, and run history.</p></span></div><div className="row-actions"><button className="secondary-button" onClick={saveToolMetadata}><Archive size={16} />Save metadata</button><button className="primary-button" onClick={saveToolVersion} disabled={!latest}><Plus size={16} />New version</button></div></div><div className="registry-editor-layout"><section className="surface registry-form-section"><div className="section-heading compact"><div><span className="eyebrow">IDENTITY</span><h3>Tool definition</h3></div><StatusPill value={toolMetadata.enabled ? "enabled" : "disabled"} /></div><div className="registry-form-body"><label>Name<input value={selectedTool.name} disabled /></label><div className="form-grid"><label>Category<input value={toolMetadata.category} onChange={(event) => setToolMetadata({ ...toolMetadata, category: event.target.value })} /></label><label>Risk<select value={toolMetadata.risk_level} onChange={(event) => setToolMetadata({ ...toolMetadata, risk_level: event.target.value })}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></label></div><label>Description<textarea rows={5} value={toolMetadata.description} onChange={(event) => setToolMetadata({ ...toolMetadata, description: event.target.value })} /></label><div className="form-grid"><label>State<select value={toolMetadata.enabled ? "enabled" : "disabled"} onChange={(event) => setToolMetadata({ ...toolMetadata, enabled: event.target.value === "enabled" })}><option value="enabled">Enabled</option><option value="disabled">Disabled</option></select></label><label>Approval<select value={toolMetadata.requires_approval ? "required" : "not_required"} onChange={(event) => setToolMetadata({ ...toolMetadata, requires_approval: event.target.value === "required" })}><option value="not_required">Not required</option><option value="required">Required</option></select></label></div></div></section><section className="surface registry-form-section"><div className="section-heading compact"><div><span className="eyebrow">EXECUTION TEST</span><h3>Published contract</h3></div><StatusPill value={latest?.status || "unversioned"} /></div><div className="registry-form-body"><label>Input parameters JSON<textarea className="mono-input" rows={9} value={toolParameters} onChange={(event) => setToolParameters(event.target.value)} /></label><button className="primary-button wide" onClick={executeSelectedTool} disabled={!latest || latest.status !== "published"}><Play size={16} />Execute published version</button><div className="policy-banner"><ShieldCheck size={18} /><span><strong>{latest?.permissions.join(", ") || "No declared permissions"}</strong><small>{latest ? `${latest.timeout_seconds}s timeout / ${latest.max_retries} retries / ${latest.cost_class} cost class` : "Create an executable version first"}</small></span></div></div></section></div>{latest && <section className="surface registry-form-section"><div className="section-heading compact"><div><span className="eyebrow">CONTRACT EDITOR</span><h3>Draft next executable version</h3></div><span className="mono">v{latest.version + 1}</span></div><div className="registry-form-body"><div className="form-grid"><label>HTTP method<select value={toolVersionForm.http_method} onChange={(event) => setToolVersionForm({ ...toolVersionForm, http_method: event.target.value })} disabled={latest.implementation_type !== "http"}><option value="GET">GET</option><option value="POST">POST</option><option value="PUT">PUT</option><option value="PATCH">PATCH</option></select></label><label>Endpoint<input value={toolVersionForm.endpoint} onChange={(event) => setToolVersionForm({ ...toolVersionForm, endpoint: event.target.value })} disabled={latest.implementation_type !== "http"} /></label></div><div className="form-grid"><label>Timeout seconds<input type="number" min={1} max={300} value={toolVersionForm.timeout_seconds} onChange={(event) => setToolVersionForm({ ...toolVersionForm, timeout_seconds: Number(event.target.value) })} /></label><label>Maximum retries<input type="number" min={0} max={5} value={toolVersionForm.max_retries} onChange={(event) => setToolVersionForm({ ...toolVersionForm, max_retries: Number(event.target.value) })} /></label></div><label>Parameter JSON Schema<textarea className="code-editor" rows={14} value={toolVersionForm.parameter_schema} onChange={(event) => setToolVersionForm({ ...toolVersionForm, parameter_schema: event.target.value })} /></label><div className="form-end"><button className="primary-button" onClick={saveToolVersion}><Archive size={16} />Save immutable version</button></div></div></section>}<section className="surface"><div className="section-heading compact"><div><span className="eyebrow">VERSION HISTORY</span><h3>Executable versions</h3></div></div><div className="table-header tool-version-grid"><span>Version</span><span>Binding</span><span>Limits</span><span>Created</span><span>Status</span><span /></div>{selectedTool.versions?.map((version) => <div className="data-row tool-version-grid" key={version.id}><strong>v{version.version}</strong><span>{version.handler_name || version.endpoint}</span><span>{version.timeout_seconds}s / {version.max_retries} retries</span><span>{new Date(version.created_at).toLocaleString()}</span><StatusPill value={version.status} /><button className="icon-button" title="Publish version" disabled={version.status === "published"} onClick={async () => { await api(`/tools/${selectedTool.id}/versions/${version.version}/publish`, { method: "POST" }); await inspectTool(selectedTool.id); await loadRegistry(); notify(`Tool version ${version.version} published`); }}><Check size={16} /></button></div>)}</section><section className="surface"><div className="section-heading compact"><div><span className="eyebrow">EXECUTION HISTORY</span><h3>Recent runs</h3></div><span>{toolExecutions.length}</span></div><div className="table-header tool-run-grid"><span>Created</span><span>Status</span><span>Duration</span><span>Parameters</span></div>{toolExecutions.length ? toolExecutions.map((execution) => <div className="data-row tool-run-grid" key={execution.id}><span>{new Date(execution.created_at).toLocaleString()}</span><StatusPill value={execution.status} /><span>{execution.duration_ms ?? "-"} ms</span><code>{JSON.stringify(execution.parameters)}</code></div>) : <div className="inline-empty">No executions for this tool in the current project.</div>}</section></div>;
  }
  return (
    <div className="view-stack">{!registryOnly && <div className="view-header"><div><h2>Agent registry and tool marketplace</h2><p>Version agent instructions and model bindings, parameterize executable tools, publish reviewed contracts, and inspect every run.</p></div><div className="row-actions"><button className="secondary-button" onClick={loadPolicy}><Settings size={17} />Run policy</button><button className="secondary-button" onClick={() => setShowToolForm(true)}><Boxes size={17} />New tool</button><button className="primary-button" onClick={() => setShowAgentForm(true)}><Plus size={17} />New agent</button></div></div>}{registryOnly && <section className="surface"><div className="section-heading"><div><span className="eyebrow">INTERNAL INTEGRATIONS</span><h3>Versioned execution contracts</h3><p>Register allowlisted HTTP or built-in tools, validate typed inputs, then publish a reviewed version for agents.</p></div><div className="row-actions"><button className="secondary-button" onClick={loadPolicy}><Settings size={17} />Run policy</button><button className="primary-button" onClick={() => setShowToolForm(true)}><Boxes size={17} />New internal tool</button></div></div></section>}
      {!registryOnly && <div className="agent-grid">{agents.map((agent) => { const Icon = iconFor(agent.name); return <article className="agent-card" key={agent.id}><div className="agent-title"><span><Icon size={20} /></span><StatusPill value={agent.enabled ? "ready" : "disabled"} /></div><h3>{agent.name}</h3><p>{agent.purpose}</p><div className="agent-meta"><span><Boxes size={15} />{agent.tool_names.length} allowed tools</span><span><ShieldCheck size={15} />Level {agent.autonomy_level}</span></div><button className="secondary-button wide" onClick={() => inspect(agent.id)}>Inspect agent <ChevronRight size={16} /></button></article>; })}</div>}
      <section className="surface registry-surface"><div className="section-heading"><div><span className="eyebrow">TOOL MARKETPLACE</span><h3>Published execution contracts</h3><p>Inputs are validated against JSON Schema before an allowlisted backend or HTTP handler can run.</p></div></div><div className="table-header tool-registry-grid"><span>Tool</span><span>Implementation</span><span>Version</span><span>Risk</span><span /></div>{tools.map((tool) => <button className="data-row tool-registry-grid" key={tool.id} onClick={() => inspectTool(tool.id)}><span><strong>{tool.name}</strong><small>{tool.description}</small></span><span>{tool.implementation_type || "definition only"}</span><span>v{tool.current_version || 0} / {tool.version_status}</span><StatusPill value={tool.requires_approval ? "approval_required" : tool.risk_level} /><ChevronRight size={16} /></button>)}</section>
      {selected && <Modal title={selected.name} onClose={() => setSelected(null)}><p className="modal-description">{selected.purpose}</p><div className="policy-banner"><ShieldCheck size={18} /><span><strong>Autonomy level {selected.autonomy_level}</strong><small>{JSON.stringify(selected.policy)}</small></span></div><label>Agent instructions<textarea value={instructions} onChange={(event) => setInstructions(event.target.value)} rows={10} /></label><div className="form-grid"><label>Model provider<select value={agentModel} onChange={(event) => setAgentModel(event.target.value)}><option value="">Use project model</option>{providers.filter((provider) => provider.enabled).map((provider) => <option value={provider.id} key={provider.id}>{provider.name} / {provider.default_model}</option>)}</select></label><label>Allowed tool names<input value={agentTools} onChange={(event) => setAgentTools(event.target.value)} /></label></div><div className="subheading"><h4>Resolved tools</h4><span>{selected.tools.length}</span></div><div className="tool-list">{selected.tools.map((tool) => <div key={tool.id}><span><strong>{tool.name}</strong><small>{tool.description}</small></span><StatusPill value={tool.requires_approval ? "approval_required" : tool.risk_level} /></div>)}</div><div className="modal-actions"><button className="secondary-button" onClick={saveAgentVersion}><Archive size={16} />Save new version</button><button className="primary-button" onClick={publishAgentVersion} disabled={selected.versions?.[0]?.status === "published"}><Check size={16} />Publish v{selected.versions?.[0]?.version || 0}</button></div></Modal>}
      {selectedTool && <Modal title={selectedTool.name} onClose={() => setSelectedTool(null)}><p className="modal-description">{selectedTool.description}</p>{selectedTool.versions?.[0] ? <><div className="policy-details"><div><span>Implementation</span><strong>{selectedTool.versions[0].implementation_type} / {selectedTool.versions[0].handler_name || selectedTool.versions[0].endpoint}</strong></div><div><span>Permissions</span><strong>{selectedTool.versions[0].permissions.join(", ") || "none"}</strong></div><div><span>State</span><strong>v{selectedTool.versions[0].version} / {selectedTool.versions[0].status}</strong></div></div>{selectedTool.versions[0].implementation_type === "http" && <label>Endpoint<input value={toolVersionForm.endpoint} onChange={(event) => setToolVersionForm({ ...toolVersionForm, endpoint: event.target.value })} /></label>}<div className="form-grid"><label>Timeout seconds<input type="number" value={toolVersionForm.timeout_seconds} onChange={(event) => setToolVersionForm({ ...toolVersionForm, timeout_seconds: Number(event.target.value) })} /></label><label>Maximum retries<input type="number" value={toolVersionForm.max_retries} onChange={(event) => setToolVersionForm({ ...toolVersionForm, max_retries: Number(event.target.value) })} /></label></div><label>Parameter JSON Schema<textarea value={toolVersionForm.parameter_schema} onChange={(event) => setToolVersionForm({ ...toolVersionForm, parameter_schema: event.target.value })} rows={7} /></label><label>Test parameters (JSON)<textarea value={toolParameters} onChange={(event) => setToolParameters(event.target.value)} rows={5} /></label><div className="modal-actions"><button className="secondary-button" onClick={saveToolVersion}><Archive size={16} />Save new version</button><button className="secondary-button" onClick={publishToolVersion} disabled={selectedTool.versions[0].status === "published"}><Check size={16} />Publish</button><button className="primary-button" onClick={executeSelectedTool} disabled={selectedTool.versions[0].status !== "published"}><Play size={16} />Execute tool</button></div></> : <div className="inline-empty">This definition has no executable version.</div>}</Modal>}
      {showAgentForm && <Modal title="Create agent" onClose={() => setShowAgentForm(false)}><form className="modal-form" onSubmit={createAgent}><label>Name<input value={agentForm.name} onChange={(event) => setAgentForm({ ...agentForm, name: event.target.value })} required /></label><label>Purpose<textarea value={agentForm.purpose} onChange={(event) => setAgentForm({ ...agentForm, purpose: event.target.value })} rows={3} required /></label><label>Instructions<textarea value={agentForm.instructions} onChange={(event) => setAgentForm({ ...agentForm, instructions: event.target.value })} rows={8} required /></label><div className="form-grid"><label>Autonomy<select value={agentForm.autonomy_level} onChange={(event) => setAgentForm({ ...agentForm, autonomy_level: Number(event.target.value) })}><option value={0}>0 - explain</option><option value={1}>1 - recommend</option><option value={2}>2 - read only</option><option value={3}>3 - approval gated</option></select></label><label>Tool names<input value={agentForm.tool_names} onChange={(event) => setAgentForm({ ...agentForm, tool_names: event.target.value })} /></label></div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowAgentForm(false)}>Cancel</button><button className="primary-button"><Plus size={16} />Create draft</button></div></form></Modal>}
      {showToolForm && <Modal title="Register HTTP tool" onClose={() => setShowToolForm(false)}><form className="modal-form" onSubmit={createTool}><div className="form-grid"><label>Name<input value={toolForm.name} onChange={(event) => setToolForm({ ...toolForm, name: event.target.value })} placeholder="team.service.action" required /></label><label>Category<input value={toolForm.category} onChange={(event) => setToolForm({ ...toolForm, category: event.target.value })} required /></label></div><label>Description<textarea value={toolForm.description} onChange={(event) => setToolForm({ ...toolForm, description: event.target.value })} rows={3} required /></label><label>Allowlisted endpoint<input value={toolForm.endpoint} onChange={(event) => setToolForm({ ...toolForm, endpoint: event.target.value })} required /></label><label>Parameter JSON Schema<textarea value={toolForm.parameter_schema} onChange={(event) => setToolForm({ ...toolForm, parameter_schema: event.target.value })} rows={8} required /></label><div className="modal-note"><ShieldCheck size={16} />New integrations are draft, approval-gated, and must target TOOL_HTTP_ALLOWLIST.</div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowToolForm(false)}>Cancel</button><button className="primary-button"><Boxes size={16} />Register draft</button></div></form></Modal>}
      {policy && <Modal title="Effective run policy" onClose={() => setPolicy(null)}><div className="policy-details">{Object.entries(policy).map(([key, value]) => <div key={key}><span>{key.replaceAll("_", " ")}</span><strong>{Array.isArray(value) ? value.join(", ") : String(value)}</strong></div>)}</div></Modal>}
    </div>
  );
}

function SemanticView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [metrics, setMetrics] = useState<SemanticMetric[]>([]);
  const [editing, setEditing] = useState<SemanticMetric | null>(null);
  const [showForm, setShowForm] = useState(false);
  const emptyForm = { name: "", description: "", formula: "", grain: "", owner: "", dimensions: "", synonyms: "", status: "draft" };
  const [form, setForm] = useState(emptyForm);
  const load = useCallback(() => api<SemanticMetric[]>("/semantic/metrics").then(setMetrics), []);
  useEffect(() => { load().catch((reason) => notify(reason instanceof Error ? reason.message : "Semantic metrics unavailable", "error")); }, [load, notify]);
  function openMetric(metric?: SemanticMetric) { setEditing(metric || null); setForm(metric ? { name: metric.name, description: metric.description || "", formula: metric.formula, grain: metric.grain, owner: metric.owner, dimensions: metric.dimensions.join(", "), synonyms: metric.synonyms.join(", "), status: metric.status } : emptyForm); setShowForm(true); }
  async function save(event: FormEvent) { event.preventDefault(); const payload = { ...form, dimensions: form.dimensions.split(",").map((item) => item.trim()).filter(Boolean), synonyms: form.synonyms.split(",").map((item) => item.trim()).filter(Boolean) }; try { await api(editing ? `/semantic/metrics/${editing.id}` : "/semantic/metrics", { method: editing ? "PUT" : "POST", body: JSON.stringify(payload) }); setShowForm(false); await load(); notify(editing ? "Metric updated" : "Metric created"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Metric could not be saved", "error"); } }
  async function remove(metric: SemanticMetric) { try { await api(`/semantic/metrics/${metric.id}`, { method: "DELETE" }); await load(); notify("Metric removed"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Metric could not be removed", "error"); } }
  return (
    <div className="view-stack"><div className="view-header"><div><h2>Semantic layer</h2><p>Approved metrics, joins, synonyms, and business definitions used to ground every agent response.</p></div><button className="primary-button" onClick={() => openMetric()}><Plus size={17} />Add metric</button></div>
      <div className="semantic-layout"><section className="surface"><div className="section-heading compact"><div><span className="eyebrow">PROJECT METRICS</span><h3>Business calculations</h3></div></div>{metrics.map((metric) => <div className="metric-definition" key={metric.id}><span className="semantic-icon"><Braces size={18} /></span><button className="metric-main" onClick={() => openMetric(metric)}><strong>{metric.name}</strong><small>{metric.formula}</small></button><span><small>Grain</small><strong>{metric.grain}</strong></span><span><small>Owner</small><strong>{metric.owner}</strong></span><span className="row-actions"><StatusPill value={metric.status} /><button className="icon-button" title="Delete metric" onClick={() => remove(metric)}><XCircle size={16} /></button></span></div>)}</section>
        <JoinPoliciesPanel notify={notify} />
      </div>
      {showForm && <Modal title={editing ? "Edit metric" : "Add metric"} onClose={() => setShowForm(false)}><form className="modal-form" onSubmit={save}><label>Name<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label><label>Description<input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label><label>Formula<textarea value={form.formula} onChange={(event) => setForm({ ...form, formula: event.target.value })} rows={3} required /></label><div className="form-grid"><label>Grain<input value={form.grain} onChange={(event) => setForm({ ...form, grain: event.target.value })} required /></label><label>Owner<input value={form.owner} onChange={(event) => setForm({ ...form, owner: event.target.value })} required /></label></div><div className="form-grid"><label>Dimensions<input value={form.dimensions} onChange={(event) => setForm({ ...form, dimensions: event.target.value })} placeholder="status, segment" /></label><label>Synonyms<input value={form.synonyms} onChange={(event) => setForm({ ...form, synonyms: event.target.value })} /></label></div><label>Status<select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}><option value="draft">Draft</option><option value="approved">Approved</option><option value="deprecated">Deprecated</option></select></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary-button"><Check size={17} />Save metric</button></div></form></Modal>}
    </div>
  );
}

function JoinPoliciesPanel({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const emptyForm = { left_asset_id: "", right_asset_id: "", left_column: "", right_column: "", join_type: "inner" as "inner" | "left", description: "", status: "draft" };
  const [policies, setPolicies] = useState<SemanticJoinPolicy[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [editing, setEditing] = useState<SemanticJoinPolicy | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const load = useCallback(async () => { const [policyData, datasetData] = await Promise.all([api<SemanticJoinPolicy[]>("/semantic/joins"), api<Dataset[]>("/datasets")]); setPolicies(policyData); setDatasets(datasetData); }, []);
  useEffect(() => { load().catch((reason) => notify(reason instanceof Error ? reason.message : "Join policies unavailable", "error")); }, [load, notify]);
  const leftAsset = datasets.find((item) => item.id === form.left_asset_id);
  const rightAsset = datasets.find((item) => item.id === form.right_asset_id);
  const relation = (id: string) => { const asset = datasets.find((item) => item.id === id); return asset ? `${asset.schema_name}.${asset.table_name}` : "Dataset unavailable"; };
  function openPolicy(policy?: SemanticJoinPolicy) { const left = policy ? datasets.find((item) => item.id === policy.left_asset_id) : datasets[0]; const right = policy ? datasets.find((item) => item.id === policy.right_asset_id) : datasets.find((item) => item.id !== left?.id); setEditing(policy || null); setForm(policy ? { left_asset_id: policy.left_asset_id, right_asset_id: policy.right_asset_id, left_column: policy.left_column, right_column: policy.right_column, join_type: policy.join_type, description: policy.description || "", status: policy.status } : { ...emptyForm, left_asset_id: left?.id || "", right_asset_id: right?.id || "", left_column: left?.columns[0]?.name || "", right_column: right?.columns[0]?.name || "" }); setShowForm(true); }
  async function save(event: FormEvent) { event.preventDefault(); try { await api(editing ? `/semantic/joins/${editing.id}` : "/semantic/joins", { method: editing ? "PUT" : "POST", body: JSON.stringify(form) }); setShowForm(false); await load(); notify(editing ? "Join policy updated" : "Join policy created"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Join policy could not be saved", "error"); } }
  async function remove(policy: SemanticJoinPolicy) { try { await api(`/semantic/joins/${policy.id}`, { method: "DELETE" }); await load(); notify("Join policy removed"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Join policy could not be removed", "error"); } }
  return <aside className="surface"><div className="section-heading compact"><div><span className="eyebrow">JOIN POLICY</span><h3>Approved paths</h3></div><button className="icon-button" title="Add join policy" onClick={() => openPolicy()} disabled={datasets.length < 2}><Plus size={16} /></button></div>{policies.length ? <div className="check-list">{policies.map((policy) => <div key={policy.id}><button className="metric-main" onClick={() => openPolicy(policy)}><strong>{relation(policy.left_asset_id)} {policy.join_type.toUpperCase()} {relation(policy.right_asset_id)}</strong><small>{policy.left_column} = {policy.right_column}{policy.description ? ` · ${policy.description}` : ""}</small></button><StatusPill value={policy.status} /><button className="icon-button" title="Delete join policy" onClick={() => remove(policy)}><XCircle size={15} /></button></div>)}</div> : <div className="empty-state"><Network size={18} /><p>No governed join paths yet.</p><small>Approved policies take precedence over inferred identifiers in pipeline generation.</small></div>}<div className="check-list"><div><ShieldCheck size={15} />Only approved policies are used automatically.</div></div>{showForm && <Modal title={editing ? "Edit join policy" : "Add join policy"} onClose={() => setShowForm(false)}><form className="modal-form" onSubmit={save}><div className="form-grid"><label>Left dataset<select value={form.left_asset_id} onChange={(event) => { const asset = datasets.find((item) => item.id === event.target.value); const right = form.right_asset_id === asset?.id ? datasets.find((item) => item.id !== asset?.id) : undefined; setForm({ ...form, left_asset_id: event.target.value, left_column: asset?.columns[0]?.name || "", right_asset_id: right?.id || form.right_asset_id, right_column: right?.columns[0]?.name || form.right_column }); }} required>{datasets.map((asset) => <option key={asset.id} value={asset.id}>{asset.schema_name}.{asset.table_name}</option>)}</select></label><label>Right dataset<select value={form.right_asset_id} onChange={(event) => { const asset = datasets.find((item) => item.id === event.target.value); setForm({ ...form, right_asset_id: event.target.value, right_column: asset?.columns[0]?.name || "" }); }} required>{datasets.filter((asset) => asset.id !== form.left_asset_id).map((asset) => <option key={asset.id} value={asset.id}>{asset.schema_name}.{asset.table_name}</option>)}</select></label></div><div className="form-grid"><label>Left column<select value={form.left_column} onChange={(event) => setForm({ ...form, left_column: event.target.value })} required>{leftAsset?.columns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}</select></label><label>Right column<select value={form.right_column} onChange={(event) => setForm({ ...form, right_column: event.target.value })} required>{rightAsset?.columns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}</select></label></div><div className="form-grid"><label>Join type<select value={form.join_type} onChange={(event) => setForm({ ...form, join_type: event.target.value as "inner" | "left" })}><option value="inner">Inner join</option><option value="left">Left join</option></select></label><label>Status<select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}><option value="draft">Draft</option><option value="approved">Approved</option><option value="deprecated">Deprecated</option></select></label></div><label>Description<input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="Business meaning and cardinality assumptions" /></label><div className="policy-banner"><ShieldCheck size={18} /><span><strong>Generation guardrail</strong><small>For a left join, select the left dataset first when building a pipeline.</small></span></div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary-button"><Check size={17} />Save policy</button></div></form></Modal>}</aside>;
}

function AdminView({ currentUser, notify }: { currentUser: SessionUser; notify: (message: string, tone?: "ok" | "error") => void }) {
  const [tab, setTab] = useState<"users" | "projects" | "connectors" | "models" | "gateway" | "governance" | "auth">("connectors");
  return (
    <div className="view-stack">
      <div className="view-header"><div><h2>Administration</h2><p>Configure local access, data sources, model routing, and enterprise identity.</p></div><StatusPill value={currentUser.role} /></div>
      <div className="tabs"><button className={tab === "connectors" ? "active" : ""} onClick={() => setTab("connectors")}><Server size={16} />Connectors</button><button className={tab === "models" ? "active" : ""} onClick={() => setTab("models")}><Bot size={16} />Model providers</button><button className={tab === "gateway" ? "active" : ""} onClick={() => setTab("gateway")}><Network size={16} />Tool gateway</button><button className={tab === "governance" ? "active" : ""} onClick={() => setTab("governance")}><ShieldCheck size={16} />Governance</button><button className={tab === "projects" ? "active" : ""} onClick={() => setTab("projects")}><Layers3 size={16} />Projects</button><button className={tab === "users" ? "active" : ""} onClick={() => setTab("users")}><Users size={16} />Users</button><button className={tab === "auth" ? "active" : ""} onClick={() => setTab("auth")}><KeyRound size={16} />Authentication</button></div>
      {tab === "connectors" && <ConnectorsAdmin notify={notify} />}
      {tab === "models" && <ModelsAdmin notify={notify} />}
      {tab === "gateway" && <GatewayAdmin notify={notify} />}
      {tab === "governance" && <GovernanceAdmin notify={notify} />}
      {tab === "projects" && <ProjectsAdmin notify={notify} />}
      {tab === "users" && <UsersAdmin notify={notify} />}
      {tab === "auth" && <AuthAdmin notify={notify} />}
    </div>
  );
}

function GatewayAdmin({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
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
  if (showWizard) return <QueryToolWizard notify={notify} onCancel={() => setShowWizard(false)} onUse={(draft) => { setSelected(null); setToolForm({ name: draft.name, description: draft.description, purpose: draft.purpose, data_source: draft.data_source, line_of_business: draft.line_of_business, owner: draft.owner, tags: draft.tags.join(", "), connector_id: draft.connector_id || "", upstream_tool_name: draft.upstream_tool_name || "", sql_template: draft.sql_template, parameter_schema: JSON.stringify(draft.parameter_schema, null, 2), allowed_relations: draft.allowed_relations.join(", "), row_limit: draft.row_limit, timeout_seconds: draft.timeout_seconds }); setTestParameters("{}"); setGrantClient(clients[0]?.id || ""); setShowWizard(false); setShowTool(true); }} />;
  return <div className="view-stack">
    <section className="surface admin-surface">
      <div className="section-heading"><div><span className="eyebrow">EXTERNAL AGENT ACCESS</span><h3>Governed query gateway</h3><p>Published parameterized tools are searchable by purpose, source, LOB, owner, and tags over REST and MCP.</p></div><div className="row-actions"><button className="secondary-button" onClick={() => setShowWizard(true)}><Database size={16} />Catalog wizard</button><button className="secondary-button" onClick={() => startFromTemplate("lookup")}><Database size={16} />Lookup template</button><button className="secondary-button" onClick={() => startFromTemplate("count")}><FlaskConical size={16} />Count template</button><button className="secondary-button" onClick={() => { setIssuedToken(""); setShowClient(true); }}><KeyRound size={16} />New client</button><button className="primary-button" onClick={() => openTool()}><Plus size={16} />New query tool</button></div></div>
      <div className="metric-grid three"><Metric label="Published" value={summary?.published ?? "-"} detail="Available to granted clients" icon={<Check size={18} />} tone="teal" /><Metric label="Invocations" value={summary?.tools.reduce((total, tool) => total + tool.invocation_count, 0) ?? "-"} detail="Audited external requests" icon={<Network size={18} />} tone="blue" /><Metric label="Never invoked" value={summary?.never_invoked ?? "-"} detail="Review for adoption or retirement" icon={<AlertCircle size={18} />} tone="amber" /></div>
      <div className="table-header gateway-tool-grid"><span>Tool</span><span>Connector</span><span>Version</span><span>Status</span><span /></div>
      {tools.map((tool) => <div className="data-row gateway-tool-grid" key={tool.id}><button className="metric-main" onClick={() => openTool(tool)}><strong>{tool.name}</strong><small>{tool.line_of_business} · {tool.purpose}</small></button><span>{connectors.find((item) => item.id === tool.connector_id)?.name || "Local PostgreSQL"}</span><span>v{tool.version}</span><StatusPill value={tool.status} /><button className="icon-button" title="Publish query tool" disabled={tool.status === "published"} onClick={() => publish(tool)}><Check size={16} /></button></div>)}
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

function QueryToolWizard({ notify, onCancel, onUse }: { notify: (message: string, tone?: "ok" | "error") => void; onCancel: () => void; onUse: (draft: QueryToolDraft) => void }) {
  const [relations, setRelations] = useState<RelationOption[]>([]);
  const [assetId, setAssetId] = useState("");
  const [template, setTemplate] = useState<"record_lookup" | "filtered_count" | "recent_records">("record_lookup");
  const [column, setColumn] = useState("");
  const [generating, setGenerating] = useState(false);
  useEffect(() => { api<RelationOption[]>("/query-tools/relation-options").then((items) => { setRelations(items); setAssetId(items[0]?.asset_id || ""); setColumn(items[0]?.columns[0]?.name || ""); }).catch((reason) => notify(reason instanceof Error ? reason.message : "Catalog relations unavailable", "error")); }, [notify]);
  const selected = relations.find((item) => item.asset_id === assetId);
  function chooseAsset(id: string) { const next = relations.find((item) => item.asset_id === id); setAssetId(id); setColumn(next?.columns[0]?.name || ""); }
  async function generate() { if (!selected || !column) return; setGenerating(true); try { const payload = template === "record_lookup" ? { asset_id: selected.asset_id, template, key_column: column } : template === "filtered_count" ? { asset_id: selected.asset_id, template, filter_column: column } : { asset_id: selected.asset_id, template, time_column: column }; const result = await api<{ suggested_tool: QueryToolDraft }>("/query-tools/wizard/preview", { method: "POST", body: JSON.stringify(payload) }); onUse(result.suggested_tool); notify("Catalog-grounded query tool draft generated"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not generate a query tool draft", "error"); } finally { setGenerating(false); } }
  const columnLabel = template === "record_lookup" ? "Identifier column" : template === "filtered_count" ? "Filter column" : "Time column";
  return <div className="view-stack"><div className="view-header"><div><h2>Catalog query-tool wizard</h2><p>Select a governed relation and column. The generated contract remains a draft for review, testing, publication, and grants.</p></div><button className="secondary-button" onClick={onCancel}>Back to gateway</button></div><section className="surface admin-surface"><form className="modal-form" onSubmit={(event) => { event.preventDefault(); void generate(); }}><label>Relation<select value={assetId} onChange={(event) => chooseAsset(event.target.value)} required>{relations.map((relation) => <option value={relation.asset_id} key={relation.asset_id}>{relation.relation} / {relation.connector_name}</option>)}</select></label>{selected && <div className="policy-banner"><Database size={18} /><span><strong>{selected.source_name}</strong><small>{selected.tags.join(", ") || "No catalog tags"}</small></span></div>}<div className="form-grid"><label>Contract template<select value={template} onChange={(event) => setTemplate(event.target.value as "record_lookup" | "filtered_count" | "recent_records")}><option value="record_lookup">Record lookup</option><option value="filtered_count">Count by filter</option><option value="recent_records">Recent records</option></select></label><label>{columnLabel}<select value={column} onChange={(event) => setColumn(event.target.value)} required>{selected?.columns.map((item) => <option key={item.name} value={item.name}>{item.name} / {item.type}</option>)}</select></label></div><div className="modal-actions"><button type="button" className="secondary-button" onClick={onCancel}>Cancel</button><button className="primary-button" disabled={!selected || !column || generating}>{generating ? <RefreshCw size={16} className="spin" /> : <Sparkles size={16} />}Generate draft</button></div></form></section></div>;
}

function GovernanceAdmin({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const emptyPrompt = { name: "", system_prompt: "", template: "", variables: "" };
  const [prompts, setPrompts] = useState<PromptArtifact[]>([]);
  const [policies, setPolicies] = useState<RetentionPolicy[]>([]);
  const [showPrompt, setShowPrompt] = useState(false);
  const [editing, setEditing] = useState<PromptArtifact | null>(null);
  const [promptForm, setPromptForm] = useState(emptyPrompt);
  const [rollbackVersion, setRollbackVersion] = useState(1);
  const [retentionForm, setRetentionForm] = useState({ resource_type: "audit_events", retention_days: 365, enabled: true });
  const load = useCallback(async () => { const [promptData, retentionData] = await Promise.all([api<PromptArtifact[]>("/prompts"), api<RetentionPolicy[]>("/retention-policies")]); setPrompts(promptData); setPolicies(retentionData); }, []);
  useEffect(() => { load().catch((reason) => notify(reason instanceof Error ? reason.message : "Governance configuration unavailable", "error")); }, [load, notify]);
  function openPrompt(prompt?: PromptArtifact) { setEditing(prompt || null); setPromptForm(prompt ? { name: prompt.name, system_prompt: prompt.content.system_prompt || "", template: prompt.content.template || "", variables: (prompt.content.variables || []).join(", ") } : emptyPrompt); setRollbackVersion(1); setShowPrompt(true); }
  async function savePrompt(event: FormEvent) { event.preventDefault(); try { await api("/prompts", { method: "POST", body: JSON.stringify({ ...promptForm, variables: promptForm.variables.split(",").map((item) => item.trim()).filter(Boolean), prompt_id: editing?.id || null, metadata: {} }) }); setShowPrompt(false); await load(); notify("Prompt draft version saved"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Prompt could not be saved", "error"); } }
  async function publishPrompt(prompt: PromptArtifact) { try { await api(`/artifacts/${prompt.id}/review`, { method: "POST", body: JSON.stringify({ decision: "approved", note: "Published from prompt governance" }) }); await load(); notify("Prompt approved"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Prompt could not be approved", "error"); } }
  async function rollbackPrompt() { if (!editing) return; try { await api(`/prompts/${editing.id}/rollback`, { method: "POST", body: JSON.stringify({ version: rollbackVersion }) }); setShowPrompt(false); await load(); notify(`Prompt rolled back from version ${rollbackVersion}`); } catch (reason) { notify(reason instanceof Error ? reason.message : "Prompt rollback failed", "error"); } }
  async function saveRetention(event: FormEvent) { event.preventDefault(); try { await api("/retention-policies", { method: "POST", body: JSON.stringify(retentionForm) }); await load(); notify("Retention policy saved"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Retention policy could not be saved", "error"); } }
  async function runRetention(policy: RetentionPolicy) { try { const result = await api<{ candidate_count: number }>(`/retention-policies/${policy.id}/run`, { method: "POST" }); notify(`${result.candidate_count} expired records sent for approval`); } catch (reason) { notify(reason instanceof Error ? reason.message : "Retention preview failed", "error"); } }
  return <div className="governance-layout"><section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">PROMPT LIFECYCLE</span><h3>Versioned prompts</h3><p>Draft, review, approve, and roll back reusable model instructions.</p></div><button className="primary-button" onClick={() => openPrompt()}><Plus size={16} />New prompt</button></div><div className="table-header prompt-grid"><span>Prompt</span><span>Version</span><span>Status</span><span /></div>{prompts.map((prompt) => <div className="data-row prompt-grid" key={prompt.id}><button className="metric-main" onClick={() => openPrompt(prompt)}><strong>{prompt.name}</strong><small>{(prompt.content.variables || []).join(", ") || "No variables"}</small></button><span>v{prompt.version}</span><StatusPill value={prompt.status} /><button className="icon-button" title="Approve prompt" disabled={prompt.status === "approved"} onClick={() => publishPrompt(prompt)}><Check size={16} /></button></div>)}</section><section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">DATA LIFECYCLE</span><h3>Retention controls</h3><p>Preview expired operational records and route permanent deletion through approval.</p></div></div><form className="inline-admin-form retention-form" onSubmit={saveRetention}><select value={retentionForm.resource_type} onChange={(event) => setRetentionForm({ ...retentionForm, resource_type: event.target.value })}><option value="audit_events">Audit events</option><option value="model_call_logs">Model call logs</option><option value="external_invocations">External invocations</option><option value="user_feedback">User feedback</option></select><input type="number" min={1} max={3650} value={retentionForm.retention_days} onChange={(event) => setRetentionForm({ ...retentionForm, retention_days: Number(event.target.value) })} aria-label="Retention days" /><button className="primary-button"><Archive size={16} />Save</button></form><div className="table-header retention-grid"><span>Resource</span><span>Days</span><span>Status</span><span /></div>{policies.map((policy) => <div className="data-row retention-grid" key={policy.id}><strong>{policy.resource_type.replaceAll("_", " ")}</strong><span>{policy.retention_days}</span><StatusPill value={policy.enabled ? "enabled" : "disabled"} /><button className="secondary-button" onClick={() => runRetention(policy)}><Play size={15} />Preview and run</button></div>)}</section>{showPrompt && <Modal title={editing ? `Edit ${editing.name}` : "Create prompt"} onClose={() => setShowPrompt(false)}><form className="modal-form" onSubmit={savePrompt}><label>Name<input value={promptForm.name} onChange={(event) => setPromptForm({ ...promptForm, name: event.target.value })} required /></label><label>System prompt<textarea rows={7} value={promptForm.system_prompt} onChange={(event) => setPromptForm({ ...promptForm, system_prompt: event.target.value })} required /></label><label>Template<textarea rows={7} value={promptForm.template} onChange={(event) => setPromptForm({ ...promptForm, template: event.target.value })} required /></label><label>Variables<input value={promptForm.variables} onChange={(event) => setPromptForm({ ...promptForm, variables: event.target.value })} placeholder="question, catalog_context" /></label>{editing && <div className="inline-admin-form prompt-rollback"><input type="number" min={1} max={editing.version} value={rollbackVersion} onChange={(event) => setRollbackVersion(Number(event.target.value))} aria-label="Rollback source version" /><button type="button" className="secondary-button" onClick={rollbackPrompt}><RefreshCw size={16} />Rollback</button></div>}<div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowPrompt(false)}>Cancel</button><button className="primary-button"><Archive size={16} />Save version</button></div></form></Modal>}</div>;
}

function ProjectsAdmin({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
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

function ConnectorsAdmin({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
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
  async function remove(connector: Connector) { if (!window.confirm(`Delete connector "${connector.name}"?`)) return; try { await api(`/connectors/${connector.id}`, { method: "DELETE" }); await load(); notify("Connector deleted"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Connector could not be deleted", "error"); } }
  async function acknowledge(id: string) { try { await api(`/schema-drift/${id}/acknowledge`, { method: "POST" }); await load(); notify("Schema drift acknowledged"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Drift could not be acknowledged", "error"); } }
  return (
    <section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">DATA ACCESS</span><h3>Connector workbench</h3><p>Every connector starts read-only and stores only a secret reference.</p></div><button className="primary-button" onClick={() => openForm()}><Plus size={17} />Add connector</button></div>
      <div className="table-header connector-grid"><span>Connector</span><span>System</span><span>Catalog</span><span>Status</span><span /></div>
      {connectors.map((connector) => <div className="data-row connector-grid" key={connector.id}><span><strong>{connector.name}</strong><small>{connector.description || `${connector.host || "Local service"} / ${connector.database || "-"}`}</small></span><span>{connectorLabels[connector.connector_type] || connector.connector_type}</span><span>{connector.metadata_summary?.tables || 0} tables</span><StatusPill value={connector.status} /><span className="row-actions"><button className="icon-button" title="Edit connector" onClick={() => openForm(connector)}><Settings size={16} /></button><button className="icon-button" title="Test connection" onClick={() => test(connector.id)}><Gauge size={16} /></button><button className="icon-button" title="Scan metadata" onClick={() => scan(connector.id)}><RefreshCw size={16} /></button><button className="icon-button" title="Delete connector" onClick={() => remove(connector)}><XCircle size={16} /></button></span></div>)}
      {drift.length > 0 && <><div className="subheading"><h4>Schema drift</h4><span>{drift.filter((item) => item.status === "detected").length} open</span></div><div className="table-header drift-grid"><span>Relation</span><span>Changes</span><span>Status</span><span /></div>{drift.map((item) => <div className="data-row drift-grid" key={item.id}><span><strong>{item.relation}</strong><small>{new Date(item.detected_at).toLocaleString()}</small></span><span>{item.changes.map((change) => `${change.kind.replaceAll("_", " ")}: ${change.column}`).join(", ")}</span><StatusPill value={item.status} /><button className="icon-button" title="Acknowledge drift" disabled={item.status === "acknowledged"} onClick={() => acknowledge(item.id)}><Check size={16} /></button></div>)}</>}
      {showForm && <Modal title={editing ? "Edit data connector" : "Add data connector"} onClose={() => { setShowForm(false); setEditing(null); }}><form className="modal-form" onSubmit={save}><label>Name<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label><div className="form-grid"><label>System<select value={form.connector_type} onChange={(event) => setForm({ ...form, connector_type: event.target.value })}><option value="postgres">PostgreSQL</option><option value="sql_server">SQL Server</option><option value="oracle">Oracle</option><option value="teradata">Teradata</option><option value="bigquery">BigQuery</option><option value="local_files">Local files</option></select></label><label>Connection mode<select value={form.connection_mode} onChange={(event) => setForm({ ...form, connection_mode: event.target.value as "direct" | "mcp", mcp_server_url: event.target.value === "mcp" ? form.mcp_server_url : "" })}><option value="direct">Native driver</option><option value="mcp">Upstream MCP</option></select></label></div><label>Description<textarea rows={3} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="Owner, domain, sensitivity, and approved use." /></label>{form.connection_mode === "mcp" ? <label>MCP server URL<input value={form.mcp_server_url} onChange={(event) => setForm({ ...form, mcp_server_url: event.target.value })} placeholder="http://mcp-toolbox:5000/mcp" required /></label> : <div className="form-grid"><label>Host / project<input value={form.host} onChange={(event) => setForm({ ...form, host: event.target.value })} /></label><label>Database / dataset<input value={form.database} onChange={(event) => setForm({ ...form, database: event.target.value })} /></label></div>}<label>Secret reference<input value={form.secret_reference} onChange={(event) => setForm({ ...form, secret_reference: event.target.value })} placeholder={form.connection_mode === "mcp" ? "env:MCP_TOOLBOX_TOKEN" : "env:POSTGRES_CREDENTIALS"} /></label><div className="modal-note"><ShieldCheck size={16} />The connector is read-only. Credentials are stored only by reference and hidden from viewer roles.</div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => { setShowForm(false); setEditing(null); }}>Cancel</button><button className="primary-button">{editing ? "Save connector" : "Add connector"}</button></div></form></Modal>}
    </section>
  );
}

function ModelsAdmin({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [usage, setUsage] = useState<ModelUsage | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", provider_type: "company_gateway", base_url: "", default_model: "", embedding_model: "", secret_reference: "" });
  const load = useCallback(() => Promise.all([api<ModelProvider[]>("/model-providers"), api<ModelUsage>("/model-usage")]).then(([providerData, usageData]) => { setProviders(providerData); setUsage(usageData); }), []);
  useEffect(() => { load(); }, [load]);
  async function create(event: FormEvent) { event.preventDefault(); try { await api("/model-providers", { method: "POST", body: JSON.stringify({ ...form, enabled: true, is_default: false }) }); setShowForm(false); await load(); notify("Model provider added"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not add provider", "error"); } }
  async function test(id: string) { try { const result = await api<{ message: string }>(`/model-providers/${id}/test`, { method: "POST" }); notify(result.message); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Provider test failed", "error"); } }
  async function setDefault(id: string) { try { await api(`/model-providers/${id}/default`, { method: "POST" }); notify("Default model provider updated"); await load(); } catch (reason) { notify(reason instanceof Error ? reason.message : "Provider could not be selected", "error"); } }
  return (
    <section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">MODEL ROUTING</span><h3>Provider registry</h3><p>Company gateway first, with Gemini, OpenAI, Claude, compatible, and local providers.</p></div><button className="primary-button" onClick={() => setShowForm(true)}><Plus size={17} />Add provider</button></div>
      <div className="provider-grid">{providers.map((provider) => <article className="provider-card" key={provider.id}><div className="provider-heading"><span className="provider-icon"><Bot size={20} /></span><span>{provider.is_default && <span className="tag">default</span>}<StatusPill value={provider.status} /></span></div><h4>{provider.name}</h4><p>{provider.provider_type.replaceAll("_", " ")}</p><dl><div><dt>Chat model</dt><dd>{provider.default_model}</dd></div><div><dt>Embeddings</dt><dd>{provider.embedding_model || "Not configured"}</dd></div><div><dt>Secret</dt><dd>{provider.secret_reference || "Not required"}</dd></div></dl><div className="provider-actions"><button className="secondary-button" onClick={() => test(provider.id)}><Gauge size={16} />Test</button><button className="secondary-button" disabled={provider.is_default || provider.status !== "healthy"} onClick={() => setDefault(provider.id)}><Check size={16} />Set default</button></div></article>)}</div>
      {usage && <section className="usage-strip"><div><span>Calls</span><strong>{usage.totals.calls}</strong></div><div><span>Input tokens</span><strong>{usage.totals.input_tokens.toLocaleString()}</strong></div><div><span>Output tokens</span><strong>{usage.totals.output_tokens.toLocaleString()}</strong></div><div><span>Estimated cost</span><strong>{usage.pricing_configured ? `$${usage.totals.estimated_cost_usd.toFixed(4)}` : "Rates not set"}</strong></div></section>}
      {showForm && <Modal title="Add model provider" onClose={() => setShowForm(false)}><form className="modal-form" onSubmit={create}><div className="form-grid"><label>Name<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label><label>Type<select value={form.provider_type} onChange={(event) => setForm({ ...form, provider_type: event.target.value })}><option value="company_gateway">Company gateway</option><option value="gemini">Gemini</option><option value="openai">OpenAI</option><option value="claude">Claude</option><option value="openai_compatible">OpenAI compatible</option><option value="local_mock">Local mock</option></select></label></div><label>Base URL<input value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} /></label><div className="form-grid"><label>Default chat model<input value={form.default_model} onChange={(event) => setForm({ ...form, default_model: event.target.value })} required /></label><label>Embedding model<input value={form.embedding_model} onChange={(event) => setForm({ ...form, embedding_model: event.target.value })} /></label></div><label>Secret reference<input value={form.secret_reference} onChange={(event) => setForm({ ...form, secret_reference: event.target.value })} placeholder="env:MODEL_API_KEY" /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary-button">Add provider</button></div></form></Modal>}
    </section>
  );
}

function UsersAdmin({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [users, setUsers] = useState<(SessionUser & { active: boolean; created_at: string })[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", role: "analyst", temporary_password: "ChangeMe123!" });
  const load = useCallback(() => api<typeof users>("/admin/users").then(setUsers), []);
  useEffect(() => { load(); }, [load]);
  async function create(event: FormEvent) { event.preventDefault(); try { await api("/admin/users", { method: "POST", body: JSON.stringify(form) }); setShowForm(false); await load(); notify("Local user added"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not add user", "error"); } }
  async function update(user: (typeof users)[number], patch: { role?: string; active?: boolean }) { try { await api(`/admin/users/${user.id}`, { method: "PUT", body: JSON.stringify({ role: patch.role ?? user.role, active: patch.active ?? user.active }) }); await load(); notify("User access updated"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not update user", "error"); } }
  return (
    <section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">LOCAL ACCESS</span><h3>Users and roles</h3><p>Admin-managed accounts remain available before and after PingFederate is enabled.</p></div><button className="primary-button" onClick={() => setShowForm(true)}><UserPlus size={17} />Add user</button></div>
      <div className="table-header user-grid"><span>User</span><span>Role</span><span>Status</span><span>Created</span></div>{users.map((user) => <div className="data-row user-grid" key={user.id}><span className="person-cell"><span className="user-avatar">{user.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</span><span><strong>{user.name}</strong><small>{user.email}</small></span></span><select className="table-select" value={user.role} onChange={(event) => update(user, { role: event.target.value })} aria-label={`Role for ${user.name}`}><option value="admin">Admin</option><option value="engineer">Engineer</option><option value="analyst">Analyst</option><option value="viewer">Viewer</option></select><button className="status-action" onClick={() => update(user, { active: !user.active })} title={user.active ? "Deactivate user" : "Activate user"}>{user.active ? <Check size={15} /> : <XCircle size={15} />}<StatusPill value={user.active ? "active" : "inactive"} /></button><span>{new Date(user.created_at).toLocaleDateString()}</span></div>)}
      {showForm && <Modal title="Add local user" onClose={() => setShowForm(false)}><form className="modal-form" onSubmit={create}><label>Full name<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label><label>Email<input type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} required /></label><div className="form-grid"><label>Role<select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}><option value="admin">Admin</option><option value="engineer">Engineer</option><option value="analyst">Analyst</option><option value="viewer">Viewer</option></select></label><label>Temporary password<input type="password" value={form.temporary_password} onChange={(event) => setForm({ ...form, temporary_password: event.target.value })} minLength={10} required /></label></div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary-button">Create user</button></div></form></Modal>}
    </section>
  );
}

function AuthAdmin({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [provider, setProvider] = useState<{ id: string; enabled: boolean; issuer_url: string; client_id: string; scopes: string; group_claim: string } | null>(null);
  useEffect(() => { api<(typeof provider)[]>("/auth-providers").then((data) => setProvider(data[0])); }, []);
  async function save(event: FormEvent) { event.preventDefault(); if (!provider) return; try { const updated = await api<typeof provider>(`/auth-providers/${provider.id}`, { method: "PUT", body: JSON.stringify(provider) }); setProvider(updated); notify("PingFederate configuration saved"); } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not save configuration", "error"); } }
  return (
    <section className="surface admin-surface"><div className="section-heading"><div><span className="eyebrow">ENTERPRISE IDENTITY</span><h3>PingFederate</h3><p>OIDC is the default integration path. Local admin login remains available as a controlled fallback.</p></div>{provider && <StatusPill value={provider.enabled ? "enabled" : "disabled"} />}</div>
      {!provider ? <LoadingBlock /> : <form className="auth-config" onSubmit={save}><div className="toggle-row"><span><strong>Enable PingFederate OIDC</strong><small>Show enterprise sign-in after issuer validation succeeds.</small></span><button type="button" className={`toggle ${provider.enabled ? "on" : ""}`} onClick={() => setProvider({ ...provider, enabled: !provider.enabled })} aria-label="Enable PingFederate"><span /></button></div><label>Issuer URL<input value={provider.issuer_url || ""} onChange={(event) => setProvider({ ...provider, issuer_url: event.target.value })} placeholder="https://sso.company.example" /></label><div className="form-grid"><label>Client ID<input value={provider.client_id || ""} onChange={(event) => setProvider({ ...provider, client_id: event.target.value })} /></label><label>Group claim<input value={provider.group_claim} onChange={(event) => setProvider({ ...provider, group_claim: event.target.value })} /></label></div><label>Scopes<input value={provider.scopes} onChange={(event) => setProvider({ ...provider, scopes: event.target.value })} /></label><div className="policy-banner"><ShieldCheck size={18} /><span><strong>Server-side authorization remains authoritative.</strong><small>PingFederate groups map to DataPilot roles; a successful login alone does not grant project access.</small></span></div><div className="form-end"><button className="primary-button"><Check size={17} />Save configuration</button></div></form>}
    </section>
  );
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><div className="modal" role="dialog" aria-modal="true" aria-label={title}><div className="modal-header"><h3>{title}</h3><button className="icon-button" onClick={onClose} aria-label="Close"><X size={19} /></button></div>{children}</div></div>;
}
