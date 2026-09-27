"use client";

import { NotebooksView } from "../../components/NotebooksView";
import { useWorkspace } from "../../lib/workspace";

export default function NotebooksPage() {
  const { notify } = useWorkspace();
  return <NotebooksView notify={notify} />;
}
