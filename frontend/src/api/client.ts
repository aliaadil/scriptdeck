// Kindling runs all API routes under /api/kindling. Call sites pass paths
// without the /api segment (e.g. "/auth/me"), and buildUrl() prepends
// API_BASE so the FastAPI router — mounted at /api/kindling — receives them.
export const API_BASE = "/api/kindling";

const TOKEN_KEY = "kindling_token";
const LEGACY_TOKEN_KEY = "scriptdeck_token";

/**
 * One-shot migration: copy any leftover token from the old key (set by the
 * pre-rebrand ScriptDeck build) into the new key, then delete the old one.
 * Lazy so it runs in a real browser context (where localStorage exists) and
 * not at module-import time in jsdom tests that mock the storage layer.
 */
function migrateLegacyToken(): void {
  try {
    if (localStorage.getItem(TOKEN_KEY)) return;
    const legacy = localStorage.getItem(LEGACY_TOKEN_KEY);
    if (!legacy) return;
    localStorage.setItem(TOKEN_KEY, legacy);
    localStorage.removeItem(LEGACY_TOKEN_KEY);
  } catch {
    // localStorage unavailable (SSR, jsdom stub, etc.) — silently no-op.
  }
}

export function getToken(): string | null {
  migrateLegacyToken();
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
  // Pass through fully-qualified URLs as-is (e.g. EventSource targets).
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  // Always prefix with API_BASE; call sites pass paths like "/auth/me".
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
