"use client";

/**
 * Interactive node-link canvas for the relationship / lineage explorer (inline SVG, no
 * graph library; the force layout is a small built-in simulation).
 *
 * - pan (drag the background), zoom (wheel, +/- buttons, fit to screen);
 * - drag nodes: a dragged node stays pinned, double-click (or "u") releases it;
 * - click a node to select it: its neighbours are highlighted, everything else dims;
 * - drill down / up: expandable nodes carry a +/- handle (keys "+" / "-") that the host
 *   maps to source -> table -> column expansion;
 * - search box finds and focuses a node; layout toggle: force or hierarchical
 *   (left-to-right by lineage level);
 * - keyboard: nodes use a roving tab stop, arrow keys move between nodes spatially,
 *   Enter / Space selects, Escape clears; honours prefers-reduced-motion;
 * - large graphs (200+ nodes) hide labels at low zoom and skip edge hit targets.
 */
import { Crosshair, Maximize2, Minimize2, Minus, Network, Pin, Plus, Scan, Search, Workflow } from "lucide-react";
import { type CSSProperties, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./graph-canvas.css";

export type GraphNodeKind = "source" | "table" | "column";
export type GraphNode = {
  id: string;
  label: string;
  sublabel?: string;
  kind: GraphNodeKind;
  /** CSS color, from tokens only (e.g. "var(--chart-3)"). */
  color: string;
  /** Hierarchical column hint (lineage level: < 0 upstream, 0 focus, > 0 downstream). */
  rank?: number | null;
  /** Column nodes: their table. */
  parent?: string | null;
  /** Where a newly shown node should appear (e.g. the source node it was expanded from). */
  seedFrom?: string | null;
  /** Size driver: asset count for a source, column count for a table. */
  weight?: number;
  expandable?: boolean;
  expanded?: boolean;
  focus?: boolean;
  warn?: boolean;
  badges?: string[];
};
export type GraphEdge = { id: string; source: string; target: string; kind: string; directed?: boolean; title?: string; weight?: number };
export type GraphLayout = "force" | "hierarchical";

type Sim = { x: number; y: number; vx: number; vy: number; fx: number | null; fy: number | null };
type Transform = { x: number; y: number; k: number };

const BOX: Record<GraphNodeKind, { w: number; h: number }> = { source: { w: 210, h: 46 }, table: { w: 196, h: 40 }, column: { w: 168, h: 22 } };
const COL_GAP = 96;
const ROW_GAP = 12;
const MAX_ROWS = 14;
const MIN_K = 0.08;
const MAX_K = 3;
const CHARGE: Record<GraphNodeKind, number> = { source: -700, table: -160, column: -35 };

const radius = (node: GraphNode) => node.kind === "source" ? 16 + Math.min(18, Math.sqrt(node.weight || 1) * 3) : node.kind === "table" ? 8 + Math.min(7, (node.weight || 0) / 6) : 4.5;
const clamp = (value: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, value));
const short = (value: string, max: number) => (value.length > max ? `${value.slice(0, max - 1)}…` : value);

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return reduced;
}

/** Left-to-right layering: explicit ranks, else longest path over directed edges; tall columns wrap. */
function hierarchicalPositions(nodes: GraphNode[], edges: GraphEdge[]) {
  const tops = nodes.filter((node) => node.kind !== "column");
  const rank = new Map<string, number>();
  const explicit = tops.some((node) => typeof node.rank === "number");
  tops.forEach((node) => rank.set(node.id, typeof node.rank === "number" ? node.rank : 0));
  if (!explicit) {
    const directed = edges.filter((edge) => edge.directed && rank.has(edge.source) && rank.has(edge.target) && edge.source !== edge.target);
    for (let pass = 0; pass < Math.min(tops.length, 30); pass += 1) {
      let changed = false;
      for (const edge of directed) {
        const next = rank.get(edge.source)! + 1;
        if (next > rank.get(edge.target)! && next < 30) { rank.set(edge.target, next); changed = true; }
      }
      if (!changed) break;
    }
  }
  const maxRows = Math.max(MAX_ROWS, Math.ceil(Math.sqrt(tops.length) * 1.6));
  const columnsOf = new Map<string, GraphNode[]>();
  nodes.filter((node) => node.kind === "column" && node.parent).forEach((node) => columnsOf.set(node.parent!, [...(columnsOf.get(node.parent!) || []), node]));
  const ranks = [...new Set(rank.values())].sort((a, b) => a - b);
  const positions = new Map<string, { x: number; y: number }>();
  let x = 0;
  for (const level of ranks) {
    const members = tops.filter((node) => rank.get(node.id) === level).sort((a, b) => (a.sublabel || "").localeCompare(b.sublabel || "") || a.label.localeCompare(b.label));
    // Units: a table plus its expanded columns stay together in one sub-column.
    let y = 0;
    let rows = 0;
    let columnWidth = 0;
    for (const node of members) {
      const box = BOX[node.kind];
      const children = columnsOf.get(node.id) || [];
      if (rows >= maxRows) { x += columnWidth + COL_GAP / 2; y = 0; rows = 0; columnWidth = 0; }
      positions.set(node.id, { x: x + box.w / 2, y: y + box.h / 2 });
      y += box.h + ROW_GAP;
      rows += 1;
      columnWidth = Math.max(columnWidth, box.w);
      children.forEach((child) => {
        positions.set(child.id, { x: x + 18 + BOX.column.w / 2, y: y + BOX.column.h / 2 });
        y += BOX.column.h + 4;
        rows += 0.5;
      });
      if (children.length) y += ROW_GAP;
    }
    x += columnWidth + COL_GAP;
  }
  // Center vertically around 0 so fit-to-screen behaves like the force layout.
  const ys = [...positions.values()].map((point) => point.y);
  const mid = ys.length ? (Math.min(...ys) + Math.max(...ys)) / 2 : 0;
  positions.forEach((point) => { point.y -= mid; });
  return positions;
}

export function GraphCanvas({
  nodes,
  edges,
  layout,
  onLayoutChange,
  selectedId,
  onSelect,
  onExpand,
  onCollapse,
  centerOn,
  fitKey,
  ariaLabel,
  height = 560,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  layout: GraphLayout;
  onLayoutChange: (layout: GraphLayout) => void;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onExpand?: (id: string) => void;
  onCollapse?: (id: string) => void;
  /** Pan to this node whenever it changes. */
  centerOn?: string | null;
  /** Changing it re-fits the whole graph to the viewport. */
  fitKey?: string | number;
  ariaLabel: string;
  height?: number;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const sims = useRef(new Map<string, Sim>());
  const alpha = useRef(0);
  const frame = useRef<number | null>(null);
  const pendingFit = useRef(true);
  const userMoved = useRef(false);
  const lastTap = useRef<{ id: string; time: number } | null>(null);
  const [, setTick] = useState(0);
  const [size, setSize] = useState({ w: 800, h: height });
  const [transform, setTransform] = useState<Transform>({ x: 400, y: height / 2, k: 1 });
  const [hovered, setHovered] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [matchIndex, setMatchIndex] = useState(0);
  const [full, setFull] = useState(false);
  const [announce, setAnnounce] = useState("");
  const reduced = usePrefersReducedMotion();
  const drag = useRef<{ id: string | null; startX: number; startY: number; originX: number; originY: number; moved: boolean; pointer: number } | null>(null);

  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const visibleEdges = useMemo(() => edges.filter((edge) => nodeById.has(edge.source) && nodeById.has(edge.target) && edge.source !== edge.target), [edges, nodeById]);
  const neighbours = useMemo(() => {
    const map = new Map<string, Set<string>>();
    visibleEdges.forEach((edge) => {
      if (!map.has(edge.source)) map.set(edge.source, new Set());
      if (!map.has(edge.target)) map.set(edge.target, new Set());
      map.get(edge.source)!.add(edge.target);
      map.get(edge.target)!.add(edge.source);
    });
    return map;
  }, [visibleEdges]);

  // ------------------------------------------------------------ size
  useEffect(() => {
    const node = wrapRef.current;
    if (!node) return;
    const update = () => { const box = node.getBoundingClientRect(); if (box.width > 0) setSize({ w: Math.floor(box.width), h: Math.floor(box.height) || height }); };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, [height, full]);

  // ------------------------------------------------------------ fit / center
  const fit = useCallback((animate = true) => {
    const points = nodes.map((node) => ({ node, sim: sims.current.get(node.id) })).filter((item) => item.sim);
    if (!points.length) return;
    let minX = Infinity; let minY = Infinity; let maxX = -Infinity; let maxY = -Infinity;
    points.forEach(({ node, sim }) => {
      const half = layout === "hierarchical" ? { w: BOX[node.kind].w / 2, h: BOX[node.kind].h / 2 } : { w: radius(node) + (node.kind === "column" ? 60 : 110), h: radius(node) + 10 };
      minX = Math.min(minX, sim!.x - half.w); maxX = Math.max(maxX, sim!.x + half.w);
      minY = Math.min(minY, sim!.y - half.h); maxY = Math.max(maxY, sim!.y + half.h);
    });
    const pad = 32;
    const k = clamp(Math.min((size.w - pad * 2) / Math.max(1, maxX - minX), (size.h - pad * 2) / Math.max(1, maxY - minY), 1.4), MIN_K, MAX_K);
    void animate;
    setTransform({ k, x: size.w / 2 - ((minX + maxX) / 2) * k, y: size.h / 2 - ((minY + maxY) / 2) * k });
  }, [nodes, layout, size]);
  const fitRef = useRef(fit);
  useEffect(() => { fitRef.current = fit; }, [fit]);

  const center = useCallback((id: string) => {
    const sim = sims.current.get(id);
    if (!sim) return;
    setTransform((current) => {
      const k = Math.max(current.k, 0.8);
      return { k, x: size.w / 2 - sim.x * k, y: size.h / 2 - sim.y * k };
    });
  }, [size]);

  // ------------------------------------------------------------ simulation
  const stepForce = useCallback((a: number) => {
    const list = nodes.map((node) => ({ node, sim: sims.current.get(node.id)! })).filter((item) => item.sim);
    const count = list.length;
    for (let i = 0; i < count; i += 1) {
      const p = list[i];
      for (let j = i + 1; j < count; j += 1) {
        const q = list[j];
        let dx = q.sim.x - p.sim.x;
        let dy = q.sim.y - p.sim.y;
        if (dx === 0 && dy === 0) { dx = (i - j) * 0.01; dy = 0.01; }
        const d2 = dx * dx + dy * dy;
        if (d2 > 640_000) continue;
        const d = Math.sqrt(d2);
        // Many-body repulsion (charge of the pair), plus collision so labels have air.
        const strength = (Math.sqrt(-CHARGE[p.node.kind] * -CHARGE[q.node.kind]) * a) / Math.max(d2, 64);
        let fx = dx * strength; // d3 many-body: force falls off with 1/d
        let fy = dy * strength;
        const minimum = radius(p.node) + radius(q.node) + (p.node.kind === "column" || q.node.kind === "column" ? 6 : 22);
        if (d < minimum) { const push = ((minimum - d) / d) * 0.5; fx += dx * push; fy += dy * push; }
        p.sim.vx -= fx; p.sim.vy -= fy;
        q.sim.vx += fx; q.sim.vy += fy;
      }
    }
    for (const edge of visibleEdges) {
      const s = sims.current.get(edge.source);
      const t = sims.current.get(edge.target);
      if (!s || !t) continue;
      const dx = t.x - s.x;
      const dy = t.y - s.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const length = edge.kind === "member" ? 42 : edge.kind === "aggregate" ? 240 : 120;
      // d3-style link strength: weaker on hubs, so leaves settle around their parent.
      const degS = neighbours.get(edge.source)?.size || 1;
      const degT = neighbours.get(edge.target)?.size || 1;
      const stiffness = (edge.kind === "member" ? 0.8 : 0.5) / Math.min(degS, degT);
      const f = ((d - length) / d) * stiffness * a;
      const bias = degS / (degS + degT); // the lighter end moves more
      s.vx += dx * f * (1 - bias); s.vy += dy * f * (1 - bias);
      t.vx -= dx * f * bias; t.vy -= dy * f * bias;
    }
    for (const { sim } of list) {
      sim.vx -= sim.x * 0.004 * a;
      sim.vy -= sim.y * 0.004 * a;
      if (sim.fx != null && sim.fy != null) { sim.x = sim.fx; sim.y = sim.fy; sim.vx = 0; sim.vy = 0; continue; }
      sim.vx *= 0.6; sim.vy *= 0.6;
      sim.x += clamp(sim.vx, -60, 60);
      sim.y += clamp(sim.vy, -60, 60);
    }
  }, [nodes, visibleEdges, neighbours]);

  // The animation loop outlives renders: always step the latest node set.
  const stepRef = useRef(stepForce);
  useEffect(() => { stepRef.current = stepForce; }, [stepForce]);

  const run = useCallback((energy: number) => {
    if (layout !== "force") return;
    alpha.current = Math.max(alpha.current, energy);
    if (frame.current != null) return;
    if (reduced) {
      // No animation: settle synchronously and draw once.
      for (let tick = 0; tick < 300 && alpha.current > 0.01; tick += 1) { stepForce(alpha.current); alpha.current *= 0.985; }
      alpha.current = 0;
      if (pendingFit.current) { pendingFit.current = false; fit(false); }
      setTick((value) => value + 1);
      return;
    }
    const loop = () => {
      const perFrame = nodes.length > 150 ? 2 : 1;
      for (let tick = 0; tick < perFrame; tick += 1) { stepRef.current(alpha.current); alpha.current *= 0.985; }
      setTick((value) => value + 1);
      if (alpha.current > 0.02) frame.current = requestAnimationFrame(loop);
      else {
        frame.current = null;
        alpha.current = 0;
        if (pendingFit.current) { pendingFit.current = false; fitRef.current(); }
      }
    };
    frame.current = requestAnimationFrame(loop);
  }, [layout, reduced, stepForce, nodes.length, fit]);

  useEffect(() => () => { if (frame.current != null) cancelAnimationFrame(frame.current); }, []);

  // Seed new nodes near where they came from; drop positions of removed nodes.
  useEffect(() => {
    const store = sims.current;
    const ids = new Set(nodes.map((node) => node.id));
    let added = 0;
    nodes.forEach((node, index) => {
      if (store.has(node.id)) return;
      added += 1;
      const anchor = (node.seedFrom && store.get(node.seedFrom)) || (node.parent && store.get(node.parent)) || [...(neighbours.get(node.id) || [])].map((id) => store.get(id)).find(Boolean);
      const angle = index * 2.399963;
      const spread = anchor ? 30 + Math.random() * 40 : 40 * Math.sqrt(index + 1);
      store.set(node.id, { x: (anchor?.x ?? 0) + Math.cos(angle) * spread, y: (anchor?.y ?? 0) + Math.sin(angle) * spread, vx: 0, vy: 0, fx: null, fy: null });
    });
    for (const id of [...store.keys()]) if (!ids.has(id)) store.delete(id);
    if (layout === "hierarchical") {
      const positions = hierarchicalPositions(nodes, visibleEdges);
      positions.forEach((point, id) => {
        const sim = store.get(id);
        if (!sim || (sim.fx != null && sim.fy != null)) return;
        sim.x = point.x; sim.y = point.y; sim.vx = 0; sim.vy = 0;
      });
      if (pendingFit.current) { pendingFit.current = false; fit(false); }
      setTick((value) => value + 1);
    } else if (added || alpha.current === 0) {
      let energy = added ? 0.9 : 0.3;
      if (added > 40 && !reduced) {
        // Settle most of a big layout synchronously (a few ms), then animate only the last
        // stretch: re-rendering hundreds of SVG nodes every frame for seconds is what hurts.
        const ticks = nodes.length > 150 ? 220 : 140;
        for (let tick = 0; tick < ticks; tick += 1) { stepForce(energy); energy *= 0.985; }
        energy = Math.max(energy, 0.05);
      }
      run(energy);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, visibleEdges, layout]);

  // Layout switch or host request: fit again once the layout settles (the seeding effect above
  // has already placed a hierarchical layout by now; a running force layout fits when it cools).
  useEffect(() => {
    userMoved.current = false;
    if (layout === "force" && alpha.current > 0) pendingFit.current = true;
    else fitRef.current(false);
  }, [layout, fitKey]);
  // Viewport resized (first measure, full screen): keep the graph framed until the user pans or zooms.
  useEffect(() => { if (!userMoved.current) fitRef.current(false); }, [size.w, size.h]);
  useEffect(() => { if (centerOn) center(centerOn); }, [centerOn, center]);

  // ------------------------------------------------------------ zoom & pan
  const zoomBy = useCallback((factor: number, originX = size.w / 2, originY = size.h / 2) => {
    setTransform((current) => {
      const k = clamp(current.k * factor, MIN_K, MAX_K);
      const ratio = k / current.k;
      return { k, x: originX - (originX - current.x) * ratio, y: originY - (originY - current.y) * ratio };
    });
  }, [size]);
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      userMoved.current = true;
      const box = svg.getBoundingClientRect();
      zoomBy(Math.exp(-event.deltaY * 0.0015), event.clientX - box.left, event.clientY - box.top);
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, [zoomBy]);

  const toGraph = (clientX: number, clientY: number) => {
    const box = svgRef.current!.getBoundingClientRect();
    return { x: (clientX - box.left - transform.x) / transform.k, y: (clientY - box.top - transform.y) / transform.k };
  };
  function onPointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return;
    const target = (event.target as Element).closest("[data-node-id]");
    const handle = (event.target as Element).closest("[data-handle]");
    if (handle) return;
    const id = target?.getAttribute("data-node-id") || null;
    drag.current = { id, startX: event.clientX, startY: event.clientY, originX: transform.x, originY: transform.y, moved: false, pointer: event.pointerId };
    try { svgRef.current?.setPointerCapture(event.pointerId); } catch { /* ignore */ }
  }
  function onPointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    const state = drag.current;
    if (!state || state.pointer !== event.pointerId) return;
    const dx = event.clientX - state.startX;
    const dy = event.clientY - state.startY;
    if (!state.moved && Math.hypot(dx, dy) < 4) return;
    state.moved = true;
    if (state.id) {
      const sim = sims.current.get(state.id);
      if (!sim) return;
      const point = toGraph(event.clientX, event.clientY);
      sim.fx = point.x; sim.fy = point.y; sim.x = point.x; sim.y = point.y;
      if (layout === "force") run(0.25); else setTick((value) => value + 1);
    } else {
      userMoved.current = true;
      setTransform((current) => ({ ...current, x: state.originX + dx, y: state.originY + dy }));
    }
  }
  function onPointerUp(event: ReactPointerEvent<SVGSVGElement>) {
    const state = drag.current;
    drag.current = null;
    if (!state || state.pointer !== event.pointerId) return;
    if (state.moved) {
      if (state.id) setAnnounce(`${nodeById.get(state.id)?.label || "Node"} pinned. Double-click to release.`);
      return;
    }
    if (state.id) {
      // Double-click (two taps within 350ms) releases a pinned node; with pointer capture on the
      // canvas the native dblclick would target the svg, not the node.
      const now = Date.now();
      if (lastTap.current && lastTap.current.id === state.id && now - lastTap.current.time < 350) { lastTap.current = null; release(state.id); return; }
      lastTap.current = { id: state.id, time: now };
      setActiveId(state.id);
      onSelect(state.id);
    } else onSelect(null);
  }
  function release(id: string) {
    const sim = sims.current.get(id);
    if (!sim || sim.fx == null) return;
    sim.fx = null; sim.fy = null;
    setAnnounce(`${nodeById.get(id)?.label || "Node"} released`);
    if (layout === "force") run(0.3);
    else {
      const point = hierarchicalPositions(nodes, visibleEdges).get(id);
      if (point) { sim.x = point.x; sim.y = point.y; }
      setTick((value) => value + 1);
    }
  }

  // ------------------------------------------------------------ search
  const needle = query.trim().toLowerCase();
  const matches = useMemo(() => (needle ? nodes.filter((node) => node.label.toLowerCase().includes(needle) || (node.sublabel || "").toLowerCase().includes(needle)) : []), [needle, nodes]);
  const matchSet = useMemo(() => new Set(matches.map((node) => node.id)), [matches]);
  function goToMatch(offset: number) {
    if (!matches.length) return;
    const index = (matchIndex + offset + matches.length) % matches.length;
    setMatchIndex(index);
    const node = matches[index];
    setActiveId(node.id);
    onSelect(node.id);
    center(node.id);
    setAnnounce(`${node.label}: match ${index + 1} of ${matches.length}`);
  }

  // ------------------------------------------------------------ keyboard
  const nodeRefs = useRef(new Map<string, SVGGElement>());
  const focusNode = (id: string) => {
    setActiveId(id);
    const sim = sims.current.get(id);
    if (sim) {
      const sx = sim.x * transform.k + transform.x;
      const sy = sim.y * transform.k + transform.y;
      if (sx < 40 || sy < 40 || sx > size.w - 40 || sy > size.h - 40) center(id);
    }
    nodeRefs.current.get(id)?.focus({ preventScroll: true });
  };
  function spatial(fromId: string, key: string) {
    const from = sims.current.get(fromId);
    if (!from) return null;
    let best: string | null = null;
    let bestScore = Infinity;
    for (const node of nodes) {
      if (node.id === fromId) continue;
      const sim = sims.current.get(node.id);
      if (!sim) continue;
      const dx = sim.x - from.x;
      const dy = sim.y - from.y;
      const primary = key === "ArrowRight" ? dx : key === "ArrowLeft" ? -dx : key === "ArrowDown" ? dy : -dy;
      if (primary <= 1) continue;
      const score = primary + Math.abs(key === "ArrowRight" || key === "ArrowLeft" ? dy : dx) * 2.2;
      if (score < bestScore) { bestScore = score; best = node.id; }
    }
    return best;
  }
  function onNodeKey(event: ReactKeyboardEvent<SVGGElement>, node: GraphNode) {
    const key = event.key;
    if (key.startsWith("Arrow")) {
      event.preventDefault();
      const next = spatial(node.id, key);
      if (next) focusNode(next);
    } else if (key === "Enter" || key === " ") {
      event.preventDefault();
      onSelect(node.id);
    } else if ((key === "+" || key === "=") && node.expandable && !node.expanded) {
      event.preventDefault();
      onExpand?.(node.id);
    } else if ((key === "-" || key === "_") && node.expandable && node.expanded) {
      event.preventDefault();
      onCollapse?.(node.id);
    } else if (key === "u" || key === "U") {
      release(node.id);
    } else if (key === "Escape") {
      if (full) setFull(false);
      onSelect(null);
    }
  }
  useEffect(() => {
    if (!full) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setFull(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [full]);
  useEffect(() => { userMoved.current = false; }, [full]);

  // ------------------------------------------------------------ render
  const focusId = selectedId || hovered;
  const lit = useMemo(() => {
    if (!focusId || !nodeById.has(focusId)) return null;
    return new Set([focusId, ...(neighbours.get(focusId) || [])]);
  }, [focusId, neighbours, nodeById]);
  const big = nodes.length > 150;
  const showAllLabels = transform.k >= (big ? 0.75 : 0.5) || nodes.length <= 60;
  const tabStop = activeId && nodeById.has(activeId) ? activeId : selectedId && nodeById.has(selectedId) ? selectedId : nodes[0]?.id;
  const hier = layout === "hierarchical";
  const pinnedCount = nodes.filter((node) => sims.current.get(node.id)?.fx != null).length;

  const endpoint = (node: GraphNode, sim: Sim, toward: Sim, outgoing: boolean) => {
    if (hier) {
      const box = BOX[node.kind];
      const right = toward.x > sim.x + 1 || (Math.abs(toward.x - sim.x) <= 1 && outgoing);
      return { x: sim.x + (right ? box.w / 2 : -box.w / 2), y: sim.y };
    }
    const dx = toward.x - sim.x;
    const dy = toward.y - sim.y;
    const d = Math.hypot(dx, dy) || 1;
    const r = radius(node) + 2;
    return { x: sim.x + (dx / d) * r, y: sim.y + (dy / d) * r };
  };
  const edgePath = (edge: GraphEdge) => {
    const s = sims.current.get(edge.source);
    const t = sims.current.get(edge.target);
    const sn = nodeById.get(edge.source);
    const tn = nodeById.get(edge.target);
    if (!s || !t || !sn || !tn) return "";
    const a = endpoint(sn, s, t, true);
    const b = endpoint(tn, t, s, false);
    if (!hier) return `M${a.x.toFixed(1)},${a.y.toFixed(1)}L${b.x.toFixed(1)},${b.y.toFixed(1)}`;
    if (Math.abs(a.x - b.x) < 2) {
      const bulge = 30 + Math.min(90, Math.abs(b.y - a.y) * 0.25);
      return `M${a.x},${a.y}C${a.x + bulge},${a.y} ${b.x + bulge},${b.y} ${b.x},${b.y}`;
    }
    const bend = Math.max(30, Math.abs(b.x - a.x) * 0.45) * (b.x > a.x ? 1 : -1);
    return `M${a.x.toFixed(1)},${a.y.toFixed(1)}C${(a.x + bend).toFixed(1)},${a.y.toFixed(1)} ${(b.x - bend).toFixed(1)},${b.y.toFixed(1)} ${b.x.toFixed(1)},${b.y.toFixed(1)}`;
  };

  return (
    <div className={`gc-wrap${full ? " is-full" : ""}`} role="region" aria-label={ariaLabel}>
      <div className="gc-toolbar">
        <div className="gc-search">
          <Search size={13} aria-hidden="true" />
          <input
            value={query}
            placeholder="Find a node in this graph…"
            aria-label="Find a node in this graph"
            onChange={(event) => { setQuery(event.target.value); setMatchIndex(-1); }}
            onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); goToMatch(event.shiftKey ? -1 : 1); } if (event.key === "Escape") setQuery(""); }}
          />
          {needle && <small>{matches.length ? `${Math.max(0, matchIndex) + 1}/${matches.length}` : "0"}</small>}
        </div>
        <div className="gc-segmented" role="group" aria-label="Layout">
          <button type="button" aria-pressed={layout === "force"} onClick={() => onLayoutChange("force")} title="Force-directed layout"><Network size={13} aria-hidden="true" />Force</button>
          <button type="button" aria-pressed={layout === "hierarchical"} onClick={() => onLayoutChange("hierarchical")} title="Hierarchical, left to right by lineage"><Workflow size={13} aria-hidden="true" />Hierarchy</button>
        </div>
        <div className="gc-buttons">
          <button type="button" className="gc-btn" onClick={() => { userMoved.current = true; zoomBy(1.25); }} aria-label="Zoom in" title="Zoom in"><Plus size={14} aria-hidden="true" /></button>
          <button type="button" className="gc-btn" onClick={() => { userMoved.current = true; zoomBy(0.8); }} aria-label="Zoom out" title="Zoom out"><Minus size={14} aria-hidden="true" /></button>
          <button type="button" className="gc-btn" onClick={() => fit()} aria-label="Fit to screen" title="Fit to screen"><Scan size={14} aria-hidden="true" /></button>
          {selectedId && nodeById.has(selectedId) && <button type="button" className="gc-btn" onClick={() => center(selectedId)} aria-label="Center on selection" title="Center on selection"><Crosshair size={14} aria-hidden="true" /></button>}
          {pinnedCount > 0 && <button type="button" className="gc-btn gc-btn--text" onClick={() => { nodes.forEach((node) => { const sim = sims.current.get(node.id); if (sim) { sim.fx = null; sim.fy = null; } }); if (layout === "force") run(0.5); else { pendingFit.current = false; const positions = hierarchicalPositions(nodes, visibleEdges); positions.forEach((point, id) => { const sim = sims.current.get(id); if (sim) { sim.x = point.x; sim.y = point.y; } }); setTick((value) => value + 1); } setAnnounce("All nodes released"); }} title="Release every pinned node"><Pin size={13} aria-hidden="true" />Unpin {pinnedCount}</button>}
          <button type="button" className="gc-btn" onClick={() => setFull((value) => !value)} aria-label={full ? "Exit full screen" : "Full screen"} title={full ? "Exit full screen (Escape)" : "Full screen"}>{full ? <Minimize2 size={14} aria-hidden="true" /> : <Maximize2 size={14} aria-hidden="true" />}</button>
        </div>
      </div>
      <div ref={wrapRef} className="gc-stage" style={full ? undefined : { height }}>
        <svg
          ref={svgRef}
          className={`gc-svg${drag.current?.moved && !drag.current.id ? " is-panning" : ""}`}
          width={size.w}
          height={size.h}
          role="group"
          aria-label={`${ariaLabel}: ${nodes.length} nodes, ${visibleEdges.length} relationships. Tab to a node, arrow keys move between nodes, Enter selects, plus and minus expand or collapse, U releases a pinned node.`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={() => { drag.current = null; }}
        >
          <defs>
            <marker id="gc-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" className="gc-arrow" /></marker>
          </defs>
          <rect className="gc-bg" width={size.w} height={size.h} />
          <g transform={`translate(${transform.x.toFixed(2)},${transform.y.toFixed(2)}) scale(${transform.k.toFixed(4)})`}>
            <g className="gc-edges">
              {visibleEdges.map((edge) => {
                const d = edgePath(edge);
                if (!d) return null;
                const on = lit ? lit.has(edge.source) && lit.has(edge.target) && (edge.source === focusId || edge.target === focusId) : false;
                const dim = (lit && !on) || (needle && !lit && !(matchSet.has(edge.source) || matchSet.has(edge.target)));
                return (
                  <g key={edge.id}>
                    <path d={d} className={`gc-edge ${edge.kind}${on ? " is-on" : ""}${dim ? " is-dim" : ""}`} style={edge.weight && edge.weight > 1 ? { strokeWidth: Math.min(7, 1.5 + Math.log2(edge.weight) * 1.3) } : undefined} markerEnd={edge.directed ? "url(#gc-arrow)" : undefined} />
                    {!big && edge.title && <path d={d} className="gc-edge-hit"><title>{edge.title}</title></path>}
                  </g>
                );
              })}
            </g>
            <g className="gc-nodes">
              {nodes.map((node) => {
                const sim = sims.current.get(node.id);
                if (!sim) return null;
                const isSelected = node.id === selectedId;
                const on = lit?.has(node.id);
                const dim = (lit && !on) || (needle && !matchSet.has(node.id) && !lit);
                const labelled = showAllLabels || isSelected || on || matchSet.has(node.id) || node.kind === "source" || node.focus;
                const pinned = sim.fx != null;
                const box = BOX[node.kind];
                const r = radius(node);
                const handleX = hier ? box.w / 2 - 2 : r * 0.75 + 4;
                const handleY = hier ? -box.h / 2 + 2 : -r * 0.75 - 4;
                const label = `${node.kind === "source" ? "Source" : node.kind === "column" ? "Column" : "Table"} ${node.label}${node.sublabel ? `, ${node.sublabel}` : ""}${node.badges?.length ? `, ${node.badges.join(", ")}` : ""}${node.expandable ? node.expanded ? ", expanded" : ", collapsed" : ""}${pinned ? ", pinned" : ""}`;
                return (
                  <g
                    key={node.id}
                    ref={(element) => { if (element) nodeRefs.current.set(node.id, element); else nodeRefs.current.delete(node.id); }}
                    data-node-id={node.id}
                    className={`gc-node gc-node--${node.kind}${isSelected ? " is-selected" : ""}${on ? " is-on" : ""}${dim ? " is-dim" : ""}${node.focus ? " is-focus" : ""}${node.warn ? " is-warn" : ""}${pinned ? " is-pinned" : ""}${matchSet.has(node.id) ? " is-match" : ""}`}
                    transform={`translate(${sim.x.toFixed(1)},${sim.y.toFixed(1)})`}
                    role="button"
                    tabIndex={node.id === tabStop ? 0 : -1}
                    aria-label={label}
                    aria-pressed={isSelected}
                    onKeyDown={(event) => onNodeKey(event, node)}
                    onFocus={() => setActiveId(node.id)}
                    onPointerEnter={() => setHovered(node.id)}
                    onPointerLeave={() => setHovered((current) => (current === node.id ? null : current))}
                    style={{ "--gc-color": node.color } as CSSProperties}
                  >
                    <title>{label}</title>
                    {hier ? (
                      <>
                        <rect className="gc-card" x={-box.w / 2} y={-box.h / 2} width={box.w} height={box.h} rx={node.kind === "column" ? 5 : 8} />
                        <rect className="gc-stripe" x={-box.w / 2} y={-box.h / 2} width={4} height={box.h} rx={2} />
                        {(labelled || transform.k >= 0.4) && (
                          <>
                            <text className="gc-label" x={-box.w / 2 + 11} y={node.kind === "column" || !node.sublabel ? 4 : -3}>{short(node.label, node.kind === "column" ? 24 : 26)}</text>
                            {node.kind !== "column" && node.sublabel && <text className="gc-sublabel" x={-box.w / 2 + 11} y={12}>{short(node.sublabel, 32)}</text>}
                          </>
                        )}
                      </>
                    ) : (
                      <>
                        <circle className="gc-dot" r={r} />
                        {node.kind === "source" && <text className="gc-count" y={4} textAnchor="middle">{node.weight ?? ""}</text>}
                        {labelled && (
                          <>
                            <text className="gc-label" x={r + 5} y={node.kind === "column" ? 3.5 : 4}>{short(node.label, node.kind === "column" ? 22 : 30)}</text>
                            {node.sublabel && node.kind !== "column" && transform.k >= 1.1 && <text className="gc-sublabel" x={r + 5} y={17}>{short(node.sublabel, 34)}</text>}
                          </>
                        )}
                      </>
                    )}
                    {pinned && <circle className="gc-pin" cx={hier ? -box.w / 2 + 4 : -r * 0.75} cy={hier ? -box.h / 2 + 4 : -r * 0.75} r={3} />}
                    {node.expandable && (labelled || hier || nodes.length <= 60) && (
                      <g
                        data-handle="true"
                        className="gc-handle"
                        transform={`translate(${handleX},${handleY})`}
                        onPointerDown={(event) => event.stopPropagation()}
                        onClick={(event) => { event.stopPropagation(); if (node.expanded) onCollapse?.(node.id); else onExpand?.(node.id); }}
                      >
                        <title>{node.expanded ? `Collapse ${node.label} (drill up)` : `Expand ${node.label} (drill down)`}</title>
                        <circle r={7} />
                        <path d={node.expanded ? "M-3.5 0H3.5" : "M-3.5 0H3.5M0 -3.5V3.5"} />
                      </g>
                    )}
                  </g>
                );
              })}
            </g>
          </g>
        </svg>
        {!nodes.length && <p className="gc-empty">Nothing to draw in this view.</p>}
        <div className="gc-zoom-readout" aria-hidden="true">{Math.round(transform.k * 100)}%{!showAllLabels ? " · zoom in for labels" : ""}</div>
      </div>
      <div className="viz-sr-only" aria-live="polite">{announce}</div>
    </div>
  );
}
