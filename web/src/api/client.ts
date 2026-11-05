// Thin fetch wrapper: JWT in localStorage, one transparent refresh on 401,
// and errors carrying the backend's stable `code` for translation.

export class ApiError extends Error {
  constructor(public status: number, public code: string, public data: Record<string, unknown> = {}, detail = "") {
    super(detail || code);
  }
}

const ACCESS = "oc.access";
const REFRESH = "oc.refresh";

export const tokens = {
  get access() { return safeGet(ACCESS); },
  get refresh() { return safeGet(REFRESH); },
  set(access: string, refresh?: string) {
    safeSet(ACCESS, access);
    if (refresh) safeSet(REFRESH, refresh);
  },
  clear() { safeSet(ACCESS, null); safeSet(REFRESH, null); },
};

function safeGet(k: string): string | null {
  try { return localStorage.getItem(k); } catch { return null; }
}
function safeSet(k: string, v: string | null) {
  try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch { /* storage unavailable */ }
}

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn; }

let refreshing: Promise<boolean> | null = null;
async function tryRefresh(): Promise<boolean> {
  const refresh = tokens.refresh;
  if (!refresh) return false;
  refreshing ??= (async () => {
    try {
      const r = await fetch("/api/auth/refresh/", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh }),
      });
      if (!r.ok) return false;
      const d = await r.json();
      tokens.set(d.access, d.refresh);
      return true;
    } catch { return false; } finally { setTimeout(() => { refreshing = null; }, 0); }
  })();
  return refreshing;
}

type Body = Record<string, unknown> | unknown[] | FormData | undefined;

export async function api<T = unknown>(method: string, path: string, body?: Body, retry = true): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (tokens.access) headers.Authorization = `Bearer ${tokens.access}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { payload = JSON.stringify(body); headers["Content-Type"] = "application/json"; }

  let res: Response;
  try {
    res = await fetch(`/api/${path.replace(/^\//, "")}`, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "network_error");
  }
  if (res.status === 401 && retry && !path.startsWith("auth/login")) {
    if (await tryRefresh()) return api<T>(method, path, body, false);
    tokens.clear();
    onUnauthorized();
  }
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    const d = (data ?? {}) as { code?: string; detail?: string; data?: Record<string, unknown> };
    throw new ApiError(res.status, d.code || `http_${res.status}`, d.data || {}, d.detail);
  }
  return data as T;
}

function safeJson(t: string) { try { return JSON.parse(t); } catch { return { detail: t }; } }

/** Authenticated file download (e.g. Excel export): fetches as a blob and saves it with the server's filename. */
export async function download(path: string, fallbackName: string): Promise<void> {
  const call = () => fetch(`/api/${path.replace(/^\//, "")}`, { headers: tokens.access ? { Authorization: `Bearer ${tokens.access}` } : {} });
  let res = await call();
  if (res.status === 401 && (await tryRefresh())) res = await call();
  if (!res.ok) throw new ApiError(res.status, `http_${res.status}`);
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "")?.[1] || fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const get = <T,>(path: string) => api<T>("GET", path);
export const post = <T,>(path: string, body?: Body) => api<T>("POST", path, body);
export const patch = <T,>(path: string, body?: Body) => api<T>("PATCH", path, body);
export const put = <T,>(path: string, body?: Body) => api<T>("PUT", path, body);

export function qs(params: Record<string, string | number | boolean | undefined | null>) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export interface Page<T> { count: number; next: string | null; previous: string | null; results: T[] }
