import {
  ArrowLeft,
  Braces,
  ChevronRight,
  ChevronsDown,
  ChevronsUp,
  CircleCheck,
  Columns3,
  Download,
  ExternalLink,
  Eye,
  FileCode2,
  FileSpreadsheet,
  LocateFixed,
  Network,
  Search,
  Share2,
  Table2,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { api } from "../lib/api";
import { GraphCanvas, type GraphEdge, type GraphLayout, type GraphNode } from "./GraphCanvas";
import { LoadingBlock, EmptyState, StatusPill } from "./shared";
import "./relationship-explorer.css";

type Notify = (message: string, tone?: "ok" | "error") => void;
type Kind = "table" | "view" | "file" | "mcp_tool" | "query";
type Scope = "all" | "source" | "group";
type EdgeType = "lineage" | "governed_join" | "inferred_join";

type ExplorerNode = {
  id: string; relation: string; schema_name: string; table_name: string; source_label: string; connector_id: string | null;
  connector_type: string; connection_mode: string; group: string; asset_type: string; kind: Kind; row_count: number | null;
  metadata_status: string; sensitivity: string; column_count: number; pii_column_count: number; described: boolean; queryable: boolean;
  level: number | null; lane: "focus" | "upstream" | "downstream" | "join" | null; distance: number | null;
};
type ColumnPair = { left: string; right: string };
type ExplorerEdge = {
  id: string; type: EdgeType; source: string; target: string; columns: ColumnPair[]; cross_connector: boolean;
  origin?: string; join_type?: string; status?: string; description?: string | null; record_count?: number;
};
type ExplorerSource = { key: string; connector_id: string | null; label: string; connector_type: string; connection_mode: string; asset_count: number; view_count: number; group_count: number };
type ExplorerGroup = { group: string; source_key: string; source_label: string; asset_count: number };
type ExplorerGraph = {
  mode: "overview" | "focus"; focus: string | null; depth: number; scope: Scope; connector_id: string | null; group: string | null; include_inferred: boolean;
  nodes: ExplorerNode[]; edges: ExplorerEdge[]; sources: ExplorerSource[]; groups: ExplorerGroup[];
  counts: { nodes: number; lineage: number; governed_join: number; inferred_join: number; cross_connector: number };
  total_in_scope: number; truncated: boolean;
};
type AssetColumn = { name: string; type?: string; nullable?: boolean; business_name?: string; description?: string; sensitivity?: string; pii_category?: string };
type Neighbour = { id: string; relation: string; source_label: string; kind: Kind };
type LineageItem = { edge_id: string; asset_id: string | null; relation: string; source_label: string | null; kind: Kind | null; origin: string; transformation: string | null; column_mapping: { source?: string; target?: string }[] };
type AssetDetail = {
  asset: ExplorerNode & { description: string | null; owner: string | null; tags: string[]; freshness_sla_hours: number | null; columns: AssetColumn[] };
  joins: (ExplorerEdge & { other: Neighbour; column_pairs: { this: string; other: string }[] })[];
  lineage: { upstream: LineageItem[]; downstream: LineageItem[] };
  view_definition: string | null;
  metrics: { id: string; name: string; description: string | null; formula: string; grain: string; owner: string; status: string }[];
  llm_context: { queryable: boolean; catalog_entry: string; grounding_text: string };
  context_checks: { key: string; label: string; ok: boolean; detail: string }[];
};

const LOCAL = "__local__";
const CARD_W = 236;
const CARD_H = 82;
const ROW_GAP = 14;
const COL_GAP = 104;
const SUB_GAP = 60;
const JOIN_GAP = 28;
const JOIN_ROW_GAP = 44;
const HEADER_H = 34;
const PAD = 20;
const OVERVIEW_ROWS = 8;
const KIND_ORDER: Kind[] = ["table", "view", "file", "query", "mcp_tool"];
const KIND_LABEL: Record<Kind, string> = { table: "Table", view: "View", file: "Staged file", query: "Saved query", mcp_tool: "MCP tool" };
const ORIGIN_LABEL: Record<string, string> = { view_definition: "view definition", pipeline: "pipeline", extraction: "external extraction", lineage: "lineage" };

const sourceKey = (node: { connector_id: string | null }) => node.connector_id || LOCAL;
const byRelation = (a: ExplorerNode, b: ExplorerNode) => a.relation.localeCompare(b.relation);

function KindIcon({ kind, size = 15 }: { kind: Kind | null; size?: number }) {
  if (kind === "view") return <Eye size={size} aria-label="View" />;
  if (kind === "file") return <FileSpreadsheet size={size} aria-label="Staged file" />;
  if (kind === "mcp_tool") return <Wrench size={size} aria-label="MCP tool" />;
  if (kind === "query") return <Braces size={size} aria-label="Saved query" />;
  return <Table2 size={size} aria-label="Table" />;
}

type Rect = { x: number; y: number; band: "flow" | "join" | "overview" };
type Header = { x: number; y: number; width: number; label: string; note?: string; color?: string };
type Layout = { width: number; height: number; rects: Map<string, Rect>; headers: Header[]; bands: { y: number; label: string; note: string }[] };

// AIDataAnalyst-style layered columns: Upstream n … Focus … Downstream n, with join
// neighbours in a band underneath so join edges never cross the data-flow arrows.
function focusLayout(nodes: ExplorerNode[], focusId: string): Layout {
  const rects = new Map<string, Rect>();
  const headers: Header[] = [];
  const flow = nodes.filter((node) => node.lane !== "join");
  const levels = [...new Set(flow.map((node) => node.level ?? 0))].sort((a, b) => a - b);
  let maxRows = 1;
  levels.forEach((level, column) => {
    const members = flow.filter((node) => (node.level ?? 0) === level).sort(byRelation);
    const x = PAD + column * (CARD_W + COL_GAP);
    headers.push({ x, y: PAD, width: CARD_W, label: level === 0 ? "Focus" : `${level < 0 ? "Upstream" : "Downstream"} ${Math.abs(level)}`, note: level === 0 ? undefined : `${members.length}` });
    members.forEach((node, row) => rects.set(node.id, { x, y: PAD + HEADER_H + row * (CARD_H + ROW_GAP), band: "flow" }));
    maxRows = Math.max(maxRows, members.length);
  });
  let width = PAD * 2 + levels.length * CARD_W + Math.max(0, levels.length - 1) * COL_GAP;
  let height = PAD + HEADER_H + maxRows * (CARD_H + ROW_GAP) - ROW_GAP + PAD;
  const bands: Layout["bands"] = [];
  const joins = nodes.filter((node) => node.lane === "join");
  if (joins.length) {
    const focusX = rects.get(focusId)?.x ?? PAD;
    const perRow = Math.max(3, levels.length + 1);
    let y = height + 12;
    bands.push({ y, label: `Joins with (${joins.length})`, note: "same queryable group only — governed policies solid, inferred dashed" });
    y += HEADER_H + 8;
    for (const hop of [...new Set(joins.map((node) => node.distance ?? 1))].sort((a, b) => a - b)) {
      const members = joins.filter((node) => (node.distance ?? 1) === hop).sort(byRelation);
      for (let start = 0; start < members.length; start += perRow) {
        const row = members.slice(start, start + perRow);
        const rowWidth = row.length * CARD_W + (row.length - 1) * JOIN_GAP;
        const x0 = Math.max(PAD, focusX + CARD_W / 2 - rowWidth / 2);
        row.forEach((node, index) => rects.set(node.id, { x: x0 + index * (CARD_W + JOIN_GAP), y, band: "join" }));
        width = Math.max(width, x0 + rowWidth + PAD);
        y += CARD_H + JOIN_ROW_GAP;
      }
    }
    height = y - JOIN_ROW_GAP + PAD + 36;
  }
  return { width, height, rects, headers, bands };
}

// Overview: one column (wrapping into sub-columns) per source, so "what lives where" reads at a glance.
function overviewLayout(nodes: ExplorerNode[], sources: ExplorerSource[], color: (key: string) => string): Layout {
  const rects = new Map<string, Rect>();
  const headers: Header[] = [];
  const bySource = new Map<string, ExplorerNode[]>();
  nodes.forEach((node) => bySource.set(sourceKey(node), [...(bySource.get(sourceKey(node)) || []), node]));
  const order = [...sources.map((source) => source.key).filter((key) => bySource.has(key)), ...[...bySource.keys()].filter((key) => !sources.some((source) => source.key === key))];
  let x = PAD;
  let maxRows = 1;
  for (const key of order) {
    const members = [...(bySource.get(key) || [])].sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind) || byRelation(a, b));
    const columns = Math.ceil(members.length / OVERVIEW_ROWS);
    const rows = Math.ceil(members.length / columns);
    members.forEach((node, index) => rects.set(node.id, { x: x + Math.floor(index / rows) * (CARD_W + SUB_GAP), y: PAD + HEADER_H + (index % rows) * (CARD_H + ROW_GAP), band: "overview" }));
    const span = columns * CARD_W + (columns - 1) * SUB_GAP;
    const meta = sources.find((source) => source.key === key);
    const views = members.filter((node) => node.kind === "view").length;
    headers.push({ x, y: PAD, width: span, label: meta?.label || members[0].source_label, note: `${members.length} asset${members.length === 1 ? "" : "s"}${views ? ` · ${views} view${views === 1 ? "" : "s"}` : ""}${meta?.connection_mode === "mcp" ? " · each tool queried alone" : ""}`, color: color(key) });
    maxRows = Math.max(maxRows, rows);
    x += span + COL_GAP;
  }
  return { width: Math.max(x - COL_GAP + PAD, 320), height: PAD + HEADER_H + maxRows * (CARD_H + ROW_GAP) - ROW_GAP + PAD, rects, headers, bands: [] };
}

function edgePath(a: Rect, b: Rect): string {
  const midY = (rect: Rect) => rect.y + CARD_H / 2;
  if (Math.abs(a.x - b.x) < 1) {
    const x = a.x + CARD_W;
    const bulge = 26 + Math.min(80, Math.abs(midY(b) - midY(a)) * 0.2);
    return `M ${x} ${midY(a)} C ${x + bulge} ${midY(a)}, ${x + bulge} ${midY(b)}, ${x} ${midY(b)}`;
  }
  if ((a.band === "join" || b.band === "join") && Math.abs(a.y - b.y) < 1) {
    const y = a.y + CARD_H;
    const x1 = a.x + CARD_W / 2, x2 = b.x + CARD_W / 2;
    const bulge = 18 + Math.min(40, Math.abs(x2 - x1) * 0.08);
    return `M ${x1} ${y} C ${x1} ${y + bulge}, ${x2} ${y + bulge}, ${x2} ${y}`;
  }
  if (a.band === "join" || b.band === "join") {
    const [top, bottom] = a.y < b.y ? [a, b] : [b, a];
    const x1 = top.x + CARD_W / 2, y1 = top.y + CARD_H, x2 = bottom.x + CARD_W / 2, y2 = bottom.y;
    const bend = Math.max(24, (y2 - y1) / 2);
    return `M ${x1} ${y1} C ${x1} ${y1 + bend}, ${x2} ${y2 - bend}, ${x2} ${y2}`;
  }
  const rightward = b.x > a.x;
  const x1 = rightward ? a.x + CARD_W : a.x;
  const x2 = rightward ? b.x : b.x + CARD_W;
  const bend = Math.max(36, Math.abs(x2 - x1) * 0.45) * (rightward ? 1 : -1);
  return `M ${x1} ${midY(a)} C ${x1 + bend} ${midY(a)}, ${x2 - bend} ${midY(b)}, ${x2} ${midY(b)}`;
}

function edgeTitle(edge: ExplorerEdge, name: (id: string) => string): string {
  const pairs = edge.columns.map((pair) => (edge.type === "lineage" ? `${pair.left} → ${pair.right}` : `${pair.left} = ${pair.right}`)).join(", ");
  if (edge.type === "lineage") return `${name(edge.source)} → ${name(edge.target)} · ${ORIGIN_LABEL[edge.origin || "lineage"] || edge.origin}${pairs ? ` · ${pairs}` : ""}${edge.cross_connector ? " · data flows across sources" : ""}`;
  if (edge.cross_connector) return `⚠ ${name(edge.source)} ↔ ${name(edge.target)} (${pairs}) — this approved policy joins two datasets that can't be queried together in one call (different connectors, or different MCP tools), so it cannot execute. Edit or remove it.`;
  return `${name(edge.source)} ↔ ${name(edge.target)} · ${pairs} · ${edge.type === "governed_join" ? `${edge.status} ${edge.join_type} join policy` : "inferred from matching column names, not governed"}`;
}

const edgeClass = (edge: ExplorerEdge) => (edge.type !== "lineage" && edge.cross_connector ? "cross" : edge.type);

/**
 * The interactive diagram's nodes and edges at the current drill level: a collapsed source is
 * one node (its relationships aggregated), an expanded source shows its tables, and a table
 * with its columns open shows column nodes plus column-level join / lineage edges.
 */
function buildCanvas(input: {
  nodes: ExplorerNode[]; edges: ExplorerEdge[]; mode: "overview" | "focus"; focus: string | null;
  collapsed: Set<string>; columns: Record<string, AssetColumn[]>; sources: ExplorerSource[];
  color: (key: string) => string; name: (id: string) => string;
}): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const { nodes, edges, mode, focus, collapsed, columns, sources, color, name } = input;
  const out: GraphNode[] = [];
  const links: GraphEdge[] = [];
  const bySource = new Map<string, ExplorerNode[]>();
  nodes.forEach((node) => bySource.set(sourceKey(node), [...(bySource.get(sourceKey(node)) || []), node]));
  const columnIds = new Set<string>();
  for (const [key, members] of bySource) {
    if (collapsed.has(key)) {
      const meta = sources.find((source) => source.key === key);
      out.push({ id: `src:${key}`, kind: "source", label: meta?.label || members[0].source_label, sublabel: `${members.length} asset${members.length === 1 ? "" : "s"} in view${meta && meta.asset_count > members.length ? ` of ${meta.asset_count}` : ""}`, color: color(key), weight: members.length, expandable: true, expanded: false, focus: members.some((node) => node.id === focus), rank: mode === "focus" ? 0 : null });
      continue;
    }
    for (const node of members) {
      const badges = [KIND_LABEL[node.kind], `${node.column_count} cols`, ...(node.pii_column_count ? [`PII ${node.pii_column_count}`] : []), ...(!node.queryable ? ["not queryable"] : [])];
      out.push({ id: node.id, kind: "table", label: node.table_name, sublabel: `${node.schema_name} · ${node.source_label}`, color: color(key), rank: mode === "focus" ? node.level ?? 0 : null, seedFrom: `src:${key}`, weight: node.column_count, expandable: node.column_count > 0, expanded: Boolean(columns[node.id]), focus: node.id === focus, warn: !node.queryable, badges });
      for (const column of columns[node.id] || []) {
        const id = `col:${node.id}:${column.name}`;
        columnIds.add(id);
        const pii = column.sensitivity === "pii" || Boolean(column.pii_category);
        out.push({ id, kind: "column", label: column.name, sublabel: column.type, parent: node.id, color: color(key), badges: pii ? ["PII"] : undefined });
        links.push({ id: `member:${id}`, source: node.id, target: id, kind: "member" });
      }
    }
  }
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const representative = (id: string) => { const node = byId.get(id); if (!node) return null; const key = sourceKey(node); return collapsed.has(key) ? `src:${key}` : id; };
  const aggregate = new Map<string, { source: string; target: string; count: number; kinds: Map<string, number> }>();
  for (const edge of edges) {
    const a = representative(edge.source);
    const b = representative(edge.target);
    if (!a || !b || a === b) continue;
    if (a.startsWith("src:") || b.startsWith("src:")) {
      const key = [a, b].sort().join("|");
      const entry = aggregate.get(key) || { source: a, target: b, count: 0, kinds: new Map<string, number>() };
      entry.count += 1;
      entry.kinds.set(edge.type, (entry.kinds.get(edge.type) || 0) + 1);
      aggregate.set(key, entry);
      continue;
    }
    const kind = edgeClass(edge);
    const directed = edge.type === "lineage";
    links.push({ id: edge.id, source: a, target: b, kind, directed, title: edgeTitle(edge, name) });
    if (columns[edge.source] && columns[edge.target]) {
      edge.columns.forEach((pair, position) => {
        const from = `col:${edge.source}:${pair.left}`;
        const to = `col:${edge.target}:${pair.right}`;
        if (columnIds.has(from) && columnIds.has(to)) links.push({ id: `${edge.id}:col:${position}`, source: from, target: to, kind, directed, title: `${name(edge.source)}.${pair.left} ${directed ? "→" : "="} ${name(edge.target)}.${pair.right}` });
      });
    }
  }
  const typeLabel: Record<string, string> = { lineage: "lineage", governed_join: "governed join", inferred_join: "inferred join" };
  aggregate.forEach((entry, key) => links.push({ id: `agg:${key}`, source: entry.source, target: entry.target, kind: "aggregate", weight: entry.count, title: `${entry.count} relationship${entry.count === 1 ? "" : "s"}: ${[...entry.kinds].map(([type, count]) => `${count} ${typeLabel[type] || type}`).join(", ")} — expand the source to see them` }));
  return { nodes: out, edges: links };
}

function download(filename: string, type: string, body: string) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function RelationshipExplorer({ notify, refreshKey = 0 }: { notify: Notify; refreshKey?: number }) {
  const [scope, setScope] = useState<Scope>("all");
  const [connectorKey, setConnectorKey] = useState("");
  const [group, setGroup] = useState("");
  const [depth, setDepth] = useState(2);
  const [includeInferred, setIncludeInferred] = useState(true);
  const [trail, setTrail] = useState<string[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [selectedColumn, setSelectedColumn] = useState<string | null>(null);
  const [layoutChoice, setLayoutChoice] = useState<GraphLayout | null>(null);
  // null = automatic: big multi-source overviews start collapsed to one node per source.
  const [collapsed, setCollapsed] = useState<Set<string> | null>(null);
  const [columnsOpen, setColumnsOpen] = useState<Record<string, AssetColumn[]>>({});
  const [extra, setExtra] = useState<{ nodes: ExplorerNode[]; edges: ExplorerEdge[] }>({ nodes: [], edges: [] });
  const [fitVersion, setFitVersion] = useState(0);
  const columnCache = useRef(new Map<string, AssetColumn[]>());
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [view, setView] = useState<"diagram" | "table">("diagram");
  const [index, setIndex] = useState<ExplorerGraph | null>(null);
  const [graph, setGraph] = useState<ExplorerGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<AssetDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const focusId = trail.length ? trail[trail.length - 1] : null;

  useEffect(() => {
    let live = true;
    api<ExplorerGraph>("/semantic/explorer?scope=all&include_inferred=false")
      .then((data) => { if (live) setIndex(data); })
      .catch((reason) => notify(reason instanceof Error ? reason.message : "Catalog index unavailable", "error"));
    return () => { live = false; };
  }, [notify, refreshKey]);

  const graphPath = useMemo(() => {
    const params = new URLSearchParams({ scope, depth: String(depth), include_inferred: String(includeInferred) });
    if (focusId) params.set("focus", focusId);
    if (scope === "source" && connectorKey) params.set("connector_id", connectorKey);
    if (scope === "group" && group) params.set("group", group);
    return `/semantic/explorer?${params}`;
  }, [scope, depth, includeInferred, focusId, connectorKey, group]);
  const scopeReady = scope === "all" || (scope === "source" ? Boolean(connectorKey || focusId) : Boolean(group || focusId));

  useEffect(() => {
    if (!scopeReady) return;
    let live = true;
    setLoading(true);
    api<ExplorerGraph>(graphPath)
      .then((data) => { if (live) setGraph(data); })
      .catch((reason) => notify(reason instanceof Error ? reason.message : "Relationship graph unavailable", "error"))
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [graphPath, scopeReady, notify, refreshKey]);

  const detailId = selectedId || focusId;
  useEffect(() => {
    if (!detailId) { setDetail(null); return; }
    let live = true;
    setDetailLoading(true);
    api<AssetDetail>(`/semantic/explorer/assets/${encodeURIComponent(detailId)}?include_inferred=${includeInferred}`)
      .then((data) => { columnCache.current.set(data.asset.id, data.asset.columns); if (live) setDetail(data); })
      .catch((reason) => notify(reason instanceof Error ? reason.message : "Dataset context unavailable", "error"))
      .finally(() => { if (live) setDetailLoading(false); });
    return () => { live = false; };
  }, [detailId, includeInferred, notify, refreshKey]);

  const sources = useMemo(() => index?.sources || graph?.sources || [], [index, graph]);
  const groups = index?.groups || graph?.groups || [];
  const sourceColorIndex = useMemo(() => new Map(sources.map((source, position) => [source.key, (position % 8) + 1])), [sources]);
  const color = useCallback((key: string) => `var(--chart-${sourceColorIndex.get(key) || 8})`, [sourceColorIndex]);
  const nodes = useMemo(() => graph?.nodes || [], [graph]);
  const nodeById = useMemo(() => new Map([...(index?.nodes || []), ...extra.nodes, ...nodes].map((node) => [node.id, node])), [index, nodes, extra]);
  const name = useCallback((id: string) => nodeById.get(id)?.relation || id, [nodeById]);
  const layout = useMemo(() => {
    if (!graph || !nodes.length) return null;
    return graph.mode === "focus" && graph.focus ? focusLayout(nodes, graph.focus) : overviewLayout(nodes, sources, color);
  }, [graph, nodes, sources, color]);
  const edges = useMemo(() => (graph?.edges || []).filter((edge) => layout?.rects.has(edge.source) && layout.rects.has(edge.target)), [graph, layout]);

  const needle = query.trim().toLowerCase();
  const matches = useCallback((node: ExplorerNode) => !needle || node.relation.toLowerCase().includes(needle) || node.source_label.toLowerCase().includes(needle), [needle]);
  const searchResults = useMemo(() => (needle ? (index?.nodes || []).filter(matches).slice(0, 10) : []), [needle, index, matches]);


  const focusOn = (id: string) => {
    setTrail((current) => {
      const existing = current.indexOf(id);
      return existing >= 0 ? current.slice(0, existing + 1) : [...current, id];
    });
    setSelectedId(null);
    setSelectedSource(null);
    setSelectedColumn(null);
    setQuery("");
    setSearchOpen(false);
  };
  const back = () => { setTrail((current) => current.slice(0, -1)); setSelectedId(null); };
  const overview = () => { setTrail([]); setSelectedId(null); };
  const changeScope = (next: Scope) => {
    setScope(next);
    const anchor = focusId ? nodeById.get(focusId) : null;
    if (next === "source" && !connectorKey) setConnectorKey(anchor ? sourceKey(anchor) : sources[0]?.key || "");
    if (next === "group" && !group) setGroup(anchor ? anchor.group : groups[0]?.group || "");
  };

  const exportJson = () => { if (graph) download("relationship-explorer.json", "application/json", JSON.stringify(graph, null, 2)); };
  const exportSvg = () => {
    if (!layout || !graph) return;
    const css = getComputedStyle(document.documentElement);
    const token = (value: string) => value.replace(/var\((--[a-z0-9-]+)\)/g, (_, variable: string) => css.getPropertyValue(variable).trim() || "#888");
    const esc = (value: string) => value.replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char] || char);
    const stroke: Record<string, string> = { lineage: "var(--blue)", governed_join: "var(--brand)", inferred_join: "var(--muted)", cross: "var(--danger)" };
    const dash: Record<string, string> = { inferred_join: "6 5", cross: "3 3" };
    const parts = [
      `<rect width="${layout.width}" height="${layout.height}" fill="${token("var(--canvas)")}"/>`,
      `<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="${token("var(--blue)")}"/></marker></defs>`,
      ...layout.headers.map((header) => `<text x="${header.x}" y="${header.y + 14}" font-size="12" font-weight="600" fill="${token("var(--text-2)")}">${esc(header.label.toUpperCase())}${header.note ? ` · ${esc(header.note)}` : ""}</text>`),
      ...layout.bands.map((band) => `<text x="${PAD}" y="${band.y + 22}" font-size="12" font-weight="600" fill="${token("var(--text-2)")}">${esc(band.label.toUpperCase())}</text>`),
      ...edges.map((edge) => {
        const kind = edgeClass(edge);
        return `<path d="${edgePath(layout.rects.get(edge.source)!, layout.rects.get(edge.target)!)}" fill="none" stroke="${token(stroke[kind])}" stroke-width="2"${dash[kind] ? ` stroke-dasharray="${dash[kind]}"` : ""}${edge.type === "lineage" ? ' marker-end="url(#a)"' : ""}><title>${esc(edgeTitle(edge, name))}</title></path>`;
      }),
      ...nodes.filter((node) => layout.rects.has(node.id)).map((node) => {
        const rect = layout.rects.get(node.id)!;
        return `<g transform="translate(${rect.x} ${rect.y})"><rect width="${CARD_W}" height="${CARD_H}" rx="9" fill="${token("var(--surface)")}" stroke="${token(node.id === graph.focus ? "var(--brand)" : "var(--line-strong)")}"/><rect width="4" height="${CARD_H}" rx="2" fill="${token(color(sourceKey(node)))}"/><text x="12" y="22" font-size="13" font-weight="600" fill="${token("var(--ink)")}">${esc(node.table_name)}</text><text x="12" y="41" font-size="12" fill="${token("var(--muted)")}">${esc(`${node.schema_name} · ${node.source_label}`)}</text><text x="12" y="62" font-size="11" fill="${token("var(--text-2)")}">${esc(`${KIND_LABEL[node.kind]} · ${node.column_count} cols${node.pii_column_count ? ` · PII ${node.pii_column_count}` : ""}`)}</text></g>`;
      }),
    ];
    download("relationship-explorer.svg", "image/svg+xml", `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="${layout.width}" height="${layout.height}" viewBox="0 0 ${layout.width} ${layout.height}" font-family="system-ui, sans-serif">${parts.join("")}</svg>`);
  };

  const focusNode = focusId ? nodeById.get(focusId) : null;
  // ---------------------------------------------------------------- interactive graph: drill source -> table -> column
  const [seenGraph, setSeenGraph] = useState<ExplorerGraph | null>(null);
  if (graph !== seenGraph) {
    // A new neighbourhood / scope starts from its own default drill level.
    setSeenGraph(graph);
    setExtra({ nodes: [], edges: [] });
    setCollapsed(null);
    setSelectedSource(null);
    setSelectedColumn(null);
  }
  const allNodes = useMemo(() => {
    const map = new Map(nodes.map((node) => [node.id, node]));
    extra.nodes.forEach((node) => { if (!map.has(node.id)) map.set(node.id, node); });
    return [...map.values()];
  }, [nodes, extra]);
  const allEdges = useMemo(() => {
    const map = new Map((graph?.edges || []).map((edge) => [edge.id, edge]));
    extra.edges.forEach((edge) => { if (!map.has(edge.id)) map.set(edge.id, edge); });
    return [...map.values()];
  }, [graph, extra]);
  const presentSources = useMemo(() => [...new Set(allNodes.map(sourceKey))], [allNodes]);
  const autoCollapsed = useMemo(() => new Set(graph?.mode === "overview" && allNodes.length > 40 && presentSources.length > 1 ? presentSources : []), [graph, allNodes.length, presentSources]);
  const collapsedSet = collapsed ?? autoCollapsed;
  const graphLayout: GraphLayout = layoutChoice ?? (graph?.mode === "focus" ? "hierarchical" : "force");
  const canvas = useMemo(() => buildCanvas({ nodes: allNodes, edges: allEdges, mode: graph?.mode || "overview", focus: graph?.focus || null, collapsed: collapsedSet, columns: columnsOpen, sources, color, name }), [allNodes, allEdges, graph, collapsedSet, columnsOpen, sources, color, name]);

  const expandSource = (key: string) => setCollapsed(new Set([...collapsedSet].filter((item) => item !== key)));
  const collapseSource = (key: string) => setCollapsed(new Set([...collapsedSet, key]));
  const showColumns = async (id: string) => {
    try {
      let columns = columnCache.current.get(id);
      if (!columns) {
        const data = await api<AssetDetail>(`/semantic/explorer/assets/${encodeURIComponent(id)}?include_inferred=${includeInferred}`);
        columns = data.asset.columns;
        columnCache.current.set(id, columns);
      }
      const shown = columns;
      setColumnsOpen((current) => ({ ...current, [id]: shown }));
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Columns unavailable", "error");
    }
  };
  const hideColumns = (id: string) => setColumnsOpen((current) => { if (!current[id]) return current; const next = { ...current }; delete next[id]; return next; });
  const expandNode = (id: string) => { if (id.startsWith("src:")) expandSource(id.slice(4)); else if (!id.startsWith("col:")) void showColumns(id); };
  const collapseNode = (id: string) => { if (id.startsWith("src:")) collapseSource(id.slice(4)); else if (!id.startsWith("col:")) hideColumns(id); };
  const expandNeighbours = async (id: string) => {
    try {
      const params = new URLSearchParams({ scope: "all", depth: "1", include_inferred: String(includeInferred), focus: id });
      const data = await api<ExplorerGraph>(`/semantic/explorer?${params}`);
      const known = new Set(allNodes.map((node) => node.id));
      const knownEdges = new Set(allEdges.map((edge) => edge.id));
      const focusMode = graph?.mode === "focus";
      const base = nodeById.get(id)?.level ?? 0;
      const fresh = data.nodes.filter((node) => !known.has(node.id)).map((node) => ({ ...node, level: focusMode ? (node.lane === "join" ? base : base + (node.level ?? 0)) : null, lane: focusMode ? node.lane : null }));
      const freshEdges = data.edges.filter((edge) => !knownEdges.has(edge.id));
      if (!fresh.length && !freshEdges.length) { notify(`Every neighbour of ${name(id)} is already shown`); return; }
      setExtra((current) => ({ nodes: [...current.nodes, ...fresh], edges: [...current.edges, ...freshEdges] }));
      const freshSources = new Set(fresh.map(sourceKey));
      if ([...freshSources].some((key) => collapsedSet.has(key))) setCollapsed(new Set([...collapsedSet].filter((key) => !freshSources.has(key))));
      notify(`Added ${fresh.length} neighbour${fresh.length === 1 ? "" : "s"} and ${freshEdges.length} relationship${freshEdges.length === 1 ? "" : "s"} around ${name(id)}`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Neighbours unavailable", "error");
    }
  };
  const selectCanvas = (id: string | null) => {
    if (!id) { setSelectedId(null); setSelectedSource(null); setSelectedColumn(null); return; }
    if (id.startsWith("src:")) { setSelectedSource(id.slice(4)); setSelectedId(null); setSelectedColumn(null); return; }
    if (id.startsWith("col:")) {
      const rest = id.slice(4);
      const cut = rest.indexOf(":");
      setSelectedId(rest.slice(0, cut));
      setSelectedColumn(rest.slice(cut + 1));
      setSelectedSource(null);
      return;
    }
    setSelectedId(id);
    setSelectedColumn(null);
    setSelectedSource(null);
  };
  const canvasSelected = selectedSource ? `src:${selectedSource}` : selectedId && selectedColumn ? `col:${selectedId}:${selectedColumn}` : selectedId;
  const selectedTable = selectedId ? nodeById.get(selectedId) || null : null;
  const levelSource = selectedSource ?? (selectedTable ? sourceKey(selectedTable) : null);
  const levelSourceLabel = levelSource ? sources.find((source) => source.key === levelSource)?.label || allNodes.find((node) => sourceKey(node) === levelSource)?.source_label || "Source" : null;
  const allSourcesLevel = () => { setCollapsed(new Set(presentSources)); setColumnsOpen({}); selectCanvas(null); setFitVersion((value) => value + 1); };
  const sourceLevel = (key: string) => { setCollapsed(new Set(presentSources.filter((item) => item !== key))); setColumnsOpen({}); setSelectedId(null); setSelectedColumn(null); setSelectedSource(key); setFitVersion((value) => value + 1); };
  const tableLevel = (id: string) => { hideColumns(id); setSelectedId(id); setSelectedColumn(null); setSelectedSource(null); };
  const canDrillUp = Boolean(selectedColumn || selectedId || (selectedSource && !collapsedSet.has(selectedSource)) || collapsedSet.size < presentSources.length);
  const drillUp = () => {
    if (selectedColumn && selectedId) { tableLevel(selectedId); return; }
    if (selectedTable) { const key = sourceKey(selectedTable); hideColumns(selectedTable.id); collapseSource(key); setSelectedId(null); setSelectedSource(key); return; }
    if (selectedSource && !collapsedSet.has(selectedSource)) { collapseSource(selectedSource); return; }
    allSourcesLevel();
  };
  const canDrillDown = Boolean((selectedSource && collapsedSet.has(selectedSource)) || (selectedTable && selectedTable.column_count > 0 && !columnsOpen[selectedTable.id]));
  const drillDown = () => {
    if (selectedSource && collapsedSet.has(selectedSource)) { expandSource(selectedSource); return; }
    if (selectedTable && !columnsOpen[selectedTable.id]) void showColumns(selectedTable.id);
  };

  const scopeLabel = scope === "source" ? sources.find((source) => source.key === (graph?.connector_id || connectorKey))?.label : scope === "group" ? "one queryable group" : "all sources";

  return (
    <section className="surface rx-panel" aria-label="Relationship explorer">
      <div className="section-heading compact">
        <div>
          <span className="eyebrow">CATALOG RELATIONSHIPS</span>
          <h3>Relationship explorer</h3>
          <p>Pick a table to see where its data comes from (upstream), what is built on it (downstream — views, pipelines, extractions) and what it can be joined with. Joins are only ever suggested between datasets one query can reach together; an approved policy that crosses sources is shown in red because it cannot run.</p>
        </div>
        <div className="row-actions">
          {graph && <StatusPill value={`${graph.counts.lineage} lineage / ${graph.counts.governed_join} governed / ${graph.counts.inferred_join} inferred`} />}
          <button className="icon-button" title="Export this view's graph data (JSON)" onClick={exportJson} disabled={!graph}><Download size={16} /></button>
          <button className="icon-button" title="Export the current view as an SVG image" onClick={exportSvg} disabled={!layout}><FileCode2 size={16} /></button>
        </div>
      </div>

      <div className="rx-scopebar">
        <div className="rx-segmented" role="group" aria-label="Scope">
          {([["all", "All sources"], ["source", "One source"], ["group", "Queryable group"]] as const).map(([value, label]) => (
            <button key={value} type="button" aria-pressed={scope === value} onClick={() => changeScope(value)}>{label}</button>
          ))}
        </div>
        {scope === "source" && (
          <label className="rx-field">Source
            <select value={connectorKey} onChange={(event) => { setConnectorKey(event.target.value); setTrail([]); }}>
              {sources.map((source) => <option key={source.key} value={source.key}>{source.label} ({source.asset_count})</option>)}
            </select>
          </label>
        )}
        {scope === "group" && (
          <label className="rx-field">Group
            <select value={group} onChange={(event) => { setGroup(event.target.value); setTrail([]); }}>
              {groups.map((item) => <option key={item.group} value={item.group}>{item.source_label}{item.asset_count === 1 && item.group.includes(":") ? ` · ${nodeById.get(item.group.split(":")[1])?.table_name || "tool"}` : ""} ({item.asset_count})</option>)}
            </select>
          </label>
        )}
        <label className="rx-field">Depth
          <select value={depth} onChange={(event) => setDepth(Number(event.target.value))} disabled={!focusId} title={focusId ? "Hops to follow from the focus" : "Pick a focus table first"}>
            {[1, 2, 3].map((value) => <option key={value} value={value}>{value} hop{value > 1 ? "s" : ""}</option>)}
          </select>
        </label>
        <label className="toggle-inline"><input type="checkbox" checked={includeInferred} onChange={(event) => setIncludeInferred(event.target.checked)} />Show inferred joins</label>
        <div className="rx-search">
          <div className="toolbar-search"><Search size={14} />
            <input
              placeholder="Find a table to focus, or filter this view…"
              value={query}
              aria-label="Find or filter tables"
              aria-expanded={searchOpen && searchResults.length > 0}
              onChange={(event) => { setQuery(event.target.value); setSearchOpen(true); }}
              onFocus={() => setSearchOpen(true)}
              onBlur={() => window.setTimeout(() => setSearchOpen(false), 150)}
              onKeyDown={(event) => { if (event.key === "Enter" && searchResults[0]) focusOn(searchResults[0].id); if (event.key === "Escape") setSearchOpen(false); }}
            />
          </div>
          {searchOpen && searchResults.length > 0 && (
            <ul className="rx-search-results" role="listbox">
              {searchResults.map((node) => (
                <li key={node.id}><button type="button" role="option" aria-selected={false} onMouseDown={(event) => event.preventDefault()} onClick={() => focusOn(node.id)}><KindIcon kind={node.kind} />{node.relation}<small>{node.source_label}</small></button></li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <nav className="rx-trail" aria-label="Focus history">
        {trail.length > 0 && <button type="button" onClick={back} title="Back to the previous focus"><ArrowLeft size={14} /></button>}
        <button type="button" onClick={overview} aria-current={trail.length === 0 ? "page" : undefined}>Overview · {scopeLabel}</button>
        {trail.map((id, position) => (
          <span key={`${id}-${position}`} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <ChevronRight size={13} />
            <button type="button" aria-current={position === trail.length - 1 ? "page" : undefined} onClick={() => setTrail(trail.slice(0, position + 1))}>{nodeById.get(id)?.relation || "…"}</button>
          </span>
        ))}
      </nav>

      <div className="rx-legend" aria-label="Legend">
        {sources.map((source) => <span key={source.key}><i className="rx-swatch" style={{ background: color(source.key) }} />{source.label} ({source.asset_count}{source.view_count ? `, ${source.view_count} views` : ""}{source.connection_mode === "mcp" ? ", tools queried separately" : ""})</span>)}
        <span><svg className="rx-line" aria-hidden><line x1="0" y1="4" x2="22" y2="4" className="rx-edge lineage" markerEnd="url(#rx-arrow)" /></svg>lineage (data flow)</span>
        <span><svg className="rx-line" aria-hidden><line x1="0" y1="4" x2="26" y2="4" className="rx-edge governed_join" /></svg>governed join</span>
        <span><svg className="rx-line" aria-hidden><line x1="0" y1="4" x2="26" y2="4" className="rx-edge inferred_join" /></svg>inferred join</span>
        <span><svg className="rx-line" aria-hidden><line x1="0" y1="4" x2="26" y2="4" className="rx-edge cross" /></svg>cross-source policy (cannot run)</span>
      </div>

      <div className={`rx-body${detailId || selectedSource ? "" : " is-wide"}`}>
        <div className="rx-stage">
          <div className="rx-stage-head">
            <span>
              {graph?.mode === "focus" && focusNode ? <>Focused on <strong>{focusNode.relation}</strong> · {depth} hop{depth > 1 ? "s" : ""} · click a node for details, + to expand, “Focus here” to re-centre</> : "Overview — click a node for details, + on a node to drill down"}
              {graph?.truncated ? ` · showing ${graph.nodes.length} of ${graph.total_in_scope}` : ""}
            </span>
            <div className="rx-segmented" role="group" aria-label="Presentation">
              <button type="button" aria-pressed={view === "diagram"} onClick={() => setView("diagram")}>Diagram</button>
              <button type="button" aria-pressed={view === "table"} onClick={() => setView("table")}>Table</button>
            </div>
          </div>
          {!graph && loading ? <LoadingBlock label="Loading relationships" /> : !graph || !layout ? (
            <EmptyState icon={<Network size={24} />} title="No datasets in this scope" body="Catalog or scan a source to see its tables, views and relationships here." />
          ) : view === "table" ? (
            <EdgeTable edges={edges} nodeById={nodeById} onFocus={focusOn} />
          ) : (
            <>
              <div className="rx-levelbar">
                <nav className="rx-levels" aria-label="Drill level: source, table, column">
                  <button type="button" onClick={allSourcesLevel} aria-current={!levelSource ? "page" : undefined} title="Collapse every source to one node">Sources</button>
                  {levelSource && <><ChevronRight size={12} aria-hidden="true" /><button type="button" onClick={() => sourceLevel(levelSource)} aria-current={!selectedTable ? "page" : undefined} title="Show only this source's tables">{levelSourceLabel}</button></>}
                  {selectedTable && <><ChevronRight size={12} aria-hidden="true" /><button type="button" onClick={() => tableLevel(selectedTable.id)} aria-current={!selectedColumn ? "page" : undefined} title="Back to the table (hides its columns)">{selectedTable.table_name}</button></>}
                  {selectedColumn && <><ChevronRight size={12} aria-hidden="true" /><span aria-current="page">{selectedColumn}</span></>}
                </nav>
                <button type="button" className="secondary-button compact" onClick={drillUp} disabled={!canDrillUp} title="Column → table → source"><ChevronsUp size={14} aria-hidden="true" />Drill up</button>
                <button type="button" className="secondary-button compact" onClick={drillDown} disabled={!canDrillDown} title="Source → tables, table → columns"><ChevronsDown size={14} aria-hidden="true" />Drill down</button>
                <small>{collapsedSet.size ? `${collapsedSet.size} of ${presentSources.length} source${presentSources.length === 1 ? "" : "s"} collapsed · ` : ""}drag to pan, wheel to zoom, drag a node to pin it, double-click to release</small>
              </div>
              <GraphCanvas
                nodes={canvas.nodes}
                edges={canvas.edges}
                layout={graphLayout}
                onLayoutChange={setLayoutChoice}
                selectedId={canvasSelected}
                onSelect={selectCanvas}
                onExpand={expandNode}
                onCollapse={collapseNode}
                fitKey={`${graphPath}:${fitVersion}`}
                ariaLabel="Relationship graph"
              />
            </>
          )}
          {graph?.mode === "focus" && graph.nodes.length === 1 && <p className="rx-note">No lineage or join relationships are recorded for this table in this scope yet. Try “All sources”, turn on inferred joins, or approve a join policy.</p>}
          {graph && graph.counts.cross_connector > 0 && <p className="rx-note warn"><TriangleAlert size={13} style={{ verticalAlign: -2 }} /> {graph.counts.cross_connector} approved join polic{graph.counts.cross_connector === 1 ? "y" : "ies"} in view cross sources and cannot execute — hover the red edge for details.</p>}
        </div>

        {selectedSource ? (
          <SourcePanel
            source={sources.find((source) => source.key === selectedSource) || null}
            label={levelSourceLabel || "Source"}
            members={allNodes.filter((node) => sourceKey(node) === selectedSource)}
            collapsed={collapsedSet.has(selectedSource)}
            color={color(selectedSource)}
            onExpand={() => expandSource(selectedSource)}
            onCollapse={() => collapseSource(selectedSource)}
            onSelectTable={(id) => { expandSource(selectedSource); selectCanvas(id); }}
            onClose={() => setSelectedSource(null)}
          />
        ) : detailId && (
          <DetailPanel
            detail={detail}
            loading={detailLoading}
            isFocus={detailId === focusId}
            color={color}
            onFocus={focusOn}
            highlightColumn={selectedColumn}
            onClose={() => (selectedId ? selectCanvas(null) : overview())}
            actions={view === "diagram" && canvas.nodes.some((node) => node.id === detailId) ? <>
              <button type="button" className="secondary-button compact" onClick={() => (columnsOpen[detailId] ? hideColumns(detailId) : void showColumns(detailId))} aria-pressed={Boolean(columnsOpen[detailId])}><Columns3 size={14} aria-hidden="true" />{columnsOpen[detailId] ? "Hide columns" : "Show columns"}</button>
              <button type="button" className="secondary-button compact" onClick={() => void expandNeighbours(detailId)} title="Add this table's direct upstream, downstream and join neighbours from every source"><Share2 size={14} aria-hidden="true" />Neighbours +1 hop</button>
            </> : null}
          />
        )}
      </div>
    </section>
  );
}

function SourcePanel({ source, label, members, collapsed, color, onExpand, onCollapse, onSelectTable, onClose }: {
  source: ExplorerSource | null; label: string; members: ExplorerNode[]; collapsed: boolean; color: string;
  onExpand: () => void; onCollapse: () => void; onSelectTable: (id: string) => void; onClose: () => void;
}) {
  return (
    <aside className="rx-detail" aria-label={`Source ${label}`}>
      <div className="rx-detail-head">
        <span className="eyebrow" style={{ display: "flex", alignItems: "center", gap: 6 }}><i className="rx-dot" style={{ "--rx-source": color } as CSSProperties} />Source{source ? ` · ${source.connector_type}${source.connection_mode === "mcp" ? " (MCP)" : ""}` : ""}</span>
        <h4>{label}</h4>
        <span className="rx-badges" style={{ flexWrap: "wrap" }}>
          <span className="rx-badge">{source?.asset_count ?? members.length} assets</span>
          {source?.view_count ? <span className="rx-badge view">{source.view_count} views</span> : null}
          {source ? <span className="rx-badge">{source.group_count} queryable group{source.group_count === 1 ? "" : "s"}</span> : null}
          <span className="rx-badge">{members.length} in this view</span>
        </span>
        <div className="rx-detail-actions">
          {collapsed
            ? <button type="button" className="secondary-button compact" onClick={onExpand}><ChevronsDown size={14} aria-hidden="true" />Expand tables</button>
            : <button type="button" className="secondary-button compact" onClick={onCollapse}><ChevronsUp size={14} aria-hidden="true" />Collapse to source</button>}
          <button type="button" className="secondary-button compact" onClick={onClose}>Close</button>
        </div>
      </div>
      <Section title="Assets in this view" count={members.length} open>
        <ul className="rx-list">
          {[...members].sort(byRelation).map((node) => (
            <li key={node.id}>
              <span style={{ display: "flex", gap: 6, alignItems: "center" }}><KindIcon kind={node.kind} size={14} /><button type="button" className="rx-link" onClick={() => onSelectTable(node.id)}>{node.relation}</button></span>
              <small>{KIND_LABEL[node.kind]} · {node.column_count} cols{node.pii_column_count ? ` · PII ${node.pii_column_count}` : ""}{node.queryable ? "" : " · not queryable"}</small>
            </li>
          ))}
        </ul>
      </Section>
    </aside>
  );
}

function EdgeTable({ edges, nodeById, onFocus }: { edges: ExplorerEdge[]; nodeById: Map<string, ExplorerNode>; onFocus: (id: string) => void }) {
  const cell = (id: string) => <button type="button" className="rx-link" onClick={() => onFocus(id)}>{nodeById.get(id)?.relation || id}</button>;
  if (!edges.length) return <p className="rx-empty">No relationships in this view.</p>;
  return (
    <div className="rx-table-wrap">
      <table className="rx-table">
        <caption className="viz-sr-only">Every relationship shown in the diagram, one per row.</caption>
        <thead><tr><th scope="col">From</th><th scope="col">To</th><th scope="col">Relationship</th><th scope="col">Columns</th></tr></thead>
        <tbody>
          {edges.map((edge) => (
            <tr key={edge.id}>
              <td>{cell(edge.source)}</td>
              <td>{cell(edge.target)}</td>
              <td>{edge.type === "lineage" ? `Lineage (${ORIGIN_LABEL[edge.origin || "lineage"] || edge.origin})` : edge.type === "governed_join" ? `Governed ${edge.join_type} join · ${edge.status}` : "Inferred join"}{edge.cross_connector && edge.type !== "lineage" ? " · crosses sources, cannot run" : ""}</td>
              <td>{edge.columns.map((pair) => `${pair.left} ${edge.type === "lineage" ? "→" : "="} ${pair.right}`).join(", ") || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Section({ title, count, open = false, children }: { title: string; count?: number | string; open?: boolean; children: ReactNode }) {
  return <details open={open}><summary>{title}{count !== undefined && <small>({count})</small>}</summary>{children}</details>;
}

function DetailPanel({ detail, loading, isFocus, color, onFocus, onClose, actions, highlightColumn }: { detail: AssetDetail | null; loading: boolean; isFocus: boolean; color: (key: string) => string; onFocus: (id: string) => void; onClose: () => void; actions?: ReactNode; highlightColumn?: string | null }) {
  if (!detail) return <aside className="rx-detail">{loading ? <LoadingBlock label="Loading dataset context" /> : <p>Select a table to see its context.</p>}</aside>;
  const { asset } = detail;
  const pii = (column: AssetColumn) => column.sensitivity === "pii" || Boolean(column.pii_category);
  const ready = detail.context_checks.filter((check) => check.ok).length;
  const lineageList = (items: LineageItem[], empty: string) => items.length ? (
    <ul className="rx-list">
      {items.map((item) => (
        <li key={item.edge_id}>
          <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <KindIcon kind={item.kind} size={14} />
            {item.asset_id ? <button type="button" className="rx-link" onClick={() => onFocus(item.asset_id!)}>{item.relation}</button> : <span>{item.relation} <small>(not catalogued)</small></span>}
          </span>
          <small>via {ORIGIN_LABEL[item.origin] || item.origin}{item.source_label ? ` · ${item.source_label}` : ""}{item.transformation ? ` · ${item.transformation}` : ""}</small>
          {item.column_mapping.length > 0 && <small>{item.column_mapping.map((pair) => `${pair.source} → ${pair.target}`).join(", ")}</small>}
        </li>
      ))}
    </ul>
  ) : <p>{empty}</p>;
  return (
    <aside className="rx-detail" aria-label={`Context for ${asset.relation}`} aria-busy={loading}>
      <div className="rx-detail-head">
        <span className="eyebrow" style={{ display: "flex", alignItems: "center", gap: 6 }}><i className="rx-dot" style={{ "--rx-source": color(sourceKey(asset)) } as CSSProperties} />{asset.source_label} · {KIND_LABEL[asset.kind]}</span>
        <h4>{asset.relation}</h4>
        <span className="rx-badges" style={{ flexWrap: "wrap" }}>
          <span className="rx-badge">{asset.column_count} columns</span>
          {asset.row_count != null && <span className="rx-badge">{asset.row_count.toLocaleString()} rows</span>}
          {asset.pii_column_count > 0 && <span className="rx-badge pii">PII {asset.pii_column_count}</span>}
          <span className="rx-badge">{asset.metadata_status.replace(/_/g, " ")}</span>
          <span className="rx-badge">sensitivity: {asset.sensitivity}</span>
          {!asset.queryable && <span className="rx-badge warn">not queryable</span>}
        </span>
        <div className="rx-detail-actions">
          {!isFocus && <button type="button" className="secondary-button compact" onClick={() => onFocus(asset.id)}><LocateFixed size={14} />Focus here</button>}
          <Link className="secondary-button compact" href={`/datasets?asset=${encodeURIComponent(asset.id)}`}><ExternalLink size={14} />Open in Datasets</Link>
          {actions}
          <button type="button" className="secondary-button compact" onClick={onClose}>{isFocus ? "Back to overview" : "Close"}</button>
        </div>
      </div>
      <p>{asset.description || "No description yet."}</p>

      <Section title="Context readiness" count={`${ready}/${detail.context_checks.length}`} open>
        <ul className="rx-checks">
          {detail.context_checks.map((check) => (
            <li key={check.key}>
              {check.ok ? <CircleCheck size={16} className="ok" aria-label="Defined" /> : <TriangleAlert size={16} className="gap" aria-label="Gap" />}
              <span>{check.label}</span>
              <small>{check.detail}</small>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Columns" count={asset.columns.length} open>
        <div className="rx-table-wrap">
          <table className="rx-table">
            <thead><tr><th scope="col">Column</th><th scope="col">Type</th><th scope="col">Business meaning</th></tr></thead>
            <tbody>
              {asset.columns.map((column) => (
                <tr key={column.name} className={highlightColumn === column.name ? "rx-row-highlight" : undefined} aria-current={highlightColumn === column.name ? "true" : undefined}>
                  <td><strong>{column.name}</strong>{pii(column) && <> <span className="rx-badge pii" title={column.pii_category || "PII"}>PII{column.pii_category ? ` · ${column.pii_category}` : ""}</span></>}</td>
                  <td>{column.type || "—"}{column.nullable === false ? " · required" : ""}</td>
                  <td>{column.business_name || column.description ? <>{column.business_name && <strong>{column.business_name}</strong>}{column.business_name && column.description ? " — " : ""}{column.description}</> : <span style={{ color: "var(--muted)" }}>not defined</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Joins" count={detail.joins.length} open={detail.joins.length > 0}>
        {detail.joins.length ? (
          <ul className="rx-list">
            {detail.joins.map((join) => (
              <li key={join.id}>
                <span><button type="button" className="rx-link" onClick={() => onFocus(join.other.id)}>{join.other.relation}</button> <small>· {join.other.source_label}</small></span>
                <small>{join.type === "governed_join" ? `Governed ${join.join_type} join · ${join.status}` : "Inferred from column names — not used until approved"} · {join.column_pairs.map((pair) => `${pair.this} = ${pair.other}`).join(", ")}</small>
                {join.cross_connector && <small className="rx-warn">Crosses sources — can’t be queried together in one call, so this policy cannot execute.</small>}
              </li>
            ))}
          </ul>
        ) : <p>No join paths. Approve a join policy to let generation combine this table with others.</p>}
      </Section>

      <Section title="Upstream — built from" count={detail.lineage.upstream.length} open={detail.lineage.upstream.length > 0}>
        {lineageList(detail.lineage.upstream, "No recorded upstream sources.")}
      </Section>
      <Section title="Downstream — used by" count={detail.lineage.downstream.length} open={detail.lineage.downstream.length > 0}>
        {lineageList(detail.lineage.downstream, "Nothing recorded as built on this table.")}
      </Section>
      {detail.view_definition && <Section title="View definition"><pre>{detail.view_definition}</pre></Section>}

      <Section title="Metrics" count={detail.metrics.length} open={detail.metrics.length > 0}>
        {detail.metrics.length ? (
          <ul className="rx-list">
            {detail.metrics.map((metric) => <li key={metric.id}><strong>{metric.name} <StatusPill value={metric.status} /></strong><small>{metric.formula} · grain {metric.grain} · owner {metric.owner}</small></li>)}
          </ul>
        ) : <p>No semantic metrics are bound to this table.</p>}
      </Section>

      <Section title="LLM context" open>
        {!detail.llm_context.queryable && <p className="rx-warn" style={{ color: "var(--danger)" }}>Not sent to SQL generation: this asset has no queryable table yet.</p>}
        <span className="rx-context-label">Catalog entry sent with every SQL generation for {asset.source_label}:</span>
        <pre>{detail.llm_context.catalog_entry}</pre>
        {detail.llm_context.grounding_text && <>
          <span className="rx-context-label">Added when a question retrieves this table (approved joins and bound metrics):</span>
          <pre>{detail.llm_context.grounding_text}</pre>
        </>}
      </Section>
    </aside>
  );
}
