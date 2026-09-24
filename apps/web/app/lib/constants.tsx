import {
  Activity,
  Archive,
  Bot,
  BookOpen,
  Braces,
  Check,
  Code2,
  Database,
  FileUp,
  FlaskConical,
  Gauge,
  GitBranch,
  GraduationCap,
  LayoutDashboard,
  MessageSquare,
  Network,
  Settings,
  ShieldCheck,
} from "lucide-react";
import type { NavKey } from "../types";

export const navItems: { key: NavKey; label: string; icon: typeof LayoutDashboard }[] = [
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
  { key: "learning", label: "Learning", icon: GraduationCap },
  { key: "admin", label: "Admin", icon: Settings },
];

export const navGroups: { key: string; label: string; items: NavKey[] }[] = [
  { key: "overview", label: "Overview", items: ["workspace", "conversations"] },
  { key: "data", label: "Data workspace", items: ["datasets", "files", "sql", "notebooks"] },
  { key: "delivery", label: "Build & operate", items: ["pipelines", "jobs", "quality", "artifacts", "approvals"] },
  { key: "governance", label: "Governance & agents", items: ["semantic", "tools", "agents", "evaluations", "learning", "superset"] },
  { key: "administration", label: "Administration", items: ["admin"] },
];

export const roleLanding: Record<string, NavKey> = {
  admin: "workspace",
  engineer: "pipelines",
  analyst: "conversations",
  viewer: "datasets",
};

export const TOUR_STORAGE_KEY = "datapilot_tour_completed_v1";

export const defaultTourSteps: { key: NavKey; title: string; body: string }[] = [
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

export type ProviderTypeOption = {
  value: string;
  label: string;
  baseUrl: string;
  modelPlaceholder: string;
  secretReference: string;
  secretPlaceholder: string;
  /** Pre-filled model id (only for providers with a single well-known model). */
  defaultModel?: string;
  /** Short note shown under the type selector. */
  hint?: string;
  /** "decision" providers return typed choices with probabilities, never text. */
  capability?: "generation" | "decision";
};

// Provider types offered when registering a model provider. `baseUrl` and
// `secretReference` pre-fill the form (empty = API default / nothing pre-filled);
// `secretPlaceholder` is only a hint.
export const providerTypeOptions: ProviderTypeOption[] = [
  { value: "company_gateway", label: "Company gateway", baseUrl: "", modelPlaceholder: "gateway-chat-model", secretReference: "", secretPlaceholder: "env:MODEL_API_KEY" },
  { value: "gemini", label: "Gemini", baseUrl: "", modelPlaceholder: "gemini-model-name", secretReference: "", secretPlaceholder: "env:MODEL_API_KEY" },
  { value: "openai", label: "OpenAI", baseUrl: "", modelPlaceholder: "openai-model-name", secretReference: "", secretPlaceholder: "env:MODEL_API_KEY" },
  { value: "claude", label: "Claude", baseUrl: "", modelPlaceholder: "claude-sonnet-5", secretReference: "", secretPlaceholder: "env:MODEL_API_KEY" },
  { value: "openai_compatible", label: "OpenAI compatible", baseUrl: "", modelPlaceholder: "model-name", secretReference: "", secretPlaceholder: "env:MODEL_API_KEY" },
  { value: "openrouter", label: "OpenRouter", baseUrl: "https://openrouter.ai/api/v1", modelPlaceholder: "anthropic/claude-sonnet-5", secretReference: "env:OPENROUTER_API_KEY", secretPlaceholder: "env:OPENROUTER_API_KEY" },
  { value: "jev", label: "TypeSafe Jev (decision model)", baseUrl: "https://openrouter.ai/api/alpha/decisions", modelPlaceholder: "typesafe/jev-1.13", defaultModel: "typesafe/jev-1.13", secretReference: "env:OPENROUTER_API_KEY", secretPlaceholder: "env:OPENROUTER_API_KEY", hint: "Decision model: returns typed choices with probabilities, not text", capability: "decision" },
  { value: "local_mock", label: "Local mock", baseUrl: "", modelPlaceholder: "local-deterministic", secretReference: "", secretPlaceholder: "Not required" },
];

/** A provider's capability; older APIs omit it, so it is derived from the provider type. */
export const providerCapability = (provider: { capability?: string | null; provider_type?: string }) =>
  provider.capability === "decision" || provider.capability === "generation"
    ? provider.capability
    : providerTypeOptions.find((option) => option.value === provider.provider_type)?.capability || "generation";

export const connectorLabels: Record<string, string> = {
  postgres: "PostgreSQL",
  sql_server: "SQL Server",
  oracle: "Oracle",
  teradata: "Teradata",
  bigquery: "BigQuery",
  local_files: "Local files",
};

export const connectorDialectForType = (connectorType: string) => {
  if (connectorType === "postgres") return "postgres";
  if (connectorType === "sql_server") return "sqlserver";
  if (connectorType === "bigquery") return "bigquery";
  if (connectorType === "oracle") return "oracle";
  if (connectorType === "teradata") return "teradata";
  return "postgres";
};

export const statusTone = (status: string) => {
  const normalized = status.toLowerCase();
  if (["healthy", "succeeded", "approved", "passed", "reachable", "staged", "completed", "helpful"].includes(normalized)) {
    return "positive";
  }
  if (["failed", "rejected", "cancelled", "not helpful"].includes(normalized)) return "negative";
  if (["pending", "waiting_for_approval", "retrying", "configuration_required", "needs_review"].includes(normalized)) {
    return "warning";
  }
  return "neutral";
};
