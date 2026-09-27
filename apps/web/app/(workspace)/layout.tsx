"use client";

import type { ReactNode } from "react";
import { QueryProvider } from "../lib/queries";
import { WorkspaceShell } from "../components/WorkspaceShell";

/**
 * Shared authenticated layout for every workspace route: TanStack Query cache,
 * session gate, sidebar, top bar, project switcher, theme toggle and toasts.
 * It stays mounted across route changes, so only the segment below re-renders.
 */
export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  return (
    <QueryProvider>
      <WorkspaceShell>{children}</WorkspaceShell>
    </QueryProvider>
  );
}
