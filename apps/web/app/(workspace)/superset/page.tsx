"use client";

import dynamic from "next/dynamic";
import { LoadingBlock } from "../../components/shared";
import { useProjects } from "../../lib/queries";
import { useWorkspace } from "../../lib/workspace";

// The Superset embedded SDK is loaded only when the analytics route is opened.
const SupersetView = dynamic(() => import("../../components/SupersetView").then((module) => module.SupersetView), {
  ssr: false,
  loading: () => <LoadingBlock label="Loading analytics" />,
});

export default function SupersetPage() {
  const { user } = useWorkspace();
  const projects = useProjects().data;
  const currentProject = projects?.find((project) => project.id === user.current_project_id) || projects?.find((project) => project.is_current);
  return <SupersetView isAdmin={user.role === "admin"} projectName={currentProject?.name || user.current_project_name || "Current project"} />;
}
