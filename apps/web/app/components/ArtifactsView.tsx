import {
  Archive,
  Check,
  GitCompare,
  MessageSquare,
  Search,
  Send,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type {
  Artifact,
  ArtifactVersion,
  ArtifactComment,
} from "../types";
import { scopes, useDebouncedValue, useInvalidate, usePagedQuery, usePagination, useQueryErrorToast } from "../lib/queries";
import { StatusPill, LoadingBlock, EmptyState, Pagination } from "./shared";

const NO_ARTIFACTS: Artifact[] = [];

export function ArtifactsView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [versions, setVersions] = useState<ArtifactVersion[]>([]);
  const [comments, setComments] = useState<ArtifactComment[]>([]);
  const [comment, setComment] = useState("");
  const [diff, setDiff] = useState("");
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search.trim());
  const pagination = usePagination(q, 50);
  const artifactsQuery = usePagedQuery<Artifact>(scopes.artifacts, "/artifacts", { q }, pagination, { staleTime: 0 });
  useQueryErrorToast(artifactsQuery.error, notify, "Artifacts could not be loaded");
  const artifacts = artifactsQuery.data?.items ?? NO_ARTIFACTS;
  const [picked, setPicked] = useState<Artifact | null>(null);
  const selected = selectedId ? artifacts.find((item) => item.id === selectedId) || (picked?.id === selectedId ? picked : null) : artifacts[0] || null;
  const setSelected = (artifact: Artifact) => { setPicked(artifact); setSelectedId(artifact.id); };
  const invalidate = useInvalidate();

  const selectedKey = selected?.id;
  useEffect(() => {
    if (!selectedKey) {
      setVersions([]);
      return;
    }
    Promise.all([api<ArtifactVersion[]>(`/artifacts/${selectedKey}/versions`), api<ArtifactComment[]>(`/artifacts/${selectedKey}/comments`)]).then(([versionData, commentData]) => { setVersions(versionData); setComments(commentData); setDiff(""); });
  }, [selectedKey]);

  async function comparePrevious() {
    if (!selected || versions.length < 2) return;
    const result = await api<{ diff: string }>(`/artifacts/${selected.id}/diff?from_version=${versions[1].version}&to_version=${versions[0].version}`);
    setDiff(result.diff || "No content changes");
  }
  async function addComment() {
    if (!selected || !comment.trim()) return;
    await api(`/artifacts/${selected.id}/comments`, { method: "POST", body: JSON.stringify({ body: comment, version: versions[0]?.version }) });
    setComment("");
    setComments(await api<ArtifactComment[]>(`/artifacts/${selected.id}/comments`));
    notify("Review comment added");
  }
  async function review(decision: "approved" | "changes_requested") {
    if (!selected) return;
    await api(`/artifacts/${selected.id}/review`, { method: "POST", body: JSON.stringify({ decision }) });
    setPicked({ ...selected, status: decision });
    await invalidate(scopes.artifacts);
    notify(`Artifact ${decision.replaceAll("_", " ")}`);
  }

  return (
    <div className="view-stack">
      <div className="view-header"><div><h2>Artifact repository</h2><p>Versioned SQL, workflows, quality rules, prompts, and runbooks produced in the workspace.</p></div><div className="row-actions"><div className="toolbar-search"><Search size={16} /><input placeholder="Search artifacts..." value={search} onChange={(e) => setSearch(e.target.value)} /></div><StatusPill value={`${artifactsQuery.data?.total ?? 0} artifacts`} /></div></div>
      {!artifacts.length ? <section className="surface">{artifactsQuery.isPending ? <LoadingBlock label="Loading artifacts" /> : q ? <EmptyState icon={<Search size={26} />} title="No matching artifacts" body="Try a different name or type." /> : <EmptyState icon={<Archive size={26} />} title="No saved artifacts" body="Save an approved SQL draft or workflow to create its first durable version." />}</section> : (
        <div className="artifact-layout">
          <section className="surface artifact-list">
            <div className="table-header artifact-grid"><span>Artifact</span><span>Type</span><span>Version</span><span>Updated</span></div>
            {artifacts.map((artifact) => <button key={artifact.id} className={`data-row artifact-grid ${selected?.id === artifact.id ? "selected" : ""}`} onClick={() => setSelected(artifact)}><span><strong>{artifact.name}</strong><small>{artifact.status}</small></span><StatusPill value={artifact.artifact_type} /><span className="mono">v{artifact.latest_version}</span><span>{new Date(artifact.updated_at).toLocaleString()}</span></button>)}
            <Pagination state={pagination} total={artifactsQuery.data?.total ?? 0} count={artifacts.length} busy={artifactsQuery.isFetching} label="artifacts" />
          </section>
          <aside className="surface artifact-detail">
            {selected && versions[0] ? <><div className="section-heading compact"><div><span className="eyebrow">LATEST VERSION</span><h3>{selected.name}</h3></div><StatusPill value={selected.status} /></div><pre><code>{diff || versions[0].content}</code></pre><div className="artifact-review-actions"><button className="secondary-button" disabled={versions.length < 2} onClick={comparePrevious}><GitCompare size={16} />Compare previous</button><button className="secondary-button" onClick={() => review("changes_requested")}><MessageSquare size={16} />Request changes</button><button className="primary-button" onClick={() => review("approved")}><Check size={16} />Approve</button></div><div className="subheading"><h4>Version history</h4><span>{versions.length}</span></div><div className="version-list">{versions.map((version) => <div key={version.id}><span className="version-number">v{version.version}</span><span><strong>{String(version.artifact_metadata.dialect || selected.artifact_type)}</strong><small>{new Date(version.created_at).toLocaleString()}</small></span></div>)}</div><div className="subheading"><h4>Review comments</h4><span>{comments.length}</span></div><div className="comment-composer"><input value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Add review comment" /><button className="icon-button" onClick={addComment} disabled={!comment.trim()} title="Add comment"><Send size={16} /></button></div><div className="comment-list">{comments.map((item) => <div key={item.id}><MessageSquare size={14} /><span><strong>{item.author}</strong><small>{item.body} / {new Date(item.created_at).toLocaleString()}</small></span></div>)}</div></> : <LoadingBlock label="Loading artifact" />}
          </aside>
        </div>
      )}
    </div>
  );
}
