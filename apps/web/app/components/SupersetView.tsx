import {
  AlertCircle,
  Database,
  FileCode2,
  LayoutDashboard,
  Lock,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Star,
} from "lucide-react";
import { embedDashboard, EmbeddedDashboard } from "@superset-ui/embedded-sdk";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { StatusPill, ControlItem } from "./shared";

type PrimaryEntry = { key: "project"; title: string; dataset_relation: string | null; chart_count: number | null; updated_at: string | null; available: boolean };
type PublishedEntry = { key: string; artifact_id: string; title: string; artifact_type: string; artifact_version: number; columns: string[]; chart_count: number; updated_at: string | null };
type DatasetEntry = { key: string; asset_id: string; relation: string; source: string; asset_type: string; row_count: number | null; column_count: number; sensitivity: string; is_default: boolean; restricted: boolean };
type Catalog = {
  scope: string;
  project: { id: string; name: string };
  superset: { available: boolean; reason: string };
  primary: PrimaryEntry;
  published: PublishedEntry[];
  datasets: DatasetEntry[];
};
type EmbedTarget = { token?: string; embedded_id: string; superset_domain: string; dashboard_title?: string; dataset_relation?: string; chart_count?: number; access_mode?: string; mapped_at?: string };

const STORAGE_KEY = "datapilot.analytics.selection";

function rememberedSelection(projectId: string): string | null {
  try {
    return (JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") as Record<string, string>)[projectId] || null;
  } catch {
    return null;
  }
}

function rememberSelection(projectId: string, key: string) {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") as Record<string, string>;
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...saved, [projectId]: key }));
  } catch {
    /* per-viewer convenience only */
  }
}

/** Guest-token endpoint for each kind of entry; every token is limited to that one dashboard. */
function tokenEndpoint(key: string): string {
  if (key === "project") return "/analytics/guest-token";
  if (key.startsWith("query:")) return `/analytics/queries/${key.slice(6)}/guest-token`;
  return `/analytics/datasets/${key.slice(8)}/guest-token`;
}

async function loadTarget(key: string): Promise<EmbedTarget> {
  if (key === "project") return api<EmbedTarget>("/analytics/config");
  return api<EmbedTarget>(tokenEndpoint(key), { method: "POST" });
}

export function SupersetView({ isAdmin, projectName }: { isAdmin: boolean; projectName: string }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const dashboardRef = useRef<EmbeddedDashboard | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [target, setTarget] = useState<EmbedTarget | null>(null);
  const [openingEditor, setOpeningEditor] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    api<Catalog>("/analytics/dashboards")
      .then((result) => {
        if (!active) return;
        setCatalog(result);
        const keys = new Set<string>([...(result.primary.available ? ["project"] : []), ...result.published.map((item) => item.key), ...result.datasets.filter((item) => !item.restricted).map((item) => item.key)]);
        const remembered = rememberedSelection(result.project.id);
        setSelected(remembered && keys.has(remembered) ? remembered : keys.values().next().value ?? null);
      })
      .catch((reason) => active && setCatalogError(reason instanceof Error ? reason.message : "Analytics catalog could not be loaded"));
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selected || !catalog) return;
    let active = true;
    rememberSelection(catalog.project.id, selected);
    async function mount() {
      if (!mountRef.current || !selected) return;
      dashboardRef.current?.unmount();
      dashboardRef.current = null;
      mountRef.current.innerHTML = "";
      setState("loading");
      setError("");
      try {
        const config = await loadTarget(selected);
        const embedded = await embedDashboard({
          id: config.embedded_id,
          supersetDomain: config.superset_domain,
          mountPoint: mountRef.current,
          fetchGuestToken: async () => (await api<{ token: string }>(tokenEndpoint(selected), { method: "POST" })).token,
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
        setTarget(config);
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
  }, [selected, catalog, attempt]);

  async function openEditor() {
    const editorWindow = window.open("about:blank", "datapilot-superset-editor");
    setOpeningEditor(true);
    try {
      const session = await api<{ url: string }>("/analytics/editor-session", { method: "POST" });
      if (editorWindow) editorWindow.location.replace(session.url);
      else window.location.assign(session.url);
    } catch (reason) {
      editorWindow?.close();
      setError(reason instanceof Error ? reason.message : "Could not open the analytics editor");
      setState("error");
    } finally {
      setOpeningEditor(false);
    }
  }

  const needle = filter.trim().toLowerCase();
  const published = useMemo(() => (catalog?.published || []).filter((item) => !needle || `${item.title} ${item.columns.join(" ")}`.toLowerCase().includes(needle)), [catalog, needle]);
  const datasetsBySource = useMemo(() => {
    const groups = new Map<string, DatasetEntry[]>();
    for (const item of catalog?.datasets || []) {
      if (needle && !`${item.relation} ${item.source}`.toLowerCase().includes(needle)) continue;
      groups.set(item.source, [...(groups.get(item.source) || []), item]);
    }
    return [...groups.entries()];
  }, [catalog, needle]);

  const selectedLabel = useMemo(() => {
    if (!catalog || !selected) return { kind: "", title: "" };
    if (selected === "project") return { kind: "Project dashboard", title: catalog.primary.title };
    const query = catalog.published.find((item) => item.key === selected);
    if (query) return { kind: `Published ${query.artifact_type === "notebook" ? "notebook" : "query"} v${query.artifact_version}`, title: query.title };
    const dataset = catalog.datasets.find((item) => item.key === selected);
    return { kind: `Dataset from ${dataset?.source || "catalog"}`, title: dataset?.relation || "" };
  }, [catalog, selected]);

  const supersetDown = catalog && !catalog.superset.available;

  return (
    <div className="view-stack">
      <div className="view-header">
        <div>
          <h2>Governed analytics</h2>
          <p>Pick the project dashboard, a published query, or any local dataset of {projectName}. Embedded without another login; every guest token is limited to that one dashboard and this project.</p>
        </div>
        <div className="analytics-header-actions">
          <StatusPill value={supersetDown ? "unavailable" : state === "ready" ? "connected" : state} />
          {isAdmin && <button className="secondary-button" onClick={openEditor} disabled={openingEditor}>{openingEditor ? <RefreshCw size={17} className="spin" /> : <Settings size={17} />}{openingEditor ? "Opening" : "Open editor"}</button>}
        </div>
      </div>
      {supersetDown && <div className="analytics-banner"><AlertCircle size={16} /><span>{catalog?.superset.reason}</span></div>}
      <div className="analytics-layout">
        <aside className="surface analytics-picker" aria-label="Dashboards">
          <label className="analytics-search"><Search size={14} /><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter dashboards and datasets" /></label>
          {catalogError && <p className="analytics-picker-note error">{catalogError}</p>}
          {!catalog && !catalogError && <p className="analytics-picker-note"><RefreshCw size={13} className="spin" /> Loading</p>}
          {catalog && (
            <>
              <div className="picker-group">
                <span className="picker-group-title">Project</span>
                <button className={`picker-item${selected === "project" ? " active" : ""}`} disabled={!catalog.primary.available} onClick={() => setSelected("project")}>
                  <LayoutDashboard size={15} />
                  <span><strong>Project dashboard</strong><small>{catalog.primary.dataset_relation || "Load or publish a local dataset first"}</small></span>
                </button>
              </div>
              <div className="picker-group">
                <span className="picker-group-title">Published queries <em>{catalog.published.length}</em></span>
                {published.length === 0 && <p className="analytics-picker-note">{catalog.published.length ? "No match" : "Publish a saved SQL query or notebook to give it its own dashboard."}</p>}
                {published.map((item) => (
                  <button key={item.key} className={`picker-item${selected === item.key ? " active" : ""}`} onClick={() => setSelected(item.key)} title={item.columns.join(", ")}>
                    <FileCode2 size={15} />
                    <span><strong>{item.title}</strong><small>v{item.artifact_version} · {item.chart_count} charts · {item.columns.slice(0, 3).join(", ")}</small></span>
                  </button>
                ))}
              </div>
              {datasetsBySource.map(([source, items]) => (
                <div className="picker-group" key={source}>
                  <span className="picker-group-title">{source} <em>{items.length}</em></span>
                  {items.map((item) => (
                    <button key={item.key} className={`picker-item${selected === item.key ? " active" : ""}`} disabled={item.restricted} onClick={() => setSelected(item.key)} title={item.restricted ? "Restricted: admins only" : `${item.column_count} columns`}>
                      {item.restricted ? <Lock size={15} /> : <Database size={15} />}
                      <span>
                        <strong>{item.relation}{item.is_default && <Star size={11} className="picker-default" aria-label="Project default" />}</strong>
                        <small>{item.row_count != null ? `${item.row_count.toLocaleString()} rows · ` : ""}{item.column_count} columns{item.sensitivity !== "unclassified" ? ` · ${item.sensitivity}` : ""}</small>
                      </span>
                    </button>
                  ))}
                </div>
              ))}
            </>
          )}
        </aside>
        <div className="analytics-main">
          <section className="surface analytics-embed-shell">
            {state === "loading" && <div className="analytics-overlay"><RefreshCw size={20} className="spin" /><strong>{selected ? "Connecting analytics" : "Choose a dashboard"}</strong></div>}
            {state === "error" && <div className="analytics-overlay error"><AlertCircle size={22} /><strong>Analytics unavailable</strong><span>{error}</span><button className="secondary-button" onClick={() => setAttempt((current) => current + 1)}><RefreshCw size={16} />Retry</button></div>}
            <div ref={mountRef} className="analytics-mount" />
          </section>
          <div className="three-column compact-cards">
            <ControlItem icon={<Database size={17} />} label="Scope" value={`Project: ${projectName}`} status="current" />
            <ControlItem icon={<LayoutDashboard size={17} />} label={selectedLabel.kind || "Dashboard"} value={target?.chart_count ? `${selectedLabel.title} / ${target.chart_count} charts` : selectedLabel.title || "-"} status={state === "ready" ? "ready" : state} />
            <ControlItem icon={<ShieldCheck size={17} />} label="Dataset" value={target?.dataset_relation || (selected === "project" ? catalog?.primary.dataset_relation || "-" : "-")} status={target ? "mapped" : state} />
            <ControlItem icon={<ShieldCheck size={17} />} label="Access" value={(target?.access_mode || "dashboard_scope").replaceAll("_", " ")} status={state === "ready" ? "enforced" : state} />
          </div>
        </div>
      </div>
    </div>
  );
}
