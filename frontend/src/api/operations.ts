import { apiGet } from "./client";
import type { Kpi, OperationModule, OperationRow, StatusTone, TimelineEvent } from "../types/operations";

type ApiRecord = Record<string, unknown>;

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
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function toneFor(status: string): StatusTone {
  return statusTones[status.toLowerCase()] ?? "info";
}

function first(record: ApiRecord, keys: string[], fallback = "-") {
  const value = keys.map((key) => record[key]).find((entry) => entry !== null && entry !== undefined && entry !== "");
  return text(value, fallback);
}

function quantityFor(record: ApiRecord, moduleKey: string) {
  if (moduleKey === "stock" || moduleKey === "receipts") {
    return `${first(record, ["quantity"], "0")} ${first(record, ["uom"], "")}`.trim();
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
    receipts: ["document_ref", "id"],
    transfers: ["transfer_number", "id"],
    orders: ["fulfillment_number", "sales_order_number", "id"],
    deliveries: ["delivery_number", "id"],
    routes: ["route_number", "id"],
    vehicles: ["code", "plate", "id"],
    stock: ["item_ref", "id"],
    audits: ["audit_number", "id"],
    dispatch: ["dispatch_number", "id"],
    shipping: ["shipment_number", "id"],
  };
  return first(record, keysByModule[moduleKey] ?? ["id"]);
}

function ownerFor(record: ApiRecord, moduleKey: string) {
  const keysByModule: Record<string, string[]> = {
    transfers: ["destination_warehouse_ref"],
    orders: ["customer_ref", "sales_order_number"],
    deliveries: ["delivery_mode", "sales_order_number"],
    routes: ["vehicle"],
    vehicles: ["plate"],
    stock: ["stock_state"],
    audits: ["blind_count"],
    dispatch: ["customer_ref"],
    shipping: ["delivery_ref", "route_ref"],
  };
  return first(record, keysByModule[moduleKey] ?? ["document_type", "source_ref", "customer_ref"]);
}

function warehouseFor(record: ApiRecord, moduleKey: string) {
  if (moduleKey === "transfers") {
    return `${first(record, ["origin_warehouse_ref"])} -> ${first(record, ["destination_warehouse_ref"])}`;
  }
  return first(record, ["warehouse_ref", "warehouse", "origin_warehouse_ref"], "-");
}

function timelineFor(record: ApiRecord): TimelineEvent[] {
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
      at: text(record[key]),
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
      priority: moduleKey === "vehicles" ? first(record, ["status"]) : "-",
      quantity: quantityFor(record, moduleKey),
      sla: first(record, ["planned_date", "posted_at"], "-"),
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

export async function fetchOperationRows(module: OperationModule) {
  const result = await apiGet<ApiRecord>(module.apiPath);
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
