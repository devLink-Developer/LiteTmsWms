import { ApiError, requestJson } from "./client";

export type WriteOffStatus = "draft" | "posted" | "cancelled" | "reversed" | string;

export type WriteOffRecord = {
  id: string;
  write_off_number?: string;
  document_ref?: string;
  status: WriteOffStatus;
  warehouse_ref: string;
  source_location_ref?: string;
  target_location_ref?: string;
  item_ref?: string;
  item_name?: string;
  lot_ref?: string;
  location_ref?: string;
  quantity?: string;
  uom?: string;
  source_stock_state?: string;
  reason_code?: "breakage" | "loss" | string;
  reason?: string;
  created_by?: string;
  requested_by?: string;
  posted_at?: string | null;
  created_at?: string | null;
  reversed_at?: string | null;
  lines?: Array<{
    id: string;
    item_ref: string;
    quantity: string;
    posted_qty: string;
    uom: string;
    lot_ref?: string;
    location_ref?: string;
    source_location_ref?: string;
    target_location_ref?: string;
    stock_state?: string;
  }>;
};

export type WriteOffFilters = {
  warehouse?: string;
  item?: string;
  status?: string;
  search?: string;
  limit?: number;
};

export type CreateWriteOffPayload = {
  warehouse_ref: string;
  reason_code: "breakage" | "loss";
  reason: string;
  source_location_ref?: string;
  lines: Array<{
    item_ref: string;
    quantity: string;
    uom: string;
    lot_ref?: string;
  }>;
};

type WriteOffListResponse = {
  results?: WriteOffRecord[];
  allowed_warehouses?: string[];
};

type CommandResult<T> = {
  result: T;
};

type LedgerEntry = {
  id: string;
  movement_type: string;
  direction: string;
  warehouse_ref: string;
  item_ref: string;
  stock_state: string;
  quantity: string;
  uom: string;
  document_type: string;
  document_ref: string;
  reason?: string;
  posted_at?: string;
  created_by?: string;
};

function queryString(filters: WriteOffFilters = {}) {
  const params = new URLSearchParams();
  if (filters.warehouse) params.set("warehouse", filters.warehouse);
  if (filters.item) params.set("item", filters.item);
  if (filters.status) params.set("status", filters.status);
  if (filters.search) params.set("search", filters.search);
  if (filters.limit) params.set("limit", String(filters.limit));
  const query = params.toString();
  return query ? `?${query}` : "";
}

function ledgerQueryString(filters: WriteOffFilters = {}) {
  const params = new URLSearchParams();
  params.set("movement_type", "write_off");
  params.set("stock_state", "scrapped");
  if (filters.warehouse) params.set("warehouse", filters.warehouse);
  if (filters.item) params.set("item", filters.item);
  if (filters.limit) params.set("limit", String(filters.limit));
  const query = params.toString();
  return query ? `?${query}` : "";
}

function idempotencyKey() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random()}`;
}

function normalizeWriteOffResponse(payload: WriteOffRecord | CommandResult<WriteOffRecord>) {
  return "result" in payload ? payload.result : payload;
}

function ledgerEntryToWriteOff(entry: LedgerEntry): WriteOffRecord {
  return {
    id: entry.id,
    document_ref: entry.document_ref,
    status: "posted",
    warehouse_ref: entry.warehouse_ref,
    item_ref: entry.item_ref,
    quantity: entry.quantity,
    uom: entry.uom,
    source_stock_state: entry.stock_state,
    reason: entry.reason,
    created_by: entry.created_by,
    posted_at: entry.posted_at,
    created_at: entry.posted_at,
  };
}

export async function fetchWriteOffs(filters: WriteOffFilters = {}): Promise<WriteOffListResponse> {
  try {
    return await requestJson<WriteOffListResponse>(`/api/v1/inventory/write-offs/${queryString(filters)}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      const ledger = await requestJson<{ results?: LedgerEntry[] }>(`/api/v1/inventory/ledger/${ledgerQueryString(filters)}`);
      return { results: (ledger.results ?? []).map(ledgerEntryToWriteOff), allowed_warehouses: [] };
    }
    throw error;
  }
}

export async function createWriteOff(payload: CreateWriteOffPayload) {
  const response = await requestJson<WriteOffRecord | CommandResult<WriteOffRecord>>("/api/v1/inventory/write-offs/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey(),
    },
    body: JSON.stringify({
      source_stock_state: "packed",
      ...payload,
    }),
  });
  return normalizeWriteOffResponse(response);
}

export async function reverseWriteOff(writeOffId: string, reason: string) {
  const response = await requestJson<CommandResult<WriteOffRecord>>(`/api/v1/inventory/write-offs/${writeOffId}/reverse/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey(),
    },
    body: JSON.stringify({ reason }),
  });
  return response.result;
}

export type { WriteOffListResponse };
