"use client";

/**
 * Data-driven result charts, drawn as inline SVG (no chart library).
 *
 * The API picks a chart for each result set (`structured.chart`, see app/types.ts
 * ChartSpec) and offers alternatives; older answers only carry
 * {type: "bar" | "line" | "table", title, x, y, data}. Every chart:
 * - measures its container, so it is responsive (the inspector is ~300-380px wide);
 * - uses the categorical palette tokens --chart-1..8 (validated for light and dark
 *   surfaces; see globals.css), fixed slot order, never cycled: extra series fold
 *   into "Other" (--chart-other);
 * - has a hover tooltip and is keyboard accessible: the plot is one tab stop and the
 *   arrow keys step through data points, announced through a live region;
 * - carries an SVG <title>/<desc>; the full values are always in the result table.
 *
 * Interaction (drill down / up):
 * - clicking a bar, slice, line point or a legend entry's drill button drills into it.
 *   Time series drill by grain client-side (year -> quarter -> month -> day) when the
 *   rows allow it; a category drills into the next dimension present in the rows
 *   (the series column, or another categorical column). When the result has no finer
 *   detail, `onDrill({ column, value, question, measure, filters })` is emitted with a
 *   natural-language follow-up for the host to ask.
 * - a breadcrumb ("All > deposit > 2026-05") drills back up; Backspace does too.
 * - legend entries toggle series on and off; line and scatter charts zoom by dragging
 *   across the x-axis (brush) with a reset; every chart can be expanded full screen.
 * - keyboard: arrow keys step, Enter / Space drills the active mark, Backspace drills up.
 */
import {
  ArrowUp,
  ChartColumn,
  ChartColumnBig,
  ChartColumnStacked,
  ChartLine,
  ChartPie,
  ChartScatter,
  ChevronRight,
  Hash,
  Maximize2,
  MessageSquarePlus,
  RotateCcw,
  Table,
  X,
} from "lucide-react";
import { createContext, KeyboardEvent, PointerEvent, ReactNode, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ChartDrillFilter, ChartDrillRequest, ChartSpec, ChartType, ChartUnit } from "../types";
import "./charts-interactive.css";

type Row = Record<string, string | number | null | undefined>;
type Tip = { title: string; rows: { key: string; label: string; value: string; swatch?: string; mark?: "line" | "rect" }[] };
type Point = { x: number; y: number };

const CHART_TYPES: ChartType[] = ["kpi", "line", "bar", "grouped_bar", "stacked_bar", "pie", "scatter", "table"];
const SLOT_COUNT = 8;
const CHAR_W = 6.3; // approx. width of one 11px UI glyph, for label fitting
const OTHER_COLOR = "var(--chart-other)";
const slot = (index: number) => `var(--chart-${index + 1})`;

export const CHART_TYPE_LABELS: Record<ChartType, string> = {
  kpi: "KPI",
  line: "Line",
  bar: "Bar",
  grouped_bar: "Grouped",
  stacked_bar: "Stacked",
  pie: "Pie",
  scatter: "Scatter",
  table: "Table",
};
const CHART_TYPE_ICONS: Record<ChartType, typeof Table> = {
  kpi: Hash,
  line: ChartLine,
  bar: ChartColumn,
  grouped_bar: ChartColumnBig,
  stacked_bar: ChartColumnStacked,
  pie: ChartPie,
  scatter: ChartScatter,
  table: Table,
};

export const isChartType = (value: unknown): value is ChartType => typeof value === "string" && (CHART_TYPES as string[]).includes(value);

// ------------------------------------------------------------------ values & formatting

const num = (value: unknown): number | null => {
  if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
const text = (value: unknown) => (value === null || value === undefined || value === "" ? "(blank)" : String(value));
export const humanize = (name: string) => {
  const spaced = name.replace(/_/g, " ").replace(/\s+/g, " ").trim();
  return spaced ? spaced[0].toUpperCase() + spaced.slice(1) : name;
};
const truncate = (label: string, maxChars: number) => (maxChars < 2 ? "" : label.length > maxChars ? `${label.slice(0, Math.max(1, maxChars - 1))}…` : label);

const SHARE_NAME = /(share|pct|percent|percentage|ratio|rate|proportion|fraction)/i;
const MONEY_NAME = /(amount|revenue|balance|price|cost|spend|value_usd|sales)/i;

/** The API sends units per measure; older answers get the same name-based guess the API makes. */
function unitFor(chart: ChartSpec, column: string | null | undefined): ChartUnit {
  if (!column) return "number";
  const declared = chart.units?.[column];
  if (declared === "percent" || declared === "fraction" || declared === "currency" || declared === "count" || declared === "number") return declared;
  const values = chart.data.map((row) => num(row[column])).filter((value): value is number => value != null);
  if (SHARE_NAME.test(column)) return values.length && Math.max(...values.map(Math.abs)) <= 1 ? "fraction" : "percent";
  if (MONEY_NAME.test(column)) return "currency";
  if (values.length && values.every((value) => Number.isInteger(value))) return "count";
  return "number";
}

const compactFormat = (value: number) => new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value);

/** Formats a measure for its unit; `compact` for axis ticks and stat tiles (12.9K, $4.2M). */
export function formatChartValue(value: number | null | undefined, unit: ChartUnit = "number", compact = false): string {
  if (value == null || !Number.isFinite(value)) return "–";
  switch (unit) {
    case "fraction":
      return new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: compact ? 0 : 1 }).format(value);
    case "percent":
      return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: compact ? 0 : 1 }).format(value)}%`;
    case "currency":
      return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", notation: compact ? "compact" : "standard", ...(compact ? { maximumFractionDigits: 1 } : Number.isInteger(value) ? { maximumFractionDigits: 0 } : { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }).format(value);
    case "count":
      return compact && Math.abs(value) >= 10_000 ? compactFormat(value) : Math.round(value).toLocaleString();
    default:
      if (compact && Math.abs(value) >= 10_000) return compactFormat(value);
      return new Intl.NumberFormat(undefined, { maximumFractionDigits: Math.abs(value) < 1 ? 3 : 2 }).format(value);
  }
}

// ------------------------------------------------------------------ scales

function niceStep(span: number, count: number) {
  const raw = span / Math.max(1, count);
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / magnitude;
  return (normalized >= 7.5 ? 10 : normalized >= 3.5 ? 5 : normalized >= 1.5 ? 2 : 1) * magnitude;
}

/** Rounds a value domain out to clean ticks (0 / 1,000 / 2,000 …). */
function niceDomain(minimum: number, maximum: number, count = 4) {
  let min = minimum;
  let max = maximum;
  if (!Number.isFinite(min) || !Number.isFinite(max)) { min = 0; max = 1; }
  if (min === max) {
    if (min === 0) max = 1;
    else if (min > 0) min = 0;
    else max = 0;
  }
  let step = niceStep(max - min, count);
  // Small integer ranges (counts like 0–2) would otherwise get 0.5 steps that round to duplicate labels.
  if (step < 1 && Number.isInteger(min) && Number.isInteger(max)) step = 1;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let tick = lo; tick <= hi + step / 2; tick += step) ticks.push(Number(tick.toPrecision(12)));
  return { lo, hi, ticks };
}

const linear = (d0: number, d1: number, r0: number, r1: number) => (value: number) => (d1 === d0 ? (r0 + r1) / 2 : r0 + ((value - d0) / (d1 - d0)) * (r1 - r0));
const invertLinear = (d0: number, d1: number, r0: number, r1: number) => (pixel: number) => (r1 === r0 ? d0 : d0 + ((pixel - r0) / (r1 - r0)) * (d1 - d0));

const DATE_PATTERN = /^\d{4}-\d{2}(-\d{2})?([T ]\d{2}(:\d{2}(:\d{2}(\.\d+)?)?)?(Z|[+-]\d{2}:?\d{2})?)?$/;

/** ISO-ish date strings → epoch ms (UTC); anything else → null. */
function parseTime(value: unknown): number | null {
  if (typeof value !== "string") return null;
  let source = value.trim();
  if (!DATE_PATTERN.test(source)) return null;
  if (source.length === 7) source += "-01";
  source = source.replace(" ", "T");
  if (source.includes("T") && !/(Z|[+-]\d{2}:?\d{2})$/.test(source)) source += "Z";
  const parsed = Date.parse(source);
  return Number.isFinite(parsed) ? parsed : null;
}

const DAY = 86_400_000;
function timeFormatters(times: number[]) {
  const span = Math.max(...times) - Math.min(...times);
  const monthly = times.every((time) => { const date = new Date(time); return date.getUTCDate() === 1 && date.getUTCHours() === 0 && date.getUTCMinutes() === 0; });
  const intraday = span < 2 * DAY && times.some((time) => time % DAY !== 0);
  const tick: Intl.DateTimeFormatOptions = intraday ? { hour: "2-digit", minute: "2-digit" } : monthly ? { month: "short", year: "2-digit" } : span > 300 * DAY ? { month: "short", year: "2-digit" } : { month: "short", day: "numeric" };
  const full: Intl.DateTimeFormatOptions = intraday ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" } : monthly ? { month: "long", year: "numeric" } : { month: "short", day: "numeric", year: "numeric" };
  const tickFormat = new Intl.DateTimeFormat(undefined, { ...tick, timeZone: "UTC" });
  const fullFormat = new Intl.DateTimeFormat(undefined, { ...full, timeZone: "UTC" });
  return { tick: (time: number) => tickFormat.format(time), full: (time: number) => fullFormat.format(time) };
}

// ------------------------------------------------------------------ time grains (drill by grain)

type Grain = "year" | "quarter" | "month" | "day";
const GRAINS: Grain[] = ["year", "quarter", "month", "day"];
const GRAIN_LABEL: Record<Grain, string> = { year: "Year", quarter: "Quarter", month: "Month", day: "Day" };

/** The grain the rows come in: "time" for intraday timestamps. */
function nativeGrain(times: number[]): Grain | "time" {
  if (times.some((time) => time % DAY !== 0)) return "time";
  const dates = times.map((time) => new Date(time));
  if (dates.some((date) => date.getUTCDate() !== 1)) return "day";
  if (dates.some((date) => date.getUTCMonth() !== 0)) return "month";
  return "year";
}
function bucketStart(time: number, grain: Grain) {
  const date = new Date(time);
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth();
  if (grain === "year") return Date.UTC(year, 0, 1);
  if (grain === "quarter") return Date.UTC(year, month - (month % 3), 1);
  if (grain === "month") return Date.UTC(year, month, 1);
  return Date.UTC(year, month, date.getUTCDate());
}
function bucketEnd(start: number, grain: Grain) {
  const date = new Date(start);
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth();
  if (grain === "year") return Date.UTC(year + 1, 0, 1);
  if (grain === "quarter") return Date.UTC(year, month + 3, 1);
  if (grain === "month") return Date.UTC(year, month + 1, 1);
  return start + DAY;
}
const isoDay = (time: number) => new Date(time).toISOString().slice(0, 10);
/** Breadcrumb / follow-up label for a period: 2026, 2026-Q2, 2026-05, 2026-05-03. */
function periodKey(time: number, grain: Grain) {
  const date = new Date(time);
  const year = date.getUTCFullYear();
  if (grain === "year") return String(year);
  if (grain === "quarter") return `${year}-Q${Math.floor(date.getUTCMonth() / 3) + 1}`;
  if (grain === "month") return isoDay(time).slice(0, 7);
  return isoDay(time);
}
function grainFormatters(grain: Grain) {
  if (grain === "year") return { tick: (time: number) => String(new Date(time).getUTCFullYear()), full: (time: number) => String(new Date(time).getUTCFullYear()) };
  if (grain === "quarter") {
    const quarter = (time: number) => Math.floor(new Date(time).getUTCMonth() / 3) + 1;
    return { tick: (time: number) => `Q${quarter(time)} '${String(new Date(time).getUTCFullYear()).slice(2)}`, full: (time: number) => `Q${quarter(time)} ${new Date(time).getUTCFullYear()}` };
  }
  const tick = new Intl.DateTimeFormat(undefined, { ...(grain === "month" ? { month: "short", year: "2-digit" } : { month: "short", day: "numeric" }), timeZone: "UTC" });
  const full = new Intl.DateTimeFormat(undefined, { ...(grain === "month" ? { month: "long", year: "numeric" } : { month: "short", day: "numeric", year: "numeric" }), timeZone: "UTC" });
  return { tick: (time: number) => tick.format(time), full: (time: number) => full.format(time) };
}
/** Grains coarser than the rows' own that still give two or more buckets. */
function coarserGrains(native: Grain | "time", times: number[]): Grain[] {
  const limit = native === "time" ? GRAINS.length : GRAINS.indexOf(native);
  return GRAINS.slice(0, limit).filter((grain) => new Set(times.map((time) => bucketStart(time, grain))).size >= 2);
}
/** Next finer grain; null means "as returned" (no aggregation). */
function finerGrain(grain: Grain, native: Grain | "time" | null): Grain | null {
  const next = GRAINS[GRAINS.indexOf(grain) + 1];
  return !next || next === native ? null : next;
}
/** Long daily series start rolled up so there is something to drill into. */
function autoGrain(times: number[], options: Grain[]): Grain | null {
  if (new Set(times).size <= 60) return null;
  for (const grain of [...options].reverse()) if (new Set(times.map((time) => bucketStart(time, grain))).size <= 60) return grain;
  return options[0] ?? null;
}

/** Axis / tooltip labels for category keys; ISO dates (a line switched to bars) read as dates. */
function categoryLabels(keys: string[], grain: Grain | null = null) {
  const times = keys.map(parseTime);
  if (keys.length && times.every((time) => time != null)) {
    const format = grain ? grainFormatters(grain) : timeFormatters(times as number[]);
    return { tick: (index: number) => format.tick(times[index]!), full: (index: number) => format.full(times[index]!) };
  }
  return { tick: (index: number) => keys[index], full: (index: number) => keys[index] };
}

/** Evenly spaced indexes (always including the first) so axis labels never collide. */
function tickIndexes(count: number, maxTicks: number) {
  if (count <= 0) return [];
  const step = Math.max(1, Math.ceil(count / Math.max(1, maxTicks)));
  const indexes: number[] = [];
  for (let index = 0; index < count; index += step) indexes.push(index);
  return indexes;
}

// ------------------------------------------------------------------ bar geometry

/** Vertical bar: 4px rounded data end, square at the baseline. */
function columnPath(x: number, width: number, base: number, end: number, radius = 4) {
  const height = Math.abs(end - base);
  if (height < 0.5 || width <= 0) return "";
  const r = Math.min(radius, height, width / 2);
  const up = end < base;
  const inner = up ? end + r : end - r;
  return `M${x},${base}L${x},${inner}Q${x},${end} ${x + r},${end}L${x + width - r},${end}Q${x + width},${end} ${x + width},${inner}L${x + width},${base}Z`;
}

/** Horizontal bar: 4px rounded data end, square at the baseline. */
function barPath(y: number, height: number, base: number, end: number, radius = 4) {
  const width = Math.abs(end - base);
  if (width < 0.5 || height <= 0) return "";
  const r = Math.min(radius, width, height / 2);
  const right = end > base;
  const inner = right ? end - r : end + r;
  return `M${base},${y}L${inner},${y}Q${end},${y} ${end},${y + r}L${end},${y + height - r}Q${end},${y + height} ${inner},${y + height}L${base},${y + height}Z`;
}

// ------------------------------------------------------------------ spec resolution

type Fields = { x: string | null; y: string | null; series: string | null; columns: string[] };

function columnsOf(chart: ChartSpec) {
  const seen = new Set<string>();
  for (const row of chart.data.slice(0, 50)) for (const key of Object.keys(row)) seen.add(key);
  return Array.from(seen);
}
const isNumericColumn = (chart: ChartSpec, column: string) => {
  const values = chart.data.map((row) => row[column]).filter((value) => value !== null && value !== undefined && value !== "");
  return values.length > 0 && values.every((value) => num(value) != null);
};

/** Fills x / y / series the way the API would when an (older) spec omits them. */
function resolveFields(chart: ChartSpec): Fields {
  const columns = columnsOf(chart);
  const has = (column?: string | null) => !!column && columns.includes(column);
  const y = has(chart.y) ? chart.y! : (chart.measures || []).find((measure) => has(measure)) || columns.find((column) => isNumericColumn(chart, column)) || null;
  const x = has(chart.x) ? chart.x! : columns.find((column) => column !== y && !isNumericColumn(chart, column)) || null;
  const series = has(chart.series) && chart.series !== x ? chart.series! : null;
  return { x, y, series, columns };
}

/**
 * Chart types the user can switch between for one result: the API's alternatives
 * (older answers: bar / line / table), always including the chosen type and Table,
 * minus types the data cannot support (pie with negative values, grouping without a series column).
 */
export function chartAlternatives(chart?: ChartSpec | null): ChartType[] {
  if (!chart?.data?.length) return [];
  const fields = resolveFields(chart);
  const primary = isChartType(chart.type) ? chart.type : "table";
  const offered = chart.alternatives?.length ? chart.alternatives.filter(isChartType) : primary === "kpi" ? ["kpi" as const] : ["bar" as const, "line" as const];
  const ordered = Array.from(new Set<ChartType>([primary, ...offered, "table"]));
  const yValues = fields.y ? chart.data.map((row) => num(row[fields.y!])) : [];
  return ordered.filter((type) => {
    if (type === "table" || type === "kpi") return true;
    if (!fields.y) return false;
    if (type === "scatter") return !!fields.x && isNumericColumn(chart, fields.x);
    if (!fields.x) return false;
    if (type === "pie") return yValues.every((value) => value == null || value >= 0) && yValues.some((value) => (value ?? 0) > 0);
    if (type === "grouped_bar" || type === "stacked_bar") return !!fields.series;
    return true;
  });
}

// ------------------------------------------------------------------ drill model

type DrillStep =
  // `grain` is the grain in effect *before* the step, restored on drill up.
  | { kind: "filter"; column: string; value: string; label: string; grain: Grain | null }
  | { kind: "period"; column: string; start: number; end: number; label: string; grain: Grain | null };
type PickTarget = { column: string; value: string };
type DrillMode = "period" | "filter" | "ask" | null;

/** One drill level: the rows and fields the chart draws at the current point of the drill path. */
type View = {
  chart: ChartSpec;
  fields: Fields;
  type: ChartType;
  rawRows: Row[];
  used: Set<string>;
  measures: string[];
  temporal: boolean;
  native: Grain | "time" | null;
  grain: Grain | null;
  grainOptions: Grain[];
  filters: ChartDrillFilter[];
};

/** The next categorical column (2-60 distinct values) not yet on the drill path. */
function nextDimension(rows: Row[], used: Set<string>, measures: string[]): string | null {
  const columns = new Set<string>();
  for (const row of rows.slice(0, 50)) for (const key of Object.keys(row)) columns.add(key);
  for (const column of columns) {
    if (used.has(column) || measures.includes(column)) continue;
    const values = rows.map((row) => row[column]).filter((value) => value !== null && value !== undefined && value !== "");
    if (!values.length || values.every((value) => num(value) != null)) continue;
    const distinct = new Set(values.map(String)).size;
    if (distinct >= 2 && distinct <= 60) return column;
  }
  return null;
}

/** Rolls rows up to a time grain: sums, or averages for share measures. */
function aggregate(chart: ChartSpec, rows: Row[], x: string, grain: Grain, series: string | null, measures: string[]): Row[] {
  const averaged = new Set(measures.filter((measure) => { const unit = unitFor(chart, measure); return unit === "percent" || unit === "fraction"; }));
  const groups = new Map<string, { row: Row; counts: Record<string, number> }>();
  for (const row of rows) {
    const time = parseTime(row[x]);
    if (time == null) continue;
    const start = bucketStart(time, grain);
    const key = `${start}\u0000${series ? text(row[series]) : ""}`;
    let entry = groups.get(key);
    if (!entry) {
      entry = { row: { [x]: isoDay(start), ...(series ? { [series]: row[series] } : {}) }, counts: {} };
      groups.set(key, entry);
    }
    for (const measure of measures) {
      const value = num(row[measure]);
      if (value == null) continue;
      entry.row[measure] = (num(entry.row[measure]) ?? 0) + value;
      entry.counts[measure] = (entry.counts[measure] || 0) + 1;
    }
  }
  const out = Array.from(groups.values()).map(({ row, counts }) => {
    for (const measure of averaged) if (counts[measure]) row[measure] = (row[measure] as number) / counts[measure];
    return row;
  });
  return out.sort((a, b) => String(a[x]).localeCompare(String(b[x])));
}

function autoType(requested: ChartType, temporal: boolean, series: string | null): ChartType {
  const barFamily = requested === "bar" || requested === "grouped_bar" || requested === "stacked_bar";
  if (temporal && !barFamily) return "line";
  if (series) return requested === "stacked_bar" ? "stacked_bar" : "grouped_bar";
  return requested === "pie" && !temporal ? "pie" : "bar";
}

function deriveView(chart: ChartSpec, base: Fields, requested: ChartType, path: DrillStep[], grainChoice: Grain | null | undefined): View {
  let rows = chart.data as Row[];
  let x = base.x;
  let series = base.series;
  const y = base.y;
  const measures = Array.from(new Set([y, ...(chart.measures || [])].filter((measure): measure is string => !!measure && base.columns.includes(measure))));
  const used = new Set<string>();
  const filters: ChartDrillFilter[] = [];
  for (const step of path) {
    if (step.kind === "period") {
      rows = rows.filter((row) => { const time = parseTime(row[step.column]); return time != null && time >= step.start && time < step.end; });
    } else {
      rows = rows.filter((row) => text(row[step.column]) === step.value);
      used.add(step.column);
      if (step.column === series) series = null;
      else if (step.column === x) {
        if (series) { x = series; series = null; } else x = nextDimension(rows, used, measures);
      }
    }
    filters.push({ column: step.column, value: step.label });
  }
  const times = x ? rows.map((row) => parseTime(row[x!])) : [];
  const temporal = !!x && rows.length > 0 && times.every((time) => time != null);
  const native = temporal ? nativeGrain(times as number[]) : null;
  const grainOptions = temporal ? coarserGrains(native!, times as number[]) : [];
  let grain: Grain | null = grainChoice === undefined ? (path.length || !temporal ? null : autoGrain(times as number[], grainOptions)) : grainChoice;
  if (grain && !grainOptions.includes(grain)) grain = null;
  if (!path.length && !grain) {
    return { chart, fields: base, type: requested, rawRows: rows, used, measures, temporal, native, grain, grainOptions, filters };
  }
  const data = temporal && grain ? aggregate(chart, rows, x!, grain, series, measures) : rows;
  const type = path.length ? autoType(requested, temporal, series) : requested;
  const derived: ChartSpec = { ...chart, data: data as ChartSpec["data"], x, y, series, type };
  return { chart: derived, fields: resolveFields(derived), type, rawRows: rows, used, measures, temporal, native, grain, grainOptions, filters };
}

const isOtherLabel = (value: string) => /^Other( \(\d+\))?$/.test(value);

function drillMode(view: View, target: PickTarget, canAsk: boolean): DrillMode {
  if (!target.value || isOtherLabel(target.value)) return null;
  const { x, series } = view.fields;
  if (target.column === x) {
    if (view.temporal && view.grain) return "period";
    if (series) return "filter";
    const rows = view.rawRows.filter((row) => text(row[target.column]) === target.value);
    if (nextDimension(rows, new Set([...view.used, target.column]), view.measures)) return "filter";
  } else if (target.column === series && x) {
    if (new Set(view.rawRows.filter((row) => text(row[series]) === target.value).map((row) => text(row[x]))).size > 1) return "filter";
  }
  return canAsk ? "ask" : null;
}

/** Whether marks on this column react to a click at all (for the pointer cursor and hints). */
function columnDrillable(view: View, column: string, canAsk: boolean) {
  if (canAsk) return true;
  const { x, series } = view.fields;
  if (column === x) return (view.temporal && !!view.grain) || !!series || !!nextDimension(view.rawRows, new Set([...view.used, column]), view.measures);
  return column === series;
}

function targetLabel(view: View, target: PickTarget) {
  if (target.column === view.fields.x && view.temporal) {
    const time = parseTime(target.value);
    const grain = view.grain ?? (view.native === "time" ? null : view.native);
    if (time != null && grain) return periodKey(time, grain);
  }
  return target.value;
}

function followUp(view: View, target: PickTarget): ChartDrillRequest {
  const label = targetLabel(view, target);
  const filters = [...view.filters, { column: target.column, value: label }];
  const measure = view.fields.y;
  const rows = view.rawRows.filter((row) => text(row[target.column]) === target.value);
  const exclude = new Set([...view.used, target.column, view.fields.x || "", view.fields.series || ""]);
  const next = nextDimension(rows, exclude, view.measures);
  const onTime = target.column === view.fields.x && view.temporal;
  const by = next ? humanize(next).toLowerCase() : onTime ? "its main categories" : "month";
  const question = `Break down ${measure ? humanize(measure).toLowerCase() : "the result"} for ${filters.map((filter) => `${filter.column} = ${filter.value}`).join(" and ")} by ${by}`;
  return { column: target.column, value: label, question, measure, filters };
}

// ------------------------------------------------------------------ interaction context

type Interaction = {
  hidden: Set<string>;
  toggle: (key: string) => void;
  pick: (target: PickTarget) => void;
  drillable: (column: string | null) => boolean;
  zoom: [number, number] | null;
  setZoom: (range: [number, number] | null) => void;
  up: (() => void) | null;
  k: number;
  grain: Grain | null;
};
const Interact = createContext<Interaction>({
  hidden: new Set(),
  toggle: () => undefined,
  pick: () => undefined,
  drillable: () => false,
  zoom: null,
  setZoom: () => undefined,
  up: null,
  k: 1,
  grain: null,
});

/** Drag-to-zoom along the x-axis; a press without a drag is a click. */
function useBrush() {
  const origin = useRef<number | null>(null);
  const [range, setRange] = useState<[number, number] | null>(null);
  const localX = (event: PointerEvent<SVGRectElement>) => event.clientX - (event.currentTarget.ownerSVGElement?.getBoundingClientRect().left ?? 0);
  return {
    range,
    begin(event: PointerEvent<SVGRectElement>) {
      if (event.button !== 0) return;
      origin.current = localX(event);
      setRange(null);
      try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* not capturable */ }
    },
    move(event: PointerEvent<SVGRectElement>) {
      if (origin.current == null) return;
      const at = localX(event);
      if (Math.abs(at - origin.current) > 4) setRange([Math.min(origin.current, at), Math.max(origin.current, at)]);
    },
    /** Returns the dragged pixel span, or null for a click. */
    end(event: PointerEvent<SVGRectElement>): [number, number] | null | "none" {
      const from = origin.current;
      origin.current = null;
      setRange(null);
      if (from == null) return "none";
      const at = localX(event);
      return Math.abs(at - from) > 8 ? [Math.min(from, at), Math.max(from, at)] : null;
    },
  };
}

// ------------------------------------------------------------------ frame, tooltip, legend

function useElementWidth(fallback = 340) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const update = () => { const next = Math.floor(node.getBoundingClientRect().width); if (next > 0) setWidth(Math.max(180, next)); };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function ChartFrame({ label, summary, width, height, count, active, onActive, onSelect, drillHint, tip, anchor, legend, note, children }: {
  label: string;
  summary: string;
  width: number;
  height: number;
  count: number;
  active: number | null;
  onActive: (index: number | null) => void;
  onSelect?: (index: number) => void;
  drillHint?: boolean;
  tip: Tip | null;
  anchor: Point | null;
  legend?: ReactNode;
  note?: ReactNode;
  children: ReactNode;
}) {
  const titleId = useId();
  const descId = useId();
  const { up } = useContext(Interact);
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Backspace" && up) { event.preventDefault(); up(); return; }
    if (!count) return;
    const current = active ?? -1;
    let next: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = Math.min(count - 1, current + 1);
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = Math.max(0, current < 0 ? 0 : current - 1);
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = count - 1;
    else if ((event.key === "Enter" || event.key === " ") && onSelect && active != null) { event.preventDefault(); onSelect(active); return; }
    else if (event.key === "Escape") { if (active != null) event.stopPropagation(); onActive(null); return; }
    if (next === null) return;
    event.preventDefault();
    onActive(next);
  }
  const live = tip ? `${tip.title}: ${tip.rows.map((row) => `${row.label} ${row.value}`).join(", ")}` : "";
  const side = anchor && anchor.x > width / 2 ? "end" : "start";
  const keys = `Use the arrow keys to read each value${drillHint && onSelect ? ", Enter to drill down" : ""}${up ? ", Backspace to drill up" : ""}.`;
  return (
    <div className="viz-frame">
      <div
        className="viz-plot"
        tabIndex={count ? 0 : -1}
        role="group"
        aria-label={count ? `${label}. ${keys}` : label}
        onKeyDown={onKeyDown}
        onFocus={(event) => { if (active == null && count && event.currentTarget.matches(":focus-visible")) onActive(0); }}
        onBlur={() => onActive(null)}
        onPointerLeave={() => onActive(null)}
      >
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby={`${titleId} ${descId}`}>
          <title id={titleId}>{label}</title>
          <desc id={descId}>{summary}</desc>
          {children}
        </svg>
        {tip && anchor && (
          <div className={`viz-tooltip viz-tooltip--${side}`} style={{ left: anchor.x, top: Math.max(4, Math.min(anchor.y, height - 40)) }} aria-hidden="true">
            <span className="viz-tooltip-title">{tip.title}</span>
            {tip.rows.map((row) => (
              <span className="viz-tooltip-row" key={row.key}>
                {row.swatch && <i className={`viz-key viz-key--${row.mark || "line"}`} style={{ background: row.swatch }} />}
                <b>{row.value}</b>
                <span>{row.label}</span>
              </span>
            ))}
            {drillHint && <span className="viz-tooltip-hint">Click to drill down</span>}
          </div>
        )}
      </div>
      <div className="viz-sr-only" aria-live="polite">{live}</div>
      {legend}
      {note && <p className="viz-note">{note}</p>}
    </div>
  );
}

/** Legend entries toggle their series; entries on a drillable column also get a drill button. */
function Legend({ items, mark, drillColumn, list = false, activeKey }: { items: { key: string; label: string; color: string; value?: string }[]; mark: "line" | "rect"; drillColumn?: string | null; list?: boolean; activeKey?: string | null }) {
  const { hidden, toggle, pick, drillable } = useContext(Interact);
  if (items.length < 2) return null;
  const canDrill = !!drillColumn && drillable(drillColumn);
  return (
    <ul className={`viz-legend${list ? " viz-legend--list" : ""} viz-legend--interactive`} aria-label="Legend: select an entry to show or hide it">
      {items.map((item) => {
        const off = hidden.has(item.key);
        return (
          <li key={item.key} title={item.label} className={`${off ? "is-off" : ""}${activeKey === item.key ? " active" : ""}`}>
            <button type="button" className="viz-legend-toggle" aria-pressed={!off} aria-label={`${off ? "Show" : "Hide"} ${item.label}`} onClick={() => toggle(item.key)}>
              <i className={`viz-key viz-key--${mark}`} style={{ background: item.color }} />
              <span>{item.label}</span>
              {item.value && <b>{item.value}</b>}
            </button>
            {canDrill && !isOtherLabel(item.key) && (
              <button type="button" className="viz-legend-drill" aria-label={`Drill into ${item.label}`} title={`Drill into ${item.label}`} onClick={() => pick({ column: drillColumn!, value: item.key })}>
                <ChevronRight size={12} aria-hidden="true" />
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function YAxis({ ticks, scale, left, right, format }: { ticks: number[]; scale: (value: number) => number; left: number; right: number; format: (value: number) => string }) {
  return (
    <g className="viz-axis">
      {ticks.map((tick) => (
        <g key={tick}>
          <line className={tick === 0 ? "viz-baseline" : "viz-grid"} x1={left} x2={right} y1={scale(tick)} y2={scale(tick)} />
          <text x={left - 6} y={scale(tick) + 3.5} textAnchor="end">{format(tick)}</text>
        </g>
      ))}
    </g>
  );
}

const tickLabelWidth = (ticks: number[], format: (value: number) => string) => Math.max(...ticks.map((tick) => format(tick).length)) * CHAR_W + 10;

// ------------------------------------------------------------------ line

function LineChart({ chart, fields, width }: { chart: ChartSpec; fields: Fields; width: number }) {
  const ix = useContext(Interact);
  const [active, setActive] = useState<number | null>(null);
  const brush = useBrush();
  const { zoom, grain } = ix;
  const model = useMemo(() => {
    const x = fields.x!;
    const y = fields.y!;
    const rows = chart.data as Row[];
    const times = rows.map((row) => parseTime(row[x]));
    const temporal = times.every((time) => time != null);
    const numericX = !temporal && rows.every((row) => typeof row[x] === "number");
    const keyOf = (row: Row) => text(row[x]);
    const positions = new Map<string, number>();
    rows.forEach((row, index) => {
      const key = keyOf(row);
      if (positions.has(key)) return;
      positions.set(key, temporal ? times[index]! : numericX ? Number(row[x]) : positions.size);
    });
    let xs = Array.from(positions.entries()).map(([key, pos]) => ({ key, pos }));
    if (temporal || numericX) xs.sort((a, b) => a.pos - b.pos);
    const total = xs.length;
    if (zoom) {
      const kept = xs.filter((item) => item.pos >= zoom[0] && item.pos <= zoom[1]);
      if (kept.length >= 2) xs = kept;
    }
    const indexOf = new Map(xs.map((item, index) => [item.key, index]));
    const unit = unitFor(chart, y);
    let names: string[];
    let valueAt: (name: string, row: Row) => number | null;
    let rowsFor: (name: string) => Row[];
    let hidden = 0;
    if (fields.series) {
      const all = Array.from(new Set(rows.map((row) => text(row[fields.series!]))));
      names = all.slice(0, SLOT_COUNT);
      hidden = all.length - names.length;
      valueAt = (_name, row) => num(row[y]);
      rowsFor = (name) => rows.filter((row) => text(row[fields.series!]) === name);
    } else {
      // Extra measures share the axis only when they share the unit (never a second y-scale).
      const measures = [y, ...(chart.measures || []).filter((measure) => measure !== y && fields.columns.includes(measure) && unitFor(chart, measure) === unit)].slice(0, 4);
      names = measures;
      valueAt = (name, row) => num(row[name]);
      rowsFor = () => rows;
    }
    const lines = names.map((name, index) => {
      const values: (number | null)[] = new Array(xs.length).fill(null);
      for (const row of rowsFor(name)) {
        const at = indexOf.get(keyOf(row));
        const value = valueAt(name, row);
        if (at != null && value != null) values[at] = (values[at] ?? 0) + value;
      }
      return { name, label: fields.series ? name : humanize(name), color: slot(index), values };
    });
    const format = temporal ? (grain ? grainFormatters(grain) : timeFormatters(xs.map((item) => item.pos))) : null;
    const xLabel = (index: number) => (format ? format.full(xs[index].pos) : numericX ? formatChartValue(xs[index].pos, "number") : xs[index].key);
    const xTick = (index: number) => (format ? format.tick(xs[index].pos) : numericX ? formatChartValue(xs[index].pos, "number", true) : xs[index].key);
    return { xs, lines, unit, xLabel, xTick, hidden, ordinal: !temporal && !numericX, zoomed: xs.length < total };
  }, [chart, fields, zoom, grain]);

  const { xs, lines, unit } = model;
  const shown = lines.filter((line) => !ix.hidden.has(line.name));
  const visibleValues = shown.flatMap((line) => line.values.filter((value): value is number => value != null));
  const vMin = visibleValues.length ? Math.min(...visibleValues) : 0;
  const vMax = visibleValues.length ? Math.max(...visibleValues) : 1;
  const domain = niceDomain(vMin >= 0 && vMin < vMax * 0.6 ? 0 : vMin, vMax, 4);
  const height = Math.round(210 * ix.k);
  const yFormat = (value: number) => formatChartValue(value, unit, true);
  const margin = { top: 12, right: 14, bottom: 26, left: tickLabelWidth(domain.ticks, yFormat) };
  const plotRight = width - margin.right;
  const plotBottom = height - margin.bottom;
  const first = xs[0]?.pos ?? 0;
  const last = xs[xs.length - 1]?.pos ?? 1;
  const xScale = linear(first, last, margin.left + 4, plotRight - 4);
  const xInvert = invertLinear(first, last, margin.left + 4, plotRight - 4);
  const yScale = linear(domain.lo, domain.hi, plotBottom, margin.top);
  const px = (index: number) => xScale(xs[index].pos);
  const pathOf = (values: (number | null)[]) => {
    let d = "";
    let open = false;
    values.forEach((value, index) => {
      if (value == null) { open = false; return; }
      d += `${open ? "L" : "M"}${px(index).toFixed(1)},${yScale(value).toFixed(1)}`;
      open = true;
    });
    return d;
  };
  const single = shown.length === 1 ? shown[0] : null;
  const singlePath = single ? pathOf(single.values) : "";
  const area = single && singlePath && single.values.every((value) => value != null) && xs.length > 1
    ? `${singlePath}L${px(xs.length - 1).toFixed(1)},${yScale(Math.max(domain.lo, 0))}L${px(0).toFixed(1)},${yScale(Math.max(domain.lo, 0))}Z`
    : "";
  const ticks = tickIndexes(xs.length, Math.floor((plotRight - margin.left) / 74));
  const maxTickChars = Math.floor(((plotRight - margin.left) / Math.max(1, ticks.length)) / CHAR_W);
  const drillHint = ix.drillable(fields.x);
  const targetAt = (index: number): PickTarget => ({ column: fields.x!, value: xs[index].key });

  const nearest = (at: number) => {
    let best = 0;
    for (let index = 1; index < xs.length; index += 1) if (Math.abs(px(index) - at) < Math.abs(px(best) - at)) best = index;
    return best;
  };
  const localX = (event: PointerEvent<SVGRectElement>) => event.clientX - (event.currentTarget.ownerSVGElement?.getBoundingClientRect().left ?? 0);
  function onMove(event: PointerEvent<SVGRectElement>) {
    brush.move(event);
    setActive(nearest(localX(event)));
  }
  function onUp(event: PointerEvent<SVGRectElement>) {
    const span = brush.end(event);
    if (span === "none") return;
    if (span) {
      if (model.ordinal) {
        const from = nearest(span[0]);
        const to = nearest(span[1]);
        if (to > from) ix.setZoom([xs[from].pos, xs[to].pos]);
      } else ix.setZoom([xInvert(span[0]), xInvert(span[1])]);
      return;
    }
    ix.pick(targetAt(nearest(localX(event))));
  }

  const tip: Tip | null = active == null || !xs[active] ? null : {
    title: model.xLabel(active),
    rows: shown.map((line) => ({ key: line.name, label: line.label, value: formatChartValue(line.values[active], unit), swatch: line.color, mark: "line" as const })),
  };
  const values = lines.flatMap((line) => line.values).filter((value): value is number => value != null);
  const summary = `Line chart of ${humanize(fields.y!)} over ${humanize(fields.x!)}: ${xs.length} points${lines.length > 1 ? `, ${lines.length} series` : ""}, from ${formatChartValue(values.length ? Math.min(...values) : null, unit)} to ${formatChartValue(values.length ? Math.max(...values) : null, unit)}.`;
  const notes = [model.hidden > 0 ? `${model.hidden} more series are only in the table.` : "", shown.length === 0 ? "Every series is hidden; select a legend entry to show it." : ""].filter(Boolean).join(" ");
  return (
    <ChartFrame
      label={chartLabel(chart, "Line chart")}
      summary={summary}
      width={width}
      height={height}
      count={xs.length}
      active={active}
      onActive={setActive}
      onSelect={(index) => ix.pick(targetAt(index))}
      drillHint={drillHint}
      tip={tip}
      anchor={active == null || !xs[active] ? null : { x: px(active), y: margin.top }}
      legend={<Legend mark="line" drillColumn={fields.series} items={lines.map((line) => ({ key: line.name, label: line.label, color: line.color }))} />}
      note={notes || null}
    >
      <YAxis ticks={domain.ticks} scale={yScale} left={margin.left} right={plotRight} format={yFormat} />
      <g className="viz-axis">
        {ticks.map((index) => {
          const anchor = index === 0 && px(index) - margin.left < 20 ? "start" : "middle";
          return <text key={index} x={px(index)} y={height - 8} textAnchor={anchor}>{truncate(model.xTick(index), Math.max(4, maxTickChars))}</text>;
        })}
      </g>
      {area && <path className="viz-area" d={area} style={{ fill: single!.color }} />}
      {shown.map((line) => <path key={line.name} className="viz-line" d={pathOf(line.values)} style={{ stroke: line.color }} />)}
      {shown.map((line) => {
        const lastIndex = line.values.map((value, index) => (value == null ? -1 : index)).filter((index) => index >= 0).pop();
        return lastIndex == null ? null : <circle key={`end-${line.name}`} className="viz-dot" cx={px(lastIndex)} cy={yScale(line.values[lastIndex]!)} r={4} style={{ fill: line.color }} />;
      })}
      {active != null && xs[active] && (
        <g pointerEvents="none">
          <line className="viz-crosshair" x1={px(active)} x2={px(active)} y1={margin.top} y2={plotBottom} />
          {shown.map((line) => line.values[active] == null ? null : <circle key={`hover-${line.name}`} className="viz-dot" cx={px(active)} cy={yScale(line.values[active]!)} r={4.5} style={{ fill: line.color }} />)}
        </g>
      )}
      {brush.range && <rect className="viz-brush" x={Math.max(margin.left, brush.range[0])} y={margin.top} width={Math.max(0, Math.min(plotRight, brush.range[1]) - Math.max(margin.left, brush.range[0]))} height={Math.max(0, plotBottom - margin.top)} />}
      <rect className={`viz-hit${drillHint ? " viz-hit--drill" : ""}`} x={margin.left} y={margin.top} width={Math.max(0, plotRight - margin.left)} height={Math.max(0, plotBottom - margin.top)} onPointerMove={onMove} onPointerDown={(event) => { brush.begin(event); setActive(nearest(localX(event))); }} onPointerUp={onUp} />
    </ChartFrame>
  );
}

// ------------------------------------------------------------------ bar (one measure)

const HORIZONTAL_ROW_CAP = 30;

function BarChart({ chart, fields, width }: { chart: ChartSpec; fields: Fields; width: number }) {
  const ix = useContext(Interact);
  const [active, setActive] = useState<number | null>(null);
  const x = fields.x!;
  const y = fields.y!;
  const unit = unitFor(chart, y);
  const all = (chart.data as Row[]).map((row) => ({ label: text(row[x]), value: num(row[y]) ?? 0 }));
  const vertical = all.length <= 12;
  const bars = vertical ? all : all.slice(0, HORIZONTAL_ROW_CAP);
  const labels = categoryLabels(bars.map((bar) => bar.label), ix.grain);
  const min = Math.min(0, ...bars.map((bar) => bar.value));
  const max = Math.max(0, ...bars.map((bar) => bar.value));
  const domain = niceDomain(min, max, 4);
  const color = slot(0);
  const fmt = (value: number) => formatChartValue(value, unit);
  const summary = `Bar chart of ${humanize(y)} by ${humanize(x)}: ${all.length} categories. Highest ${bars.reduce((best, bar) => (bar.value > best.value ? bar : best), bars[0]).label} (${fmt(max)}).`;
  const tip: Tip | null = active == null || !bars[active] ? null : { title: labels.full(active), rows: [{ key: "value", label: humanize(y), value: fmt(bars[active].value) }] };
  const drillHint = ix.drillable(x);
  const pickAt = (index: number) => ix.pick({ column: x, value: bars[index].label });
  const hitClass = `viz-hit${drillHint ? " viz-hit--drill" : ""}`;

  if (vertical) {
    const height = Math.round(220 * ix.k);
    const yFormat = (value: number) => formatChartValue(value, unit, true);
    const margin = { top: 16, right: 8, bottom: 30, left: tickLabelWidth(domain.ticks, yFormat) };
    const plotRight = width - margin.right;
    const plotBottom = height - margin.bottom;
    const band = (plotRight - margin.left) / bars.length;
    const barWidth = Math.max(2, Math.min(24 * ix.k, band * 0.62));
    const yScale = linear(domain.lo, domain.hi, plotBottom, margin.top);
    const base = yScale(0);
    const labelEvery = Math.max(1, Math.ceil((Math.min(10, Math.max(4, ...bars.map((_, index) => labels.tick(index).length))) * CHAR_W + 6) / band));
    const maxChars = Math.floor((band * labelEvery - 4) / CHAR_W);
    const showValues = bars.length <= 6 && band >= 36;
    return (
      <ChartFrame label={chartLabel(chart, "Bar chart")} summary={summary} width={width} height={height} count={bars.length} active={active} onActive={setActive} onSelect={pickAt} drillHint={drillHint} tip={tip}
        anchor={active == null || !bars[active] ? null : { x: margin.left + band * active + band / 2, y: Math.min(yScale(bars[active].value), base) }}>
        <YAxis ticks={domain.ticks} scale={yScale} left={margin.left} right={plotRight} format={yFormat} />
        {bars.map((bar, index) => {
          const cx = margin.left + band * index + band / 2;
          const end = yScale(bar.value);
          return (
            <g key={`${bar.label}-${index}`}>
              <path className={`viz-bar${active === index ? " active" : ""}`} d={columnPath(cx - barWidth / 2, barWidth, base, end)} style={{ fill: color }} />
              {showValues && <text className="viz-value" x={cx} y={bar.value >= 0 ? end - 5 : end + 12} textAnchor="middle">{formatChartValue(bar.value, unit, true)}</text>}
              {index % labelEvery === 0 && <text className="viz-axis-text" x={cx} y={height - 12} textAnchor="middle">{truncate(labels.tick(index), maxChars)}</text>}
              <rect className={hitClass} x={margin.left + band * index} y={margin.top} width={band} height={plotBottom - margin.top + 18} onPointerEnter={() => setActive(index)} onPointerDown={() => setActive(index)} onClick={() => pickAt(index)} />
            </g>
          );
        })}
      </ChartFrame>
    );
  }

  // Horizontal: every bar carries its value at the tip, so the value axis is left out.
  const rowHeight = 24;
  const barHeight = 14;
  const longest = Math.max(...bars.map((_, index) => labels.tick(index).length));
  const labelWidth = Math.min(width * 0.38, longest * CHAR_W + 10);
  const valueWidth = Math.max(...bars.map((bar) => formatChartValue(bar.value, unit, true).length)) * CHAR_W + 10;
  const margin = { top: 4, right: valueWidth, bottom: 4, left: labelWidth };
  const height = margin.top + margin.bottom + rowHeight * bars.length;
  const xScale = linear(domain.lo, domain.hi, margin.left, width - margin.right);
  const base = xScale(0);
  const maxChars = Math.floor((labelWidth - 10) / CHAR_W);
  return (
    <ChartFrame label={chartLabel(chart, "Bar chart")} summary={summary} width={width} height={height} count={bars.length} active={active} onActive={setActive} onSelect={pickAt} drillHint={drillHint} tip={tip}
      anchor={active == null || !bars[active] ? null : { x: Math.max(xScale(bars[active].value), base), y: margin.top + rowHeight * active }}
      note={all.length > bars.length ? `Showing the first ${bars.length} of ${all.length} categories; all rows are in the table.` : null}>
      <line className="viz-baseline" x1={base} x2={base} y1={margin.top} y2={height - margin.bottom} />
      {bars.map((bar, index) => {
        const top = margin.top + rowHeight * index;
        const end = xScale(bar.value);
        return (
          <g key={`${bar.label}-${index}`}>
            <text className="viz-axis-text" x={labelWidth - 8} y={top + rowHeight / 2 + 3.5} textAnchor="end">{truncate(labels.tick(index), maxChars)}</text>
            <path className={`viz-bar${active === index ? " active" : ""}`} d={barPath(top + (rowHeight - barHeight) / 2, barHeight, base, end)} style={{ fill: color }} />
            <text className="viz-value" x={bar.value >= 0 ? end + 5 : base + 5} y={top + rowHeight / 2 + 3.5}>{formatChartValue(bar.value, unit, true)}</text>
            <rect className={hitClass} x={0} y={top} width={width} height={rowHeight} onPointerEnter={() => setActive(index)} onPointerDown={() => setActive(index)} onClick={() => pickAt(index)} />
          </g>
        );
      })}
    </ChartFrame>
  );
}

// ------------------------------------------------------------------ grouped / stacked bars

const CATEGORY_CAP = 12;

function GroupedBarChart({ chart, fields, width, stacked }: { chart: ChartSpec; fields: Fields; width: number; stacked: boolean }) {
  const ix = useContext(Interact);
  const [active, setActive] = useState<number | null>(null);
  const x = fields.x!;
  const y = fields.y!;
  const seriesField = fields.series!;
  const unit = unitFor(chart, y);
  const model = useMemo(() => {
    const rows = chart.data as Row[];
    const allCategories = Array.from(new Set(rows.map((row) => text(row[x]))));
    const categories = allCategories.slice(0, CATEGORY_CAP);
    const allSeries = Array.from(new Set(rows.map((row) => text(row[seriesField]))));
    // Past eight series, the tail folds into "Other" (never a generated ninth hue).
    const named = allSeries.length > SLOT_COUNT ? allSeries.slice(0, SLOT_COUNT - 1) : allSeries;
    const series = allSeries.length > SLOT_COUNT ? [...named, "Other"] : named;
    const matrix = categories.map(() => new Array(series.length).fill(0) as number[]);
    for (const row of rows) {
      const c = categories.indexOf(text(row[x]));
      if (c < 0) continue;
      const name = text(row[seriesField]);
      const s = named.includes(name) ? named.indexOf(name) : series.length - 1;
      matrix[c][s] += num(row[y]) ?? 0;
    }
    return { categories, series, matrix, hiddenCategories: allCategories.length - categories.length, folded: allSeries.length > SLOT_COUNT };
  }, [chart, x, y, seriesField]);
  const { categories, series, matrix } = model;
  const visible = series.map((name, index) => ({ name, index })).filter((item) => !ix.hidden.has(item.name));
  const labels = categoryLabels(categories, ix.grain);
  const colorOf = (index: number) => (model.folded && index === series.length - 1 ? OTHER_COLOR : slot(index));
  let min = 0;
  let max = 0;
  for (const row of matrix) {
    const values = visible.map((item) => row[item.index]);
    if (stacked) {
      max = Math.max(max, values.filter((value) => value > 0).reduce((sum, value) => sum + value, 0));
      min = Math.min(min, values.filter((value) => value < 0).reduce((sum, value) => sum + value, 0));
    } else {
      max = Math.max(max, ...values);
      min = Math.min(min, ...values);
    }
  }
  const domain = niceDomain(min, max, 4);
  const height = Math.round(220 * ix.k);
  const yFormat = (value: number) => formatChartValue(value, unit, true);
  const margin = { top: 12, right: 8, bottom: 30, left: tickLabelWidth(domain.ticks, yFormat) };
  const plotRight = width - margin.right;
  const plotBottom = height - margin.bottom;
  const band = (plotRight - margin.left) / Math.max(1, categories.length);
  const yScale = linear(domain.lo, domain.hi, plotBottom, margin.top);
  const base = yScale(0);
  const gap = 2;
  const drawn = Math.max(1, visible.length);
  const groupWidth = Math.min(band * 0.84, drawn * 24 * ix.k + (drawn - 1) * gap);
  const barWidth = stacked ? Math.max(2, Math.min(24 * ix.k, band * 0.6)) : Math.max(1, (groupWidth - (drawn - 1) * gap) / drawn);
  const labelEvery = Math.max(1, Math.ceil((Math.min(10, Math.max(4, ...categories.map((_, index) => labels.tick(index).length))) * CHAR_W + 6) / band));
  const maxChars = Math.floor((band * labelEvery - 4) / CHAR_W);
  const fmt = (value: number) => formatChartValue(value, unit);
  const tip: Tip | null = active == null || !matrix[active] ? null : {
    title: labels.full(active),
    rows: [
      ...visible.map(({ name, index }) => ({ key: name, label: name, value: fmt(matrix[active][index]), swatch: colorOf(index), mark: "rect" as const })),
      ...(stacked ? [{ key: "__total", label: "Total", value: fmt(visible.reduce((sum, item) => sum + matrix[active][item.index], 0)) }] : []),
    ],
  };
  const drillHint = ix.drillable(x);
  const pickAt = (index: number) => ix.pick({ column: x, value: categories[index] });
  const summary = `${stacked ? "Stacked" : "Grouped"} bar chart of ${humanize(y)} by ${humanize(x)} and ${humanize(seriesField)}: ${categories.length} categories, ${series.length} series.`;
  const notes = [model.hiddenCategories > 0 ? `Showing the first ${categories.length} categories.` : "", model.folded ? `Series past the seventh are combined as "Other".` : "", visible.length === 0 ? "Every series is hidden; select a legend entry to show it." : ""].filter(Boolean).join(" ");
  return (
    <ChartFrame label={chartLabel(chart, stacked ? "Stacked bar chart" : "Grouped bar chart")} summary={summary} width={width} height={height} count={categories.length} active={active} onActive={setActive} onSelect={pickAt} drillHint={drillHint} tip={tip}
      anchor={active == null ? null : { x: margin.left + band * active + band / 2, y: margin.top }}
      legend={<Legend mark="rect" drillColumn={seriesField} items={series.map((name, index) => ({ key: name, label: name, color: colorOf(index) }))} />}
      note={notes || null}>
      <YAxis ticks={domain.ticks} scale={yScale} left={margin.left} right={plotRight} format={yFormat} />
      {categories.map((category, c) => {
        const cx = margin.left + band * c + band / 2;
        const marks: ReactNode[] = [];
        if (stacked) {
          const items = visible.map((item) => ({ value: matrix[c][item.index], index: item.index }));
          const positives = items.filter((item) => item.value > 0);
          const negatives = items.filter((item) => item.value < 0);
          for (const group of [positives, negatives]) {
            let running = 0;
            group.forEach((item, order) => {
              const from = yScale(running);
              running += item.value;
              const to = yScale(running);
              const outermost = order === group.length - 1;
              // 2px surface gap between touching segments: trim 1px off each inner end.
              const top = Math.min(from, to) + (item.value > 0 ? (outermost ? 0 : gap / 2) : order === 0 ? 0 : gap / 2);
              const bottom = Math.max(from, to) - (item.value > 0 ? (order === 0 ? 0 : gap / 2) : outermost ? 0 : gap / 2);
              if (bottom - top < 0.5) return;
              marks.push(outermost
                ? <path key={item.index} className="viz-bar" d={columnPath(cx - barWidth / 2, barWidth, item.value > 0 ? bottom : top, item.value > 0 ? top : bottom)} style={{ fill: colorOf(item.index) }} />
                : <rect key={item.index} className="viz-bar" x={cx - barWidth / 2} y={top} width={barWidth} height={bottom - top} style={{ fill: colorOf(item.index) }} />);
            });
          }
        } else {
          const start = cx - groupWidth / 2;
          visible.forEach((item, order) => {
            marks.push(<path key={item.index} className="viz-bar" d={columnPath(start + order * (barWidth + gap), barWidth, base, yScale(matrix[c][item.index]))} style={{ fill: colorOf(item.index) }} />);
          });
        }
        return (
          <g key={`${category}-${c}`} className={active === c ? "viz-group active" : "viz-group"}>
            {marks}
            {c % labelEvery === 0 && <text className="viz-axis-text" x={cx} y={height - 12} textAnchor="middle">{truncate(labels.tick(c), maxChars)}</text>}
            <rect className={`viz-hit${drillHint ? " viz-hit--drill" : ""}`} x={margin.left + band * c} y={margin.top} width={band} height={plotBottom - margin.top + 18} onPointerEnter={() => setActive(c)} onPointerDown={() => setActive(c)} onClick={() => pickAt(c)} />
          </g>
        );
      })}
    </ChartFrame>
  );
}

// ------------------------------------------------------------------ pie (donut)

const PIE_SLICES = 8;

function PieChart({ chart, fields, width }: { chart: ChartSpec; fields: Fields; width: number }) {
  const ix = useContext(Interact);
  const [active, setActive] = useState<number | null>(null);
  const x = fields.x!;
  const y = fields.y!;
  const unit = unitFor(chart, y);
  const slices = useMemo(() => {
    const items = (chart.data as Row[]).map((row) => ({ label: text(row[x]), value: Math.max(0, num(row[y]) ?? 0) })).filter((item) => item.value > 0);
    if (items.length <= PIE_SLICES) return items.map((item, index) => ({ ...item, color: slot(index) }));
    const sorted = [...items].sort((a, b) => b.value - a.value);
    const head = sorted.slice(0, PIE_SLICES - 1).map((item, index) => ({ ...item, color: slot(index) }));
    const rest = sorted.slice(PIE_SLICES - 1).reduce((sum, item) => sum + item.value, 0);
    return [...head, { label: `Other (${sorted.length - head.length})`, value: rest, color: OTHER_COLOR }];
  }, [chart, x, y]);
  const visibleSlices = slices.filter((slice) => !ix.hidden.has(slice.label));
  const total = visibleSlices.reduce((sum, item) => sum + item.value, 0);
  const grandTotal = slices.reduce((sum, item) => sum + item.value, 0);
  if (!grandTotal) return <div className="chart-empty">Nothing to show as parts of a whole</div>;
  const side = width >= 400;
  const size = Math.min(side ? width * 0.46 : width, Math.round(210 * ix.k));
  const height = size;
  const cx = size / 2;
  const cy = size / 2;
  const outer = size / 2 - 8;
  const inner = outer * 0.62;
  let angle = -Math.PI / 2;
  const arcs = visibleSlices.map((slice) => {
    const sweep = total ? (slice.value / total) * Math.PI * 2 : 0;
    const start = angle;
    angle += sweep;
    return { ...slice, start, end: angle, share: total ? slice.value / total : 0 };
  });
  const arcPath = (start: number, end: number, r0: number, r1: number) => {
    if (end - start >= Math.PI * 2 - 1e-6) end = start + Math.PI * 2 - 1e-4;
    const large = end - start > Math.PI ? 1 : 0;
    const p = (r: number, a: number) => `${(cx + r * Math.cos(a)).toFixed(2)},${(cy + r * Math.sin(a)).toFixed(2)}`;
    return `M${p(r1, start)}A${r1},${r1} 0 ${large} 1 ${p(r1, end)}L${p(r0, end)}A${r0},${r0} 0 ${large} 0 ${p(r0, start)}Z`;
  };
  const pct = (share: number) => new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: share < 0.1 ? 1 : 0 }).format(share);
  const focus = active == null ? null : arcs[active] ?? null;
  // A share measure that already sums to the whole would repeat itself as "% of total".
  const sharesOfWhole = (unit === "fraction" && Math.abs(total - 1) < 0.01) || (unit === "percent" && Math.abs(total - 100) < 1);
  const tip: Tip | null = focus ? { title: focus.label, rows: [{ key: "value", label: humanize(y), value: formatChartValue(focus.value, unit) }, ...(sharesOfWhole ? [] : [{ key: "share", label: "of total", value: pct(focus.share) }])] } : null;
  const mid = focus ? (focus.start + focus.end) / 2 : 0;
  const summary = `Donut chart of ${humanize(y)} by ${humanize(x)}, total ${formatChartValue(total, unit)}: ${arcs.map((arc) => `${arc.label} ${pct(arc.share)}`).join(", ")}.`;
  const drillHint = ix.drillable(x);
  const pickAt = (index: number) => { const arc = arcs[index]; if (arc && arc.color !== OTHER_COLOR) ix.pick({ column: x, value: arc.label }); };
  const shareOf = (label: string) => arcs.find((arc) => arc.label === label)?.share;
  return (
    <div className={`viz-pie${side ? " viz-pie--side" : ""}`}>
      <ChartFrame label={chartLabel(chart, "Donut chart")} summary={summary} width={size} height={height} count={arcs.length} active={active} onActive={setActive} onSelect={pickAt} drillHint={drillHint} tip={tip}
        anchor={focus ? { x: cx + (outer + 4) * Math.cos(mid), y: cy + (outer + 4) * Math.sin(mid) } : null}>
        {arcs.map((arc, index) => (
          <path key={`${arc.label}-${index}`} className={`viz-slice${active === index ? " active" : ""}${drillHint && arc.color !== OTHER_COLOR ? " viz-slice--drill" : ""}`} d={arcPath(arc.start, arc.end, inner, active === index ? outer + 4 : outer)} style={{ fill: arc.color }} onPointerEnter={() => setActive(index)} onPointerDown={() => setActive(index)} onClick={() => pickAt(index)} />
        ))}
        <text className="viz-center-value" x={cx} y={cy + 2} textAnchor="middle">{focus ? pct(focus.share) : formatChartValue(total, unit, true)}</text>
        <text className="viz-center-label" x={cx} y={cy + 17} textAnchor="middle">{focus ? truncate(focus.label, Math.floor((inner * 2 - 8) / CHAR_W)) : "Total"}</text>
      </ChartFrame>
      <Legend
        list
        mark="rect"
        drillColumn={x}
        activeKey={focus?.label ?? null}
        items={slices.map((slice) => { const share = shareOf(slice.label); return { key: slice.label, label: slice.label, color: slice.color, value: share == null ? "–" : pct(share) }; })}
      />
    </div>
  );
}

// ------------------------------------------------------------------ scatter

const SCATTER_SERIES_CAP = 3; // the palette's first three slots validate for all-pairs comparison

function ScatterChart({ chart, fields, width }: { chart: ChartSpec; fields: Fields; width: number }) {
  const ix = useContext(Interact);
  const [active, setActive] = useState<number | null>(null);
  const brush = useBrush();
  const x = fields.x!;
  const y = fields.y!;
  const xUnit = unitFor(chart, x);
  const yUnit = unitFor(chart, y);
  const { zoom } = ix;
  const model = useMemo(() => {
    const rows = chart.data as Row[];
    const seriesNames = fields.series ? Array.from(new Set(rows.map((row) => text(row[fields.series!])))) : [];
    const colored = seriesNames.length > 1 && seriesNames.length <= SCATTER_SERIES_CAP;
    const all = rows
      .map((row) => ({ x: num(row[x]), y: num(row[y]), label: fields.series ? text(row[fields.series]) : "", row }))
      .filter((point): point is { x: number; y: number; label: string; row: Row } => point.x != null && point.y != null)
      .slice(0, 500)
      .sort((a, b) => a.x - b.x);
    const zoomed = zoom ? all.filter((point) => point.x >= zoom[0] && point.x <= zoom[1]) : all;
    const points = zoomed.length ? zoomed : all;
    // A categorical column names each point (for drill); the series column when coloured.
    const labelColumn = colored ? fields.series : fields.columns.find((column) => column !== x && column !== y && !isNumericColumn(chart, column)) || null;
    return { points, total: all.length, seriesNames: colored ? seriesNames : [], colored, labelColumn };
  }, [chart, x, y, fields.series, fields.columns, zoom]);
  const points = model.points.filter((point) => !model.colored || !ix.hidden.has(point.label));
  if (!model.points.length) return <div className="chart-empty">No numeric pairs to plot</div>;
  const height = Math.round(230 * ix.k);
  const domainPoints = points.length ? points : model.points;
  const xDomain = niceDomain(Math.min(...domainPoints.map((p) => p.x)), Math.max(...domainPoints.map((p) => p.x)), 4);
  const yDomain = niceDomain(Math.min(...domainPoints.map((p) => p.y)), Math.max(...domainPoints.map((p) => p.y)), 4);
  const yFormat = (value: number) => formatChartValue(value, yUnit, true);
  const margin = { top: 14, right: 14, bottom: 34, left: tickLabelWidth(yDomain.ticks, yFormat) };
  const plotRight = width - margin.right;
  const plotBottom = height - margin.bottom;
  const xScale = linear(xDomain.lo, xDomain.hi, margin.left, plotRight);
  const xInvert = invertLinear(xDomain.lo, xDomain.hi, margin.left, plotRight);
  const yScale = linear(yDomain.lo, yDomain.hi, plotBottom, margin.top);
  const colorOf = (label: string) => (model.colored ? slot(model.seriesNames.indexOf(label)) : slot(0));
  const xTicks = xDomain.ticks.filter((_, index) => index % Math.max(1, Math.ceil(xDomain.ticks.length / Math.floor((plotRight - margin.left) / 60))) === 0);
  const drillHint = ix.drillable(model.labelColumn);
  const targetAt = (index: number): PickTarget | null => (model.labelColumn && points[index] ? { column: model.labelColumn, value: text(points[index].row[model.labelColumn]) } : null);
  const local = (event: PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.ownerSVGElement!.getBoundingClientRect();
    return { mx: event.clientX - box.left, my: event.clientY - box.top };
  };
  function nearest(mx: number, my: number) {
    let best = -1;
    let bestDistance = 24 * 24; // hit radius: 24px, much larger than the 8px dot
    points.forEach((point, index) => {
      const distance = (xScale(point.x) - mx) ** 2 + (yScale(point.y) - my) ** 2;
      if (distance < bestDistance) { bestDistance = distance; best = index; }
    });
    return best < 0 ? null : best;
  }
  function onMove(event: PointerEvent<SVGRectElement>) {
    brush.move(event);
    const { mx, my } = local(event);
    setActive(nearest(mx, my));
  }
  function onUp(event: PointerEvent<SVGRectElement>) {
    const span = brush.end(event);
    if (span === "none") return;
    if (span) { ix.setZoom([xInvert(span[0]), xInvert(span[1])]); return; }
    const { mx, my } = local(event);
    const hit = nearest(mx, my);
    const target = hit == null ? null : targetAt(hit);
    if (target) ix.pick(target);
  }
  const focus = active == null ? null : points[active] ?? null;
  const tip: Tip | null = focus ? {
    title: model.colored ? focus.label : model.labelColumn ? text(focus.row[model.labelColumn]) : `Point ${active! + 1} of ${points.length}`,
    rows: [{ key: "y", label: humanize(y), value: formatChartValue(focus.y, yUnit) }, { key: "x", label: humanize(x), value: formatChartValue(focus.x, xUnit) }],
  } : null;
  const summary = `Scatter plot of ${humanize(y)} against ${humanize(x)}: ${points.length} points.`;
  const notes = [chart.data.length > model.total ? `${chart.data.length - model.total} rows without both values are not plotted.` : "", model.points.length < model.total ? `Zoomed to ${model.points.length} of ${model.total} points.` : ""].filter(Boolean).join(" ");
  return (
    <ChartFrame label={chartLabel(chart, "Scatter plot")} summary={summary} width={width} height={height} count={points.length} active={active} onActive={setActive}
      onSelect={(index) => { const target = targetAt(index); if (target) ix.pick(target); }} drillHint={drillHint} tip={tip}
      anchor={focus ? { x: xScale(focus.x), y: yScale(focus.y) } : null}
      legend={<Legend mark="rect" drillColumn={model.colored ? fields.series : null} items={model.seriesNames.map((name, index) => ({ key: name, label: name, color: slot(index) }))} />}
      note={notes || null}>
      <YAxis ticks={yDomain.ticks} scale={yScale} left={margin.left} right={plotRight} format={yFormat} />
      <g className="viz-axis">
        {xTicks.map((tick) => (
          <g key={tick}>
            <line className="viz-grid" x1={xScale(tick)} x2={xScale(tick)} y1={margin.top} y2={plotBottom} />
            <text x={xScale(tick)} y={plotBottom + 14} textAnchor="middle">{formatChartValue(tick, xUnit, true)}</text>
          </g>
        ))}
        <text className="viz-axis-title" x={plotRight} y={height - 4} textAnchor="end">{humanize(x)} →</text>
      </g>
      {points.map((point, index) => (
        <circle key={index} className={`viz-dot${active === index ? " active" : ""}`} cx={xScale(point.x)} cy={yScale(point.y)} r={active === index ? 6 : 4} style={{ fill: colorOf(point.label) }} />
      ))}
      {brush.range && <rect className="viz-brush" x={Math.max(margin.left, brush.range[0])} y={margin.top} width={Math.max(0, Math.min(plotRight, brush.range[1]) - Math.max(margin.left, brush.range[0]))} height={Math.max(0, plotBottom - margin.top)} />}
      <rect className={`viz-hit${drillHint ? " viz-hit--drill" : ""}`} x={margin.left - 12} y={margin.top - 12} width={Math.max(0, plotRight - margin.left + 24)} height={Math.max(0, plotBottom - margin.top + 24)} onPointerMove={onMove} onPointerDown={(event) => { brush.begin(event); const { mx, my } = local(event); setActive(nearest(mx, my)); }} onPointerUp={onUp} />
    </ChartFrame>
  );
}

// ------------------------------------------------------------------ KPI tiles

function KpiTiles({ chart, fields }: { chart: ChartSpec; fields: Fields }) {
  const row = chart.data[0] as Row;
  const declared = (chart.measures?.length ? chart.measures : fields.y ? [fields.y] : []).filter((measure) => num(row[measure]) != null);
  const measures = (declared.length ? declared : fields.columns.filter((column) => num(row[column]) != null)).slice(0, 6);
  const context = fields.columns.filter((column) => !measures.includes(column) && row[column] != null && num(row[column]) == null).slice(0, 2);
  if (!measures.length) return <div className="chart-empty">No numeric values to summarise</div>;
  return (
    <div className="viz-kpis" role="list" aria-label={chartLabel(chart, "Key figures")}>
      {measures.map((measure) => {
        const value = num(row[measure]);
        const unit = unitFor(chart, measure);
        const compact = value != null && Math.abs(value) >= 100_000;
        return (
          <div className="viz-kpi" role="listitem" key={measure}>
            <span>{humanize(measure)}</span>
            <strong title={formatChartValue(value, unit)}>{formatChartValue(value, unit, compact)}</strong>
          </div>
        );
      })}
      {context.length > 0 && <small className="viz-kpi-context">{context.map((column) => `${humanize(column)}: ${text(row[column])}`).join(" · ")}</small>}
    </div>
  );
}

// ------------------------------------------------------------------ public components

const chartLabel = (chart: ChartSpec, kind: string) => (chart.title ? `${kind}: ${chart.title}` : kind);

type BodyKind = "empty" | "none" | "kpi" | "line" | "grouped" | "stacked" | "pie" | "scatter" | "bar";
function bodyKind(view: View | null): BodyKind {
  if (!view || !view.chart.data.length) return "empty";
  const { type, fields, chart } = view;
  if (type === "table") return "none";
  if (type === "kpi") return "kpi";
  if (!fields.x || !fields.y) return "empty";
  if (type === "line") return "line";
  if ((type === "grouped_bar" || type === "stacked_bar") && fields.series) return type === "stacked_bar" ? "stacked" : "grouped";
  if (type === "pie" && chart.data.every((row) => (num(row[fields.y!]) ?? 0) >= 0)) return "pie";
  if (type === "scatter" && isNumericColumn(chart, fields.x)) return "scatter";
  return "bar";
}

function ChartBody({ view, kind }: { view: View | null; kind: BodyKind }) {
  const [ref, width] = useElementWidth();
  let body: ReactNode = null;
  if (kind === "empty" || !view) body = <div className="chart-empty">No chartable result</div>;
  else if (kind === "kpi") body = <KpiTiles chart={view.chart} fields={view.fields} />;
  else if (kind === "line") body = <LineChart chart={view.chart} fields={view.fields} width={width} />;
  else if (kind === "grouped" || kind === "stacked") body = <GroupedBarChart chart={view.chart} fields={view.fields} width={width} stacked={kind === "stacked"} />;
  else if (kind === "pie") body = <PieChart chart={view.chart} fields={view.fields} width={width} />;
  else if (kind === "scatter") body = <ScatterChart chart={view.chart} fields={view.fields} width={width} />;
  else if (kind === "bar") body = <BarChart chart={view.chart} fields={view.fields} width={width} />;
  // Measured element: the content box, so charts never overflow the figure's padding.
  return <div ref={ref} className="viz-measure">{body}</div>;
}

/**
 * Renders a result chart. `type` overrides the API's choice (the inspector's
 * chart-type switcher); "table" renders nothing because the result table is
 * always shown below the chart.
 *
 * `onDrill` (optional) receives a follow-up when a clicked mark has no finer detail
 * in the returned rows, e.g. `{ column: "account_type", value: "deposit", question:
 * "Break down balance for account_type = deposit by month", measure: "balance",
 * filters: [{ column: "account_type", value: "deposit" }] }`. Without it, marks that
 * cannot drill client-side are not clickable.
 */
export function AnalysisChart({ chart, type, showTitle = true, onDrill }: { chart?: ChartSpec | null; type?: ChartType; showTitle?: boolean; onDrill?: (request: ChartDrillRequest) => void }) {
  const baseFields = useMemo(() => (chart?.data?.length ? resolveFields(chart) : null), [chart]);
  const requested: ChartType = type || (isChartType(chart?.type) ? chart!.type as ChartType : "table");
  const [path, setPath] = useState<DrillStep[]>([]);
  const [grainChoice, setGrainChoice] = useState<Grain | null | undefined>(undefined);
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  const [zoom, setZoom] = useState<[number, number] | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [announce, setAnnounce] = useState("");
  // Identity of the result, not of the spec object: a host re-render that rebuilds the same
  // spec (same rows array and fields) must not throw the user out of their drill path.
  const sameResult = (a?: ChartSpec | null, b?: ChartSpec | null) => a === b || (!!a && !!b && a.data === b.data && a.x === b.x && a.y === b.y && a.series === b.series && a.type === b.type);
  const [seen, setSeen] = useState({ chart, requested });
  if (!sameResult(seen.chart, chart) || seen.requested !== requested) {
    // A new result (or chart type) starts a fresh drill: reset during render, no flash of stale state.
    if (!sameResult(seen.chart, chart)) { setPath([]); setGrainChoice(undefined); }
    setSeen({ chart, requested });
    setHidden(new Set());
    setZoom(null);
  }
  const view = useMemo(() => (chart && baseFields ? deriveView(chart, baseFields, requested, path, grainChoice) : null), [chart, baseFields, requested, path, grainChoice]);
  const kind = bodyKind(view);
  const canAsk = Boolean(onDrill);
  const expandRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  const resetLevel = () => { setHidden(new Set()); setZoom(null); };
  const drillTo = useCallback((depth: number) => {
    const step = path[depth];
    if (!step) return;
    setPath(path.slice(0, depth));
    setGrainChoice(step.grain);
    setHidden(new Set());
    setZoom(null);
    setAnnounce(`Drilled up to ${depth === 0 ? "all rows" : path[depth - 1].label}`);
  }, [path]);
  const up = path.length ? () => drillTo(path.length - 1) : null;

  const pick = useCallback((target: PickTarget) => {
    if (!view) return;
    const mode = drillMode(view, target, canAsk);
    if (mode === "period" && view.grain) {
      const time = parseTime(target.value);
      if (time == null) return;
      const start = bucketStart(time, view.grain);
      setPath([...path, { kind: "period", column: target.column, start, end: bucketEnd(start, view.grain), label: periodKey(start, view.grain), grain: view.grain }]);
      setGrainChoice(finerGrain(view.grain, view.native));
      setHidden(new Set());
      setZoom(null);
      setAnnounce(`Drilled into ${humanize(target.column)} ${periodKey(start, view.grain)}`);
    } else if (mode === "filter") {
      const label = targetLabel(view, target);
      setPath([...path, { kind: "filter", column: target.column, value: target.value, label, grain: view.grain }]);
      setGrainChoice(undefined);
      setHidden(new Set());
      setZoom(null);
      setAnnounce(`Drilled into ${humanize(target.column)} = ${label}`);
    } else if (mode === "ask" && onDrill) {
      const request = followUp(view, target);
      onDrill(request);
      setAnnounce(`Asked a follow-up: ${request.question}`);
    }
  }, [view, path, canAsk, onDrill]);

  const interaction = useMemo<Interaction>(() => ({
    hidden,
    toggle: (key) => setHidden((current) => { const next = new Set(current); if (next.has(key)) next.delete(key); else next.add(key); return next; }),
    pick,
    drillable: (column) => (view && column ? columnDrillable(view, column, canAsk) : false),
    zoom,
    setZoom,
    up,
    k: 1,
    grain: view?.grain ?? null,
  }), [hidden, pick, view, canAsk, zoom, up]);

  useEffect(() => {
    if (!expanded) return;
    closeRef.current?.focus();
    const onKey = (event: globalThis.KeyboardEvent) => { if (event.key === "Escape") setExpanded(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded]);
  const closeExpanded = () => { setExpanded(false); window.setTimeout(() => expandRef.current?.focus(), 0); };

  const interactive = kind !== "empty" && kind !== "none";
  const zoomable = kind === "line" || kind === "scatter";
  const last = path[path.length - 1];
  const askCurrent = () => {
    if (!onDrill || !view || !last) return;
    const filters = view.filters;
    const measure = view.fields.y;
    const question = `Break down ${measure ? humanize(measure).toLowerCase() : "the result"} for ${filters.map((filter) => `${filter.column} = ${filter.value}`).join(" and ")}${view.fields.x ? ` by ${humanize(view.fields.x).toLowerCase()}` : ""}`;
    onDrill({ column: last.column, value: last.label, question, measure, filters });
    setAnnounce(`Asked a follow-up: ${question}`);
  };
  const toolbar = (inOverlay: boolean) => (
    <div className="viz-toolbar">
      {path.length > 0 ? (
        <nav className="viz-crumbs" aria-label="Drill path">
          <button type="button" className="viz-tool" onClick={() => up?.()} aria-label="Drill up one level" title="Drill up (Backspace)"><ArrowUp size={13} aria-hidden="true" /></button>
          <ol>
            <li><button type="button" onClick={() => drillTo(0)}>All</button></li>
            {path.map((step, depth) => (
              <li key={`${step.column}-${depth}`}>
                <ChevronRight size={12} aria-hidden="true" />
                {depth === path.length - 1
                  ? <span aria-current="page" title={`${humanize(step.column)} = ${step.label}`}>{step.label}</span>
                  : <button type="button" onClick={() => drillTo(depth + 1)} title={`${humanize(step.column)} = ${step.label}`}>{step.label}</button>}
              </li>
            ))}
          </ol>
        </nav>
      ) : <span className="viz-hint">{interactive && kind !== "kpi" ? `${canAsk || view?.fields.series || view?.grain ? "Click a mark to drill down" : "Hover for values"}${zoomable ? " · drag across to zoom" : ""}` : ""}</span>}
      <div className="viz-tools">
        {view && view.temporal && (view.grainOptions.length > 0) && kind !== "kpi" && (
          <label className="viz-grain">Grain
            <select value={view.grain ?? ""} onChange={(event) => { setGrainChoice((event.target.value || null) as Grain | null); resetLevel(); }}>
              <option value="">{view.native === "time" ? "As returned" : `${GRAIN_LABEL[view.native as Grain]} (as returned)`}</option>
              {view.grainOptions.map((grain) => <option key={grain} value={grain}>{GRAIN_LABEL[grain]}</option>)}
            </select>
          </label>
        )}
        {zoom && <button type="button" className="viz-tool" onClick={() => setZoom(null)} title="Reset zoom"><RotateCcw size={13} aria-hidden="true" />Reset zoom</button>}
        {onDrill && last && <button type="button" className="viz-tool" onClick={askCurrent} title="Ask this drill-down as a follow-up question"><MessageSquarePlus size={13} aria-hidden="true" />Ask</button>}
        {inOverlay
          ? <button ref={closeRef} type="button" className="viz-tool" onClick={closeExpanded} aria-label="Close expanded chart" title="Close (Escape)"><X size={14} aria-hidden="true" /></button>
          : <button ref={expandRef} type="button" className="viz-tool" onClick={() => setExpanded(true)} aria-label="Expand chart" title="Expand"><Maximize2 size={13} aria-hidden="true" /></button>}
      </div>
    </div>
  );
  return (
    <Interact.Provider value={interaction}>
      <figure className="result-chart" data-chart-type={requested} hidden={kind === "none"}>
        {showTitle && chart?.title && kind !== "none" && <figcaption><h4>{chart.title}</h4></figcaption>}
        {interactive && toolbar(false)}
        {kind !== "none" && <ChartBody view={view} kind={kind} />}
        <div className="viz-sr-only" aria-live="polite">{announce}</div>
      </figure>
      {expanded && interactive && typeof document !== "undefined" && createPortal(
        <div className="viz-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) closeExpanded(); }}>
          <div className="viz-overlay-panel result-chart" role="dialog" aria-modal="true" aria-label={`${chart?.title || "Chart"} (expanded)`}>
            {chart?.title && <h4>{chart.title}</h4>}
            {toolbar(true)}
            <Interact.Provider value={{ ...interaction, k: 1.9 }}>
              <ChartBody view={view} kind={kind} />
            </Interact.Provider>
          </div>
        </div>,
        document.body,
      )}
    </Interact.Provider>
  );
}

/** Segmented control listing the chart types a result supports (plus Table). */
export function ChartTypeSwitcher({ options, value, onChange, reason }: { options: ChartType[]; value: ChartType; onChange: (type: ChartType) => void; reason?: string }) {
  if (options.length < 2) return null;
  return (
    <div className="chart-switcher">
      <div className="chart-switcher-options" role="group" aria-label="Chart type">
        {options.map((option) => {
          const Icon = CHART_TYPE_ICONS[option];
          return (
            <button key={option} type="button" className={option === value ? "active" : undefined} aria-pressed={option === value} onClick={() => onChange(option)}>
              <Icon size={13} aria-hidden="true" />{CHART_TYPE_LABELS[option]}
            </button>
          );
        })}
      </div>
      {reason && <small className="chart-switcher-reason">Suggested because {reason}</small>}
    </div>
  );
}
