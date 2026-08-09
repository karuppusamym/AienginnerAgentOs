import {
  Activity,
  AlertCircle,
  Archive,
  Bot,
  BookOpen,
  Boxes,
  Braces,
  Check,
  ChevronDown,
  ChevronRight,
  CircleGauge,
  Clock3,
  CalendarClock,
  Code2,
  Database,
  FileSpreadsheet,
  FileUp,
  FlaskConical,
  Gauge,
  GitBranch,
  GitCompare,
  KeyRound,
  Layers3,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  Network,
  PanelLeftClose,
  Play,
  Plus,
  RefreshCw,
  Search,
  Send,
  Server,
  Settings,
  ShieldCheck,
  Sparkles,
  UserPlus,
  Users,
  X,
  XCircle,
} from "lucide-react";
import { embedDashboard, EmbeddedDashboard } from "@superset-ui/embedded-sdk";
import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { statusTone } from "../lib/constants";
import type {
  NavKey,
  Overview,
  Recommendation,
  SecurityCategoryKey,
  SecurityOverview,
  Dataset,
  Connector,
  ModelProvider,
  Project,
  AgentVersion,
  AgentDefinition,
  ToolVersion,
  ToolDefinition,
  SemanticMetric,
  SemanticJoinPolicy,
  PipelineDefinition,
  Incident,
  Job,
  Approval,
  IngestedFile,
  MappingColumn,
  LoadMode,
  IngestionMapping,
  QualityRun,
  QualityRule,
  SQLResult,
  SQLExecutionResult,
  SearchResult,
  Artifact,
  ArtifactVersion,
  IngestionSchedule,
  MappingOption,
  ArtifactComment,
  EvaluationSet,
  NotebookCellData,
  Notebook,
  Conversation,
  ConversationMessage,
  ExternalClient,
  QueryTool,
  QueryToolDraft,
  RelationOption,
  QueryToolUsage,
  QueryToolRegistrySummary,
  PromptArtifact,
  RetentionPolicy,
  SchemaDrift,
  ModelUsage,
} from "../types";

export function StatusPill({ value }: { value: string }) {
  return <span className={`status-pill ${statusTone(value)}`}>{value.replaceAll("_", " ")}</span>;
}

export function LoadingBlock({ label = "Loading workspace" }: { label?: string }) {
  return (
    <div className="loading-block">
      <RefreshCw size={18} className="spin" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon: ReactNode;
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{body}</p>
      {action}
    </div>
  );
}

export function AnalysisChart({ chart }: { chart?: ConversationMessage["structured"]["chart"] }) {
  if (!chart?.data?.length || !chart.x || !chart.y) return <div className="chart-empty">No chartable result</div>;
  const values = chart.data.map((row) => Number(row[chart.y!] || 0));
  const maximum = Math.max(...values.map((value) => Math.abs(value)), 1);
  return <div className="result-chart"><h4>{chart.title}</h4>{chart.data.slice(0, 12).map((row, index) => <div className="chart-row" key={`${String(row[chart.x!])}-${index}`}><span title={String(row[chart.x!])}>{String(row[chart.x!])}</span><i><b style={{ width: `${Math.max(2, Math.abs(Number(row[chart.y!] || 0)) / maximum * 100)}%` }} /></i><strong>{String(row[chart.y!])}</strong></div>)}</div>;
}

export function Metric({ label, value, detail, icon, tone }: { label: string; value: ReactNode; detail: string; icon: ReactNode; tone: string }) {
  return (
    <div className="metric">
      <span className={`metric-icon ${tone}`}>{icon}</span>
      <div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
    </div>
  );
}

export function ControlItem({ icon, label, value, status }: { icon: ReactNode; label: string; value: string; status: string }) {
  return (
    <div className="control-item">
      <span className="control-icon">{icon}</span>
      <span><small>{label}</small><strong>{value}</strong></span>
      <StatusPill value={status} />
    </div>
  );
}

export function SecurityOverviewPanel({
  data,
  onOpenIncidents,
}: {
  data: SecurityOverview | null;
  onOpenIncidents: () => void;
}) {
  const categoryStyles: Record<SecurityCategoryKey, { label: string; tone: string }> = {
    prompt_injection: { label: "Prompt Injection", tone: "amber" },
    pii_exposure: { label: "PII Exposure", tone: "blue" },
    toxic_content: { label: "Toxic Content", tone: "rose" },
  };
  const maxBucketTotal = useMemo(
    () => Math.max(...(data?.event_series.map((bucket) => Object.values(bucket.counts).reduce((sum, count) => sum + count, 0)) || [1]), 1),
    [data],
  );

  if (!data) {
    return (
      <section className="surface security-overview">
        <div className="section-heading">
          <div>
            <span className="eyebrow">GUARDRAILS</span>
            <h3>Security Overview</h3>
            <p>Real-time summary of security posture and key risk indicators across your AI applications.</p>
          </div>
          <StatusPill value="loading" />
        </div>
        <div className="security-loading">
          <LoadingBlock label="Loading security posture" />
        </div>
      </section>
    );
  }

  const delta = data.overview.score_delta_pp;
  const deltaPrefix = delta > 0 ? "+" : "";
  const deltaTone = delta > 0 ? "positive" : delta < 0 ? "negative" : "neutral";
  const totalIncidentCount = data.incidents_by_severity.reduce((sum, item) => sum + item.count, 0);

  return (
    <section className="surface security-overview">
      <div className="section-heading">
        <div>
          <span className="eyebrow">GUARDRAILS</span>
          <h3>Security Overview</h3>
          <p>Real-time summary of security posture and key risk indicators across your AI applications.</p>
        </div>
        <div className="security-range">
          <strong>{data.period.key}</strong>
          <span>{data.period.label}</span>
        </div>
      </div>

      <div className="security-summary-grid">
        <article className="security-score-card">
          <span className="security-card-label">Overall Security Score</span>
          <strong>{data.overview.overall_security_score}%</strong>
          <div className="security-score-meta">
            <StatusPill value={data.overview.posture} />
            <small className={`security-delta ${deltaTone}`}>{deltaPrefix}{delta}pp vs last period</small>
          </div>
        </article>
        <article className="security-stat-card">
          <span>Total Security Events</span>
          <strong>{data.overview.total_security_events}</strong>
          <small>{data.overview.total_security_events ? "Needs review" : "No events detected"}</small>
        </article>
        <article className="security-stat-card">
          <span>Blocked Requests</span>
          <strong>{data.overview.blocked_requests}</strong>
          <small>{data.overview.blocked_requests ? "Guardrails intervened" : "No blocked requests"}</small>
        </article>
        <article className="security-stat-card">
          <span>Critical Incidents</span>
          <strong>{data.overview.critical_incidents}</strong>
          <small>{data.overview.critical_incidents ? "Immediate action needed" : "No critical incidents"}</small>
        </article>
      </div>

      <div className="security-layout">
        <div className="security-main">
          <section className="security-panel">
            <div className="security-panel-head">
              <div>
                <h4>Security Events Over Time</h4>
                <p>{data.period.label}</p>
              </div>
              <div className="security-legend">
                {Object.entries(categoryStyles).map(([key, item]) => (
                  <span key={key}><i className={`security-tone ${item.tone}`} />{item.label}</span>
                ))}
              </div>
            </div>
            <div className="security-chart">
              {data.event_series.map((bucket) => {
                const bucketTotal = Object.values(bucket.counts).reduce((sum, count) => sum + count, 0);
                return (
                  <div className="security-chart-group" key={`${bucket.label}-${bucket.start_at}`}>
                    <div className="security-chart-stack" title={`${bucket.label}: ${bucketTotal} events`}>
                      {(Object.keys(categoryStyles) as SecurityCategoryKey[]).map((key) => {
                        const count = bucket.counts[key];
                        const height = count ? `${Math.max(12, (count / maxBucketTotal) * 100)}%` : "0%";
                        return <i key={key} className={`security-segment ${categoryStyles[key].tone}`} style={{ height }} />;
                      })}
                      {!bucketTotal && <b className="security-chart-empty-line" />}
                    </div>
                    <span>{bucket.label}</span>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="security-panel">
            <div className="security-panel-head">
              <div>
                <h4>Top Security Risks</h4>
                <p>{data.overview.total_security_events} total</p>
              </div>
              <button className="text-button" onClick={onOpenIncidents}>View incidents <ChevronRight size={16} /></button>
            </div>
            <div className="security-risk-list">
              {data.top_security_risks.map((risk) => (
                <div className="security-risk-row" key={risk.key}>
                  <div>
                    <strong>{risk.category}</strong>
                    <small>{risk.count} events</small>
                  </div>
                  <div className="security-risk-meter">
                    <span style={{ width: `${risk.share_percent}%` }} className={categoryStyles[risk.key].tone} />
                  </div>
                  <strong>{risk.share_percent}%</strong>
                </div>
              ))}
            </div>
          </section>
        </div>

        <div className="security-side">
          <section className="security-panel">
            <div className="security-panel-head">
              <div>
                <h4>Security Events by Category</h4>
              </div>
            </div>
            <div className="security-category-list">
              {data.events_by_category.map((item) => (
                <div className="security-category-row" key={item.key}>
                  <span><i className={`security-tone ${categoryStyles[item.key].tone}`} />{item.category}</span>
                  <strong>{item.count}</strong>
                </div>
              ))}
            </div>
          </section>

          <section className="security-panel">
            <div className="security-panel-head">
              <div>
                <h4>Incidents by Severity</h4>
              </div>
            </div>
            {totalIncidentCount ? (
              <div className="security-severity-list">
                {data.incidents_by_severity.map((item) => (
                  <div className="security-severity-row" key={item.severity}>
                    <span>{item.severity}</span>
                    <strong>{item.count}</strong>
                  </div>
                ))}
              </div>
            ) : (
              <div className="security-empty">No guardrail incidents in this range</div>
            )}
          </section>

          <section className="security-panel">
            <div className="security-panel-head">
              <div>
                <h4>Recent Security Incidents</h4>
              </div>
              <button className="text-button" onClick={onOpenIncidents}>View all <ChevronRight size={16} /></button>
            </div>
            {data.recent_incidents.length ? (
              <div className="security-incident-list">
                {data.recent_incidents.map((incident) => (
                  <button className="security-incident-row" key={incident.id} onClick={onOpenIncidents}>
                    <span className="security-incident-icon"><AlertCircle size={16} /></span>
                    <span>
                      <strong>{incident.title}</strong>
                      <small>{incident.category} / {new Date(incident.created_at).toLocaleString()}</small>
                    </span>
                    <StatusPill value={incident.severity} />
                  </button>
                ))}
              </div>
            ) : (
              <div className="security-empty">No guardrail incidents in this range</div>
            )}
          </section>
        </div>
      </div>
    </section>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><div className="modal" role="dialog" aria-modal="true" aria-label={title}><div className="modal-header"><h3>{title}</h3><button className="icon-button" onClick={onClose} aria-label="Close"><X size={19} /></button></div>{children}</div></div>;
}

/**
 * Hotlink target for a saved SQL artifact or notebook cell once it has an
 * approved, dedicated Superset dashboard (see SupersetQueryDashboard /
 * POST|GET /analytics/queries/{artifact_id}). This is deliberately a
 * *separate* dashboard identity from the project's primary SupersetView —
 * publishing one query must never replace what the project dashboard shows.
 */
export function PublishedQueryAnalyticsModal({ artifactId, title, onClose }: { artifactId: string; title: string; onClose: () => void }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const dashboardRef = useRef<EmbeddedDashboard | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    async function mount() {
      if (!mountRef.current) return;
      try {
        const initial = await api<{ token: string; embedded_id: string; superset_domain: string }>(`/analytics/queries/${artifactId}/guest-token`, { method: "POST" });
        const embedded = await embedDashboard({
          id: initial.embedded_id,
          supersetDomain: initial.superset_domain,
          mountPoint: mountRef.current,
          fetchGuestToken: async () => (await api<{ token: string }>(`/analytics/queries/${artifactId}/guest-token`, { method: "POST" })).token,
          dashboardUiConfig: {
            hideTitle: false,
            hideTab: true,
            hideChartControls: false,
            filters: { visible: true, expanded: false },
            urlParams: { standalone: 2 },
          },
          iframeTitle: "DataPilot governed query analytics",
          referrerPolicy: "strict-origin-when-cross-origin",
        });
        if (!active) {
          embedded.unmount();
          return;
        }
        dashboardRef.current = embedded;
        setState("ready");
      } catch (reason) {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "This published query's analytics dashboard could not be loaded");
        setState("error");
      }
    }
    mount();
    return () => {
      active = false;
      dashboardRef.current?.unmount();
      dashboardRef.current = null;
    };
  }, [artifactId]);

  return (
    <Modal title={title} onClose={onClose}>
      <section className="surface analytics-embed-shell">
        {state === "loading" && <div className="analytics-overlay"><RefreshCw size={20} className="spin" /><strong>Connecting analytics</strong></div>}
        {state === "error" && <div className="analytics-overlay error"><AlertCircle size={22} /><strong>Analytics unavailable</strong><span>{error}</span></div>}
        <div ref={mountRef} className="analytics-mount" />
      </section>
    </Modal>
  );
}
