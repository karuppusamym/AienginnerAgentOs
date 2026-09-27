"use client";

import { QualityView } from "../../components/QualityView";
import { useWorkspace } from "../../lib/workspace";

export default function QualityPage() {
  const { notify } = useWorkspace();
  return <QualityView notify={notify} />;
}
