"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback } from "react";
import { LearningView, type LearningTab } from "../../components/LearningView";
import { LoadingBlock } from "../../components/shared";
import { useWorkspace } from "../../lib/workspace";

const TABS: LearningTab[] = ["verified", "optimization", "indexes", "router"];

export default function LearningPage() {
  return (
    <Suspense fallback={<LoadingBlock label="Opening learning" />}>
      <LearningRoute />
    </Suspense>
  );
}

/** Tab and selected optimization run live in the URL (?tab=…&run=…) so they survive refresh and deep links. */
function LearningRoute() {
  const { notify } = useWorkspace();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const rawTab = searchParams?.get("tab") as LearningTab | null;
  const tab: LearningTab = rawTab && TABS.includes(rawTab) ? rawTab : "verified";
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
    />
  );
}
