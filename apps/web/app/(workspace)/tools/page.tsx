"use client";

import { RouteRedirect } from "../../components/RouteRedirect";
import { NAV_REDIRECTS } from "../../lib/routes";

/** The tool registry is a tab of Agents & tools; old /tools links land on it. */
export default function ToolsPage() {
  return <RouteRedirect to={NAV_REDIRECTS.tools || "/agents?tab=tools"} label="Opening Agents & tools" />;
}
