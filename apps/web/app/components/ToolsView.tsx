import {
  Boxes,
  History,
  Network,
} from "lucide-react";
import { useState } from "react";
import { useWorkspace } from "../lib/workspace";
import { AgentsView } from "./AgentsView";
import { GatewayAdmin } from "./admin";
import { InvocationHistory } from "./InvocationHistory";


export function ToolsView({ notify }: { notify: (message: string, tone?: "ok" | "error") => void }) {
  const { user } = useWorkspace();
  const [kind, setKind] = useState<"internal" | "external" | "history">("internal");
  const isAdmin = user.role === "admin";
  return <div className="view-stack"><div className="view-header"><div><h2>Tool registry</h2><p>Create reviewed internal integrations or publish controlled customer-data tools for external agents. Every path remains versioned and routed through DataPilot.</p></div></div><div className="tabs"><button className={kind === "internal" ? "active" : ""} onClick={() => setKind("internal")}><Boxes size={16} />Internal integrations</button><button className={kind === "external" ? "active" : ""} onClick={() => setKind("external")}><Network size={16} />External data tools</button>{isAdmin && <button className={kind === "history" ? "active" : ""} onClick={() => setKind("history")}><History size={16} />Invocation history</button>}</div>{kind === "internal" ? <AgentsView notify={notify} registryOnly /> : kind === "history" && isAdmin ? <InvocationHistory notify={notify} /> : <GatewayAdmin notify={notify} />}</div>;
}
