import { apiPost, requestJson } from "./client";

export type InventoryBalance = {
  id: string;
  warehouse_ref: string;
  warehouse_name?: string;
  warehouse_location_ref?: string;
  location_ref?: string;
  location_name?: string;
  purpose?: string;
  zone_ref?: string;
  aisle?: string;
  floor?: string;
  level?: string;
  position?: string;
  is_dispatchable?: boolean;
  is_reservable?: boolean;
  is_pickable?: boolean;
  allows_scrap?: boolean;
  system_location?: boolean;
  item_ref: string;
  item_name?: string;
  supplier_ref?: string;
  category_ref?: string;
  category?: string;
  rubro_ref?: string;
  lot_ref?: string;
  pallet_ref?: string;
  quality_status?: string;
  stock_state: string;
  quantity: string;
  uom: string;
  version: number;
};

export type InventoryBalancesResponse = {
  results: InventoryBalance[];
  allowed_warehouses?: string[];
};

export type InventoryBalanceFilters = {
  warehouse?: string;
  location?: string;
  item?: string;
  supplier?: string;
  category?: string;
  rubro?: string;
  lot?: string;
  pallet?: string;
  quality?: string;
  state?: string;
  locationScope?: "available" | "all";
  search?: string;
  limit?: number;
};

function buildInventoryQuery(filters: InventoryBalanceFilters = {}) {
  const params = new URLSearchParams();
  if (filters.warehouse) params.set("warehouse", filters.warehouse);
  if (filters.location) params.set("location", filters.location);
  if (filters.item) params.set("item", filters.item);
  if (filters.supplier) params.set("supplier", filters.supplier);
  if (filters.category) params.set("category", filters.category);
  if (filters.rubro) params.set("rubro", filters.rubro);
  if (filters.lot) params.set("lot", filters.lot);
  if (filters.pallet) params.set("pallet", filters.pallet);
  if (filters.quality) params.set("quality", filters.quality);
  if (filters.state) params.set("state", filters.state);
  if (filters.locationScope) params.set("location_scope", filters.locationScope);
  if (filters.search) params.set("search", filters.search);
  if (filters.limit) params.set("limit", String(filters.limit));
  return params.toString();
}

export async function fetchInventoryBalances(filters: InventoryBalanceFilters = {}) {
  const query = buildInventoryQuery(filters);
  return requestJson<InventoryBalancesResponse>(`/api/v1/inventory/balances/${query ? `?${query}` : ""}`);
}

export type InventoryStockReportRow = {
  id: string;
  warehouse_ref: string;
  warehouse_name?: string;
  warehouse_location_ref?: string;
  location_ref?: string;
  location_name?: string;
  purpose?: string;
  zone_ref?: string;
  aisle?: string;
  floor?: string;
  level?: string;
  position?: string;
  is_dispatchable?: boolean;
  is_reservable?: boolean;
  is_pickable?: boolean;
  allows_scrap?: boolean;
  system_location?: boolean;
  item_ref: string;
  item_name?: string;
  supplier_ref?: string;
  category_ref?: string;
  category?: string;
  rubro_ref?: string;
  lot_ref?: string;
  pallet_ref?: string;
  quality_status?: string;
  uom: string;
  quantities?: Partial<Record<"on_hand" | "reserved" | "picking" | "packed" | "in_transit" | "scrapped", string | number>>;
  balances?: InventoryBalance[];
};

export type InventoryStockReportResponse = {
  results: InventoryStockReportRow[];
  allowed_warehouses?: string[];
};

type AdvancedStockRow = {
  warehouse_ref: string;
  warehouse_name?: string;
  item_ref: string;
  item_name?: string;
  item_long_name?: string;
  supplier_ref?: string;
  category_ref?: string;
  category?: string;
  rubro_ref?: string;
  coverage_group?: string;
  lot_ref?: string;
  warehouse_location_ref?: string;
  location_ref?: string;
  location_name?: string;
  purpose?: string;
  zone_ref?: string;
  aisle?: string;
  floor?: string;
  level?: string;
  position?: string;
  is_dispatchable?: boolean;
  is_reservable?: boolean;
  is_pickable?: boolean;
  allows_scrap?: boolean;
  system_location?: boolean;
  location_ref_is_fallback?: boolean;
  pallet_ref?: string;
  quality_status?: string;
  uom: string;
  quantities?: Partial<Record<"available" | "reserved" | "in_preparation" | "prepared" | "in_transit" | "damaged_waste" | "total", string | number>>;
};

type AdvancedStockResponse = {
  results: AdvancedStockRow[];
  allowed_warehouses?: string[];
};

function reportRowId(row: Pick<InventoryStockReportRow, "warehouse_ref" | "location_ref" | "item_ref" | "lot_ref" | "uom">) {
  return [row.warehouse_ref, row.location_ref || "", row.item_ref, row.lot_ref || "", row.uom].join("|");
}

function advancedToStockReport(payload: AdvancedStockResponse): InventoryStockReportResponse {
  return {
    allowed_warehouses: payload.allowed_warehouses,
    results: (payload.results ?? []).map((row) => {
      const quantities = row.quantities ?? {};
      const actualLocation = row.location_ref || "";
      const displayLocation = row.warehouse_location_ref || actualLocation || row.lot_ref || "";
      const reportRow: InventoryStockReportRow = {
        id: "",
        warehouse_ref: row.warehouse_ref,
        warehouse_name: row.warehouse_name,
        warehouse_location_ref: displayLocation,
        location_ref: actualLocation,
        location_name: row.location_name,
        purpose: row.purpose,
        zone_ref: row.zone_ref,
        aisle: row.aisle,
        floor: row.floor,
        level: row.level,
        position: row.position,
        is_dispatchable: row.is_dispatchable,
        is_reservable: row.is_reservable,
        is_pickable: row.is_pickable,
        allows_scrap: row.allows_scrap,
        system_location: row.system_location,
        item_ref: row.item_ref,
        item_name: row.item_name || row.item_long_name,
        supplier_ref: row.supplier_ref,
        category_ref: row.category_ref,
        category: row.category,
        rubro_ref: row.rubro_ref,
        lot_ref: row.lot_ref || "",
        pallet_ref: row.pallet_ref,
        quality_status: row.quality_status,
        uom: row.uom,
        quantities: {
          on_hand: quantities.available ?? 0,
          reserved: quantities.reserved ?? 0,
          picking: quantities.in_preparation ?? 0,
          packed: quantities.prepared ?? 0,
          in_transit: quantities.in_transit ?? 0,
          scrapped: quantities.damaged_waste ?? 0,
        },
        balances: [],
      };
      reportRow.id = reportRowId(reportRow);
      return reportRow;
    }),
  };
}

function balancesToStockReport(payload: InventoryBalancesResponse): InventoryStockReportResponse {
  const groups = new Map<string, InventoryStockReportRow>();
  for (const row of payload.results ?? []) {
    const displayLocation = row.warehouse_location_ref || row.location_ref || row.lot_ref || "";
    const actualLocation = row.location_ref || "";
    const category = row.category_ref || row.rubro_ref || row.category || "";
    const key = [
      row.warehouse_ref,
      actualLocation,
      row.item_ref,
      row.supplier_ref || "",
      category,
      row.lot_ref || "",
      row.pallet_ref || "",
      row.quality_status || "",
      row.uom,
    ].join("|");
    const current =
      groups.get(key) ??
      ({
        id: key,
        warehouse_ref: row.warehouse_ref,
        warehouse_name: row.warehouse_name,
        warehouse_location_ref: displayLocation,
        location_ref: actualLocation,
        location_name: row.location_name,
        purpose: row.purpose,
        zone_ref: row.zone_ref,
        aisle: row.aisle,
        floor: row.floor,
        level: row.level,
        position: row.position,
        is_dispatchable: row.is_dispatchable,
        is_reservable: row.is_reservable,
        is_pickable: row.is_pickable,
        allows_scrap: row.allows_scrap,
        system_location: row.system_location,
        item_ref: row.item_ref,
        item_name: row.item_name,
        supplier_ref: row.supplier_ref,
        category_ref: row.category_ref,
        category: row.category,
        rubro_ref: row.rubro_ref,
        lot_ref: row.lot_ref,
        pallet_ref: row.pallet_ref,
        quality_status: row.quality_status,
        uom: row.uom,
        quantities: {},
        balances: [],
      } satisfies InventoryStockReportRow);
    current.quantities = {
      ...current.quantities,
      [row.stock_state]: Number(current.quantities?.[row.stock_state as keyof InventoryStockReportRow["quantities"]] ?? 0) + Number(row.quantity || 0),
    };
    current.balances = [...(current.balances ?? []), row];
    groups.set(key, current);
  }
  return { results: Array.from(groups.values()), allowed_warehouses: payload.allowed_warehouses };
}

export async function fetchInventoryStockReport(filters: InventoryBalanceFilters = {}) {
  const query = buildInventoryQuery(filters);
  try {
    const response = await requestJson<AdvancedStockResponse>(`/api/v1/inventory/advanced-stock/${query ? `?${query}` : ""}`);
    return advancedToStockReport(response);
  } catch (error) {
    if (error instanceof Error && "status" in error && error.status === 404) {
      return balancesToStockReport(await fetchInventoryBalances(filters));
    }
    throw error;
  }
}

export type InventoryMaterialOption = {
  item_ref: string;
  sap_code?: string;
  sap_item_id?: string;
  name?: string;
  long_name?: string;
  category?: string;
  coverage_group?: string;
  uom?: string;
  uom_code?: string;
};

export async function fetchInventoryMaterials(filters: { query?: string; limit?: number } = {}) {
  const params = new URLSearchParams();
  if (filters.query) params.set("q", filters.query);
  if (filters.limit) params.set("limit", String(filters.limit));
  const query = params.toString();
  return requestJson<{ results?: InventoryMaterialOption[] }>(`/api/v1/inventory/materials/${query ? `?${query}` : ""}`);
}

type CommandResult<T> = {
  result: T;
};

function inventoryTransactionQuery(filters: { warehouse?: string; item?: string; status?: string; purchaseOrderRef?: string; limit?: number } = {}) {
  const params = new URLSearchParams();
  if (filters.warehouse) params.set("warehouse", filters.warehouse);
  if (filters.item) params.set("item", filters.item);
  if (filters.status) params.set("status", filters.status);
  if (filters.purchaseOrderRef) params.set("purchase_order_ref", filters.purchaseOrderRef);
  if (filters.limit) params.set("limit", String(filters.limit));
  const query = params.toString();
  return query ? `?${query}` : "";
}

export type PurchaseReceiptLine = {
  id?: string;
  item_ref: string;
  warehouse_ref?: string;
  location_ref?: string;
  lot_ref?: string;
  expected_qty?: string;
  received_qty: string;
  difference_qty?: string;
  uom: string;
  incident_ref?: string;
  legacy_line_id?: string;
};

export type PurchaseReceipt = {
  id: string;
  purchase_order_ref: string;
  supplier_ref?: string;
  status: string;
  warehouse_ref: string;
  reason?: string;
  received_at?: string | null;
  closed_at?: string | null;
  lines_count?: number;
  lines?: PurchaseReceiptLine[];
};

export type CreatePurchaseReceiptPayload = {
  warehouse_ref: string;
  purchase_order_ref: string;
  supplier_ref?: string;
  location_ref?: string;
  target_location_ref?: string;
  reason?: string;
  lines: Array<{
    item_ref: string;
    received_qty: string;
    expected_qty?: string;
    uom: string;
    location_ref?: string;
    target_location_ref?: string;
    lot_ref?: string;
    incident_ref?: string;
    legacy_line_id?: string;
  }>;
};

export async function fetchPurchaseReceipts(filters: { warehouse?: string; item?: string; status?: string; purchaseOrderRef?: string; limit?: number } = {}) {
  return requestJson<{ results?: PurchaseReceipt[] }>(`/api/v1/inventory/receipts/${inventoryTransactionQuery(filters)}`);
}

export async function createPurchaseReceipt(payload: CreatePurchaseReceiptPayload, idempotencyKey?: string) {
  const response = await apiPost<CommandResult<PurchaseReceipt>>("/api/v1/inventory/receipts/", payload, { idempotencyKey });
  return response.result;
}

export type InventoryExchangeLine = {
  id?: string;
  role: "input" | "output" | string;
  item_ref: string;
  warehouse_ref?: string;
  location_ref?: string;
  lot_ref?: string;
  quantity: string;
  uom: string;
  parent_line_ref?: string;
  conversion_factor?: string;
};

export type InventoryExchange = {
  id: string;
  transformation_type: string;
  status: string;
  warehouse_ref: string;
  reason?: string;
  conversion_group_id?: string;
  posted_at?: string | null;
  lines?: InventoryExchangeLine[];
};

export type CreateInventoryExchangePayload = {
  warehouse_ref: string;
  reason?: string;
  input: {
    item_ref: string;
    quantity: string;
    uom: string;
    location_ref: string;
    lot_ref?: string;
  };
  outputs: Array<{
    item_ref: string;
    quantity: string;
    uom: string;
    input_conversion_factor: string;
    location_ref?: string;
    target_location_ref?: string;
    lot_ref?: string;
  }>;
};

export async function fetchInventoryExchanges(filters: { warehouse?: string; item?: string; limit?: number } = {}) {
  return requestJson<{ results?: InventoryExchange[] }>(`/api/v1/inventory/exchanges/${inventoryTransactionQuery(filters)}`);
}

export async function createInventoryExchange(payload: CreateInventoryExchangePayload, idempotencyKey?: string) {
  const response = await apiPost<CommandResult<InventoryExchange>>("/api/v1/inventory/exchanges/", payload, { idempotencyKey });
  return response.result;
}

export type CreateLocationMovePayload = {
  warehouse_ref: string;
  source_location_ref: string;
  target_location_ref: string;
  item_ref: string;
  lot_ref?: string;
  quantity: string;
  uom: string;
  reason?: string;
};

export type LocationMoveResult = CreateLocationMovePayload & {
  document_ref: string;
  stock_state: string;
  ledger_entry_ids?: string[];
};

export async function createLocationMove(payload: CreateLocationMovePayload, idempotencyKey?: string) {
  const response = await apiPost<CommandResult<LocationMoveResult>>("/api/v1/inventory/location-moves/", payload, { idempotencyKey });
  return response.result;
}

export type InventoryLedgerEntry = {
  id: string;
  movement_type: string;
  direction: "increase" | "decrease" | string;
  warehouse_ref: string;
  location_ref?: string;
  lot_ref?: string;
  item_ref: string;
  stock_state: string;
  quantity: string;
  uom: string;
  document_type: string;
  document_ref: string;
  reason?: string;
  created_by?: string;
  is_reversal?: boolean;
  reversal_of?: string;
  legacy_transaction_number?: string;
  legacy_sales_order_number?: string;
  legacy_line_id?: string;
  posted_at?: string;
};

export type InventoryLedgerFilters = {
  search?: string;
  warehouse?: string;
  item?: string;
  movementType?: string;
  direction?: string;
  stockState?: string;
  location?: string;
  lot?: string;
  documentType?: string;
  documentRef?: string;
  dateFrom?: string;
  dateTo?: string;
  limit?: number;
};

function inventoryLedgerQuery(filters: InventoryLedgerFilters = {}) {
  const params = new URLSearchParams();
  if (filters.search) params.set("search", filters.search);
  if (filters.warehouse) params.set("warehouse", filters.warehouse);
  if (filters.item) params.set("item", filters.item);
  if (filters.movementType) params.set("movement_type", filters.movementType);
  if (filters.direction) params.set("direction", filters.direction);
  if (filters.stockState) params.set("stock_state", filters.stockState);
  if (filters.location) params.set("location", filters.location);
  if (filters.lot) params.set("lot", filters.lot);
  if (filters.documentType) params.set("document_type", filters.documentType);
  if (filters.documentRef) params.set("document_ref", filters.documentRef);
  if (filters.dateFrom) params.set("date_from", filters.dateFrom);
  if (filters.dateTo) params.set("date_to", filters.dateTo);
  if (filters.limit) params.set("limit", String(filters.limit));
  const query = params.toString();
  return query ? `?${query}` : "";
}

export async function fetchInventoryLedgerEntries(filters: InventoryLedgerFilters = {}) {
  return requestJson<{ results?: InventoryLedgerEntry[] }>(`/api/v1/inventory/ledger/${inventoryLedgerQuery(filters)}`);
}

export type ManualStockAdjustmentPayload = {
  warehouse_ref: string;
  direction: "increase" | "decrease";
  item_ref: string;
  location_ref: string;
  lot_ref?: string;
  quantity: string;
  uom: string;
  reason: string;
};

export type ManualStockAdjustmentResult = ManualStockAdjustmentPayload & {
  document_ref: string;
  stock_state: string;
  ledger_entries?: InventoryLedgerEntry[];
};

export async function fetchManualStockAdjustments(filters: { warehouse?: string; item?: string; direction?: string; limit?: number } = {}) {
  const params = new URLSearchParams();
  if (filters.warehouse) params.set("warehouse", filters.warehouse);
  if (filters.item) params.set("item", filters.item);
  if (filters.direction) params.set("direction", filters.direction);
  if (filters.limit) params.set("limit", String(filters.limit));
  const query = params.toString();
  return requestJson<{ results?: InventoryLedgerEntry[]; allowed_warehouses?: string[] }>(
    `/api/v1/inventory/manual-adjustments/${query ? `?${query}` : ""}`,
  );
}

export async function createManualStockAdjustment(payload: ManualStockAdjustmentPayload, idempotencyKey?: string) {
  const response = await apiPost<CommandResult<ManualStockAdjustmentResult>>("/api/v1/inventory/manual-adjustments/", payload, { idempotencyKey });
  return response.result;
}
