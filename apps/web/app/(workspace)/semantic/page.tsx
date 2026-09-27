"use client";

import { SemanticView } from "../../components/SemanticView";
import { useWorkspace } from "../../lib/workspace";

export default function SemanticPage() {
  const { notify } = useWorkspace();
  return <SemanticView notify={notify} />;
}
