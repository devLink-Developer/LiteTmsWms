import { apiHeaders, trackedFetch } from "./client";

export type LiveStatusEvent = {
  id: string;
  entity_type: "delivery_order" | "delivery_document" | "delivery_preparation_task" | "fulfillment_order" | "route_sheet" | "route_stop";
  entity_id: string;
  from_status: string;
  to_status: string;
  actor: string;
  reason: string;
  payload: Record<string, unknown>;
  warehouse_ref: string;
  route_id?: string;
  delivery_id?: string;
  fulfillment_id?: string;
  created_at: string;
};

export type LiveStatusEventsResponse = {
  results: LiveStatusEvent[];
  cursor: string;
};

export async function fetchLiveStatusEvents(since: string, limit = 100) {
  const params = new URLSearchParams({
    since,
    limit: String(limit),
  });
  const response = await trackedFetch(`/api/v1/live/status-events/?${params.toString()}`, {
    credentials: "include",
    headers: apiHeaders(),
  }, { globalLoading: false });
  const payload = (await response.json().catch(() => ({}))) as LiveStatusEventsResponse & { error?: { message?: string } };
  if (!response.ok) {
    throw new Error(payload.error?.message ?? `API live/status-events respondio ${response.status}`);
  }
  return payload;
}
