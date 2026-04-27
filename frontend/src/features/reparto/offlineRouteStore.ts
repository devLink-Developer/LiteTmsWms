import type { RouteSheet } from "../../api/routing";

export type OfflineExecutionPayload = {
  route_stop_id: string;
  status: "delivered_complete" | "delivered_partial" | "not_delivered";
  reason?: string;
  observations?: string;
  timestamp?: string;
  lines?: Array<{ source_line_ref: string; delivered_qty: string; rejected_qty?: string }>;
};

export type QueuedExecution = {
  id: string;
  routeId: string;
  idempotencyKey: string;
  payload: OfflineExecutionPayload;
  createdAt: string;
};

const ROUTES_KEY = "tmswms.offline.routes";
const EXECUTIONS_KEY = "tmswms.offline.executions";

function readJson<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(key, JSON.stringify(value));
}

export function offlineRoutes() {
  return readJson<Record<string, RouteSheet>>(ROUTES_KEY, {});
}

export function offlineRouteList() {
  return Object.values(offlineRoutes()).sort((left, right) => right.planned_date.localeCompare(left.planned_date));
}

export function saveOfflineRoute(route: RouteSheet) {
  writeJson(ROUTES_KEY, { ...offlineRoutes(), [route.id]: route });
}

export function getOfflineRoute(routeId: string) {
  return offlineRoutes()[routeId] ?? null;
}

export function queueExecution(routeId: string, payload: OfflineExecutionPayload) {
  const queued = readJson<QueuedExecution[]>(EXECUTIONS_KEY, []);
  const item: QueuedExecution = {
    id: crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`,
    routeId,
    idempotencyKey: crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`,
    payload,
    createdAt: new Date().toISOString(),
  };
  writeJson(EXECUTIONS_KEY, [...queued, item]);
  return item;
}

export function queuedExecutions() {
  return readJson<QueuedExecution[]>(EXECUTIONS_KEY, []);
}

export function removeQueuedExecution(id: string) {
  writeJson(EXECUTIONS_KEY, queuedExecutions().filter((item) => item.id !== id));
}

export function updateOfflineRouteExecution(route: RouteSheet, payload: OfflineExecutionPayload) {
  const stops = route.stops.map((stop) => {
    if (stop.id !== payload.route_stop_id) return stop;
    const deliveredByLine = new Map((payload.lines ?? []).map((line) => [line.source_line_ref, Number(line.delivered_qty || 0)]));
    const lines = stop.lines.map((line) => {
      const delivered = payload.status === "delivered_complete" ? Number(line.quantity) : payload.status === "not_delivered" ? 0 : deliveredByLine.get(line.source_line_ref) ?? 0;
      const rejected = Math.max(0, Number(line.quantity) - delivered);
      return {
        ...line,
        delivered_qty: String(delivered),
        returned_qty: String(rejected),
        difference_qty: "0",
      };
    });
    return {
      ...stop,
      status: payload.status === "not_delivered" ? "failed" : "delivered",
      outcome_status: payload.status,
      outcome_reason: payload.reason ?? "",
      lines,
    };
  });
  const nextRoute = { ...route, stops };
  saveOfflineRoute(nextRoute);
  return nextRoute;
}
