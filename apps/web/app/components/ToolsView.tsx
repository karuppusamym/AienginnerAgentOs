import {
  Boxes,
  Network,
} from "lucide-react";
import { useState } from "react";
import { AgentsView } from "./AgentsView";
import { GatewayAdmin } from "./admin";


export function ToolsView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const [kind, setKind] = useState<"internal" | "external">("internal");
  return <div className="view-stack"><div className="view-header"><div><h2>Tool registry</h2><p>Create reviewed internal integrations or publish controlled customer-data tools for external agents. Every path remains versioned and routed through DataPilot.</p></div></div><div className="tabs"><button className={kind === "internal" ? "active" : ""} onClick={() => setKind("internal")}><Boxes size={16} />Internal integrations</button><button className={kind === "external" ? "active" : ""} onClick={() => setKind("external")}><Network size={16} />External data tools</button></div>{kind === "internal" ? <AgentsView notify={notify} registryOnly /> : <GatewayAdmin notify={notify} />}</div>;
}
