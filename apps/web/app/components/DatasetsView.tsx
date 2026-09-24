import {
  ChevronRight,
  Code2,
  Database,
  FileSpreadsheet,
  FileUp,
  MessageSquare,
  Search,
} from "lucide-react";
import { ChangeEvent, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { scopes, useDatasets, useInvalidate, useQueryErrorToast } from "../lib/queries";
import type {
  Dataset,
} from "../types";
import {
  connectorLabels,
} from "../lib/constants";
import { LoadingBlock, Modal } from "./shared";


const NO_DATASETS: Dataset[] = [];

export function DatasetsView({ onOpenSQL, onStartAnalysis, notify }: { onOpenSQL: (dataset: Dataset) => void; onStartAnalysis?: (dataset: Dataset) => void; notify?: (message: string, tone?: "ok" | "error") => void }) {
  const datasetsQuery = useDatasets();
  const datasets = datasetsQuery.data ?? NO_DATASETS;
  useQueryErrorToast(datasetsQuery.error, notify, "Datasets could not be loaded");
  const invalidate = useInvalidate();
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = datasets.find((item) => item.id === selectedId) || datasets[0] || null;
  const [editing, setEditing] = useState(false);
  const [editDescription, setEditDescription] = useState("");
  const [editTags, setEditTags] = useState("");
  const [editOwner, setEditOwner] = useState("");
  const [editSensitivity, setEditSensitivity] = useState("unclassified");
  const [editFreshnessHours, setEditFreshnessHours] = useState("");
  const [editMetadataStatus, setEditMetadataStatus] = useState("scanned");
  const [editColumnNotes, setEditColumnNotes] = useState<Record<string, { business_name: string; description: string }>>({});
  const [saving, setSaving] = useState(false);
  const load = () => { void invalidate(scopes.datasets); };
  const openEdit = () => {
    if (!selected) return;
    setEditDescription(selected.description || "");
    setEditTags((selected.tags || []).join(", "));
    setEditOwner(selected.owner || "");
    setEditSensitivity(selected.sensitivity || "unclassified");
    setEditFreshnessHours(selected.freshness_sla_hours != null ? String(selected.freshness_sla_hours) : "");
    setEditMetadataStatus(selected.metadata_status || "scanned");
    setEditColumnNotes(
      Object.fromEntries(
        (selected.columns || []).map((column) => [column.name, { business_name: column.business_name || "", description: column.description || "" }])
      )
    );
    setEditing(true);
  };
  const saveEdit = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      const tags = editTags.split(",").map((tag) => tag.trim()).filter(Boolean);
      const columnNotes = Object.fromEntries(
        Object.entries(editColumnNotes)
          .map(([name, notes]) => {
            const original = (selected.columns || []).find((column) => column.name === name);
            const trimmed = { business_name: notes.business_name.trim(), description: notes.description.trim() };
            const changed = trimmed.business_name !== (original?.business_name || "") || trimmed.description !== (original?.description || "");
            return changed ? [name, Object.fromEntries(Object.entries(trimmed).filter(([, value]) => value))] : null;
          })
          .filter((entry): entry is [string, Record<string, string>] => entry !== null)
      );
      await api(`/datasets/${selected.id}`, {
        method: "PUT",
        body: JSON.stringify({
          description: editDescription,
          tags,
          owner: editOwner.trim() || null,
          sensitivity: editSensitivity,
          freshness_sla_hours: editFreshnessHours.trim() ? Number(editFreshnessHours) : null,
          metadata_status: editMetadataStatus,
          ...(Object.keys(columnNotes).length ? { column_notes: columnNotes } : {}),
        }),
      });
      notify?.("Dataset metadata updated", "ok");
      setEditing(false);
      load();
    } catch (error) {
      notify?.(error instanceof ApiError ? error.message : "Could not update dataset metadata", "error");
    } finally {
      setSaving(false);
    }
  };
  const [importing, setImporting] = useState(false);
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const handleImportFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setImporting(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("source_name", `Catalog import / ${file.name}`);
      const result = await api<{ tables: number; columns_processed: number; created: number; updated: number }>("/datasets/import", { method: "POST", body: form });
      notify?.(`Imported ${result.tables} table${result.tables === 1 ? "" : "s"} (${result.created} new, ${result.updated} updated) from ${file.name}`, "ok");
      load();
    } catch (error) {
      notify?.(error instanceof ApiError ? error.message : "Catalog import failed", "error");
    } finally {
      setImporting(false);
    }
  };
  const sources = Array.from(new Set(datasets.map((dataset) => dataset.source?.name || dataset.source_name))).sort();
  const categories = Array.from(new Set(datasets.map((dataset) => dataset.category))).sort();
  const filtered = datasets.filter((dataset) => {
    const sourceName = dataset.source?.name || dataset.source_name;
    const matchesText = `${dataset.schema_name}.${dataset.table_name} ${dataset.description} ${sourceName} ${dataset.category}`.toLowerCase().includes(query.toLowerCase());
    const matchesSource = sourceFilter === "all" || sourceName === sourceFilter;
    const matchesCategory = categoryFilter === "all" || dataset.category === categoryFilter;
    return matchesText && matchesSource && matchesCategory;
  });
  return (
    <div className="view-stack">
      <div className="view-header">
        <div><h2>Dataset explorer</h2><p>Browse metadata, profile signals, and business context available to agents.</p></div>
        <div className="dataset-toolbar">
          <select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)} aria-label="Filter by source"><option value="all">All sources</option>{sources.map((source) => <option key={source} value={source}>{source}</option>)}</select>
          <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)} aria-label="Filter by category"><option value="all">All categories</option>{categories.map((category) => <option key={category} value={category}>{category}</option>)}</select>
          <div className="toolbar-search"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter datasets" /></div>
          <input ref={importInputRef} type="file" accept=".csv" hidden onChange={handleImportFile} />
          <button className="secondary-button" title="Import a schema_name,table_name,column_name catalog CSV without a live connection" disabled={importing} onClick={() => importInputRef.current?.click()}><FileUp size={16} />{importing ? "Importing…" : "Import catalog CSV"}</button>
        </div>
      </div>
      <div className="dataset-layout">
        <section className="surface dataset-list">
          <div className="table-header dataset-grid"><span>Dataset</span><span>Rows</span><span>Category</span><span /></div>
          {filtered.map((dataset) => (
            <button className={`data-row dataset-grid ${selected?.id === dataset.id ? "selected" : ""}`} key={dataset.id} onClick={() => setSelectedId(dataset.id)}>
              <span className="dataset-name"><Database size={17} /><span><strong>{dataset.schema_name}.{dataset.table_name}</strong><small>{dataset.source?.name || dataset.source_name} / {connectorLabels[dataset.source?.connector_type || ""] || dataset.source?.connector_type || "registered source"}</small></span></span>
              <span className="mono">{dataset.row_count?.toLocaleString() || "-"}</span>
              <span className="tag-list"><span className="tag">{dataset.category}</span>{dataset.tags.slice(0, 2).map((tag) => <span className="tag" key={tag}>{tag}</span>)}</span>
              <ChevronRight size={16} />
            </button>
          ))}
        </section>
        <aside className="surface detail-panel">
          {selected ? (
            <>
              <div className="detail-title"><span className="dataset-icon"><Database size={21} /></span><div><span>{selected.schema_name}</span><h3>{selected.table_name}</h3></div></div>
              <p className="detail-description">{selected.description}</p>
              <div className="tag-list">{(selected.tags || []).map((tag) => <span className="tag" key={tag}>{tag}</span>)}</div>
              <div className="detail-stats"><div><span>Rows</span><strong>{selected.row_count?.toLocaleString()}</strong></div><div><span>Category</span><strong>{selected.category}</strong></div><div><span>System</span><strong>{connectorLabels[selected.source?.connector_type || ""] || selected.source?.connector_type || selected.asset_type}</strong></div></div>
              <div className="subheading"><h4>Columns</h4><span>{selected.columns.length}</span></div>
              <div className="column-list">
                {selected.columns.map((column) => (
                  <div key={column.name}><span><strong>{column.business_name || column.name}</strong><small>{column.business_name ? `${column.name} · ` : ""}{column.type}{column.description ? ` — ${column.description}` : ""}</small></span><span>{column.nullable ? "nullable" : "required"}</span></div>
                ))}
              </div>
              <button className="secondary-button wide" onClick={openEdit}><FileSpreadsheet size={17} />Review / edit metadata</button>
              <button className="secondary-button wide" onClick={() => onStartAnalysis?.(selected)}><MessageSquare size={17} />Start analysis</button>
              <button className="secondary-button wide" onClick={() => onOpenSQL(selected)}><Code2 size={17} />Open in SQL workspace</button>
            </>
          ) : datasetsQuery.isPending ? <LoadingBlock label="Loading catalog" /> : <div className="inline-empty">No datasets are catalogued in this project yet.</div>}
        </aside>
      </div>
      {editing && selected && (
        <Modal title={`Review metadata — ${selected.schema_name}.${selected.table_name}`} onClose={() => setEditing(false)}>
          <form className="modal-form" onSubmit={(event) => { event.preventDefault(); saveEdit(); }}>
            <label>Description<textarea rows={4} value={editDescription} onChange={(event) => setEditDescription(event.target.value)} placeholder="Business description for this dataset" /></label>
            <label>Tags (comma separated)<input value={editTags} onChange={(event) => setEditTags(event.target.value)} placeholder="pii, finance, verified" /></label>
            <div className="form-grid">
              <label>Owner<input value={editOwner} onChange={(event) => setEditOwner(event.target.value)} placeholder="team or person" /></label>
              <label>Sensitivity<select value={editSensitivity} onChange={(event) => setEditSensitivity(event.target.value)}>
                <option value="unclassified">Unclassified</option>
                <option value="internal">Internal</option>
                <option value="confidential">Confidential</option>
                <option value="restricted">Restricted</option>
              </select></label>
              <label>Freshness SLA (hours)<input type="number" min={1} max={8760} value={editFreshnessHours} onChange={(event) => setEditFreshnessHours(event.target.value)} placeholder="24" /></label>
              <label>Metadata status<select value={editMetadataStatus} onChange={(event) => setEditMetadataStatus(event.target.value)}>
                <option value="scanned">Scanned</option>
                <option value="reviewed">Reviewed</option>
                <option value="certified">Certified</option>
                <option value="deprecated">Deprecated</option>
              </select></label>
            </div>
            {selected.columns.length > 0 && (
              <div className="column-notes-editor">
                <label>Column business names &amp; descriptions<small>Feeds SQL-generation grounding — a business-friendly name/definition helps the model pick the right column for a plain-language question.</small></label>
                {selected.columns.map((column) => (
                  <div className="column-notes-row" key={column.name}>
                    <span className="mono">{column.name}</span>
                    <input
                      value={editColumnNotes[column.name]?.business_name || ""}
                      onChange={(event) => setEditColumnNotes((current) => ({ ...current, [column.name]: { business_name: event.target.value, description: current[column.name]?.description || "" } }))}
                      placeholder="Business name, e.g. Customer ID"
                    />
                    <input
                      value={editColumnNotes[column.name]?.description || ""}
                      onChange={(event) => setEditColumnNotes((current) => ({ ...current, [column.name]: { business_name: current[column.name]?.business_name || "", description: event.target.value } }))}
                      placeholder="What this column means"
                    />
                  </div>
                ))}
              </div>
            )}
            <div className="modal-actions">
              <button type="button" className="secondary-button" onClick={() => setEditing(false)} disabled={saving}>Cancel</button>
              <button className="primary-button" disabled={saving}>{saving ? "Saving…" : "Save metadata"}</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
