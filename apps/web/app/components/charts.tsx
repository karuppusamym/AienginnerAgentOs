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
 */
import {
  ChartColumn,
  ChartColumnBig,
  ChartColumnStacked,
  ChartLine,
  ChartPie,
  ChartScatter,
  Hash,
  Table,
} from "lucide-react";
import { KeyboardEvent, PointerEvent, ReactNode, useEffect, useId, useMemo, useRef, useState } from "react";
import type { ChartSpec, ChartType, ChartUnit } from "../types";

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
  const step = niceStep(max - min, count);
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let tick = lo; tick <= hi + step / 2; tick += step) ticks.push(Number(tick.toPrecision(12)));
  return { lo, hi, ticks };
}

const linear = (d0: number, d1: number, r0: number, r1: number) => (value: number) => (d1 === d0 ? (r0 + r1) / 2 : r0 + ((value - d0) / (d1 - d0)) * (r1 - r0));

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

/** Axis / tooltip labels for category keys; ISO dates (a line switched to bars) read as dates. */
function categoryLabels(keys: string[]) {
  const times = keys.map(parseTime);
  if (keys.length && times.every((time) => time != null)) {
    const format = timeFormatters(times as number[]);
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

function ChartFrame({ label, summary, width, height, count, active, onActive, tip, anchor, legend, note, children }: {
  label: string;
  summary: string;
  width: number;
  height: number;
  count: number;
  active: number | null;
  onActive: (index: number | null) => void;
  tip: Tip | null;
  anchor: Point | null;
  legend?: ReactNode;
  note?: ReactNode;
  children: ReactNode;
}) {
  const titleId = useId();
  const descId = useId();
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!count) return;
    const current = active ?? -1;
    let next: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = Math.min(count - 1, current + 1);
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = Math.max(0, current < 0 ? 0 : current - 1);
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = count - 1;
    else if (event.key === "Escape") { onActive(null); return; }
    if (next === null) return;
    event.preventDefault();
    onActive(next);
  }
  const live = tip ? `${tip.title}: ${tip.rows.map((row) => `${row.label} ${row.value}`).join(", ")}` : "";
  const side = anchor && anchor.x > width / 2 ? "end" : "start";
  return (
    <div className="viz-frame">
      <div
        className="viz-plot"
        tabIndex={count ? 0 : -1}
        role="group"
        aria-label={count ? `${label}. Use the arrow keys to read each value.` : label}
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
          </div>
        )}
      </div>
      <div className="viz-sr-only" aria-live="polite">{live}</div>
      {legend}
      {note && <p className="viz-note">{note}</p>}
    </div>
  );
}

function Legend({ items, mark }: { items: { key: string; label: string; color: string; value?: string }[]; mark: "line" | "rect" }) {
  if (items.length < 2) return null;
  return (
    <ul className="viz-legend" aria-label="Legend">
      {items.map((item) => (
        <li key={item.key} title={item.label}>
          <i className={`viz-key viz-key--${mark}`} style={{ background: item.color }} />
          <span>{item.label}</span>
          {item.value && <b>{item.value}</b>}
        </li>
      ))}
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
  const [active, setActive] = useState<number | null>(null);
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
    const xs = Array.from(positions.entries()).map(([key, pos]) => ({ key, pos }));
    if (temporal || numericX) xs.sort((a, b) => a.pos - b.pos);
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
    const all = lines.flatMap((line) => line.values.filter((value): value is number => value != null));
    const min = Math.min(...all);
    const max = Math.max(...all);
    const domain = niceDomain(min >= 0 && min < max * 0.6 ? 0 : min, max, 4);
    const format = temporal ? timeFormatters(xs.map((item) => item.pos)) : null;
    const xLabel = (index: number) => (format ? format.full(xs[index].pos) : numericX ? formatChartValue(xs[index].pos, "number") : xs[index].key);
    const xTick = (index: number) => (format ? format.tick(xs[index].pos) : numericX ? formatChartValue(xs[index].pos, "number", true) : xs[index].key);
    return { xs, lines, unit, domain, xLabel, xTick, hidden, ordinal: !temporal && !numericX };
  }, [chart, fields]);

  const { xs, lines, unit, domain } = model;
  const height = 210;
  const yFormat = (value: number) => formatChartValue(value, unit, true);
  const margin = { top: 12, right: 14, bottom: 26, left: tickLabelWidth(domain.ticks, yFormat) };
  const plotRight = width - margin.right;
  const plotBottom = height - margin.bottom;
  const first = xs[0]?.pos ?? 0;
  const last = xs[xs.length - 1]?.pos ?? 1;
  const xScale = linear(first, last, margin.left + 4, plotRight - 4);
  const yScale = linear(domain.lo, domain.hi, plotBottom, margin.top);
  const px = (index: number) => xScale(xs[index].pos);
  const paths = lines.map((line) => {
    let d = "";
    let open = false;
    line.values.forEach((value, index) => {
      if (value == null) { open = false; return; }
      d += `${open ? "L" : "M"}${px(index).toFixed(1)},${yScale(value).toFixed(1)}`;
      open = true;
    });
    return d;
  });
  const single = lines.length === 1 ? lines[0] : null;
  const area = single && paths[0] && single.values.every((value) => value != null) && xs.length > 1
    ? `${paths[0]}L${px(xs.length - 1).toFixed(1)},${yScale(Math.max(domain.lo, 0))}L${px(0).toFixed(1)},${yScale(Math.max(domain.lo, 0))}Z`
    : "";
  const ticks = tickIndexes(xs.length, Math.floor((plotRight - margin.left) / 74));
  const maxTickChars = Math.floor(((plotRight - margin.left) / Math.max(1, ticks.length)) / CHAR_W);

  function onMove(event: PointerEvent<SVGRectElement>) {
    const box = event.currentTarget.ownerSVGElement!.getBoundingClientRect();
    const at = event.clientX - box.left;
    let best = 0;
    for (let index = 1; index < xs.length; index += 1) if (Math.abs(px(index) - at) < Math.abs(px(best) - at)) best = index;
    setActive(best);
  }

  const tip: Tip | null = active == null ? null : {
    title: model.xLabel(active),
    rows: lines.map((line) => ({ key: line.name, label: line.label, value: formatChartValue(line.values[active], unit), swatch: line.color, mark: "line" as const })),
  };
  const values = lines.flatMap((line) => line.values).filter((value): value is number => value != null);
  const summary = `Line chart of ${humanize(fields.y!)} over ${humanize(fields.x!)}: ${xs.length} points${lines.length > 1 ? `, ${lines.length} series` : ""}, from ${formatChartValue(Math.min(...values), unit)} to ${formatChartValue(Math.max(...values), unit)}.`;
  return (
    <ChartFrame
      label={chartLabel(chart, "Line chart")}
      summary={summary}
      width={width}
      height={height}
      count={xs.length}
      active={active}
      onActive={setActive}
      tip={tip}
      anchor={active == null ? null : { x: px(active), y: margin.top }}
      legend={<Legend mark="line" items={lines.map((line) => ({ key: line.name, label: line.label, color: line.color }))} />}
      note={model.hidden > 0 ? `${model.hidden} more series are only in the table.` : null}
    >
      <YAxis ticks={domain.ticks} scale={yScale} left={margin.left} right={plotRight} format={yFormat} />
      <g className="viz-axis">
        {ticks.map((index) => {
          const anchor = index === 0 && px(index) - margin.left < 20 ? "start" : "middle";
          return <text key={index} x={px(index)} y={height - 8} textAnchor={anchor}>{truncate(model.xTick(index), Math.max(4, maxTickChars))}</text>;
        })}
      </g>
      {area && <path className="viz-area" d={area} style={{ fill: single!.color }} />}
      {lines.map((line, index) => <path key={line.name} className="viz-line" d={paths[index]} style={{ stroke: line.color }} />)}
      {lines.map((line) => {
        const lastIndex = line.values.map((value, index) => (value == null ? -1 : index)).filter((index) => index >= 0).pop();
        return lastIndex == null ? null : <circle key={`end-${line.name}`} className="viz-dot" cx={px(lastIndex)} cy={yScale(line.values[lastIndex]!)} r={4} style={{ fill: line.color }} />;
      })}
      {active != null && (
        <g pointerEvents="none">
          <line className="viz-crosshair" x1={px(active)} x2={px(active)} y1={margin.top} y2={plotBottom} />
          {lines.map((line) => line.values[active] == null ? null : <circle key={`hover-${line.name}`} className="viz-dot" cx={px(active)} cy={yScale(line.values[active]!)} r={4.5} style={{ fill: line.color }} />)}
        </g>
      )}
      <rect className="viz-hit" x={margin.left} y={margin.top} width={Math.max(0, plotRight - margin.left)} height={Math.max(0, plotBottom - margin.top)} onPointerMove={onMove} onPointerDown={onMove} />
    </ChartFrame>
  );
}

// ------------------------------------------------------------------ bar (one measure)

const HORIZONTAL_ROW_CAP = 30;

function BarChart({ chart, fields, width }: { chart: ChartSpec; fields: Fields; width: number }) {
  const [active, setActive] = useState<number | null>(null);
  const x = fields.x!;
  const y = fields.y!;
  const unit = unitFor(chart, y);
  const all = (chart.data as Row[]).map((row) => ({ label: text(row[x]), value: num(row[y]) ?? 0 }));
  const vertical = all.length <= 12;
  const bars = vertical ? all : all.slice(0, HORIZONTAL_ROW_CAP);
  const labels = categoryLabels(bars.map((bar) => bar.label));
  const min = Math.min(0, ...bars.map((bar) => bar.value));
  const max = Math.max(0, ...bars.map((bar) => bar.value));
  const domain = niceDomain(min, max, 4);
  const color = slot(0);
  const fmt = (value: number) => formatChartValue(value, unit);
  const summary = `Bar chart of ${humanize(y)} by ${humanize(x)}: ${all.length} categories. Highest ${bars.reduce((best, bar) => (bar.value > best.value ? bar : best), bars[0]).label} (${fmt(max)}).`;
  const tip: Tip | null = active == null ? null : { title: labels.full(active), rows: [{ key: "value", label: humanize(y), value: fmt(bars[active].value) }] };

  if (vertical) {
    const height = 220;
    const yFormat = (value: number) => formatChartValue(value, unit, true);
    const margin = { top: 16, right: 8, bottom: 30, left: tickLabelWidth(domain.ticks, yFormat) };
    const plotRight = width - margin.right;
    const plotBottom = height - margin.bottom;
    const band = (plotRight - margin.left) / bars.length;
    const barWidth = Math.max(2, Math.min(24, band * 0.62));
    const yScale = linear(domain.lo, domain.hi, plotBottom, margin.top);
    const base = yScale(0);
    const labelEvery = Math.max(1, Math.ceil((Math.min(10, Math.max(4, ...bars.map((_, index) => labels.tick(index).length))) * CHAR_W + 6) / band));
    const maxChars = Math.floor((band * labelEvery - 4) / CHAR_W);
    const showValues = bars.length <= 6 && band >= 36;
    return (
      <ChartFrame label={chartLabel(chart, "Bar chart")} summary={summary} width={width} height={height} count={bars.length} active={active} onActive={setActive} tip={tip}
        anchor={active == null ? null : { x: margin.left + band * active + band / 2, y: Math.min(yScale(bars[active].value), base) }}>
        <YAxis ticks={domain.ticks} scale={yScale} left={margin.left} right={plotRight} format={yFormat} />
        {bars.map((bar, index) => {
          const cx = margin.left + band * index + band / 2;
          const end = yScale(bar.value);
          return (
            <g key={`${bar.label}-${index}`}>
              <path className={`viz-bar${active === index ? " active" : ""}`} d={columnPath(cx - barWidth / 2, barWidth, base, end)} style={{ fill: color }} />
              {showValues && <text className="viz-value" x={cx} y={bar.value >= 0 ? end - 5 : end + 12} textAnchor="middle">{formatChartValue(bar.value, unit, true)}</text>}
              {index % labelEvery === 0 && <text className="viz-axis-text" x={cx} y={height - 12} textAnchor="middle">{truncate(labels.tick(index), maxChars)}</text>}
              <rect className="viz-hit" x={margin.left + band * index} y={margin.top} width={band} height={plotBottom - margin.top + 18} onPointerEnter={() => setActive(index)} onPointerDown={() => setActive(index)} />
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
    <ChartFrame label={chartLabel(chart, "Bar chart")} summary={summary} width={width} height={height} count={bars.length} active={active} onActive={setActive} tip={tip}
      anchor={active == null ? null : { x: Math.max(xScale(bars[active].value), base), y: margin.top + rowHeight * active }}
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
            <rect className="viz-hit" x={0} y={top} width={width} height={rowHeight} onPointerEnter={() => setActive(index)} onPointerDown={() => setActive(index)} />
          </g>
        );
      })}
    </ChartFrame>
  );
}

// ------------------------------------------------------------------ grouped / stacked bars

const CATEGORY_CAP = 12;

function GroupedBarChart({ chart, fields, width, stacked }: { chart: ChartSpec; fields: Fields; width: number; stacked: boolean }) {
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
  const labels = categoryLabels(categories);
  const colorOf = (index: number) => (model.folded && index === series.length - 1 ? OTHER_COLOR : slot(index));
  let min = 0;
  let max = 0;
  for (const values of matrix) {
    if (stacked) {
      max = Math.max(max, values.filter((value) => value > 0).reduce((sum, value) => sum + value, 0));
      min = Math.min(min, values.filter((value) => value < 0).reduce((sum, value) => sum + value, 0));
    } else {
      max = Math.max(max, ...values);
      min = Math.min(min, ...values);
    }
  }
  const domain = niceDomain(min, max, 4);
  const height = 220;
  const yFormat = (value: number) => formatChartValue(value, unit, true);
  const margin = { top: 12, right: 8, bottom: 30, left: tickLabelWidth(domain.ticks, yFormat) };
  const plotRight = width - margin.right;
  const plotBottom = height - margin.bottom;
  const band = (plotRight - margin.left) / Math.max(1, categories.length);
  const yScale = linear(domain.lo, domain.hi, plotBottom, margin.top);
  const base = yScale(0);
  const gap = 2;
  const groupWidth = Math.min(band * 0.84, series.length * 24 + (series.length - 1) * gap);
  const barWidth = stacked ? Math.max(2, Math.min(24, band * 0.6)) : Math.max(1, (groupWidth - (series.length - 1) * gap) / series.length);
  const labelEvery = Math.max(1, Math.ceil((Math.min(10, Math.max(4, ...categories.map((_, index) => labels.tick(index).length))) * CHAR_W + 6) / band));
  const maxChars = Math.floor((band * labelEvery - 4) / CHAR_W);
  const fmt = (value: number) => formatChartValue(value, unit);
  const tip: Tip | null = active == null ? null : {
    title: labels.full(active),
    rows: [
      ...series.map((name, index) => ({ key: name, label: name, value: fmt(matrix[active][index]), swatch: colorOf(index), mark: "rect" as const })),
      ...(stacked ? [{ key: "__total", label: "Total", value: fmt(matrix[active].reduce((sum, value) => sum + value, 0)) }] : []),
    ],
  };
  const summary = `${stacked ? "Stacked" : "Grouped"} bar chart of ${humanize(y)} by ${humanize(x)} and ${humanize(seriesField)}: ${categories.length} categories, ${series.length} series.`;
  const notes = [model.hiddenCategories > 0 ? `Showing the first ${categories.length} categories.` : "", model.folded ? `Series past the seventh are combined as "Other".` : ""].filter(Boolean).join(" ");
  return (
    <ChartFrame label={chartLabel(chart, stacked ? "Stacked bar chart" : "Grouped bar chart")} summary={summary} width={width} height={height} count={categories.length} active={active} onActive={setActive} tip={tip}
      anchor={active == null ? null : { x: margin.left + band * active + band / 2, y: margin.top }}
      legend={<Legend mark="rect" items={series.map((name, index) => ({ key: name, label: name, color: colorOf(index) }))} />}
      note={notes || null}>
      <YAxis ticks={domain.ticks} scale={yScale} left={margin.left} right={plotRight} format={yFormat} />
      {categories.map((category, c) => {
        const cx = margin.left + band * c + band / 2;
        const marks: ReactNode[] = [];
        if (stacked) {
          const positives = matrix[c].map((value, index) => ({ value, index })).filter((item) => item.value > 0);
          const negatives = matrix[c].map((value, index) => ({ value, index })).filter((item) => item.value < 0);
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
          matrix[c].forEach((value, index) => {
            marks.push(<path key={index} className="viz-bar" d={columnPath(start + index * (barWidth + gap), barWidth, base, yScale(value))} style={{ fill: colorOf(index) }} />);
          });
        }
        return (
          <g key={`${category}-${c}`} className={active === c ? "viz-group active" : "viz-group"}>
            {marks}
            {c % labelEvery === 0 && <text className="viz-axis-text" x={cx} y={height - 12} textAnchor="middle">{truncate(labels.tick(c), maxChars)}</text>}
            <rect className="viz-hit" x={margin.left + band * c} y={margin.top} width={band} height={plotBottom - margin.top + 18} onPointerEnter={() => setActive(c)} onPointerDown={() => setActive(c)} />
          </g>
        );
      })}
    </ChartFrame>
  );
}

// ------------------------------------------------------------------ pie (donut)

const PIE_SLICES = 8;

function PieChart({ chart, fields, width }: { chart: ChartSpec; fields: Fields; width: number }) {
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
  const total = slices.reduce((sum, item) => sum + item.value, 0);
  if (!total) return <div className="chart-empty">Nothing to show as parts of a whole</div>;
  const side = width >= 400;
  const size = Math.min(side ? width * 0.46 : width, 210);
  const height = size;
  const cx = size / 2;
  const cy = size / 2;
  const outer = size / 2 - 8;
  const inner = outer * 0.62;
  let angle = -Math.PI / 2;
  const arcs = slices.map((slice) => {
    const sweep = (slice.value / total) * Math.PI * 2;
    const start = angle;
    angle += sweep;
    return { ...slice, start, end: angle, share: slice.value / total };
  });
  const arcPath = (start: number, end: number, r0: number, r1: number) => {
    if (end - start >= Math.PI * 2 - 1e-6) end = start + Math.PI * 2 - 1e-4;
    const large = end - start > Math.PI ? 1 : 0;
    const p = (r: number, a: number) => `${(cx + r * Math.cos(a)).toFixed(2)},${(cy + r * Math.sin(a)).toFixed(2)}`;
    return `M${p(r1, start)}A${r1},${r1} 0 ${large} 1 ${p(r1, end)}L${p(r0, end)}A${r0},${r0} 0 ${large} 0 ${p(r0, start)}Z`;
  };
  const pct = (share: number) => new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: share < 0.1 ? 1 : 0 }).format(share);
  const focus = active == null ? null : arcs[active];
  // A share measure that already sums to the whole would repeat itself as "% of total".
  const sharesOfWhole = (unit === "fraction" && Math.abs(total - 1) < 0.01) || (unit === "percent" && Math.abs(total - 100) < 1);
  const tip: Tip | null = focus ? { title: focus.label, rows: [{ key: "value", label: humanize(y), value: formatChartValue(focus.value, unit) }, ...(sharesOfWhole ? [] : [{ key: "share", label: "of total", value: pct(focus.share) }])] } : null;
  const mid = focus ? (focus.start + focus.end) / 2 : 0;
  const summary = `Donut chart of ${humanize(y)} by ${humanize(x)}, total ${formatChartValue(total, unit)}: ${arcs.map((arc) => `${arc.label} ${pct(arc.share)}`).join(", ")}.`;
  return (
    <div className={`viz-pie${side ? " viz-pie--side" : ""}`}>
      <ChartFrame label={chartLabel(chart, "Donut chart")} summary={summary} width={size} height={height} count={arcs.length} active={active} onActive={setActive} tip={tip}
        anchor={focus ? { x: cx + (outer + 4) * Math.cos(mid), y: cy + (outer + 4) * Math.sin(mid) } : null}>
        {arcs.map((arc, index) => (
          <path key={`${arc.label}-${index}`} className={`viz-slice${active === index ? " active" : ""}`} d={arcPath(arc.start, arc.end, inner, active === index ? outer + 4 : outer)} style={{ fill: arc.color }} onPointerEnter={() => setActive(index)} onPointerDown={() => setActive(index)} />
        ))}
        <text className="viz-center-value" x={cx} y={cy + 2} textAnchor="middle">{focus ? pct(focus.share) : formatChartValue(total, unit, true)}</text>
        <text className="viz-center-label" x={cx} y={cy + 17} textAnchor="middle">{focus ? truncate(focus.label, Math.floor((inner * 2 - 8) / CHAR_W)) : "Total"}</text>
      </ChartFrame>
      <ul className="viz-legend viz-legend--list" aria-label="Legend">
        {arcs.map((arc, index) => (
          <li key={`${arc.label}-${index}`} className={active === index ? "active" : undefined} title={`${arc.label}: ${formatChartValue(arc.value, unit)}`}>
            <i className="viz-key viz-key--rect" style={{ background: arc.color }} />
            <span>{arc.label}</span>
            <b>{pct(arc.share)}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ------------------------------------------------------------------ scatter

const SCATTER_SERIES_CAP = 3; // the palette's first three slots validate for all-pairs comparison

function ScatterChart({ chart, fields, width }: { chart: ChartSpec; fields: Fields; width: number }) {
  const [active, setActive] = useState<number | null>(null);
  const x = fields.x!;
  const y = fields.y!;
  const xUnit = unitFor(chart, x);
  const yUnit = unitFor(chart, y);
  const model = useMemo(() => {
    const rows = chart.data as Row[];
    const seriesNames = fields.series ? Array.from(new Set(rows.map((row) => text(row[fields.series!])))) : [];
    const colored = seriesNames.length > 1 && seriesNames.length <= SCATTER_SERIES_CAP;
    const points = rows
      .map((row) => ({ x: num(row[x]), y: num(row[y]), label: fields.series ? text(row[fields.series]) : "", row }))
      .filter((point): point is { x: number; y: number; label: string; row: Row } => point.x != null && point.y != null)
      .slice(0, 500)
      .sort((a, b) => a.x - b.x);
    return { points, seriesNames: colored ? seriesNames : [], colored };
  }, [chart, x, y, fields.series]);
  const { points } = model;
  if (!points.length) return <div className="chart-empty">No numeric pairs to plot</div>;
  const height = 230;
  const xDomain = niceDomain(Math.min(...points.map((p) => p.x)), Math.max(...points.map((p) => p.x)), 4);
  const yDomain = niceDomain(Math.min(...points.map((p) => p.y)), Math.max(...points.map((p) => p.y)), 4);
  const yFormat = (value: number) => formatChartValue(value, yUnit, true);
  const margin = { top: 14, right: 14, bottom: 34, left: tickLabelWidth(yDomain.ticks, yFormat) };
  const plotRight = width - margin.right;
  const plotBottom = height - margin.bottom;
  const xScale = linear(xDomain.lo, xDomain.hi, margin.left, plotRight);
  const yScale = linear(yDomain.lo, yDomain.hi, plotBottom, margin.top);
  const colorOf = (label: string) => (model.colored ? slot(model.seriesNames.indexOf(label)) : slot(0));
  const xTicks = xDomain.ticks.filter((_, index) => index % Math.max(1, Math.ceil(xDomain.ticks.length / Math.floor((plotRight - margin.left) / 60))) === 0);
  function onMove(event: PointerEvent<SVGRectElement>) {
    const box = event.currentTarget.ownerSVGElement!.getBoundingClientRect();
    const mx = event.clientX - box.left;
    const my = event.clientY - box.top;
    let best = -1;
    let bestDistance = 24 * 24; // hit radius: 24px, much larger than the 8px dot
    points.forEach((point, index) => {
      const distance = (xScale(point.x) - mx) ** 2 + (yScale(point.y) - my) ** 2;
      if (distance < bestDistance) { bestDistance = distance; best = index; }
    });
    setActive(best < 0 ? null : best);
  }
  const focus = active == null ? null : points[active];
  const tip: Tip | null = focus ? {
    title: model.colored ? focus.label : `Point ${active! + 1} of ${points.length}`,
    rows: [{ key: "y", label: humanize(y), value: formatChartValue(focus.y, yUnit) }, { key: "x", label: humanize(x), value: formatChartValue(focus.x, xUnit) }],
  } : null;
  const summary = `Scatter plot of ${humanize(y)} against ${humanize(x)}: ${points.length} points.`;
  return (
    <ChartFrame label={chartLabel(chart, "Scatter plot")} summary={summary} width={width} height={height} count={points.length} active={active} onActive={setActive} tip={tip}
      anchor={focus ? { x: xScale(focus.x), y: yScale(focus.y) } : null}
      legend={<Legend mark="rect" items={model.seriesNames.map((name, index) => ({ key: name, label: name, color: slot(index) }))} />}
      note={chart.data.length > points.length ? `${chart.data.length - points.length} rows without both values are not plotted.` : null}>
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
      <rect className="viz-hit" x={margin.left - 12} y={margin.top - 12} width={Math.max(0, plotRight - margin.left + 24)} height={Math.max(0, plotBottom - margin.top + 24)} onPointerMove={onMove} onPointerDown={onMove} />
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

/**
 * Renders a result chart. `type` overrides the API's choice (the inspector's
 * chart-type switcher); "table" renders nothing because the result table is
 * always shown below the chart.
 */
export function AnalysisChart({ chart, type, showTitle = true }: { chart?: ChartSpec | null; type?: ChartType; showTitle?: boolean }) {
  const [ref, width] = useElementWidth();
  const fields = useMemo(() => (chart?.data?.length ? resolveFields(chart) : null), [chart]);
  const requested: ChartType = type || (isChartType(chart?.type) ? chart!.type as ChartType : "table");
  let body: ReactNode = null;
  if (!chart?.data?.length || !fields) {
    body = <div className="chart-empty">No chartable result</div>;
  } else if (requested === "table") {
    body = null;
  } else if (requested === "kpi") {
    body = <KpiTiles chart={chart} fields={fields} />;
  } else if (!fields.x || !fields.y) {
    body = <div className="chart-empty">No chartable result</div>;
  } else if (requested === "line") {
    body = <LineChart chart={chart} fields={fields} width={width} />;
  } else if ((requested === "grouped_bar" || requested === "stacked_bar") && fields.series) {
    body = <GroupedBarChart chart={chart} fields={fields} width={width} stacked={requested === "stacked_bar"} />;
  } else if (requested === "pie" && chart.data.every((row) => (num(row[fields.y!]) ?? 0) >= 0)) {
    body = <PieChart chart={chart} fields={fields} width={width} />;
  } else if (requested === "scatter" && isNumericColumn(chart, fields.x)) {
    body = <ScatterChart chart={chart} fields={fields} width={width} />;
  } else {
    body = <BarChart chart={chart} fields={fields} width={width} />;
  }
  return (
    <figure className="result-chart" data-chart-type={requested} hidden={!body}>
      {showTitle && chart?.title && body && <figcaption><h4>{chart.title}</h4></figcaption>}
      {/* Measured element: the content box, so charts never overflow the figure's padding. */}
      <div ref={ref} className="viz-measure">{body}</div>
    </figure>
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
