import { requestJson } from "./client";

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
