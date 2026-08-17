const TOKEN_KEY = "scriptdeck_token";

export const API_BASE = "/api/kindling";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

function buildUrl(path: string): string {
  // If path is absolute (starts with /) or already includes the API_BASE,
  // pass it through; otherwise prefix with API_BASE.
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  if (path.startsWith(API_BASE)) return path;
  if (path.startsWith("/")) return `${API_BASE}${path}`;
  return `${API_BASE}/${path}`;
}

export async function api<T = unknown>(
  path: string,
  opts: RequestInit = {},
): Promise<T> {
  const headers = new Headers(opts.headers ?? {});
  headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const url = buildUrl(path);
  const res = await fetch(url, { ...opts, headers });
  if (!res.ok) {
    let detail = res.statusText;
    let code = "unknown";
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
      code = body.code ?? code;
    } catch {
      // not JSON
    }
    if (res.status === 401) {
      setToken(null);
      window.location.assign("/login");
    }
    throw new ApiError(res.status, code, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
