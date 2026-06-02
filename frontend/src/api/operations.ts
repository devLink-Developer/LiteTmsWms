import { apiGet, requestJson } from "./client";
import { formatAppDateTime } from "../shared/utils/dateFormat";
import { formatIdentifier } from "../shared/utils/identifierFormat";
import { translateStatusLabel } from "../shared/utils/statusLabels";
import type { Kpi, OperationModule, OperationRow, StatusTone, TimelineEvent } from "../types/operations";

type ApiRecord = Record<string, unknown>;

export type OperationalDashboardKpi = {
  key: string;
  label: string;
  value: number | string;
  tone: StatusTone;
  detail: string;
};

export type DashboardCountDatum = {
  key: string;
  label: string;
  count: number;
};

export type DashboardQuantityByUom = {
  uom: string;
  quantity: string;
};

export type DashboardStockState = {
  key: string;
  label: string;
  buckets: number;
  quantity_by_uom: DashboardQuantityByUom[];
};

export type DashboardLedgerDay = {
  date: string;
  increase_count: number;
  decrease_count: number;
  increase_quantity_by_uom: DashboardQuantityByUom[];
  decrease_quantity_by_uom: DashboardQuantityByUom[];
};

export type DashboardRouteLoad = {
  route_number: string;
  status: string;
  planned_date: string;
  stops: number;
  planned_weight_kg: string;
  planned_volume_m3: string;
};

export type OperationalDashboardAlert = {
  key: string;
  label: string;
  value: number;
  tone: StatusTone;
  detail: string;
};

export type OperationalDashboardModule = {
  key: string;
  label: string;
  path: string;
  count: number;
  active: number;
  issues: number;
  tone: StatusTone;
};

export type OperationalDashboard = {
  generated_at: string;
  scope: {
    warehouse_ref: string;
    mode: string;
    window: string;
    authorized_warehouses?: string[];
  };
  kpis: OperationalDashboardKpi[];
  charts: {
    fulfillment_status: DashboardCountDatum[];
    delivery_pipeline: DashboardCountDatum[];
    stock_by_state: DashboardStockState[];
    ledger_by_day: DashboardLedgerDay[];
    route_load: DashboardRouteLoad[];
    module_coverage: DashboardCountDatum[];
  };
  alerts: OperationalDashboardAlert[];
  modules: OperationalDashboardModule[];
};

const statusTones: Record<string, StatusTone> = {
  created: "neutral",
  draft: "neutral",
  pending: "neutral",
  planned: "success",
  delivered: "success",
  completed: "success",
  closed: "success",
  cancelled: "danger",
  failed: "danger",
  blocked: "danger",
  partial: "warning",
  in_transit: "info",
};

function text(value: unknown, fallback = "-") {
  return formatIdentifier(value, fallback);
}

function toneFor(status: string): StatusTone {
  return statusTones[status.toLowerCase()] ?? "info";
}

function first(record: ApiRecord, keys: string[], fallback = "-") {
  const value = keys.map((key) => record[key]).find((entry) => entry !== null && entry !== undefined && entry !== "");
  return text(value, fallback);
}

function objectValue(record: ApiRecord, key: string): ApiRecord {
  const value = record[key];
  return value && typeof value === "object" && !Array.isArray(value) ? (value as ApiRecord) : {};
}

function quantityFor(record: ApiRecord, moduleKey: string) {
  if (moduleKey === "orders") {
    if (Array.isArray(record.lines)) {
      return `${record.lines.length} lineas`;
    }
    return `${first(record, ["lines_count"], "0")} lineas`;
  }
  if (moduleKey === "stock" || moduleKey === "stock-movements") {
    return `${first(record, ["quantity"], "0")} ${first(record, ["uom"], "")}`.trim();
  }
  if (moduleKey === "receipts") {
    return first(record, ["lines_count", "quantity"], "-");
  }
  if (moduleKey === "tasks") {
    return `${first(record, ["total_qty"], "0")} ${first(Array.isArray(record.lines) ? (record.lines[0] as ApiRecord) : {}, ["uom"], "")}`.trim();
  }
  if (moduleKey === "routes") {
    return `${first(record, ["planned_weight_kg"], "0")} kg / ${first(record, ["planned_volume_m3"], "0")} m3`;
  }
  if (moduleKey === "vehicles") {
    return `${first(record, ["max_weight_kg"], "0")} kg / ${first(record, ["max_volume_m3"], "0")} m3`;
  }
  if (Array.isArray(record.lines)) {
    return `${record.lines.length} lineas`;
  }
  return "-";
}

function refFor(record: ApiRecord, moduleKey: string) {
  const keysByModule: Record<string, string[]> = {
    receipts: ["purchase_order_ref", "document_ref", "id"],
    transfers: ["transfer_number", "id"],
    orders: ["fulfillment_number", "sales_order_number", "id"],
    tasks: ["id"],
    deliveries: ["delivery_number", "id"],
    distribution: ["delivery_number", "id"],
    routes: ["route_number", "id"],
    vehicles: ["code", "plate", "id"],
    stock: ["item_ref", "id"],
    "stock-movements": ["document_ref", "id"],
    audits: ["audit_number", "id"],
    dispatch: ["dispatch_number", "id"],
    shipping: ["shipment_number", "id"],
    returns: ["shipment_number", "id"],
  };
  if (moduleKey === "tasks") {
    return first(objectValue(record, "delivery"), ["delivery_number"], first(record, ["id"]));
  }
  return first(record, keysByModule[moduleKey] ?? ["id"]);
}

function ownerFor(record: ApiRecord, moduleKey: string) {
  const keysByModule: Record<string, string[]> = {
    transfers: ["destination_warehouse_ref"],
    receipts: ["supplier_ref"],
    tasks: ["assigned_employee_ref", "prepared_by"],
    orders: ["customer_ref", "sales_order_number"],
    deliveries: ["delivery_mode", "sales_order_number"],
    distribution: ["delivery_mode", "sales_order_number"],
    routes: ["vehicle"],
    vehicles: ["plate"],
    stock: ["stock_state"],
    "stock-movements": ["document_type", "source_ref", "stock_state"],
    audits: ["blind_count"],
    dispatch: ["customer_ref"],
    shipping: ["delivery_ref", "route_ref"],
    returns: ["delivery_ref", "route_ref"],
  };
  if (moduleKey === "tasks") {
    const order = objectValue(record, "order");
    return first(record, keysByModule.tasks, first(order, ["customer_ref", "sales_order_number"]));
  }
  return first(record, keysByModule[moduleKey] ?? ["document_type", "source_ref", "customer_ref"]);
}

function warehouseFor(record: ApiRecord, moduleKey: string) {
  if (moduleKey === "transfers") {
    return `${first(record, ["origin_warehouse_ref"])} -> ${first(record, ["destination_warehouse_ref"])}`;
  }
  return first(record, ["warehouse_ref", "warehouse", "origin_warehouse_ref"], "-");
}

function timelineFor(record: ApiRecord): TimelineEvent[] {
  if (Array.isArray(record.movements)) {
    return record.movements.map((entry, index) => {
      const movement = entry && typeof entry === "object" ? (entry as ApiRecord) : {};
      const routeNumber = first(movement, ["route_number"], "");
      const documentNumber = first(movement, ["document_number"], "");
      const deliveredQty = first(movement, ["delivered_qty"], "");
      const returnedQty = first(movement, ["returned_qty"], "");
      const details = [
        first(movement, ["detail"], ""),
        routeNumber ? `Hoja de ruta ${routeNumber}` : "",
        documentNumber ? `Remito ${documentNumber}` : "",
        deliveredQty ? `Entregado ${deliveredQty}` : "",
        returnedQty ? `Devuelto ${returnedQty}` : "",
      ]
        .filter(Boolean)
        .join(" / ");
      return {
        id: first(movement, ["key", "source_ref"], `movement-${index}`),
        label: first(movement, ["label"], "Movimiento"),
        actor: first(movement, ["actor", "source_type"], "api"),
        at: formatAppDateTime(first(movement, ["at"], ""), first(movement, ["at"], "-")),
        details: details || translateStatusLabel(first(movement, ["status"], "Movimiento informado por backend.")),
      };
    });
  }

  const events = [
    ["created_at", "Creado"],
    ["updated_at", "Actualizado"],
    ["posted_at", "Posteado"],
    ["planned_date", "Fecha planificada"],
  ] as const;

  return events
    .filter(([key]) => record[key])
    .map(([key, label]) => ({
      id: key,
      label,
      actor: "api",
      at: formatAppDateTime(text(record[key]), text(record[key])),
      details: `Valor informado por backend para ${key}.`,
    }));
}

export function mapOperationRows(moduleKey: string, records: ApiRecord[]): OperationRow[] {
  return records.map((record) => {
    const status = first(record, ["status", "movement_type", "stock_state"], "sin estado");
    return {
      id: first(record, ["id", "delivery_number", "fulfillment_number", "route_number", "code"]),
      ref: refFor(record, moduleKey),
      status,
      statusTone: toneFor(status),
      warehouse: warehouseFor(record, moduleKey),
      owner: ownerFor(record, moduleKey),
      priority: moduleKey === "vehicles" ? translateStatusLabel(first(record, ["status"])) : "-",
      quantity: quantityFor(record, moduleKey),
      sla: formatAppDateTime(first(record, ["planned_date", "posted_at"], ""), "-"),
      raw: record,
      timeline: timelineFor(record),
    };
  });
}

export function buildKpis(rows: OperationRow[]): Kpi[] {
  const total = rows.length;
  const warnings = rows.filter((row) => row.statusTone === "warning").length;
  const critical = rows.filter((row) => row.statusTone === "danger").length;
  return [
    { label: "Registros", value: String(total), delta: "API", tone: "info" },
    { label: "En revision", value: String(warnings), delta: "warning", tone: warnings > 0 ? "warning" : "success" },
    { label: "Criticos", value: String(critical), delta: critical > 0 ? "accion" : "sin bloqueos", tone: critical > 0 ? "danger" : "success" },
  ];
}

function operationPathWithFilters(module: OperationModule, filters?: Record<string, string>) {
  if (!filters) {
    return module.apiPath;
  }
  const [path, query = ""] = module.apiPath.split("?");
  const params = new URLSearchParams(query);
  const search = filters.busqueda?.trim();
  const status = filters.estado?.trim();
  const warehouse = filters.warehouse?.trim();
  const date = filters.fecha?.trim();
  if (search) params.set("q", search);
  if (status) params.set("status", status);
  if (warehouse) params.set("warehouse", warehouse);
  if (date) params.set(module.key === "orders" ? "requested_date" : "planned_date", date);
  const nextQuery = params.toString();
  return nextQuery ? `${path}?${nextQuery}` : path;
}

export async function fetchOperationRows(module: OperationModule, filters?: Record<string, string>) {
  const result = await apiGet<ApiRecord>(operationPathWithFilters(module, filters));
  if (result.error) {
    throw new Error(result.error.message);
  }
  return mapOperationRows(module.key, result.results ?? []);
}

export async function fetchOperationalOverview() {
  const result = await apiGet<never>("/api/v1/logistics/overview/");
  if (result.error) {
    throw new Error(result.error.message);
  }
  return result;
}

export async function fetchOperationalDashboard() {
  return requestJson<OperationalDashboard>("/api/v1/logistics/dashboard/");
}
