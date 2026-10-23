const TOKEN_KEY = "dataclaw.token";

export class ApiError extends Error {
  code: string;
  status: number;
  detail?: unknown;
  constructor(message: string, code = "UNKNOWN", status = 0, detail?: unknown) {
    super(message);
    this.code = code;
    this.status = status;
    this.detail = detail;
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path.startsWith("http") ? path : `/api${path}`, { ...init, headers });
  if (res.status === 401 && !path.includes("/auth/login")) {
    clearToken();
    if (!location.pathname.startsWith("/login")) location.href = "/login";
    throw new ApiError("登录已过期，请重新登录", "UNAUTHORIZED", 401);
  }
  const text = await res.text();
  let data: any = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const err = data?.error || {};
    throw new ApiError(err.message || `请求失败（${res.status}）`, err.code || `HTTP_${res.status}`, res.status, err.detail);
  }
  return data as T;
}

function qs(params?: Record<string, unknown>): string {
  if (!params) return "";
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const api = {
  get: <T>(path: string, params?: Record<string, unknown>) => request<T>(`${path}${qs(params)}`),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body === undefined ? undefined : JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: <T>(path: string, file: File | FormData) => {
    const fd = file instanceof FormData ? file : new FormData();
    if (!(file instanceof FormData)) fd.append("file", file);
    return request<T>(path, { method: "POST", body: fd });
  },
};

export type StreamHandlers = {
  onEvent: (event: string, data: any) => void;
  onError?: (err: Error) => void;
  onClose?: () => void;
};

/** POST + SSE（浏览器 EventSource 不支持 POST，因此手写解析） */
export function streamChat(path: string, body: unknown, handlers: StreamHandlers): { abort: () => void } {
  const controller = new AbortController();
  const token = getToken();
  (async () => {
    try {
      const res = await fetch(`/api${path}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        let message = `请求失败（${res.status}）`;
        try {
          const j = await res.json();
          message = j?.error?.message || message;
        } catch {}
        throw new Error(message);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) >= 0) {
          const raw = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          parseEvent(raw, handlers);
        }
      }
      if (buffer.trim()) parseEvent(buffer, handlers);
      handlers.onClose?.();
    } catch (e: any) {
      if (e?.name !== "AbortError") handlers.onError?.(e instanceof Error ? e : new Error(String(e)));
      handlers.onClose?.();
    }
  })();
  return { abort: () => controller.abort() };
}

function parseEvent(raw: string, handlers: StreamHandlers) {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return;
  const payload = dataLines.join("\n");
  try {
    handlers.onEvent(event, JSON.parse(payload));
  } catch {
    handlers.onEvent(event, payload);
  }
}

export const artifactDownloadUrl = (id: string) => `/api/artifacts/${id}/download`;
export const fileDownloadUrl = (id: string) => `/api/files/${id}/download`;

export async function downloadWithAuth(url: string, filename?: string) {
  const token = getToken();
  const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new Error("下载失败");
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename || "download";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
