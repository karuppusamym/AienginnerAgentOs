import { Clock3, Search } from "lucide-react";
import { useState } from "react";
import { scopes, useDebouncedValue, usePagedQuery, usePagination, useQueryErrorToast } from "../lib/queries";
import { EmptyState, LoadingBlock, Pagination } from "./shared";

type AuditEvent = { id: string; actor_id: string | null; event_type: string; entity_type: string; entity_id: string | null; details: Record<string, unknown>; created_at: string };

const ENTITY_TYPES = ["", "query_tool", "external_client", "job", "approval", "artifact", "dataset", "conversation", "pipeline", "prompt", "user"];

/** Project audit trail (GET /audit), newest first, paged server-side. */
export function AuditLogPanel({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [eventType, setEventType] = useState("");
  const [entityType, setEntityType] = useState("");
  const eventFilter = useDebouncedValue(eventType.trim());
  const params = { event_type: eventFilter, entity_type: entityType };
  const pagination = usePagination(params, 50);
  const page = usePagedQuery<AuditEvent>(scopes.audit, "/audit", params, pagination);
  useQueryErrorToast(page.error, notify, "Audit log could not be loaded");
  const items = page.data?.items ?? [];
  return (
    <section className="surface admin-surface">
      <div className="section-heading"><div><span className="eyebrow">GOVERNANCE</span><h3>Audit log</h3><p>Every governed change and external-client event recorded for this project.</p></div><div className="row-actions"><div className="toolbar-search"><Search size={16} /><input placeholder="Event type, e.g. query_tool." value={eventType} onChange={(event) => setEventType(event.target.value)} aria-label="Filter by event type" /></div><select value={entityType} onChange={(event) => setEntityType(event.target.value)} aria-label="Filter by entity type">{ENTITY_TYPES.map((value) => <option key={value} value={value}>{value ? value.replaceAll("_", " ") : "All entities"}</option>)}</select></div></div>
      {items.length ? <>
        <div className="table-header audit-grid"><span>Time</span><span>Event</span><span>Entity</span><span>Details</span></div>
        {items.map((item) => <div className="data-row audit-grid" key={item.id}><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time><span><strong>{item.event_type}</strong><small>{item.actor_id ? `actor ${item.actor_id.slice(0, 8)}` : "system / external"}</small></span><span><strong>{item.entity_type.replaceAll("_", " ")}</strong>{item.entity_id && <small className="mono">{item.entity_id}</small>}</span><code className="audit-details" title={JSON.stringify(item.details)}>{Object.keys(item.details || {}).length ? JSON.stringify(item.details) : "-"}</code></div>)}
      </> : page.isPending ? <LoadingBlock label="Loading audit log" /> : <EmptyState icon={<Clock3 size={24} />} title="No audit events" body={eventFilter || entityType ? "No events match these filters." : "Governed actions will be recorded here."} />}
      <Pagination state={pagination} total={page.data?.total ?? 0} count={items.length} busy={page.isFetching} label="events" />
    </section>
  );
}
