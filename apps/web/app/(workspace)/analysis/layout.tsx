"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { ReactNode, Suspense, useCallback, useEffect, useRef } from "react";
import { ConversationsView } from "../../components/ConversationsView";
import { LoadingBlock } from "../../components/shared";
import { analysisPath } from "../../lib/routes";
import { useWorkspace } from "../../lib/workspace";

/**
 * /analysis and /analysis/[conversationId]?m=<messageId> share this layout, so the
 * three-panel view stays mounted while the thread or inspected answer changes
 * (an in-flight streamed answer is not aborted by the URL update).
 */
export default function AnalysisLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<LoadingBlock label="Opening analysis" />}>
      <AnalysisRoute />
      {children}
    </Suspense>
  );
}

function AnalysisRoute() {
  const params = useParams<{ conversationId?: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { notify, user, analysisSeed, setAnalysisSeed } = useWorkspace();
  const conversationId = typeof params?.conversationId === "string" ? safeDecode(params.conversationId) : "";
  const messageId = searchParams?.get("m") || "";
  const clearSeed = useCallback(() => setAnalysisSeed(null), [setAnalysisSeed]);
  // router.push/replace commit asynchronously, so compare against the last URL we
  // asked for (until the router catches up) rather than window.location alone.
  const currentUrl = analysisPath(conversationId, messageId);
  const requestedRef = useRef<string | null>(null);
  const inFlightRef = useRef(new Set<string>());
  const lastUrlRef = useRef(currentUrl);
  useEffect(() => {
    if (lastUrlRef.current === currentUrl) return;
    lastUrlRef.current = currentUrl;
    if (inFlightRef.current.has(currentUrl)) {
      inFlightRef.current.delete(currentUrl);
      if (requestedRef.current === currentUrl) requestedRef.current = null;
    } else {
      // Back/forward or a link: nothing we requested is authoritative any more.
      inFlightRef.current.clear();
      requestedRef.current = null;
    }
  }, [currentUrl]);
  const onRouteChange = useCallback((c: string, m: string, push: boolean) => {
    const target = analysisPath(c, m);
    const current = requestedRef.current ?? `${window.location.pathname}${window.location.search}`;
    if (current === target) return;
    requestedRef.current = target;
    inFlightRef.current.add(target);
    if (push) router.push(target, { scroll: false }); else router.replace(target, { scroll: false });
  }, [router]);
  return (
    <ConversationsView
      notify={notify}
      currentUser={user}
      seed={analysisSeed}
      onSeedConsumed={clearSeed}
      routeConversationId={conversationId}
      routeMessageId={messageId}
      onRouteChange={onRouteChange}
    />
  );
}

function safeDecode(value: string) {
  try { return decodeURIComponent(value); } catch { return value; }
}
