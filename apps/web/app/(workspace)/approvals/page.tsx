"use client";

import { ApprovalsView } from "../../components/ApprovalsView";
import { useWorkspace } from "../../lib/workspace";

export default function ApprovalsPage() {
  const { notify } = useWorkspace();
  return <ApprovalsView notify={notify} />;
}
