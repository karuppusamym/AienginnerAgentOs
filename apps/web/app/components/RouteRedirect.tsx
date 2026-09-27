"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { LoadingBlock } from "./shared";

/**
 * Client-side redirect for routes whose page was merged into another screen
 * (docs/UX_CONSOLIDATION.md). Extra query parameters on the old link are kept,
 * so `/tools?x=1` becomes `/agents?tab=tools&x=1`.
 */
export function RouteRedirect({ to, label }: { to: string; label: string }) {
  const router = useRouter();
  useEffect(() => {
    const [path, query = ""] = to.split("?");
    const params = new URLSearchParams(query);
    new URLSearchParams(window.location.search).forEach((value, key) => { if (!params.has(key)) params.set(key, value); });
    const search = params.toString();
    router.replace(`${path}${search ? `?${search}` : ""}`);
  }, [router, to]);
  return <LoadingBlock label={label} />;
}
