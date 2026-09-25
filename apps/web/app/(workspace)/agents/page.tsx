"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback } from "react";
import { AgentsView, agentsTabsFor, type AgentsTab } from "../../components/AgentsView";
import { LoadingBlock } from "../../components/shared";
import { useWorkspace } from "../../lib/workspace";

export default function AgentsPage() {
  return (
    <Suspense fallback={<LoadingBlock label="Opening agents and tools" />}>
      <AgentsRoute />
    </Suspense>
  );
}

// Older links used the Tool registry's tab names.
const TAB_ALIASES: Record<string, AgentsTab> = { internal: "tools", external: "gateway", invocations: "history" };

/** Agents & tools: the tab lives in the URL (?tab=agents|tools|gateway|history); /tools redirects to ?tab=tools. */
function AgentsRoute() {
  const { notify, user } = useWorkspace();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = searchParams?.get("tab") || "";
  const requested = (TAB_ALIASES[raw] || raw) as AgentsTab;
  const allowed = agentsTabsFor(user.role, user.hidden_screens || []);
  const tab: AgentsTab = allowed.includes(requested) ? requested : "agents";
  const onTab = useCallback((next: AgentsTab) => {
    const params = new URLSearchParams(searchParams?.toString() || "");
    params.set("tab", next);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }, [pathname, router, searchParams]);
  return <AgentsView notify={notify} tab={tab} onTab={onTab} role={user.role} hiddenScreens={user.hidden_screens || []} />;
}
