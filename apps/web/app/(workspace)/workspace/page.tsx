"use client";

import { WorkspaceView } from "../../components/WorkspaceView";
import { useWorkspace } from "../../lib/workspace";

export default function WorkspacePage() {
  const { navigate, notify } = useWorkspace();
  return <WorkspaceView setActive={navigate} notify={notify} />;
}
