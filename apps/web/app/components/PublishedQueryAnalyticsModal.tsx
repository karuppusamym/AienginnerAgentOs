import { AlertCircle, RefreshCw } from "lucide-react";
import { embedDashboard, EmbeddedDashboard } from "@superset-ui/embedded-sdk";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { Modal } from "./shared";

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
