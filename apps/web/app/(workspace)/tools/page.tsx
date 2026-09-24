"use client";

import { ToolsView } from "../../components/ToolsView";
import { useWorkspace } from "../../lib/workspace";

export default function ToolsPage() {
  const { notify } = useWorkspace();
  return <ToolsView notify={notify} />;
}
