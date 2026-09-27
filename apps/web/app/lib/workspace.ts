"use client";

import { createContext, useContext } from "react";
import type { SessionUser } from "./api";
import type { NavKey } from "../types";

export type Notify = (message: string, tone?: "ok" | "error") => void;
export type AnalysisSeed = { question: string; connector_id: string };
export type SqlSeed = { question: string; dialect: string };
export type NavigateOptions = {
  /** Replace the current history entry instead of pushing a new one. */
  replace?: boolean;
  /** Analysis only: open a fresh thread even when Analysis is already showing. */
  fresh?: boolean;
};

/** Shared state of the authenticated workspace shell, available to every route segment. */
export type WorkspaceContextValue = {
  user: SessionUser;
  /** Active project id; part of every TanStack Query key so a project switch never shows stale data. */
  projectId: string;
  notify: Notify;
  navigate: (view: NavKey, options?: NavigateOptions) => void;
  analysisSeed: AnalysisSeed | null;
  setAnalysisSeed: (seed: AnalysisSeed | null) => void;
  sqlSeed: SqlSeed | null;
  setSqlSeed: (seed: SqlSeed | null) => void;
};

export const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function useWorkspace(): WorkspaceContextValue {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace must be used inside the workspace layout");
  return value;
}
