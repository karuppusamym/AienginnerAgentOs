"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback } from "react";
import { LearningView, learningTabsFor, type LearningTab } from "../../components/LearningView";
import { LoadingBlock } from "../../components/shared";
import { useWorkspace } from "../../lib/workspace";

export default function LearningPage() {
  return (
    <Suspense fallback={<LoadingBlock label="Opening learning" />}>
      <LearningRoute />
    </Suspense>
  );
}

/**
 * Tab and selected optimization run live in the URL (?tab=…&run=…) so they survive refresh and deep links.
 * /evaluations redirects to ?tab=evaluations. Tabs are limited per role (learningTabsFor).
 */
function LearningRoute() {
  const { notify, user } = useWorkspace();
  const allowed = learningTabsFor(user.role, user.hidden_screens || []);
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const rawTab = searchParams?.get("tab") as LearningTab | null;
  const tab: LearningTab = rawTab && allowed.includes(rawTab) ? rawTab : allowed[0];
  const runId = searchParams?.get("run") || "";
  const update = useCallback((next: { tab?: LearningTab; run?: string }) => {
    const params = new URLSearchParams(searchParams?.toString() || "");
    if (next.tab) params.set("tab", next.tab);
    if (next.run !== undefined) { if (next.run) params.set("run", next.run); else params.delete("run"); }
    if (next.tab && next.tab !== "optimization") params.delete("run");
    const query = params.toString();
    router.replace(`${pathname}${query ? `?${query}` : ""}`, { scroll: false });
  }, [pathname, router, searchParams]);
  return (
    <LearningView
      notify={notify}
      tab={tab}
      onTab={(value) => update({ tab: value })}
      runId={runId}
      onRun={(value) => update({ tab: "optimization", run: value })}
      role={user.role}
    />
  );
}
