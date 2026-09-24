"use client";

import { AdminView } from "../../components/admin";
import { useWorkspace } from "../../lib/workspace";

export default function AdminPage() {
  const { user, notify, navigate } = useWorkspace();
  return <AdminView currentUser={user} notify={notify} setActive={navigate} />;
}
