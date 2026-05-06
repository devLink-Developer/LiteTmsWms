import { beginGlobalLoading, isGlobalLoadingSuppressed } from "../stores/useGlobalLoadingStore";

export type ApiResult<T> = {
  results?: T[];
  modules?: string[];
  principles?: string[];
  error?: {
    code: string;
    message: string;
    details: Record<string, unknown>;
    correlation_id: string;
  };
};

export function apiUrl(path: string) {
  return `${import.meta.env.VITE_API_BASE_URL ?? ""}${path}`;
}

function loadingLabelForRequest(init?: RequestInit) {
  const method = String(init?.method || "GET").toUpperCase();
  return method === "GET" || method === "HEAD" ? "Cargando datos..." : "Procesando accion...";
}

export type RequestTrackingOptions = {
  globalLoading?: boolean;
  label?: string;
};

function trackingOptions(options?: string | RequestTrackingOptions): RequestTrackingOptions {
  if (typeof options === "string") return { label: options };
  return options ?? {};
}

export async function trackedFetch(path: string, init?: RequestInit, options?: string | RequestTrackingOptions): Promise<Response> {
  const tracking = trackingOptions(options);
  if (tracking.globalLoading === false || isGlobalLoadingSuppressed()) {
    return fetch(apiUrl(path), init);
  }
  const finish = beginGlobalLoading(tracking.label || loadingLabelForRequest(init));
  try {
    return await fetch(apiUrl(path), init);
  } finally {
    finish();
  }
}

export class ApiError extends Error {
  status: number;
  data: unknown;
  code: string;
  details: Record<string, unknown>;

  constructor(message: string, status: number, data: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
    const error = typeof data === "object" && data && "error" in data ? data.error : null;
    this.code = typeof error === "object" && error && "code" in error && typeof error.code === "string" ? error.code : "";
    this.details =
      typeof error === "object" && error && "details" in error && typeof error.details === "object" && error.details
        ? (error.details as Record<string, unknown>)
        : {};
  }
}

function getCookie(name: string): string {
  if (typeof document === "undefined") {
    return "";
  }

  try {
    const cookie = document.cookie
      .split(";")
      .map((value) => value.trim())
      .find((value) => value.startsWith(`${name}=`));

    return cookie ? decodeURIComponent(cookie.split("=").slice(1).join("=")) : "";
  } catch {
    return "";
  }
}

function setHeader(headers: Record<string, string>, name: string, value: string) {
  const existingKey = Object.keys(headers).find((key) => key.toLowerCase() === name.toLowerCase());
  headers[existingKey || name] = value;
}

function hasHeader(headers: Record<string, string>, name: string): boolean {
  return Object.keys(headers).some((key) => key.toLowerCase() === name.toLowerCase());
}

function buildHeaders(init?: HeadersInit): Record<string, string> {
  const headers: Record<string, string> = {};
  if (Array.isArray(init)) {
    init.forEach(([key, value]) => setHeader(headers, key, value));
  } else if (init && typeof (init as Headers).forEach === "function") {
    (init as Headers).forEach((value, key) => setHeader(headers, key, value));
  } else if (init) {
    Object.entries(init).forEach(([key, value]) => setHeader(headers, key, value));
  }

  if (!hasHeader(headers, "Accept")) {
    setHeader(headers, "Accept", "application/json");
  }

  const csrfToken = getCookie("csrftoken");
  if (csrfToken && !hasHeader(headers, "X-CSRFToken")) {
    setHeader(headers, "X-CSRFToken", csrfToken);
  }

  return headers;
}

export function apiHeaders(init?: HeadersInit): Record<string, string> {
  const headers = buildHeaders(init);
  Object.entries(actorHeaders()).forEach(([key, value]) => setHeader(headers, key, value));
  return headers;
}

function buildActorHeaders(): Record<string, string> {
  const headers = buildHeaders();
  Object.entries(actorHeaders()).forEach(([key, value]) => setHeader(headers, key, value));
  return headers;
}

async function parseResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") || "";
  if (response.status === 204) {
    return {} as T;
  }
  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }
  return (await response.text()) as T;
}

function errorMessage(data: unknown, fallback: string): string {
  if (typeof data === "object" && data) {
    if ("error" in data) {
      const error = data.error;
      if (typeof error === "string") {
        return error;
      }
      if (typeof error === "object" && error && "message" in error && typeof error.message === "string") {
        return error.message;
      }
    }
  }
  return fallback;
}

export function actorHeaders(): Record<string, string> {
  const configuredActor = String(import.meta.env.VITE_TMSWMS_ACTOR ?? "").trim();
  let storedActor = "";
  try {
    storedActor = typeof window === "undefined" ? "" : window.localStorage.getItem("tmswms.actor")?.trim() ?? "";
  } catch {
    storedActor = "";
  }
  const actor = configuredActor || storedActor;
  if (!actor) {
    return {};
  }
  return {
    "X-Actor": actor,
    "X-User": actor,
    "X-User-Email": actor,
  };
}

export async function apiGet<T>(path: string, options?: RequestTrackingOptions): Promise<ApiResult<T>> {
  const response = await trackedFetch(path, {
    credentials: "include",
    headers: buildActorHeaders(),
  }, options);
  if (!response.ok) {
    return {
      error: {
        code: "http_error",
        message: `API ${path} respondio ${response.status}`,
        details: {},
        correlation_id: "",
      },
    };
  }
  return response.json() as Promise<ApiResult<T>>;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const response = await trackedFetch(path, {
    method: "POST",
    credentials: "include",
    headers: buildHeaders({
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`,
      ...actorHeaders(),
    }),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = (await response.json().catch(() => ({}))) as T & ApiResult<never>;
  if (!response.ok) {
    throw new ApiError(errorMessage(payload, `API ${path} respondio ${response.status}`), response.status, payload);
  }
  return payload;
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await trackedFetch(path, {
    credentials: "include",
    ...init,
    headers: apiHeaders(init?.headers),
  });
  const payload = await parseResponse<T | { error?: string | { message?: string } }>(response);
  if (!response.ok) {
    throw new ApiError(errorMessage(payload, response.statusText || "Request failed"), response.status, payload);
  }
  return payload as T;
}
