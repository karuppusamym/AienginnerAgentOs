"use client";

import { AgentsView } from "../../components/AgentsView";
import { useWorkspace } from "../../lib/workspace";

export default function AgentsPage() {
  const { notify } = useWorkspace();
  return <AgentsView notify={notify} />;
}
