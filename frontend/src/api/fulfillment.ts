import { actorHeaders, apiGet, apiPost, apiUrl } from "./client";

export type ApiFulfillmentLine = {
  id: string;
  legacy_line_id: string;
  item_ref: string;
  warehouse_ref: string;
  ordered_qty: string;
  reserved_qty: string;
  prepared_qty: string;
  delivered_qty: string;
  cancelled_qty: string;
  pending_qty: string;
  planned_qty?: string;
  stock_available?: string;
  max_dispatchable_qty?: string;
  uom: string;
};

export type ApiDeliveryLine = {
  id: string;
  fulfillment_line_id: string;
  legacy_line_id: string;
  item_ref: string;
  planned_qty: string;
  dispatched_qty: string;
  delivered_qty: string;
  uom: string;
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
  address_snapshot?: Record<string, string>;
  lines: ApiDeliveryLine[];
  documents: ApiDeliveryDocument[];
  preparation_task?: ApiDeliveryPreparationTask | null;
};

export type ApiFulfillmentOrder = {
  id: string;
  created_at: string;
  updated_at: string;
  fulfillment_number: string;
  status: string;
  sales_order_number: string;
  transaction_number: string;
  customer_ref: string;
  customer_dni?: string;
  customer_document?: string;
  delivery_mode: string;
  requested_date: string | null;
  warehouse_ref: string;
  source_hash: string;
  lines: ApiFulfillmentLine[];
  deliveries: ApiDeliveryOrder[];
};

type CommandResult<T> = {
  result: T;
};

export type ExpeditionQueueSearch = {
  mode: "sales_order" | "customer_ref" | "customer_dni";
  value: string;
};

function expeditionQueuePath(search: ExpeditionQueueSearch) {
  const params = new URLSearchParams({ pending_delivery: "true" });
  if (search.mode === "sales_order") {
    params.set("sales_order_number", search.value);
  }
  if (search.mode === "customer_ref") {
    params.set("customer_ref", search.value);
  }
  if (search.mode === "customer_dni") {
    params.set("customer_dni", search.value);
  }
  return `/api/v1/fulfillment/expedition-queue/?${params.toString()}`;
}

export async function fetchExpeditionQueue(search: ExpeditionQueueSearch) {
  const result = await apiGet<ApiFulfillmentOrder>(expeditionQueuePath(search));
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
    lines: Array<{ fulfillment_line_id: string; split_qty: number }>;
  },
) {
  const result = await apiPost<CommandResult<ApiDeliveryOrder>>(`/api/v1/fulfillment/${fulfillmentId}/split`, payload);
  return result.result;
}

export async function confirmDeliveryStock(deliveryId: string) {
  const result = await apiPost<CommandResult<ApiDeliveryOrder>>(
    `/api/v1/fulfillment/deliveries/${deliveryId}/validate-stock`,
  );
  return result.result;
}

export async function sendDeliveryToPrepare(deliveryId: string) {
  const result = await apiPost<CommandResult<ApiDeliveryOrder>>(
    `/api/v1/fulfillment/deliveries/${deliveryId}/send-to-prepare`,
  );
  return result.result;
}

export async function markDeliveryPrepared(deliveryId: string) {
  const result = await apiPost<CommandResult<ApiDeliveryOrder>>(
    `/api/v1/fulfillment/deliveries/${deliveryId}/mark-prepared`,
  );
  return result.result;
}

export async function issueDeliveryRemito(deliveryId: string) {
  const result = await apiPost<CommandResult<ApiDeliveryDocument>>(`/api/v1/fulfillment/deliveries/${deliveryId}/remito`);
  return result.result;
}

export async function downloadDeliveryRemitoPdf(deliveryId: string, documentNumber?: string) {
  const response = await fetch(apiUrl(`/api/v1/fulfillment/deliveries/${deliveryId}/remito.pdf`), {
    headers: { Accept: "application/pdf", ...actorHeaders() },
  });
  if (!response.ok) {
    throw new Error(`No se pudo descargar el remito PDF (${response.status}).`);
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
