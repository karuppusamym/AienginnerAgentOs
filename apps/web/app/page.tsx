"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, clearLegacyToken, SessionUser, setActiveProject } from "./lib/api";
import { roleLanding } from "./lib/constants";
import { legacyViewTarget, NAV_PATHS } from "./lib/routes";
import { LoadingBlock } from "./components/shared";
import { LoginScreen } from "./components/LoginScreen";

const landingPath = (role: string) => NAV_PATHS[roleLanding[role] || "workspace"];

/**
 * `/` sends a signed-in user to their role's landing route (admin → /workspace,
 * engineer → /pipelines, analyst → /analysis, viewer → /datasets) and shows the
 * sign-in screen otherwise. Old `/?view=…&c=…&m=…` links redirect to their
 * App Router route (e.g. `/analysis/<c>?m=<m>`). The workspace itself lives in
 * app/(workspace)/ with the shared shell in components/WorkspaceShell.tsx.
 */
export default function Home() {
  const router = useRouter();
  const [needsLogin, setNeedsLogin] = useState(false);

  useEffect(() => {
    const legacy = legacyViewTarget(window.location.search);
    if (legacy) {
      router.replace(legacy);
      return;
    }
    clearLegacyToken();
    let active = true;
    api<SessionUser>("/auth/me")
      .then((me) => {
        if (!active) return;
        setActiveProject(me.current_project_id);
        router.replace(landingPath(me.role));
      })
      .catch(() => { if (active) setNeedsLogin(true); });
    return () => { active = false; };
  }, [router]);

  if (!needsLogin) {
    return (
      <main className="auth-page">
        <LoadingBlock label="Opening local workspace" />
      </main>
    );
  }
  return <LoginScreen notice="" onLogin={(signedIn) => { setActiveProject(signedIn.current_project_id); router.replace(landingPath(signedIn.role)); }} />;
}
