"use client";

import { ArtifactsView } from "../../components/ArtifactsView";
import { useWorkspace } from "../../lib/workspace";

export default function ArtifactsPage() {
  const { notify } = useWorkspace();
  return <ArtifactsView notify={notify} />;
}
