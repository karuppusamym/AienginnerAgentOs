import type { NavKey } from "../types";

/**
 * App Router paths per navigation key. The Analysis view keeps its historical
 * key ("conversations") but lives at /analysis[/<conversationId>]?m=<messageId>.
 */
export const NAV_PATHS: Record<NavKey, string> = {
  workspace: "/workspace",
  conversations: "/analysis",
  datasets: "/datasets",
  files: "/files",
  sql: "/sql",
  notebooks: "/notebooks",
  pipelines: "/pipelines",
  jobs: "/jobs",
  artifacts: "/artifacts",
  quality: "/quality",
  superset: "/superset",
  approvals: "/approvals",
  tools: "/tools",
  agents: "/agents",
  semantic: "/semantic",
  evaluations: "/evaluations",
  learning: "/learning",
  admin: "/admin",
  architecture: "/architecture",
};

export function isNavKey(value: string | null | undefined): value is NavKey {
  return !!value && Object.prototype.hasOwnProperty.call(NAV_PATHS, value);
}

/** Maps a pathname such as "/analysis/abc" to its nav key, or null for unknown paths. */
export function navKeyForPath(pathname: string | null | undefined): NavKey | null {
  if (!pathname) return null;
  const first = pathname.split("/").filter(Boolean)[0] || "";
  const match = (Object.entries(NAV_PATHS) as [NavKey, string][]).find(([, path]) => path === `/${first}`);
  return match ? match[0] : null;
}

/** /analysis, /analysis/<c>, or /analysis/<c>?m=<m>. */
export function analysisPath(conversationId?: string, messageId?: string) {
  if (!conversationId) return NAV_PATHS.conversations;
  const base = `${NAV_PATHS.conversations}/${encodeURIComponent(conversationId)}`;
  return messageId ? `${base}?m=${encodeURIComponent(messageId)}` : base;
}

/** Role gate shared by the shell and the root redirect. */
export function canView(view: NavKey, role: string) {
  if (view === "admin") return role === "admin";
  if (view === "tools" || view === "learning") return ["admin", "engineer"].includes(role);
  return true;
}

/**
 * Translates a pre-App-Router link (`/?view=conversations&c=…&m=…`) into its
 * route, or null when the query string carries no known view.
 */
export function legacyViewTarget(search: string): string | null {
  const params = new URLSearchParams(search);
  const view = params.get("view");
  if (!isNavKey(view)) return null;
  if (view === "conversations") return analysisPath(params.get("c") || "", params.get("m") || "");
  return NAV_PATHS[view];
}
