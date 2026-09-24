"use client";

import { EvaluationsView } from "../../components/EvaluationsView";
import { useWorkspace } from "../../lib/workspace";

export default function EvaluationsPage() {
  const { notify } = useWorkspace();
  return <EvaluationsView notify={notify} />;
}
