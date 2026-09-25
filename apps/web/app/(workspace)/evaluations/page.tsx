"use client";

import { RouteRedirect } from "../../components/RouteRedirect";
import { NAV_REDIRECTS } from "../../lib/routes";

/** Evaluations is a tab of Learning; old /evaluations links land on it. */
export default function EvaluationsPage() {
  return <RouteRedirect to={NAV_REDIRECTS.evaluations || "/learning?tab=evaluations"} label="Opening evaluations" />;
}
