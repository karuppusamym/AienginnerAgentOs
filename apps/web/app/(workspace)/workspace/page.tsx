"use client";

import { WorkspaceView } from "../../components/WorkspaceView";
import { useWorkspace } from "../../lib/workspace";

export default function WorkspacePage() {
  const { navigate, notify, user, setAnalysisSeed } = useWorkspace();
  return (
    <WorkspaceView
      setActive={navigate}
      notify={notify}
      // Same hand-off Datasets uses: seed a fresh Analysis conversation with the question.
      onAskInAnalysis={(question) => {
        setAnalysisSeed({ question, connector_id: "" });
        navigate("conversations", { fresh: true });
      }}
      canRunAgent={user.role === "admin" || user.role === "engineer"}
    />
  );
}
