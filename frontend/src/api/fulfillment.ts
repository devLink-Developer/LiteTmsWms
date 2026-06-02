import { apiGet, apiHeaders, apiPost, trackedFetch, type RequestTrackingOptions } from "./client";

export type ApiFulfillmentLine = {
  id: string;
  legacy_line_id: string;
  item_ref: string;
  item_name?: string;
  item_long_name?: string;
  category?: string;
  coverage_group?: string;
  warehouse_ref: string;
  ordered_qty: string;
  reserved_qty: string;
  prepared_qty: string;
  delivered_qty: string;
  cancelled_qty: string;
  returned_qty?: string;
  pending_qty: string;
  planned_qty?: string;
  stock_available?: string;
  max_dispatchable_qty?: string;
  uom: string;
  sales_uom?: string;
  delivery_uom?: string;
  conversion_factor?: string;
  planned_delivery_unit_qty?: string;
  max_dispatchable_delivery_unit_qty?: string;
  unit_weight_kg?: string;
  unit_volume_m3?: string;
  planned_weight_kg?: string;
  planned_volume_m3?: string;
  item_snapshot?: Record<string, string>;
};

export type ApiDeliveryLine = {
  id: string;
  fulfillment_line_id: string;
  legacy_line_id: string;
  item_ref: string;
  item_name?: string;
  planned_qty: string;
  delivery_unit_qty?: string;
  delivery_uom?: string;
  conversion_factor?: string;
  dispatched_qty: string;
  delivered_qty: string;
  uom: string;
  warehouse_ref?: string;
  store_ref?: string;
  planned_weight_kg?: string;
  planned_volume_m3?: string;
  item_snapshot?: Record<string, string>;
};

export type ApiDeliveryDocument = {
  id: string;
  document_number: string;
  document_type: string;
  status: string;
  issued_at: string;
  delivery_id?: string;
  sales_order_number?: string;
};

export type ApiDeliveryPreparationTask = {
  id: string;
  delivery_id: string;
  status: string;
  assigned_employee_ref: string;
  assigned_at: string | null;
  prepared_by: string;
  prepared_at: string | null;
  notes: string;
};

export type ApiPreparationTaskListItem = ApiDeliveryPreparationTask & {
  warehouse_ref: string;
  store_ref: string;
  total_qty: string;
  delivery: {
    id: string;
    delivery_number: string;
    status: string;
    delivery_mode: string;
    planned_date: string | null;
  };
  order: {
    id: string;
    fulfillment_number: string;
    sales_order_number: string;
    transaction_number: string;
    customer_ref: string;
  };
  lines: Array<{
    id: string;
    item_ref: string;
    warehouse_ref: string;
    planned_qty: string;
    uom: string;
    legacy_line_id: string;
  }>;
};

export type ApiDeliveryOrder = {
  id: string;
  created_at?: string;
  updated_at?: string;
  delivery_number: string;
  status: string;
  delivery_mode: string;
  planned_date: string | null;
  fulfillment_id: string;
  sales_order_number: string;
  warehouse_ref?: string;
  store_ref?: string;
  address_snapshot?: Record<string, string>;
  route_sheet?: {
    id: string;
    route_number: string;
    status: string;
    stop_id?: string;
    stop_status?: string;
  } | null;
  lines: ApiDeliveryLine[];
  documents: ApiDeliveryDocument[];
  preparation_task?: ApiDeliveryPreparationTask | null;
  totals?: {
    delivery_unit_qty: string;
    commercial_qty: string;
    planned_weight_kg: string;
    planned_volume_m3: string;
  };
  movements?: ApiLogisticsMovement[];
};

export type ApiLogisticsMovement = {
  key: string;
  at: string | null;
  label: string;
  status?: string;
  detail?: string;
  actor?: string;
  source_type?: string;
  source_ref?: string;
  route_number?: string;
  document_number?: string;
  delivered_qty?: string;
  returned_qty?: string;
  uom?: string;
};

export type ApiFulfillmentImpact = {
  id: string;
  type: "anulacion" | "devolucion";
  impact_type: "annulment" | "return";
  status: string;
  sales_order_number: string;
  transaction_number: string;
  original_sales_order_number: string;
  warehouse_ref: string;
  impact_date: string | null;
  lines: Array<{
    id: string;
    fulfillment_line_id?: string;
    item_ref: string;
    warehouse_ref: string;
    quantity: string;
    applied_qty: string;
    uom: string;
  }>;
};

export type ApiRepartoDelivery = {
  id: string;
  source_type: "delivery" | "fulfillment";
  delivery_id: string | null;
  delivery_number: string;
  status: string;
  delivery_mode: string;
  warehouse_ref: string;
  planned_date: string | null;
  fulfillment_id: string;
  fulfillment_number: string;
  sales_order_number: string;
  transaction_number: string;
  customer_ref: string;
  documents_count: number;
  lines_count: number;
  total_qty: string;
  total_weight_kg: string;
  total_volume_m3: string;
  address_snapshot?: Record<string, string>;
  lines: Array<{
    delivery_line_id?: string | null;
    fulfillment_line_id: string;
    item_ref: string;
    item_name?: string;
    item_long_name?: string;
    warehouse_ref: string;
    split_qty: string;
    delivery_unit_qty?: string;
    uom: string;
    delivery_uom?: string;
    conversion_factor?: string;
    planned_weight_kg?: string;
    planned_volume_m3?: string;
    stock_available?: string;
    max_dispatchable_qty?: string;
  }>;
};

export type ApiStockValidationIssue = {
  line_id: string;
  item_ref: string;
  warehouse_ref: string;
  planned_qty: string;
  available_qty: string;
  uom: string;
  reason?: string;
};

export type ApiStockValidationResult = {
  reference_type: string;
  reference_id: string;
  reference_number: string;
  status: "ok" | "insufficient";
  can_confirm: boolean;
  issues: ApiStockValidationIssue[];
  lines: Array<ApiStockValidationIssue & { fulfillment_line_id?: string; packed_qty?: string }>;
};

export type ApiCustomerSnapshot = {
  customer_ref: string;
  name: string;
  document_type?: string;
  document_number?: string;
  phone?: string;
  email?: string;
  address?: Record<string, string>;
  address_text?: string;
  source?: string;
};

export type ApiPickupAuthorization = {
  name: string;
  reference?: string;
  source?: string;
};

export type ApiFulfillmentOrder = {
  id: string;
  created_at: string;
  updated_at: string;
  fulfillment_number: string;
  status: string;
  sales_order_type?: string;
  sales_order_number: string;
  transaction_number: string;
  customer_ref: string;
  customer_dni?: string;
  customer_document?: string;
  customer?: ApiCustomerSnapshot;
  pickup_authorization?: ApiPickupAuthorization;
  delivery_mode: string;
  requested_date: string | null;
  warehouse_ref: string;
  source_hash: string;
  lines: ApiFulfillmentLine[];
  deliveries: ApiDeliveryOrder[];
  impacts?: ApiFulfillmentImpact[];
  movements?: ApiLogisticsMovement[];
};

type CommandResult<T> = {
  result: T;
};

export type ExpeditionCommandOptions = {
  allow_past_reparto_date?: boolean;
  target_warehouse_ref?: string;
};

export type ExpeditionQueueSearch = {
  mode: "sales_order" | "customer_ref" | "customer_dni";
  value: string;
  warehouseRef?: string;
};

function expeditionQueuePath(search: ExpeditionQueueSearch) {
  const params = new URLSearchParams();
  if (search.mode === "sales_order") {
    params.set("sales_order_number", search.value);
  }
  if (search.mode === "customer_ref") {
    params.set("customer_ref", search.value);
  }
  if (search.mode === "customer_dni") {
    params.set("customer_dni", search.value);
  }
  if (search.warehouseRef) {
    params.set("target_warehouse_ref", search.warehouseRef);
  }
  return `/api/v1/fulfillment/expedition-queue/?${params.toString()}`;
}

export async function fetchExpeditionQueue(search: ExpeditionQueueSearch, options?: RequestTrackingOptions) {
  const result = await apiGet<ApiFulfillmentOrder>(expeditionQueuePath(search), options);
  if (result.error) {
    throw new Error(result.error.message);
  }
  return result.results ?? [];
}

export async function fetchRepartoDeliveries(filters: {
  plannedDate?: string;
  warehouse?: string;
  status?: string;
  query?: string;
}) {
  const params = new URLSearchParams();
  if (filters.plannedDate) params.set("planned_date", filters.plannedDate);
  if (filters.warehouse) params.set("warehouse", filters.warehouse);
  if (filters.status) params.set("status", filters.status);
  if (filters.query) params.set("q", filters.query);
  const result = await apiGet<ApiRepartoDelivery>(`/api/v1/fulfillment/reparto-confirmation/?${params.toString()}`);
  if (result.error) {
    throw new Error(result.error.message);
  }
  return result.results ?? [];
}

export async function splitFulfillmentDelivery(
  fulfillmentId: string,
  payload: {
    delivery_mode: string;
    planned_date: string;
    reason: string;
    receiver?: string;
    reference?: string;
    lines: Array<{ fulfillment_line_id: string; delivery_unit_qty?: number; split_qty?: number }>;
  } & ExpeditionCommandOptions,
) {
  const result = await apiPost<CommandResult<ApiDeliveryOrder>>(`/api/v1/fulfillment/${fulfillmentId}/split`, payload);
  return result.result;
}

export async function checkFulfillmentStock(
  fulfillmentId: string,
  lines: Array<{ fulfillment_line_id: string; delivery_unit_qty?: number; split_qty?: number }>,
  options: ExpeditionCommandOptions = {},
) {
  const result = await apiPost<CommandResult<ApiStockValidationResult>>(
    `/api/v1/fulfillment/${fulfillmentId}/stock-check`,
    { lines, ...options },
  );
  return result.result;
}

export async function checkDeliveryStock(deliveryId: string, options: ExpeditionCommandOptions = {}) {
  const result = await apiPost<CommandResult<ApiStockValidationResult>>(
    `/api/v1/fulfillment/deliveries/${deliveryId}/stock-check`,
    options,
  );
  return result.result;
}

export async function confirmDeliveryStock(deliveryId: string, options: ExpeditionCommandOptions = {}) {
  const result = await apiPost<CommandResult<ApiDeliveryOrder>>(
    `/api/v1/fulfillment/deliveries/${deliveryId}/validate-stock`,
    options,
  );
  return result.result;
}

export async function confirmAvailableDeliveryStock(
  deliveryId: string,
  payload: {
    lines: Array<{ delivery_line_id: string; planned_qty: number }>;
  } & ExpeditionCommandOptions,
) {
  const result = await apiPost<CommandResult<ApiDeliveryOrder>>(
    `/api/v1/fulfillment/deliveries/${deliveryId}/confirm-available`,
    payload,
  );
  return result.result;
}

export async function reassignDeliveryWarehouse(deliveryId: string, payload: Required<ExpeditionCommandOptions>) {
  const result = await apiPost<CommandResult<ApiDeliveryOrder>>(
    `/api/v1/fulfillment/deliveries/${deliveryId}/reassign-warehouse`,
    payload,
  );
  return result.result;
}

export async function sendDeliveryToPrepare(deliveryId: string, options: ExpeditionCommandOptions = {}) {
  const result = await apiPost<CommandResult<ApiDeliveryOrder>>(
    `/api/v1/fulfillment/deliveries/${deliveryId}/send-to-prepare`,
    options,
  );
  return result.result;
}

export async function markDeliveryPrepared(deliveryId: string, options: ExpeditionCommandOptions = {}) {
  const result = await apiPost<CommandResult<ApiDeliveryOrder>>(
    `/api/v1/fulfillment/deliveries/${deliveryId}/mark-prepared`,
    options,
  );
  return result.result;
}

export async function fetchPreparationTasks(status = "open", options?: RequestTrackingOptions) {
  const params = new URLSearchParams({ status });
  const result = await apiGet<ApiPreparationTaskListItem>(`/api/v1/fulfillment/preparation-tasks/?${params.toString()}`, options);
  if (result.error) {
    throw new Error(result.error.message);
  }
  return result.results ?? [];
}

export async function markPreparationTaskPrepared(taskId: string) {
  const result = await apiPost<CommandResult<ApiDeliveryOrder>>(
    `/api/v1/fulfillment/preparation-tasks/${taskId}/mark-prepared`,
  );
  return result.result;
}

export async function issueDeliveryRemito(deliveryId: string, options: ExpeditionCommandOptions = {}) {
  const result = await apiPost<CommandResult<ApiDeliveryDocument>>(`/api/v1/fulfillment/deliveries/${deliveryId}/remito`, options);
  return result.result;
}

export async function downloadDeliveryRemitoPdf(deliveryId: string, documentNumber?: string) {
  const response = await trackedFetch(`/api/v1/fulfillment/deliveries/${deliveryId}/remito.pdf`, {
    credentials: "include",
    headers: apiHeaders({ Accept: "application/pdf" }),
  }, "Descargando remito...");
  if (!response.ok) {
    throw new Error(`Remito PDF no descargado (${response.status}).`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${documentNumber ?? `remito-${deliveryId}`}.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
