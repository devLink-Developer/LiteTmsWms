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

export function actorHeaders(): Record<string, string> {
  const configuredActor = String(import.meta.env.VITE_TMSWMS_ACTOR ?? "").trim();
  const storedActor =
    typeof window === "undefined" ? "" : window.localStorage.getItem("tmswms.actor")?.trim() ?? "";
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

export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  const response = await fetch(apiUrl(path), {
    headers: { Accept: "application/json", ...actorHeaders() },
  });
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
  const response = await fetch(apiUrl(path), {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`,
      ...actorHeaders(),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = (await response.json().catch(() => ({}))) as T & ApiResult<never>;
  if (!response.ok) {
    throw new Error(payload.error?.message ?? `API ${path} respondio ${response.status}`);
  }
  return payload;
}
