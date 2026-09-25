import { useSupersetStatus } from "../lib/queries";
import dynamic from "next/dynamic";
import {
  Archive,
  BookOpen,
  ChevronRight,
  Code2,
  Database,
  LayoutDashboard,
  MessageSquare,
  Network,
  Play,
  Plus,
  RefreshCw,
  Sparkles,
  XCircle,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type {
  NotebookCellData,
  Notebook,
} from "../types";
import { StatusPill, EmptyState, Modal, useConfirm } from "./shared";
import { SaveAsMenu } from "./SaveAsMenu";

// "Save as…" acts on the notebook's last non-empty SQL cell, the same cell Superset publication uses.
const lastSqlCell = (notebook: Notebook | null) => [...(notebook?.cells || [])].reverse().find((cell) => cell.type === "sql" && cell.source.trim())?.source.trim() || "";

// The Superset embedded SDK is only needed once a published dashboard is opened.
const PublishedQueryAnalyticsModal = dynamic(() => import("./PublishedQueryAnalyticsModal").then((module) => module.PublishedQueryAnalyticsModal), { ssr: false });


export function NotebooksView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [confirm, confirmDialog] = useConfirm();
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const superset = useSupersetStatus();
  const supersetDown = superset.data !== undefined && !superset.data.available;
  const [selected, setSelected] = useState<Notebook | null>(null);
  const [busy, setBusy] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [analyticsStatus, setAnalyticsStatus] = useState<{ published: boolean; dashboard_title?: string } | null>(null);
  const [analyticsOpen, setAnalyticsOpen] = useState(false);
  const [savingAs, setSavingAs] = useState(false);
  const [saveAsDialog, setSaveAsDialog] = useState<"verified" | "tool" | null>(null);
  const [saveAsName, setSaveAsName] = useState("");
  const load = useCallback(() => api<Notebook[]>("/notebooks").then((data) => { setNotebooks(data); setSelected((current) => data.find((item) => item.id === current?.id) || data[0] || null); }), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!selected) { setAnalyticsStatus(null); return; }
    api<{ published: boolean; dashboard_title?: string }>(`/analytics/queries/${selected.id}`)
      .then(setAnalyticsStatus)
      .catch(() => setAnalyticsStatus(null));
  }, [selected?.id]);
  async function createNotebook() {
    setBusy(true);
    try {
      const result = await api<Notebook>("/notebooks", { method: "POST", body: JSON.stringify({ name: `Analysis ${new Date().toLocaleDateString()}`, cells: [{ id: "notes", type: "markdown", source: "# Analysis" }, { id: "query", type: "sql", source: "SELECT 1 AS value" }, { id: "calculation", type: "python", source: "row_count = len(last_rows)\nrow_count" }] }) });
      await load();
      setSelected(result);
      notify("Notebook created");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Notebook could not be created", "error");
    } finally {
      setBusy(false);
    }
  }
  function updateCell(id: string, source: string) { setSelected((current) => current ? { ...current, cells: current.cells.map((cell) => cell.id === id ? { ...cell, source } : cell) } : current); }
  function addCell(type: NotebookCellData["type"]) { setSelected((current) => current ? { ...current, cells: [...current.cells, { id: `cell-${Date.now()}`, type, source: type === "sql" ? "SELECT 1 AS value" : type === "python" ? "sum([1, 2, 3])" : "## Notes" }] } : current); }
  async function save(runAfter = false) {
    if (!selected) return;
    setBusy(true);
    try {
      const saved = await api<{ id: string }>("/notebooks", { method: "POST", body: JSON.stringify({ notebook_id: selected.id, name: selected.name, cells: selected.cells }) });
      if (runAfter) {
        const result = await api<{ status: string; outputs: Notebook["outputs"]; job_id: string }>(`/notebooks/${saved.id}/run`, { method: "POST" });
        notify(`Notebook ${result.status}; trace ${result.job_id.slice(0, 8)}`);
      } else notify("Notebook version saved");
      await load();
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Notebook operation failed", "error"); } finally { setBusy(false); }
  }
  async function remove() {
    if (!selected || !(await confirm({ title: "Delete notebook", body: `Delete notebook "${selected.name}" and its version history?` }))) return;
    try { await api(`/notebooks/${selected.id}`, { method: "DELETE" }); await load(); notify("Notebook deleted"); }
    catch (reason) { notify(reason instanceof Error ? reason.message : "Notebook could not be deleted", "error"); }
  }
  async function requestSupersetPublication() {
    if (!selected) return;
    setPublishing(true);
    try {
      // Save first so the approval always points at an immutable notebook
      // version, rather than the user's unsaved editor text.
      const saved = await api<{ id: string }>("/notebooks", { method: "POST", body: JSON.stringify({ notebook_id: selected.id, name: selected.name, cells: selected.cells }) });
      const request = await api<{ approval_id: string; status: string }>("/analytics/publish-sql", { method: "POST", body: JSON.stringify({ notebook_id: saved.id, name: selected.name }) });
      await load();
      notify(request.status === "auto_approved" ? "Notebook SQL published to Superset: auto-approved by policy" : `Notebook SQL publication is awaiting approval (${request.approval_id.slice(0, 8)}); "Open in Superset" appears here once an admin approves it`);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Superset publication could not be requested", "error"); }
    finally { setPublishing(false); }
  }
  async function saveSqlArtifact() {
    const sql = lastSqlCell(selected);
    if (!selected || !sql) { notify("Add a SQL cell first", "error"); return; }
    setSavingAs(true);
    try {
      const artifact = await api<{ version: number }>("/artifacts", { method: "POST", body: JSON.stringify({ name: `${selected.name} (SQL)`.slice(0, 120), artifact_type: "sql", content: sql, metadata: { dialect: "postgres", question: selected.name, connector_id: null, notebook_id: selected.id } }) });
      notify(`Notebook SQL saved as artifact version ${artifact.version}`);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Artifact could not be saved", "error"); }
    finally { setSavingAs(false); }
  }
  async function submitSaveAs(event: FormEvent) {
    event.preventDefault();
    const sql = lastSqlCell(selected);
    if (!selected || !sql || !saveAsDialog) return;
    setSavingAs(true);
    try {
      if (saveAsDialog === "verified") {
        await api("/verified-queries", { method: "POST", body: JSON.stringify({ question: saveAsName, sql, dialect: "postgres", connector_id: null }) });
        notify("Saved as a verified query — future matching questions can reuse it");
      } else {
        await api("/query-tools", { method: "POST", body: JSON.stringify({
          name: ("tool_" + saveAsName.toLowerCase().replace(/[^a-z0-9_.-]+/g, "_")).slice(0, 120),
          description: `Published from notebook ${selected.name}`,
          purpose: saveAsName,
          data_source: "DataPilot workspace",
          line_of_business: "general",
          owner: "notebook",
          sql_template: sql,
          parameter_schema: { type: "object", properties: {}, additionalProperties: false },
          requires_approval: true,
        }) });
        notify("Tool publication requested and sent to Approvals");
      }
      setSaveAsDialog(null);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Could not save", "error"); }
    finally { setSavingAs(false); }
  }
  const hasSql = Boolean(lastSqlCell(selected));
  return <div className="view-stack"><div className="view-header"><div><h2>Governed notebooks</h2><p>Versioned SQL, notes, safe calculations, outputs, and review history.</p></div><button className="primary-button" onClick={createNotebook} disabled={busy}>{busy ? <RefreshCw size={17} className="spin" /> : <Plus size={17} />}New notebook</button></div><div className="notebook-layout"><section className="surface notebook-list">{notebooks.map((notebook) => <button key={notebook.id} className={selected?.id === notebook.id ? "selected" : ""} onClick={() => setSelected(notebook)}><BookOpen size={17} /><span><strong>{notebook.name}</strong><small>v{notebook.version} / {notebook.status}</small></span><ChevronRight size={16} /></button>)}</section><section className="surface notebook-editor">{selected ? <><div className="section-heading compact"><div><span className="eyebrow">NOTEBOOK</span><input className="notebook-name" value={selected.name} onChange={(event) => setSelected({ ...selected, name: event.target.value })} aria-label="Notebook name" />{selected.job_id && <small className="notebook-run-link">Last run trace: <code>{selected.job_id}</code></small>}</div><div className="row-actions"><button className="icon-button" title="Delete notebook" onClick={remove} disabled={busy}><XCircle size={16} /></button><button className="secondary-button" onClick={() => save(false)} disabled={busy}><Archive size={16} />Save</button>{analyticsStatus?.published && <button className="secondary-button" onClick={() => setAnalyticsOpen(true)}><LayoutDashboard size={16} />Open in Superset</button>}<SaveAsMenu items={[
        { key: "artifact", label: "Save as artifact", icon: <Archive size={15} />, onSelect: saveSqlArtifact, busy: savingAs && !saveAsDialog, disabled: busy || !hasSql, title: hasSql ? "Saves the last SQL cell as a versioned SQL artifact" : "Add a SQL cell first" },
        { key: "verified", label: "Save as verified query", icon: <Sparkles size={15} />, onSelect: () => { setSaveAsName(selected.name); setSaveAsDialog("verified"); }, disabled: busy || !hasSql, title: "Future matching questions reuse the last SQL cell" },
        { key: "tool", label: "Publish as query tool", icon: <Network size={15} />, onSelect: () => { setSaveAsName(selected.name.slice(0, 50)); setSaveAsDialog("tool"); }, disabled: busy || !hasSql, title: "Publishes the last SQL cell as an API tool after approval" },
        { key: "superset", label: "Publish to Superset", icon: <LayoutDashboard size={15} />, onSelect: requestSupersetPublication, busy: publishing, hidden: Boolean(analyticsStatus?.published), disabled: busy || supersetDown || !hasSql, title: supersetDown ? `Superset unavailable: ${superset.data?.reason}` : "Requests admin approval before this notebook's SQL cell becomes a Superset dashboard" },
      ]} />{saveAsDialog && <Modal title={saveAsDialog === "verified" ? "Save as verified query" : "Publish as query tool"} onClose={() => setSaveAsDialog(null)}><form className="modal-form" onSubmit={submitSaveAs}><label>{saveAsDialog === "verified" ? "Business question this SQL answers" : "Tool name"}<input value={saveAsName} onChange={(event) => setSaveAsName(event.target.value)} required minLength={3} /></label><p className="caption">Uses the notebook's last SQL cell.</p><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setSaveAsDialog(null)} disabled={savingAs}>Cancel</button><button className="primary-button" disabled={savingAs}>{savingAs ? "Saving…" : saveAsDialog === "verified" ? "Save" : "Request approval"}</button></div></form></Modal>}<button className="primary-button" onClick={() => save(true)} disabled={busy}>{busy ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}Run all</button></div></div><div className="notebook-toolbar"><button onClick={() => addCell("sql")}><Database size={15} />SQL</button><button onClick={() => addCell("python")}><Code2 size={15} />Python</button><button onClick={() => addCell("markdown")}><MessageSquare size={15} />Notes</button></div><div className="notebook-cells">{selected.cells.map((cell, index) => <div className="notebook-cell" key={cell.id}><div><span>{index + 1}</span><StatusPill value={cell.type} /></div><textarea value={cell.source} onChange={(event) => updateCell(cell.id, event.target.value)} rows={cell.type === "markdown" ? 3 : 5} aria-label={`${cell.type} cell ${index + 1}`} />{selected.outputs.find((output) => output.cell_id === cell.id) && <pre>{JSON.stringify(selected.outputs.find((output) => output.cell_id === cell.id), null, 2)}</pre>}</div>)}</div>{analyticsOpen && selected && <PublishedQueryAnalyticsModal artifactId={selected.id} title={analyticsStatus?.dashboard_title || "Notebook query analytics"} onClose={() => setAnalyticsOpen(false)} />}</> : <EmptyState icon={<BookOpen size={24} />} title="No notebook selected" body="Create a notebook to begin a governed local analysis." />}</section></div>{confirmDialog}</div>;
}
