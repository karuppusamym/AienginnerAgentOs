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
import type { NavKey } from "../types";
import { embedDashboard, EmbeddedDashboard } from "@superset-ui/embedded-sdk";
import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

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
  { key: "admin", label: "Admin", icon: Settings },
];

export const navGroups: { key: string; label: string; items: NavKey[] }[] = [
  { key: "overview", label: "Overview", items: ["workspace", "conversations"] },
  { key: "data", label: "Data workspace", items: ["datasets", "files", "sql", "notebooks"] },
  { key: "delivery", label: "Build & operate", items: ["pipelines", "jobs", "quality", "artifacts", "approvals"] },
  { key: "governance", label: "Governance & agents", items: ["semantic", "tools", "agents", "evaluations", "superset"] },
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
  if (["healthy", "succeeded", "approved", "passed", "reachable", "staged"].includes(normalized)) {
    return "positive";
  }
  if (["failed", "rejected", "cancelled"].includes(normalized)) return "negative";
  if (["pending", "waiting_for_approval", "retrying", "configuration_required"].includes(normalized)) {
    return "warning";
  }
  return "neutral";
};
