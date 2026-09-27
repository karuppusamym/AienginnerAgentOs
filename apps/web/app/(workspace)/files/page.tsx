"use client";

import { FilesView } from "../../components/FilesView";
import { useWorkspace } from "../../lib/workspace";

export default function FilesPage() {
  const { notify, user } = useWorkspace();
  return <FilesView notify={notify} currentUser={user} />;
}
