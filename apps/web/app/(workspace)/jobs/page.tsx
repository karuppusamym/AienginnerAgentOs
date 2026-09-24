"use client";

import { JobsView } from "../../components/JobsView";
import { useWorkspace } from "../../lib/workspace";

export default function JobsPage() {
  const { notify } = useWorkspace();
  return <JobsView notify={notify} />;
}
