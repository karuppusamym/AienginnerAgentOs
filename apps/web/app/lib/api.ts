export const API_URL = "/api";

export type SessionUser = {
  id: string;
  email: string;
  name: string;
  role: string;
  must_change_password?: boolean;
  current_project_id?: string | null;
  current_project_name?: string | null;
};

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

// The httpOnly `datapilot_session` cookie is the primary credential. A bearer
// token is kept in memory for the current tab only (never in localStorage) so
// requests keep working if the cookie is blocked, without persisting it.
const LEGACY_TOKEN_KEY = "datapilot_token";
let memoryToken: string | null = null;
let activeProjectId: string | null = null;
let unauthorizedHandler: (() => void) | null = null;
// Endpoints where a 401 is an expected answer (bad credentials), not an expired session.
const AUTH_EXEMPT = ["/auth/login", "/auth/logout"];

export function clearLegacyToken() {
  try { window.localStorage.removeItem(LEGACY_TOKEN_KEY); } catch { /* storage unavailable */ }
}

/** Pins every subsequent request to this project via `X-Project-Id`. */
export function setActiveProject(projectId?: string | null) {
  activeProjectId = projectId || null;
}

export function getActiveProject() {
  return activeProjectId;
}

/** Registers the single global handler for expired or missing sessions. */
export function onUnauthorized(handler: (() => void) | null) {
  unauthorizedHandler = handler;
  return () => { if (unauthorizedHandler === handler) unauthorizedHandler = null; };
}

function buildHeaders(options: RequestInit): Headers {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  // CSRF guard for cookie-authenticated writes; harmless on reads.
  headers.set("X-Requested-With", "datapilot");
  if (memoryToken && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${memoryToken}`);
  if (activeProjectId && !headers.has("X-Project-Id")) headers.set("X-Project-Id", activeProjectId);
  return headers;
}

function unreachable() {
  return new ApiError(
    `The DataPilot API at ${API_URL} is unreachable. Start the API service; the web server proxies ${API_URL} to INTERNAL_API_URL (default http://api:8000).`,
    0,
  );
}

async function errorFrom(response: Response, path: string): Promise<ApiError> {
  const payload = await response.json().catch(() => null);
  const detail = payload?.detail;
  const message = typeof detail === "string" ? detail
    : Array.isArray(detail) ? detail.map((item: { msg?: string }) => item?.msg || String(item)).join("; ")
    : detail && typeof detail === "object" && typeof detail.message === "string" ? detail.message
    : `Request failed (${response.status})`;
  if (response.status === 401 && !AUTH_EXEMPT.some((prefix) => path.startsWith(prefix))) {
    memoryToken = null;
    unauthorizedHandler?.();
  }
  return new ApiError(message, response.status);
}

/** Low-level fetch with auth, CSRF and project headers. Throws ApiError for non-2xx. */
export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...options, credentials: "same-origin", headers: buildHeaders(options) });
  } catch (reason) {
    if (reason instanceof DOMException && reason.name === "AbortError") throw reason;
    throw unreachable();
  }
  if (!response.ok) throw await errorFrom(response, path);
  return response;
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await apiFetch(path, options);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

/** Like `api`, but also returns the response headers (pagination flags). */
export async function apiWithHeaders<T>(path: string, options: RequestInit = {}): Promise<{ data: T; headers: Headers }> {
  const response = await apiFetch(path, options);
  const data = response.status === 204 ? (undefined as T) : ((await response.json()) as T);
  return { data, headers: response.headers };
}

export function isUnauthorized(reason: unknown) {
  return reason instanceof ApiError && reason.status === 401;
}

/**
 * POSTs and consumes a `text/event-stream` response with fetch (EventSource
 * cannot POST). Each complete event is passed to `onEvent`; resolves when the
 * stream ends. Abort with `options.signal`.
 */
export async function apiStream(path: string, options: RequestInit, onEvent: (event: string, data: unknown) => void): Promise<void> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "text/event-stream");
  const response = await apiFetch(path, { ...options, headers });
  if (!response.body) throw new ApiError("Streaming is not supported by this browser", 0);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const flush = (block: string) => {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (!line || line.startsWith(":")) continue;
      const index = line.indexOf(":");
      const field = index === -1 ? line : line.slice(0, index);
      const value = index === -1 ? "" : line.slice(index + 1).replace(/^ /, "");
      if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (!data.length) return;
    const raw = data.join("\n");
    let parsed: unknown = raw;
    try { parsed = JSON.parse(raw); } catch { /* plain text payload */ }
    onEvent(event, parsed);
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let match: RegExpExecArray | null;
    while ((match = /\r?\n\r?\n/.exec(buffer))) {
      flush(buffer.slice(0, match.index));
      buffer = buffer.slice(match.index + match[0].length);
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) flush(buffer);
}

export async function login(email: string, password: string) {
  const result = await api<{
    access_token: string;
    user: SessionUser;
  }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  clearLegacyToken();
  memoryToken = result.access_token || null;
  setActiveProject(result.user?.current_project_id);
  return result.user;
}

export async function logout() {
  try {
    await apiFetch("/auth/logout", { method: "POST" });
  } catch { /* the session is cleared locally either way */ }
  memoryToken = null;
  activeProjectId = null;
  clearLegacyToken();
}
