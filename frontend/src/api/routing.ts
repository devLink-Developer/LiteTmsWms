import { apiGet, apiHeaders, apiPost, trackedFetch } from "./client";
import {
  fetchWarehouseOptions as fetchLogisticsWarehouseOptions,
  fetchWarehouseOptionsForStore as fetchLogisticsWarehouseOptionsForStore,
} from "./logistics";

export type { WarehouseOption } from "./logistics";

export type RoutingDelivery = {
  id: string;
  delivery_number: string;
  status: string;
  delivery_mode: string;
  planned_date: string | null;
  warehouse_ref: string;
  customer_ref: string;
  sales_order_number: string;
  address_snapshot: Record<string, string>;
  lat: string | null;
  lng: string | null;
  planned_weight_kg: string;
  planned_volume_m3: string;
};

export type RouteStopLine = {
  id: string;
  delivery_ref: string;
  source_line_ref: string;
  item_ref: string;
  item_name: string;
  quantity: string;
  delivered_qty: string;
  returned_qty: string;
  difference_qty: string;
  uom: string;
  warehouse_ref: string;
};

export type RouteStop = {
  id: string;
  sequence: number;
  status: string;
  stop_type: string;
  source_type: string;
  source_ref: string;
  source_label: string;
  delivery_number: string;
  sales_order_number: string;
  delivery_mode: string;
  customer_ref: string;
  customer_name?: string;
  address_snapshot: Record<string, string>;
  lat: string | null;
  lng: string | null;
  planned_weight_kg: string;
  planned_volume_m3: string;
  outcome_status: string;
  outcome_reason: string;
  lines: RouteStopLine[];
};

export type RouteSheet = {
  id: string;
  route_number: string;
  status: string;
  branch_ref: string;
  warehouse_ref: string;
  vehicle_id: string | null;
  vehicle: string | null;
  driver_ref: string;
  planned_date: string;
  planned_weight_kg: string;
  planned_volume_m3: string;
  loaded_weight_kg: string;
  loaded_volume_m3: string;
  total_distance_km: string;
  total_time_minutes: number;
  routing_provider: string;
  reviewed_at: string | null;
  route_geometry: { type?: string; coordinates?: number[][] };
  preview_payload: {
    excluded?: Array<Record<string, string>>;
    routing_status?: string;
    input?: {
      origin?: Record<string, unknown>;
    };
  };
  stops: RouteStop[];
};

export type RouteSheetSummary = Pick<
  RouteSheet,
  | "id"
  | "route_number"
  | "status"
  | "planned_date"
  | "warehouse_ref"
  | "vehicle"
  | "driver_ref"
  | "planned_weight_kg"
  | "planned_volume_m3"
  | "total_distance_km"
  | "total_time_minutes"
> & {
  stops_count: number;
};

export type VehicleOption = {
  id: string;
  code: string;
  plate: string;
  status: string;
  max_weight_kg: string;
  max_volume_m3: string;
};

type CommandResult<T> = {
  result: T;
  rendition_id?: string;
};

export async function fetchRoutingDeliveries(filters: { warehouse?: string; plannedDate?: string }) {
  const params = new URLSearchParams();
  if (filters.warehouse) params.set("warehouse_ref", filters.warehouse);
  if (filters.plannedDate) params.set("planned_date", filters.plannedDate);
  const response = await apiGet<RoutingDelivery>(`/api/v1/routing/pending-deliveries/?${params.toString()}`);
  if (response.error) throw new Error(response.error.message);
  return response.results ?? [];
}

export async function fetchVehicles() {
  const response = await apiGet<VehicleOption>("/api/v1/vehicles/");
  if (response.error) throw new Error(response.error.message);
  return response.results ?? [];
}

export async function fetchWarehouseOptions() {
  return fetchLogisticsWarehouseOptions();
}

export async function fetchWarehouseOptionsForStore(store?: string) {
  return fetchLogisticsWarehouseOptionsForStore(store);
}

export async function fetchRouteSheets(filters: { warehouse?: string; plannedDate?: string; status?: string[]; driverRef?: string }) {
  const params = new URLSearchParams();
  if (filters.warehouse) params.set("warehouse_ref", filters.warehouse);
  if (filters.plannedDate) params.set("planned_date", filters.plannedDate);
  if (filters.status?.length) params.set("status", filters.status.join(","));
  if (filters.driverRef) params.set("driver_ref", filters.driverRef);
  const response = await apiGet<RouteSheetSummary>(`/api/v1/routesheets/?${params.toString()}`);
  if (response.error) throw new Error(response.error.message);
  return response.results ?? [];
}

export async function fetchRouteSheet(routeId: string) {
  const response = await trackedFetch(`/api/v1/routesheets/${routeId}/`, {
    credentials: "include",
    headers: apiHeaders(),
  });
  const payload = (await response.json().catch(() => ({}))) as CommandResult<RouteSheet> & {
    error?: { message: string };
  };
  if (!response.ok) throw new Error(payload.error?.message ?? `API routesheets/${routeId} respondio ${response.status}`);
  return payload.result;
}

export async function optimizeRoute(payload: {
  warehouse_ref: string;
  branch_ref: string;
  planned_date: string;
  vehicle_id?: string;
  driver_ref?: string;
  origin?: { lat: number; lng: number };
  deliveries: Array<{ delivery_id: string; lat?: string | null; lng?: string | null }>;
}) {
  const response = await apiPost<CommandResult<RouteSheet>>("/api/v1/routing/optimize", payload);
  return response.result;
}

export async function updateRouteStopOrder(
  routeId: string,
  stops: Array<{ id: string; sequence: number; lat?: string | null; lng?: string | null }>,
  removeStopIds: string[] = [],
) {
  const response = await trackedFetch(`/api/v1/routesheets/${routeId}/stops`, {
    method: "PATCH",
    credentials: "include",
    headers: apiHeaders({
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`,
    }),
    body: JSON.stringify({ stops, remove_stop_ids: removeStopIds }),
  });
  const payload = (await response.json().catch(() => ({}))) as CommandResult<RouteSheet> & {
    error?: { message: string };
  };
  if (!response.ok) throw new Error(payload.error?.message ?? `API routesheets/${routeId}/stops respondio ${response.status}`);
  return payload.result;
}

export async function confirmRoute(routeId: string, payload: { vehicle_id?: string; driver_ref?: string; reviewed?: boolean }) {
  const response = await trackedFetch(`/api/v1/routesheets/${routeId}/confirm`, {
    method: "PUT",
    credentials: "include",
    headers: apiHeaders({
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`,
    }),
    body: JSON.stringify(payload),
  });
  const body = (await response.json().catch(() => ({}))) as CommandResult<RouteSheet> & { error?: { message: string } };
  if (!response.ok) throw new Error(body.error?.message ?? `API routesheets/${routeId}/confirm respondio ${response.status}`);
  return body.result;
}

export async function routeCommand(routeId: string, command: "start-loading" | "depart" | "close", payload: Record<string, unknown> = {}) {
  const response = await apiPost<CommandResult<RouteSheet>>(`/api/v1/routesheets/${routeId}/${command}`, payload);
  return response.result;
}

export async function executeStop(payload: {
  route_stop_id: string;
  status: "delivered_complete" | "delivered_partial" | "not_delivered";
  reason?: string;
  observations?: string;
  timestamp?: string;
  lines?: Array<{ source_line_ref: string; delivered_qty: string; rejected_qty?: string }>;
}, idempotencyKey?: string) {
  const response = await trackedFetch("/api/v1/deliveries/execute", {
    method: "POST",
    credentials: "include",
    headers: apiHeaders({
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey || crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`,
    }),
    body: JSON.stringify(payload),
  });
  const body = (await response.json().catch(() => ({}))) as CommandResult<RouteSheet> & { error?: { message: string } };
  if (!response.ok) throw new Error(body.error?.message ?? `API deliveries/execute respondio ${response.status}`);
  return body.result;
}
