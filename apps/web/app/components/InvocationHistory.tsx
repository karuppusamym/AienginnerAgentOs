import {
  AlertCircle,
  Check,
  Clock3,
  Network,
  RefreshCw,
  Rows3,
  X,
} from "lucide-react";
import { useState } from "react";
import { scopes, useInvalidate, usePagedQuery, usePagination, useProjectQuery, useQueryErrorToast } from "../lib/queries";
import type { ExternalClient, QueryTool } from "../types";
import { Drawer, EmptyState, LoadingBlock, Metric, Pagination, StatusPill } from "./shared";

export type ExternalInvocation = {
  id: string;
  external_client_id: string;
  query_tool_id: string;
  client_name: string;
  client_id: string | null;
  tool_name: string;
  channel: "rest" | "mcp" | string;
  status: string;
  parameters: Record<string, unknown>;
  result_metadata: { columns?: string[]; row_count?: number; truncated?: boolean };
  row_count: number | null;
  error: string | null;
  duration_ms: number | null;
  created_at: string;
};

export type ExternalInvocationDetail = ExternalInvocation & {
  tool: { id: string; name: string; status: string; purpose: string; data_source: string; line_of_business: string; owner: string; version: number; row_limit: number } | null;
  client: { id: string; name: string; client_id: string; active: boolean; scopes: string[] } | null;
};

type Bucket = { id: string | null; name: string; count: number; failed: number };
type InvocationWindow = { since: string; total: number; succeeded: number; failed: number; success_rate: number | null; avg_latency_ms: number | null; rows_returned: number; by_client: Bucket[]; by_tool: Bucket[]; by_status: Bucket[]; by_channel: Bucket[] };
type InvocationSummary = { generated_at: string; windows: { "24h": InvocationWindow; "7d": InvocationWindow } };

const RANGES: { value: string; label: string; ms: number | null }[] = [
  { value: "1h", label: "Last hour", ms: 3_600_000 },
  { value: "24h", label: "Last 24 hours", ms: 86_400_000 },
  { value: "7d", label: "Last 7 days", ms: 7 * 86_400_000 },
  { value: "30d", label: "Last 30 days", ms: 30 * 86_400_000 },
  { value: "all", label: "All time", ms: null },
  { value: "custom", label: "Custom range", ms: null },
];

const formatLatency = (value: number | null | undefined) => (value == null ? "-" : value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`);
const toIso = (local: string) => (local ? new Date(local).toISOString() : "");

function Breakdown({ title, buckets, onPick }: { title: string; buckets: Bucket[]; onPick?: (bucket: Bucket) => void }) {
  const max = Math.max(1, ...buckets.map((bucket) => bucket.count));
  return (
    <div>
      <h4>{title}</h4>
      {buckets.length ? buckets.slice(0, 5).map((bucket) => (
        <div className="breakdown-row" key={`${bucket.id}-${bucket.name}`}>
          <span>{onPick && bucket.id ? <button type="button" className="text-button" onClick={() => onPick(bucket)} title={`Filter the history by ${bucket.name}`}>{bucket.name}</button> : bucket.name}</span>
          <small>{bucket.count.toLocaleString()}{bucket.failed ? ` · ${bucket.failed} failed` : ""}</small>
          <span className="breakdown-bar" aria-hidden="true"><i style={{ width: `${((bucket.count - bucket.failed) / max) * 100}%` }} /><i className="failed" style={{ width: `${(bucket.failed / max) * 100}%` }} /></span>
        </div>
      )) : <div className="list-empty">No calls in this window.</div>}
    </div>
  );
}

function InvocationDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const detail = useProjectQuery<ExternalInvocationDetail>([...scopes.externalInvocations, "detail", id], `/external-invocations/${encodeURIComponent(id)}`);
  const item = detail.data;
  return (
    <Drawer title={item ? item.tool_name : "Invocation"} subtitle={item ? `${new Date(item.created_at).toLocaleString()} · ${item.id}` : id} onClose={onClose}>
      {!item ? (detail.error ? <div className="drawer-error">{detail.error.message}</div> : <LoadingBlock label="Loading invocation" />) : (
        <>
          <dl className="kv-list">
            <dt>Status</dt><dd><StatusPill value={item.status} /></dd>
            <dt>Client</dt><dd>{item.client_name}{item.client_id && <> · <code>{item.client_id}</code></>}{item.client && !item.client.active && <> · <StatusPill value="disabled" /></>}</dd>
            <dt>Channel</dt><dd><span className={`channel-tag ${item.channel}`}>{item.channel}</span> {item.channel === "mcp" ? "MCP tools/call" : "REST /external/v1/query-tools/…/invoke"}</dd>
            <dt>Latency</dt><dd>{formatLatency(item.duration_ms)}</dd>
            <dt>Rows</dt><dd>{item.row_count ?? "-"}{item.result_metadata?.truncated ? " (truncated at the row limit)" : ""}</dd>
            {item.tool && <><dt>Tool</dt><dd>{item.tool.name} v{item.tool.version} · {item.tool.status}</dd><dt>Source / LOB</dt><dd>{item.tool.data_source || "-"} / {item.tool.line_of_business || "-"}</dd><dt>Owner</dt><dd>{item.tool.owner || "-"}</dd></>}
          </dl>
          {item.error && <div className="drawer-error"><strong>Error</strong><br />{item.error}</div>}
          <div><div className="subheading"><h4>Parameters</h4><span>secret-like keys masked</span></div><pre>{JSON.stringify(item.parameters, null, 2)}</pre></div>
          <div><div className="subheading"><h4>Result summary</h4><span>{item.result_metadata?.columns?.length ?? 0} columns</span></div>{item.result_metadata?.columns?.length ? <div className="tag-list">{item.result_metadata.columns.map((column) => <span className="tag" key={column}>{column}</span>)}</div> : <div className="list-empty">No result columns were recorded{item.status === "failed" ? " because the call failed" : ""}.</div>}</div>
        </>
      )}
    </Drawer>
  );
}

/** Calls made by external agents through the governed gateway (REST and MCP), newest first. */
export function InvocationHistory({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [windowKey, setWindowKey] = useState<"24h" | "7d">("24h");
  const [clientId, setClientId] = useState("");
  const [toolId, setToolId] = useState("");
  const [status, setStatus] = useState("");
  const [channel, setChannel] = useState("");
  const [range, setRange] = useState({ preset: "7d", since: new Date(Date.now() - 7 * 86_400_000).toISOString(), until: "" });
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const invalidate = useInvalidate();
  const summary = useProjectQuery<InvocationSummary>([...scopes.externalInvocations, "summary"], "/external-invocations/summary", { refetchInterval: 30_000 });
  const clients = useProjectQuery<ExternalClient[]>([...scopes.externalInvocations, "clients"], "/external-clients");
  const tools = useProjectQuery<QueryTool[]>(scopes.queryTools, "/query-tools");
  const filters = { client_id: clientId, tool_id: toolId, status, channel, since: range.since, until: range.until };
  const pagination = usePagination(filters, 50);
  const history = usePagedQuery<ExternalInvocation>(scopes.externalInvocations, "/external-invocations", filters, pagination);
  useQueryErrorToast(history.error || summary.error, notify, "Invocation history could not be loaded");
  const current = summary.data?.windows[windowKey];
  const items = history.data?.items ?? [];
  const filtered = !!(clientId || toolId || status || channel || range.preset !== "7d");

  function choosePreset(preset: string) {
    const option = RANGES.find((item) => item.value === preset);
    if (preset === "custom") { setRange({ preset, since: toIso(customFrom), until: toIso(customTo) }); return; }
    setRange({ preset, since: option?.ms ? new Date(Date.now() - option.ms).toISOString() : "", until: "" });
  }
  function clearFilters() { setClientId(""); setToolId(""); setStatus(""); setChannel(""); choosePreset("7d"); }

  return (
    <div className="view-stack">
      <section className="surface admin-surface">
        <div className="history-window">
          <div className="section-heading compact"><div><span className="eyebrow">EXTERNAL AGENT TRAFFIC</span><h3>Invocation history</h3><p>Every call an external agent made through the gateway, over REST or MCP, with its outcome.</p></div></div>
          <div className="row-actions">
            <div className="segmented" role="group" aria-label="Summary window"><button type="button" className={windowKey === "24h" ? "active" : ""} onClick={() => setWindowKey("24h")}>24 hours</button><button type="button" className={windowKey === "7d" ? "active" : ""} onClick={() => setWindowKey("7d")}>7 days</button></div>
            <button type="button" className="icon-button" title="Refresh" aria-label="Refresh history" onClick={() => void invalidate(scopes.externalInvocations)}><RefreshCw size={16} className={history.isFetching || summary.isFetching ? "spin" : undefined} /></button>
          </div>
        </div>
        <div className="metric-grid">
          <Metric label="Calls" value={current ? current.total.toLocaleString() : "-"} detail={windowKey === "24h" ? "Last 24 hours" : "Last 7 days"} icon={<Network size={18} />} tone="blue" />
          <Metric label="Success rate" value={current?.success_rate != null ? `${current.success_rate}%` : "-"} detail={current ? `${current.succeeded.toLocaleString()} succeeded` : "No calls yet"} icon={<Check size={18} />} tone="teal" />
          <Metric label="Failed" value={current ? current.failed.toLocaleString() : "-"} detail="Execution or validation errors" icon={<AlertCircle size={18} />} tone="amber" />
          <Metric label="Avg latency" value={formatLatency(current?.avg_latency_ms)} detail={current ? `${current.rows_returned.toLocaleString()} rows returned` : "-"} icon={<Clock3 size={18} />} tone="blue" />
        </div>
        {current && (
          <div className="history-breakdown">
            <Breakdown title="Top clients" buckets={current.by_client} onPick={(bucket) => setClientId(bucket.id || "")} />
            <Breakdown title="Top tools" buckets={current.by_tool} onPick={(bucket) => setToolId(bucket.id || "")} />
            <Breakdown title="By channel" buckets={current.by_channel.map((bucket) => ({ ...bucket, name: String(bucket.name).toUpperCase() }))} onPick={(bucket) => setChannel(bucket.id || "")} />
          </div>
        )}
      </section>
      <section className="surface">
        <div className="history-toolbar">
          <label>Client<select value={clientId} onChange={(event) => setClientId(event.target.value)}><option value="">All clients</option>{(clients.data || []).map((client) => <option key={client.id} value={client.id}>{client.name}</option>)}</select></label>
          <label>Tool<select value={toolId} onChange={(event) => setToolId(event.target.value)}><option value="">All tools</option>{(tools.data || []).map((tool) => <option key={tool.id} value={tool.id}>{tool.name}</option>)}</select></label>
          <label>Status<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">Any status</option><option value="succeeded">Succeeded</option><option value="failed">Failed</option><option value="running">Running</option></select></label>
          <label>Channel<select value={channel} onChange={(event) => setChannel(event.target.value)}><option value="">REST and MCP</option><option value="rest">REST</option><option value="mcp">MCP</option></select></label>
          <label>Range<select value={range.preset} onChange={(event) => choosePreset(event.target.value)}>{RANGES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
          {range.preset === "custom" && <>
            <label>From<input type="datetime-local" value={customFrom} onChange={(event) => { setCustomFrom(event.target.value); setRange({ preset: "custom", since: toIso(event.target.value), until: toIso(customTo) }); }} /></label>
            <label>To<input type="datetime-local" value={customTo} onChange={(event) => { setCustomTo(event.target.value); setRange({ preset: "custom", since: toIso(customFrom), until: toIso(event.target.value) }); }} /></label>
          </>}
          {filtered && <button type="button" className="text-button" onClick={clearFilters}><X size={14} />Clear filters</button>}
        </div>
        <div className="table-header invocation-grid"><span>Time</span><span>Client</span><span>Tool</span><span>Channel</span><span>Status</span><span>Rows</span><span>Latency</span><span>Error</span></div>
        {items.length ? items.map((item) => (
          <button type="button" className={`data-row invocation-grid ${openId === item.id ? "selected" : ""}`} key={item.id} onClick={() => setOpenId(item.id)}>
            <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time>
            <span><strong>{item.client_name}</strong>{item.client_id && <small>{item.client_id}</small>}</span>
            <span><strong>{item.tool_name}</strong></span>
            <span><span className={`channel-tag ${item.channel}`}>{item.channel}</span></span>
            <StatusPill value={item.status} />
            <span className="mono">{item.row_count ?? "-"}</span>
            <span className="mono">{formatLatency(item.duration_ms)}</span>
            <span className="error-cell" title={item.error || undefined}>{item.error || ""}</span>
          </button>
        )) : history.isPending ? <LoadingBlock label="Loading invocation history" /> : <EmptyState icon={<Rows3 size={24} />} title={filtered ? "No calls match these filters" : "No external calls yet"} body={filtered ? "Widen the date range or clear a filter." : "Calls from granted external clients over REST or MCP appear here."} />}
        <Pagination state={pagination} total={history.data?.total ?? 0} count={items.length} busy={history.isFetching} label="calls" />
      </section>
      {openId && <InvocationDrawer id={openId} onClose={() => setOpenId(null)} />}
    </div>
  );
}
