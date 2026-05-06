import { apiGet, apiHeaders, requestJson, trackedFetch } from "./client";

export type StoreOption = {
  id?: string;
  store_code: string;
  store_name?: string;
  active?: boolean;
  operational_status?: string;
  zone?: string;
  zone_code?: string;
  province?: string;
  city?: string;
  commercial_site_code?: string;
  company?: string;
  pickup_warehouse_ref?: string;
  shipping_warehouse_ref?: string;
  delivery_modes?: Array<{
    mode_id?: string;
    name?: string;
    external_id?: string;
    is_pickup_allowed?: boolean;
    is_shipping_allowed?: boolean;
  }>;
};

export type WarehouseOption = {
  warehouse_id?: string;
  warehouse_code: string;
  warehouse_name?: string;
  warehouse_type?: string;
  store_code?: string;
  store_name?: string;
  is_pickup_allowed?: boolean;
  is_shipping_allowed?: boolean;
};

export type WarehouseLocation = {
  id: string;
  warehouse_ref: string;
  location_ref: string;
  location_name?: string;
  name?: string;
  location_type: string;
  purpose: string;
  zone_ref?: string;
  aisle?: string;
  floor?: string;
  level?: string;
  position?: string;
  is_dispatchable: boolean;
  is_reservable: boolean;
  is_pickable: boolean;
  allows_scrap: boolean;
  system_location: boolean;
  generated: boolean;
  active: boolean;
};

export type WarehouseRecord = WarehouseOption & {
  id: string;
  warehouse_ref: string;
  name?: string;
  branch_ref?: string;
  store_ref?: string;
  active: boolean;
  default_available_location_ref?: string;
  default_reserved_location_ref?: string;
  default_preparation_location_ref?: string;
  default_breakage_location_ref?: string;
  default_loss_location_ref?: string;
  locations?: WarehouseLocation[];
};

export type WarehousePayload = {
  warehouse_ref: string;
  name: string;
  warehouse_type?: string;
  branch_ref?: string;
  store_ref?: string;
  store_name?: string;
  is_pickup_allowed?: boolean;
  is_shipping_allowed?: boolean;
  active?: boolean;
  layout?: {
    zones?: number | string;
    aisles?: number | string;
    floors?: number | string;
    levels?: number | string;
    positions?: number | string;
  };
};

export type MaterialOption = {
  item_ref: string;
  sap_code?: string;
  sap_item_id?: string;
  name?: string;
  long_name?: string;
  category?: string;
  coverage_group?: string;
  uom?: string;
  uom_code?: string;
  store_number?: string;
  store_name?: string;
  available_for_sale?: string | number;
  freight_product?: boolean;
  service_product?: boolean;
  virtual_product?: boolean;
};

export type SheetCuttingCategory = {
  category: string;
  item_count: number;
  store_count: number;
  min_length_cm: number;
  max_length_cm: number;
  min_length_m: number;
  max_length_m: number;
  length_count: number;
};

export type SheetCuttingMaterial = {
  item_ref: string;
  sap_code?: string;
  sap_item_id?: string;
  category: string;
  name?: string;
  long_name?: string;
  uom?: string;
  uom_code?: string;
  length_cm: number;
  length_m: number;
  width?: number;
  height?: number;
  price_with_tax?: number;
  available_for_delivery?: number;
  store_number?: string;
  store_name?: string;
  source_file?: string;
};

export type SheetCuttingLengthOption = {
  length_cm: number;
  length_m: number;
  item_count: number;
  available_for_delivery: number;
  examples: Array<{
    item_ref: string;
    name?: string;
    long_name?: string;
    uom?: string;
    available_for_delivery?: number;
  }>;
};

export type SheetCuttingOptions = {
  source_files?: string[];
  unit: "cm";
  categories: SheetCuttingCategory[];
  materials: SheetCuttingMaterial[];
  length_options: SheetCuttingLengthOption[];
};

export type SheetCuttingPlanLine = {
  item_ref?: string;
  name?: string;
  long_name?: string;
  length_cm: number;
  length_m: number;
  quantity: number;
  used_cm: number;
  used_m: number;
};

export type SheetCuttingPlan = {
  unit: "cm";
  valid: boolean;
  category: string;
  source: {
    item_ref?: string;
    name?: string;
    long_name?: string;
    length_cm: number;
    length_m: number;
    quantity: number;
    total_cm: number;
    total_m: number;
  };
  outputs: SheetCuttingPlanLine[];
  used_cm: number;
  used_m: number;
  waste_cm: number;
  waste_m: number;
  message: string;
};

export type SheetCuttingStockValidation = {
  plan: SheetCuttingPlan;
  stock: {
    warehouse_ref: string;
    source_item_ref: string;
    source_uom: string;
    stock_state: string;
    required_qty: string | number;
    available_qty: string | number;
    has_stock: boolean;
  };
  valid: boolean;
  message: string;
};

export type SheetCuttingExecution = {
  id: string;
  status: string;
  warehouse_ref: string;
  transformation_type: string;
  reason: string;
  posted_at?: string | null;
  source: SheetCuttingPlan["source"];
  outputs: SheetCuttingPlanLine[];
  used_cm: number;
  used_m: number;
  waste_cm: number;
  waste_m: number;
  stock: SheetCuttingStockValidation["stock"];
};

type MasterDataResponse<T> = {
  source_file?: string;
  results?: T[];
};

function masterDataQuery(filters: { store?: string; query?: string; active?: string; limit?: number } = {}) {
  const params = new URLSearchParams();
  if (filters.store) params.set("store", filters.store);
  if (filters.query) params.set("q", filters.query);
  if (filters.active) params.set("active", filters.active);
  if (filters.limit) params.set("limit", String(filters.limit));
  const query = params.toString();
  return query ? `?${query}` : "";
}

export async function fetchStoreOptions(filters: { query?: string; active?: string; limit?: number } = {}) {
  const response = await apiGet<StoreOption>(`/api/v1/logistics/master-data/stores/${masterDataQuery(filters)}`);
  if (response.error) throw new Error(response.error.message);
  return response.results ?? [];
}

export async function fetchWarehouseOptions(filters: { store?: string; query?: string; limit?: number } = {}) {
  const response = await apiGet<WarehouseOption>(`/api/v1/logistics/master-data/warehouses/${masterDataQuery(filters)}`);
  if (response.error) throw new Error(response.error.message);
  return response.results ?? [];
}

export async function fetchWarehouseOptionsForStore(store?: string) {
  return fetchWarehouseOptions({ store });
}

export async function fetchMaterialOptions(filters: { store?: string; query?: string; limit?: number } = {}) {
  const response = await apiGet<MaterialOption>(`/api/v1/logistics/master-data/materials/${masterDataQuery(filters)}`);
  if (response.error) throw new Error(response.error.message);
  return response.results ?? [];
}

export async function fetchSheetCuttingOptions(filters: { store?: string; category?: string; query?: string; limit?: number } = {}) {
  const params = new URLSearchParams();
  if (filters.store) params.set("store", filters.store);
  if (filters.category) params.set("category", filters.category);
  if (filters.query) params.set("q", filters.query);
  if (filters.limit) params.set("limit", String(filters.limit));
  const query = params.toString();
  return requestJson<SheetCuttingOptions>(`/api/v1/logistics/master-data/sheet-cutting/${query ? `?${query}` : ""}`);
}

export async function calculateSheetCuttingPlan(payload: {
  store?: string;
  category: string;
  source_item_ref?: string;
  source_length_cm?: number | string;
  source_quantity?: number | string;
  cuts: Array<{ item_ref?: string; length_cm: number | string; quantity: number | string }>;
}) {
  const response = await requestJson<{ result: SheetCuttingPlan }>("/api/v1/logistics/master-data/sheet-cutting/plan/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return response.result;
}

export async function validateSheetCuttingStock(payload: {
  store?: string;
  category: string;
  source_item_ref: string;
  source_quantity?: number | string;
  cuts: Array<{ item_ref?: string; length_cm: number | string; quantity: number | string }>;
}) {
  const response = await requestJson<{ result: SheetCuttingStockValidation }>("/api/v1/inventory/sheet-cutting/validate/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return response.result;
}

export async function executeSheetCutting(payload: {
  store?: string;
  category: string;
  source_item_ref: string;
  source_quantity?: number | string;
  cuts: Array<{ item_ref?: string; length_cm: number | string; quantity: number | string }>;
  reason?: string;
}) {
  const response = await requestJson<{ result: SheetCuttingExecution }>("/api/v1/inventory/sheet-cutting/execute/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey(),
    },
    body: JSON.stringify(payload),
  });
  return response.result;
}

function localWarehouseQuery(filters: { store?: string; query?: string; active?: string; limit?: number } = {}) {
  const params = new URLSearchParams();
  if (filters.store) params.set("store", filters.store);
  if (filters.query) params.set("q", filters.query);
  if (filters.active) params.set("active", filters.active);
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

export async function fetchWarehouseMasters(filters: { store?: string; query?: string; active?: string; limit?: number } = {}) {
  const payload = await requestJson<{ results?: WarehouseRecord[] }>(`/api/v1/logistics/warehouses/${localWarehouseQuery(filters)}`);
  return payload.results ?? [];
}

export async function saveWarehouseMaster(payload: WarehousePayload, warehouseRef?: string) {
  const path = warehouseRef ? `/api/v1/logistics/warehouses/${encodeURIComponent(warehouseRef)}/` : "/api/v1/logistics/warehouses/";
  const response = await trackedFetch(path, {
    method: warehouseRef ? "PATCH" : "POST",
    credentials: "include",
    headers: apiHeaders({
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey(),
    }),
    body: JSON.stringify(payload),
  });
  const data = (await response.json().catch(() => ({}))) as { result?: WarehouseRecord; error?: { message?: string } };
  if (!response.ok || !data.result) throw new Error(data.error?.message ?? `API ${path} respondio ${response.status}`);
  return data.result;
}

export async function fetchWarehouseLocations(warehouseRef: string) {
  const payload = await requestJson<{ results?: WarehouseLocation[] }>(`/api/v1/logistics/warehouses/${encodeURIComponent(warehouseRef)}/locations/`);
  return payload.results ?? [];
}

export async function generateWarehouseLocations(warehouseRef: string, layout?: WarehousePayload["layout"]) {
  const payload = await requestJson<{ results?: WarehouseLocation[] }>(`/api/v1/logistics/warehouses/${encodeURIComponent(warehouseRef)}/locations/generate/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ layout }),
  });
  return payload.results ?? [];
}

export type { MasterDataResponse };
