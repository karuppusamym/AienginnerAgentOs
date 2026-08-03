export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

function getToken() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("datapilot_token");
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const isForm = options.body instanceof FormData;
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        ...(isForm ? {} : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
    });
  } catch {
    throw new ApiError(
      `The DataPilot API at ${API_URL} is unreachable. Start the API service and confirm NEXT_PUBLIC_API_URL.`,
      0,
    );
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(payload?.detail || `Request failed (${response.status})`, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function login(email: string, password: string) {
  const result = await api<{
    access_token: string;
    user: SessionUser;
  }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  window.localStorage.setItem("datapilot_token", result.access_token);
  return result.user;
}

export function logout() {
  window.localStorage.removeItem("datapilot_token");
}
