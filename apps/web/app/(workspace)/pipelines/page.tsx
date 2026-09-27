"use client";

import { PipelinesView } from "../../components/PipelinesView";
import { useWorkspace } from "../../lib/workspace";

export default function PipelinesPage() {
  const { notify } = useWorkspace();
  return <PipelinesView notify={notify} />;
}
