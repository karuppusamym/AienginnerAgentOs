"use client";

/**
 * TanStack Query layer over `lib/api.ts`.
 *
 * - Every key starts with ["project", <active project id>], so switching project
 *   can never render another project's cached data.
 * - Query functions pass TanStack's AbortSignal through to fetch.
 * - 401s are handled by the global `onUnauthorized` handler inside `api()`;
 *   4xx responses are never retried.
 */
import {
  keepPreviousData,
  QueryClient,
  QueryClientProvider,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type QueryKey,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { ReactNode, useCallback, useEffect, useState } from "react";
import { api, ApiError, apiWithHeaders, isUnauthorized } from "./api";
import { useWorkspace, type Notify } from "./workspace";
import type {
  Approval,
  Connector,
  Conversation,
  ConversationMessage,
  Dataset,
  DdlSuggestion,
  EvaluationSet,
  Incident,
  IndexRecommendation,
  Job,
  ModelProvider,
  ModelRouting,
  ModelUsage,
  Project,
  PromptOptimization,
  PromptOptimizationDetail,
  RouterDecisionRecord,
  SchemaDrift,
  VerifiedQuery,
} from "../types";

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
          return failureCount < 2;
        },
      },
      mutations: { retry: false },
    },
  });
}

export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(createQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** Query-key scopes (appended to ["project", projectId]). */
export const scopes = {
  projects: ["projects"],
  conversations: ["conversations"],
  messages: (conversationId: string) => ["messages", conversationId],
  connectors: ["connectors"],
  schemaDrift: ["schema-drift"],
  modelProviders: ["model-providers"],
  modelRouting: ["model-routing"],
  modelUsage: ["model-usage"],
  jobs: ["jobs"],
  incidents: ["incidents"],
  approvals: ["approvals"],
  datasets: ["datasets"],
  evaluations: ["evaluations"],
  verifiedQueries: ["verified-queries"],
  promptOptimizations: ["prompt-optimizations"],
  indexRecommendations: ["index-recommendations"],
  ddlSuggestions: ["ddl-suggestions"],
  routerDecisions: ["router-decisions"],
  analyticsStatus: ["analytics-status"],
  artifacts: ["artifacts"],
  pipelines: ["pipelines"],
  qualityRules: ["quality-rules"],
  files: ["files"],
  queryTools: ["query-tools"],
  externalInvocations: ["external-invocations"],
  audit: ["audit"],
  users: ["users"],
} as const;

export type Scope = readonly unknown[];

export function projectKey(projectId: string, ...scope: Scope): QueryKey {
  return ["project", projectId, ...scope];
}

type ProjectQueryOptions<T> = Omit<UseQueryOptions<T, Error, T, QueryKey>, "queryKey" | "queryFn" | "enabled"> & { enabled?: boolean };

/** `useQuery` bound to the active project; `path === null` disables the query. */
export function useProjectQuery<T>(scope: Scope, path: string | null, options: ProjectQueryOptions<T> = {}) {
  const { projectId } = useWorkspace();
  const { enabled = true, ...rest } = options;
  return useQuery<T, Error, T, QueryKey>({
    queryKey: projectKey(projectId, ...scope),
    queryFn: ({ signal }) => api<T>(path as string, { signal }),
    enabled: path !== null && enabled,
    ...rest,
  });
}

/** Superset reachability (it only runs with the Compose "analytics" profile); rechecked every 30s. */
export function useSupersetStatus() {
  return useProjectQuery<{ available: boolean; reason: string; public_url?: string }>(scopes.analyticsStatus, "/analytics/status", { staleTime: 15_000, refetchInterval: 30_000 });
}

/** Returns `invalidate(scopeA, scopeB, …)` for the active project; resolves after refetches settle. */
export function useInvalidate() {
  const client = useQueryClient();
  const { projectId } = useWorkspace();
  return useCallback(
    async (...targets: Scope[]) => {
      await Promise.all(targets.map((scope) => client.invalidateQueries({ queryKey: projectKey(projectId, ...scope) })));
    },
    [client, projectId],
  );
}

/** `useMutation` that invalidates the given scopes after success (awaited by `mutateAsync`). */
export function useApiMutation<TVars = void, TResult = unknown>(mutationFn: (vars: TVars) => Promise<TResult>, invalidates: Scope[] = []) {
  const invalidate = useInvalidate();
  return useMutation<TResult, Error, TVars>({
    mutationFn,
    onSuccess: () => invalidate(...invalidates),
  });
}

/** The endpoint does not exist on this API build (feature being rolled out). */
export function isEndpointUnavailable(error: unknown) {
  return error instanceof ApiError && (error.status === 404 || error.status === 405);
}

/** Toasts a query error once per distinct error; skips aborts, 401s and (optionally) 404s. */
export function useQueryErrorToast(error: unknown, notify: Notify | undefined, fallback: string, options: { ignoreUnavailable?: boolean } = {}) {
  const { ignoreUnavailable = false } = options;
  useEffect(() => {
    if (!error || !notify) return;
    if (error instanceof DOMException && error.name === "AbortError") return;
    if (isUnauthorized(error)) return;
    if (ignoreUnavailable && isEndpointUnavailable(error)) return;
    notify(error instanceof Error ? error.message : fallback, "error");
  }, [error, notify, fallback, ignoreUnavailable]);
}

// ---------------------------------------------------------------- paged lists

export type PageParams = Record<string, string | number | boolean | null | undefined>;
/** One page of a list endpoint: `X-Total-Count` / `X-Has-More` from the API (see app/pagination.py). */
export type Paged<T> = { items: T[]; total: number; hasMore: boolean };
export type Facet = { value: string; count: number };
export const PAGE_SIZES = [25, 50, 100, 200];

/** Appends non-empty params to a path (`false`, "", null and undefined are dropped). */
export function withParams(path: string, params: PageParams = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "" || value === false) continue;
    search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `${path}${path.includes("?") ? "&" : "?"}${query}` : path;
}

/** `value` after it has been stable for `delay` ms (search boxes that drive server-side filters). */
export function useDebouncedValue<T>(value: T, delay = 300) {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

/** Offset/limit state that returns to the first page whenever `resetKey` (filters, search) changes. */
export function usePagination(resetKey: unknown = null, initialLimit = 50) {
  const [limit, setLimitState] = useState(initialLimit);
  const [offset, setOffset] = useState(0);
  const key = JSON.stringify(resetKey ?? null);
  const [seenKey, setSeenKey] = useState(key);
  if (seenKey !== key) {
    setSeenKey(key);
    setOffset(0);
  }
  const setLimit = useCallback((value: number) => { setLimitState(value); setOffset(0); }, []);
  return { offset: seenKey === key ? offset : 0, limit, setOffset, setLimit };
}
export type PaginationState = ReturnType<typeof usePagination>;

type PagedQueryOptions<T> = Omit<UseQueryOptions<Paged<T>, Error, Paged<T>, QueryKey>, "queryKey" | "queryFn" | "enabled" | "placeholderData"> & { enabled?: boolean };

/**
 * One server-side page of `path` with `params` as filters. Keys extend `scope`, so
 * invalidating the scope refreshes every page; the previous page stays on screen while the next loads.
 */
export function usePagedQuery<T>(scope: Scope, path: string | null, params: PageParams, page: { offset: number; limit: number }, options: PagedQueryOptions<T> = {}) {
  const { projectId } = useWorkspace();
  const { enabled = true, ...rest } = options;
  return useQuery<Paged<T>, Error, Paged<T>, QueryKey>({
    queryKey: projectKey(projectId, ...scope, "page", params, page.offset, page.limit),
    queryFn: async ({ signal }) => {
      const { data, headers } = await apiWithHeaders<T[]>(withParams(path as string, { ...params, limit: page.limit, offset: page.offset }), { signal });
      const total = Number(headers.get("X-Total-Count"));
      return {
        items: data,
        total: headers.has("X-Total-Count") && Number.isFinite(total) ? total : page.offset + data.length,
        hasMore: headers.get("X-Has-More") === "true",
      };
    },
    enabled: path !== null && enabled,
    placeholderData: keepPreviousData,
    ...rest,
  });
}

/** Group counts for grouped list views (`/datasets/facets`, `/jobs/facets`, `/query-tools/facets`). */
export function useFacets<T>(scope: Scope, path: string | null, params: PageParams = {}, options: ProjectQueryOptions<T> = {}) {
  return useProjectQuery<T>([...scope, "facets", params], path === null ? null : withParams(path, params), { placeholderData: keepPreviousData, ...options });
}

// ---------------------------------------------------------------- workspace

export const useProjects = (enabled = true) => useProjectQuery<Project[]>(scopes.projects, "/projects", { enabled });
export const useModelProviders = () => useProjectQuery<ModelProvider[]>(scopes.modelProviders, "/model-providers");
export const useModelRouting = () => useProjectQuery<ModelRouting>(scopes.modelRouting, "/model-routing");
export const useModelUsage = () => useProjectQuery<ModelUsage>(scopes.modelUsage, "/model-usage");
export const useConnectors = () => useProjectQuery<Connector[]>(scopes.connectors, "/connectors");
export const useSchemaDrift = () => useProjectQuery<SchemaDrift[]>(scopes.schemaDrift, "/schema-drift");
export const useDatasets = () => useProjectQuery<Dataset[]>(scopes.datasets, "/datasets");
export const useEvaluationSets = () => useProjectQuery<EvaluationSet[]>(scopes.evaluations, "/evaluations");

/** All approvals, or only one status (e.g. the sidebar's pending count). */
export function useApprovals(status?: "pending") {
  return useProjectQuery<Approval[]>(status ? [...scopes.approvals, { status }] : scopes.approvals, status ? `/approvals?status=${status}` : "/approvals");
}

// ---------------------------------------------------------------- jobs

export const ACTIVE_JOB_STATES = ["RUNNING", "QUEUED", "PLANNING", "RETRYING"];
export const hasActiveJob = (jobs: Job[] | undefined) => !!jobs?.some((job) => ACTIVE_JOB_STATES.includes(job.status));

/**
 * Jobs poll every 2 s only while at least one job is active. TanStack pauses the
 * interval while the tab is hidden (refetchIntervalInBackground is false).
 */
export function useJobs() {
  return useProjectQuery<Job[]>(scopes.jobs, "/jobs", {
    staleTime: 0,
    refetchInterval: (query) => (hasActiveJob(query.state.data) ? 2000 : false),
    refetchOnWindowFocus: (query) => hasActiveJob(query.state.data),
  });
}

export function useIncidents(poll: boolean) {
  return useProjectQuery<Incident[]>(scopes.incidents, "/incidents", {
    refetchInterval: poll ? 2000 : false,
    refetchOnWindowFocus: poll,
  });
}

// ---------------------------------------------------------------- conversations

export const MESSAGE_PAGE_SIZE = 100;
export type MessagePage = { items: ConversationMessage[]; hasMore: boolean };
export type MessagePages = InfiniteData<MessagePage, string>;

export const useConversations = () => useProjectQuery<Conversation[]>(scopes.conversations, "/conversations");

/**
 * Messages of one thread, newest page first. `fetchNextPage()` loads the page
 * before the oldest loaded message (`?before=<id>`, `X-Has-More` header).
 */
export function useConversationMessages(conversationId: string) {
  const { projectId } = useWorkspace();
  return useInfiniteQuery<MessagePage, Error, MessagePages, QueryKey, string>({
    queryKey: projectKey(projectId, ...scopes.messages(conversationId)),
    enabled: !!conversationId,
    initialPageParam: "",
    queryFn: async ({ pageParam, signal }) => {
      const before = pageParam ? `&before=${encodeURIComponent(pageParam)}` : "";
      const { data, headers } = await apiWithHeaders<ConversationMessage[]>(`/conversations/${conversationId}/messages?limit=${MESSAGE_PAGE_SIZE}${before}`, { signal });
      return { items: data, hasMore: headers.get("X-Has-More") === "true" && data.length > 0 };
    },
    getNextPageParam: (last) => (last.hasMore ? last.items.find((item) => !item.id.startsWith("pending-"))?.id : undefined),
  });
}

// ---------------------------------------------------------------- learning & quality

const OPTIMIZATION_ACTIVE = ["queued", "running"];
export const optimizationIsActive = (status?: string) => !!status && OPTIMIZATION_ACTIVE.includes(status);

export const useVerifiedQueries = () => useProjectQuery<VerifiedQuery[]>(scopes.verifiedQueries, "/verified-queries");
/**
 * Index (DDL) suggestions from the query workload. By default only queries slower than the
 * server's threshold count; `minMs = 0` includes candidates from every query.
 */
export const useIndexRecommendations = (minMs: number | null = null) => useProjectQuery<IndexRecommendation[]>(
  [...scopes.indexRecommendations, minMs ?? "slow"],
  minMs == null ? "/sql/index-recommendations" : `/sql/index-recommendations?min_ms=${encodeURIComponent(String(minMs))}`,
);
/** DDL saved for DBA review (never executed by DataPilot). */
export const useDdlSuggestions = () => useProjectQuery<DdlSuggestion[]>(scopes.ddlSuggestions, "/sql/ddl-suggestions");
export const useRouterDecisions = (limit = 100) => useProjectQuery<RouterDecisionRecord[]>([...scopes.routerDecisions, limit], `/router/decisions?limit=${limit}`);

/** Optimization runs; polls every 3 s while any run is queued or running. */
export function usePromptOptimizations() {
  return useProjectQuery<PromptOptimization[]>(scopes.promptOptimizations, "/prompt-optimizations", {
    refetchInterval: (query) => (query.state.data?.some((run) => optimizationIsActive(run.status)) ? 3000 : false),
  });
}

/** One run with candidates, cases and log; polls while it is queued or running. */
export function usePromptOptimization(id: string | null) {
  return useProjectQuery<PromptOptimizationDetail>([...scopes.promptOptimizations, id], id ? `/prompt-optimizations/${id}` : null, {
    refetchInterval: (query) => (optimizationIsActive(query.state.data?.status) ? 2500 : false),
  });
}
