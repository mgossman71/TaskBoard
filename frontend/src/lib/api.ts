/**
 * HTTP client for the ForgeBoard API.
 *
 * - Access token lives only in memory; it is attached as a Bearer header.
 * - The refresh token is an HttpOnly cookie; refreshing sends the double-submit
 *   CSRF header read from the `fb_csrf` cookie.
 * - Refreshes are single-flight within a tab and serialized across tabs with the
 *   Web Locks API, so concurrent refreshes never present an already-rotated
 *   token (which the server treats as token theft).
 */
import type { TokenResponse } from "./types";

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
  get isConflict() {
    return this.status === 409 && this.code === "version_conflict";
  }
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    if (Array.isArray(this.details)) {
      for (const d of this.details as { loc: string[]; msg: string }[]) {
        const field = d.loc?.[d.loc.length - 1];
        if (field && !out[field]) out[field] = d.msg;
      }
    }
    return out;
  }
}

type Listener = (token: string | null) => void;

const BASE = "/api/v1";
let accessToken: string | null = null;
let accessExpiresAt = 0;
let refreshPromise: Promise<TokenResponse | null> | null = null;
let refreshTimer: ReturnType<typeof setTimeout> | undefined;
const listeners = new Set<Listener>();
let onSessionExpired: (() => void) | null = null;

export function getAccessToken() {
  return accessToken;
}

export function onTokenChange(fn: Listener) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function setSessionExpiredHandler(fn: (() => void) | null) {
  onSessionExpired = fn;
}

export function setTokens(resp: TokenResponse | null) {
  accessToken = resp?.access_token ?? null;
  accessExpiresAt = resp ? new Date(resp.expires_at).getTime() : 0;
  clearTimeout(refreshTimer);
  if (resp) {
    // Proactively refresh one minute before expiry.
    const delay = Math.max(5_000, accessExpiresAt - Date.now() - 60_000);
    refreshTimer = setTimeout(() => {
      void refreshSession().catch(() => undefined);
    }, delay);
  }
  listeners.forEach((l) => l(accessToken));
}

function readCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp("(?:^|; )" + name.replace(/[.$?*|{}()[\]\\/+^]/g, "\\$&") + "=([^;]*)"));
  return m ? decodeURIComponent(m[1]) : null;
}

async function parseError(res: Response): Promise<ApiError> {
  let body: any = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error */
  }
  const err = body?.error;
  if (err) return new ApiError(res.status, err.code, err.message, err.details);
  if (res.status === 429) return new ApiError(429, "rate_limited", "Too many requests. Please slow down.");
  if (res.status >= 500) return new ApiError(res.status, "server_error", "The server encountered an error. Please try again.");
  return new ApiError(res.status, "http_error", res.statusText || "Request failed");
}

async function doRefresh(): Promise<TokenResponse | null> {
  const csrf = readCookie("fb_csrf");
  if (!csrf) return null;
  const res = await fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf },
  });
  if (!res.ok) {
    if (res.status === 401 || res.status === 403) return null;
    throw await parseError(res);
  }
  return (await res.json()) as TokenResponse;
}

/** Refresh the session (single-flight; cross-tab serialized). Resolves null if logged out. */
export function refreshSession(): Promise<TokenResponse | null> {
  if (!refreshPromise) {
    const run = async () => {
      const locks = (navigator as any).locks;
      const resp = locks?.request ? await locks.request("forgeboard-refresh", doRefresh) : await doRefresh();
      setTokens(resp);
      return resp as TokenResponse | null;
    };
    refreshPromise = run().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | string[] | undefined | null>;
  signal?: AbortSignal;
  raw?: boolean;
  auth?: boolean;
}

function buildUrl(path: string, query?: RequestOptions["query"]) {
  const url = new URL(BASE + path, window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === "" || v === false) continue;
      if (Array.isArray(v)) v.forEach((x) => url.searchParams.append(k, x));
      else url.searchParams.set(k, String(v));
    }
  }
  return url.pathname + url.search;
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, signal, raw, auth = true } = opts;
  const send = async () => {
    const headers: Record<string, string> = {};
    if (auth && accessToken) headers.Authorization = `Bearer ${accessToken}`;
    let payload: BodyInit | undefined;
    if (body instanceof FormData) payload = body;
    else if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    return fetch(buildUrl(path, query), { method, headers, body: payload, signal, credentials: "same-origin" });
  };
  let res: Response;
  try {
    res = await send();
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network_error", "Network error — check your connection and try again.");
  }
  if (res.status === 401 && auth) {
    const refreshed = await refreshSession().catch(() => null);
    if (refreshed) res = await send();
    else {
      onSessionExpired?.();
      throw await parseError(res);
    }
  }
  if (!res.ok) throw await parseError(res);
  if (raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T,>(path: string, query?: RequestOptions["query"], signal?: AbortSignal) => request<T>(path, { query, signal }),
  post: <T,>(path: string, body?: unknown) => request<T>(path, { method: "POST", body }),
  patch: <T,>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
  put: <T,>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body }),
  del: <T = void,>(path: string, query?: RequestOptions["query"]) => request<T>(path, { method: "DELETE", query }),
};

/** Unauthenticated / cookie endpoints used by the auth flows. */
export async function logoutRequest() {
  const csrf = readCookie("fb_csrf") ?? "";
  await fetch(`${BASE}/auth/logout`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf, ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}) },
  }).catch(() => undefined);
  setTokens(null);
}

export async function downloadAttachment(id: string, filename: string) {
  const res = await request<Response>(`/attachments/${id}/download`, { raw: true });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
