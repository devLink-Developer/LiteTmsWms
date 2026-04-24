import { type FormEvent, useEffect, useMemo, useState } from "react";

import {
  confirmDeliveryStock,
  downloadDeliveryRemitoPdf,
  fetchExpeditionQueue,
  issueDeliveryRemito,
  markDeliveryPrepared,
  sendDeliveryToPrepare,
  splitFulfillmentDelivery,
  type ApiDeliveryOrder,
  type ExpeditionQueueSearch,
  type ApiFulfillmentOrder,
} from "../../api/fulfillment";
import { StatusBadge } from "../../shared/components/StatusBadge";
import type { StatusTone } from "../../types/operations";

type DeliveryStatus = "draft" | "reserved" | "preparing" | "prepared" | "remito";
type DeliverySource = "api" | "draft";

type DeliveryLineAllocation = {
  lineId: string;
  qty: number;
};

type DeliveryDraft = {
  id: string;
  number: string;
  source: DeliverySource;
  status: DeliveryStatus;
  mode: string;
  plannedDate: string;
  receiver: string;
  reference: string;
  remitoNumber?: string;
  preparationAssignee?: string;
  preparationTaskStatus?: string;
  lines: DeliveryLineAllocation[];
};

type ExpeditionLine = {
  id: string;
  itemRef: string;
  description: string;
  orderedQty: number;
  reservedQty: number;
  preparedQty: number;
  deliveredQty: number;
  pendingQty: number;
  plannedQty: number;
  stockAvailable: number;
  maxDispatchableQty: number;
  uom: string;
  warehouse: string;
  location: string;
};

type ExpeditionOrder = {
  id: string;
  orderNumber: string;
  transactionNumber: string;
  customerName: string;
  customerRef: string;
  customerDni: string;
  warehouse: string;
  base: string;
  status: string;
  priority: string;
  deliveryType: string;
  requestedDate: string;
  address: string;
  contact: string;
  lines: ExpeditionLine[];
  deliveries: DeliveryDraft[];
};

type DraftState = {
  orderId: string;
  delivery: DeliveryDraft;
} | null;

type ValidationMessage = {
  tone: StatusTone;
  text: string;
} | null;

type SearchMode = ExpeditionQueueSearch["mode"];

type SearchState = {
  mode: SearchMode;
  value: string;
};

const statusTone: Record<DeliveryStatus, StatusTone> = {
  draft: "neutral",
  reserved: "success",
  preparing: "warning",
  prepared: "success",
  remito: "info",
};

const statusLabel: Record<DeliveryStatus, string> = {
  draft: "creada",
  reserved: "stock reservado",
  preparing: "en preparacion",
  prepared: "preparada",
  remito: "remito generado",
};

const orderStatusTone: Record<string, StatusTone> = {
  pendiente: "neutral",
  parcial: "warning",
  "stock reservado": "success",
  "en preparacion": "warning",
  preparada: "success",
};

const searchModeLabels: Record<SearchMode, string> = {
  sales_order: "Pedido VENT8",
  customer_ref: "ID cliente",
  customer_dni: "DNI cliente",
};

const searchModePlaceholders: Record<SearchMode, string> = {
  sales_order: "Ej. VENT8-000184",
  customer_ref: "Ej. CLI-10924",
  customer_dni: "Ej. 30111222",
};

function asNumber(value: string | number | null | undefined) {
  const numberValue = Number(value ?? 0);
  return Number.isFinite(numberValue) ? numberValue : 0;
}

function formatQty(value: number, uom?: string) {
  return `${new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 }).format(value)}${uom ? ` ${uom}` : ""}`;
}

function getDeliveryLineQty(delivery: DeliveryDraft | undefined, lineId: string) {
  return delivery?.lines.find((line) => line.lineId === lineId)?.qty ?? 0;
}

function sumDeliveryQty(delivery: DeliveryDraft) {
  return delivery.lines.reduce((total, line) => total + line.qty, 0);
}

function getMaxDispatchableQty(line: ExpeditionLine, delivery?: DeliveryDraft) {
  const currentDeliveryQty = delivery?.source === "api" && delivery.status !== "remito" ? getDeliveryLineQty(delivery, line.id) : 0;
  return Math.max(0, line.maxDispatchableQty + currentDeliveryQty);
}

function isOperationalDelivery(delivery: DeliveryDraft) {
  return delivery.status !== "remito";
}

function deliveryStatusFromApi(delivery: ApiDeliveryOrder): DeliveryStatus {
  if (delivery.documents.some((document) => document.document_type === "remito" && document.status === "issued")) {
    return "remito";
  }
  if (delivery.status === "delivered_complete" || delivery.status === "delivered_partial") {
    return "remito";
  }
  if (delivery.status === "loaded" || delivery.status === "prepared") {
    return "prepared";
  }
  if (delivery.status === "assigned" || delivery.status === "preparing") {
    return "preparing";
  }
  if (delivery.status === "confirmed" || delivery.status === "planned" || delivery.status === "reserved") {
    return "reserved";
  }
  return "draft";
}

function orderStatusFromApi(order: ApiFulfillmentOrder) {
  if (order.deliveries.some((delivery) => deliveryStatusFromApi(delivery) === "remito")) {
    return "parcial";
  }
  if (order.deliveries.some((delivery) => deliveryStatusFromApi(delivery) === "prepared")) {
    return "preparada";
  }
  if (order.deliveries.some((delivery) => deliveryStatusFromApi(delivery) === "preparing")) {
    return "en preparacion";
  }
  if (order.deliveries.some((delivery) => deliveryStatusFromApi(delivery) === "reserved")) {
    return "stock reservado";
  }
  return "pendiente";
}

function deliveryFromApi(delivery: ApiDeliveryOrder): DeliveryDraft {
  const remito = delivery.documents.find((document) => document.document_type === "remito" && document.status === "issued");
  return {
    id: delivery.id,
    number: delivery.delivery_number,
    source: "api",
    status: deliveryStatusFromApi(delivery),
    mode: delivery.delivery_mode,
    plannedDate: delivery.planned_date ?? "",
    receiver: delivery.address_snapshot?.receiver ?? delivery.sales_order_number,
    reference: delivery.address_snapshot?.reference ?? delivery.delivery_number,
    remitoNumber: remito?.document_number,
    preparationAssignee: delivery.preparation_task?.assigned_employee_ref,
    preparationTaskStatus: delivery.preparation_task?.status,
    lines: delivery.lines.map((line) => ({
      lineId: line.fulfillment_line_id,
      qty: asNumber(line.planned_qty),
    })),
  };
}

function orderFromApi(order: ApiFulfillmentOrder): ExpeditionOrder {
  const firstDeliveryAddress = order.deliveries.find((delivery) => delivery.address_snapshot)?.address_snapshot ?? {};
  const requestedDate = order.requested_date ?? order.created_at.slice(0, 10);
  return {
    id: order.id,
    orderNumber: order.sales_order_number || order.fulfillment_number,
    transactionNumber: order.transaction_number,
    customerName: order.customer_ref,
    customerRef: order.customer_ref,
    customerDni: order.customer_dni ?? order.customer_document ?? "",
    warehouse: order.warehouse_ref,
    base: order.warehouse_ref || "S/E",
    status: orderStatusFromApi(order),
    priority: order.deliveries.length ? "En gestion" : "Nueva",
    deliveryType: order.delivery_mode || "Sin modalidad",
    requestedDate,
    address: [firstDeliveryAddress.description, firstDeliveryAddress.street, firstDeliveryAddress.city]
      .filter(Boolean)
      .join(" / ") || "Direccion no informada por snapshot TMS/WMS",
    contact: order.customer_ref,
    lines: order.lines.map((line) => ({
      id: line.id,
      itemRef: line.item_ref,
      description: `Linea legacy ${line.legacy_line_id}`,
      orderedQty: asNumber(line.ordered_qty),
      reservedQty: asNumber(line.reserved_qty),
      preparedQty: asNumber(line.prepared_qty),
      deliveredQty: asNumber(line.delivered_qty),
      pendingQty: asNumber(line.pending_qty),
      plannedQty: asNumber(line.planned_qty),
      stockAvailable: asNumber(line.stock_available),
      maxDispatchableQty: asNumber(line.max_dispatchable_qty),
      uom: line.uom,
      warehouse: line.warehouse_ref,
      location: line.warehouse_ref,
    })),
    deliveries: order.deliveries.map(deliveryFromApi),
  };
}

function hasPendingDeliveryQty(order: ExpeditionOrder) {
  return order.lines.some((line) => line.pendingQty > 0);
}

function orderMatchesSearch(order: ExpeditionOrder, search: ExpeditionQueueSearch) {
  const value = search.value.trim().toLowerCase();
  if (!value) {
    return false;
  }
  if (search.mode === "sales_order") {
    return order.orderNumber.toLowerCase() === value || order.transactionNumber.toLowerCase() === value;
  }
  if (search.mode === "customer_ref") {
    return order.customerRef.toLowerCase() === value;
  }
  return true;
}

export function DeliveryExpeditionPage() {
  const [orders, setOrders] = useState<ExpeditionOrder[]>([]);
  const [activeOrderId, setActiveOrderId] = useState("");
  const [activeDeliveryId, setActiveDeliveryId] = useState("");
  const [draftState, setDraftState] = useState<DraftState>(null);
  const [search, setSearch] = useState<SearchState>({
    mode: "sales_order",
    value: "",
  });
  const [submittedSearch, setSubmittedSearch] = useState<ExpeditionQueueSearch | null>(null);
  const [message, setMessage] = useState<ValidationMessage>(null);
  const [loading, setLoading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadQueue(nextSearch: ExpeditionQueueSearch, { silent = false } = {}) {
    if (!silent) {
      setLoading(true);
    }
    try {
      const apiOrders = await fetchExpeditionQueue(nextSearch);
      const nextOrders = apiOrders
        .map(orderFromApi)
        .filter((order) => hasPendingDeliveryQty(order) && orderMatchesSearch(order, nextSearch));
      setOrders(nextOrders);
      setError(null);
      setActiveOrderId((current) => {
        if (current && nextOrders.some((order) => order.id === current)) {
          return current;
        }
        return nextOrders[0]?.id ?? "";
      });
    } catch (apiError) {
      setError(apiError instanceof Error ? apiError.message : "No se pudo cargar la cola real de expedicion.");
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    if (!submittedSearch) {
      return undefined;
    }
    const interval = window.setInterval(() => {
      void loadQueue(submittedSearch, { silent: true });
    }, 60000);
    return () => window.clearInterval(interval);
  }, [submittedSearch]);

  const activeOrder = orders.find((order) => order.id === activeOrderId) ?? orders[0];
  const visibleDeliveries = useMemo(() => {
    if (!activeOrder) {
      return [];
    }
    if (draftState?.orderId === activeOrder.id) {
      return [...activeOrder.deliveries, draftState.delivery];
    }
    return activeOrder.deliveries;
  }, [activeOrder, draftState]);
  const activeDelivery =
    visibleDeliveries.find((delivery) => delivery.id === activeDeliveryId) ?? visibleDeliveries.find(isOperationalDelivery);
  const canEditActiveDelivery = activeDelivery?.source === "draft";

  useEffect(() => {
    if (!activeOrder) {
      setActiveDeliveryId("");
      return;
    }
    if (draftState?.orderId === activeOrder.id) {
      if (activeDeliveryId !== draftState.delivery.id) {
        setActiveDeliveryId(draftState.delivery.id);
      }
      return;
    }
    if (activeDeliveryId && visibleDeliveries.some((delivery) => delivery.id === activeDeliveryId)) {
      return;
    }
    setActiveDeliveryId(visibleDeliveries.find(isOperationalDelivery)?.id ?? "");
  }, [activeDeliveryId, activeOrder, draftState, visibleDeliveries]);

  function updateSearch(key: keyof SearchState, value: string) {
    setSearch((current) => ({ ...current, [key]: value }));
  }

  function executeSearch(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const value = search.value.trim();
    if (!value) {
      setMessage({ tone: "danger", text: "Ingresa un pedido VENT8, ID de cliente o DNI para buscar entregas." });
      setOrders([]);
      setActiveOrderId("");
      setActiveDeliveryId("");
      setDraftState(null);
      return;
    }
    const nextSearch = { mode: search.mode, value };
    setSubmittedSearch(nextSearch);
    setOrders([]);
    setActiveOrderId("");
    setActiveDeliveryId("");
    setDraftState(null);
    setMessage(null);
    void loadQueue(nextSearch);
  }

  function selectOrder(order: ExpeditionOrder) {
    setActiveOrderId(order.id);
    setActiveDeliveryId(order.deliveries.find(isOperationalDelivery)?.id ?? "");
    if (draftState?.orderId !== order.id) {
      setDraftState(null);
    }
    setMessage(null);
  }

  function addDelivery() {
    if (!activeOrder) {
      return;
    }
    const nextIndex = activeOrder.deliveries.length + 1;
    const draft: DeliveryDraft = {
      id: `draft-${activeOrder.id}-${Date.now()}`,
      number: `Nueva entrega ${nextIndex}`,
      source: "draft",
      status: "draft",
      mode: activeOrder.deliveryType,
      plannedDate: activeOrder.requestedDate,
      receiver: activeOrder.customerRef,
      reference: "Pendiente de confirmacion",
      lines: activeOrder.lines.map((line) => ({
        lineId: line.id,
        qty: 0,
      })),
    };
    setDraftState({ orderId: activeOrder.id, delivery: draft });
    setActiveDeliveryId(draft.id);
    setMessage({ tone: "info", text: "Completa cantidades manualmente o usa Entregar todo para cargar el maximo entregable." });
  }

  function updateDraftDelivery(updater: (delivery: DeliveryDraft) => DeliveryDraft) {
    if (!activeOrder || draftState?.orderId !== activeOrder.id) {
      return;
    }
    setDraftState({ orderId: activeOrder.id, delivery: updater(draftState.delivery) });
    setMessage(null);
  }

  function updateLineQty(lineId: string, value: string) {
    if (!canEditActiveDelivery) {
      return;
    }
    const qty = Number(value);
    const nextQty = Number.isFinite(qty) ? Math.max(0, qty) : 0;
    updateDraftDelivery((delivery) => ({
      ...delivery,
      lines: delivery.lines.map((line) => (line.lineId === lineId ? { ...line, qty: nextQty } : line)),
    }));
  }

  function updateDeliveryField(field: keyof Pick<DeliveryDraft, "mode" | "plannedDate" | "receiver" | "reference">, value: string) {
    if (!canEditActiveDelivery) {
      return;
    }
    updateDraftDelivery((delivery) => ({ ...delivery, [field]: value }));
  }

  function fillActiveDeliveryWithMaxQty() {
    if (!canEditActiveDelivery || !activeOrder || !activeDelivery || activeDelivery.status !== "draft") {
      return;
    }
    updateDraftDelivery((delivery) => ({
      ...delivery,
      lines: delivery.lines.map((deliveryLine) => {
        const orderLine = activeOrder.lines.find((line) => line.id === deliveryLine.lineId);
        return {
          ...deliveryLine,
          qty: orderLine ? getMaxDispatchableQty(orderLine, delivery) : 0,
        };
      }),
    }));
  }

  async function persistDraftDelivery(delivery: DeliveryDraft) {
    if (!activeOrder) {
      throw new Error("No hay pedido activo para crear entrega.");
    }
    const lines = delivery.lines
      .filter((line) => line.qty > 0)
      .map((line) => ({ fulfillment_line_id: line.lineId, split_qty: line.qty }));
    if (!lines.length) {
      throw new Error("La entrega no tiene cantidades a despachar.");
    }
    activeOrder.lines.forEach((line) => {
      const plannedQty = getDeliveryLineQty(delivery, line.id);
      const maxQty = getMaxDispatchableQty(line, delivery);
      if (plannedQty > maxQty) {
        throw new Error(`${line.itemRef}: solicitado ${formatQty(plannedQty)}, disponible ${formatQty(maxQty, line.uom)}`);
      }
    });
    const created = await splitFulfillmentDelivery(activeOrder.id, {
      delivery_mode: delivery.mode,
      planned_date: delivery.plannedDate,
      reason: delivery.reference || "Split desde pantalla de expedicion",
      lines,
    });
    setDraftState(null);
    return created;
  }

  async function confirmActiveDelivery() {
    if (!activeDelivery) {
      setMessage({ tone: "danger", text: "Primero selecciona o crea una entrega para confirmar." });
      return null;
    }
    setProcessing(true);
    try {
      const deliveryToConfirm =
        activeDelivery.source === "draft" ? await persistDraftDelivery(activeDelivery) : ({ id: activeDelivery.id } as ApiDeliveryOrder);
      const confirmed = await confirmDeliveryStock(deliveryToConfirm.id);
      if (submittedSearch) {
        await loadQueue(submittedSearch, { silent: true });
      }
      setActiveDeliveryId(confirmed.id);
      setMessage({ tone: "success", text: `${confirmed.delivery_number} confirmada; stock reservado.` });
      return confirmed;
    } catch (apiError) {
      setMessage({
        tone: "danger",
        text: apiError instanceof Error ? apiError.message : "No se pudo confirmar la entrega.",
      });
      return null;
    } finally {
      setProcessing(false);
    }
  }

  async function sendActiveDeliveryToPrepare() {
    if (!activeDelivery || activeDelivery.status !== "reserved") {
      setMessage({ tone: "danger", text: "La entrega debe estar confirmada con stock reservado." });
      return;
    }
    setProcessing(true);
    try {
      const preparing = await sendDeliveryToPrepare(activeDelivery.id);
      if (submittedSearch) {
        await loadQueue(submittedSearch, { silent: true });
      }
      setActiveDeliveryId(preparing.id);
      setMessage({ tone: "success", text: `${preparing.delivery_number} enviada a preparar.` });
    } catch (apiError) {
      setMessage({
        tone: "danger",
        text: apiError instanceof Error ? apiError.message : "No se pudo enviar la entrega a preparar.",
      });
    } finally {
      setProcessing(false);
    }
  }

  async function markActiveDeliveryPrepared() {
    if (!activeDelivery || activeDelivery.status !== "preparing") {
      setMessage({ tone: "danger", text: "La entrega debe estar en preparacion para marcarla preparada." });
      return;
    }
    setProcessing(true);
    try {
      const prepared = await markDeliveryPrepared(activeDelivery.id);
      if (submittedSearch) {
        await loadQueue(submittedSearch, { silent: true });
      }
      setActiveDeliveryId(prepared.id);
      setMessage({ tone: "success", text: `${prepared.delivery_number} marcada como preparada.` });
    } catch (apiError) {
      setMessage({
        tone: "danger",
        text: apiError instanceof Error ? apiError.message : "No se pudo marcar la entrega como preparada.",
      });
    } finally {
      setProcessing(false);
    }
  }

  async function generateRemitoPdf() {
    if (!activeDelivery) {
      return;
    }
    if (activeDelivery.status !== "prepared") {
      setMessage({ tone: "danger", text: "El remito solo se puede generar cuando la entrega esta preparada." });
      return;
    }
    setProcessing(true);
    try {
      const deliveryId = activeDelivery.id;
      const document = await issueDeliveryRemito(deliveryId);
      await downloadDeliveryRemitoPdf(deliveryId, document.document_number);
      if (submittedSearch) {
        await loadQueue(submittedSearch, { silent: true });
      }
      setActiveDeliveryId("");
      setMessage({ tone: "info", text: `Remito ${document.document_number} generado desde TMS/WMS.` });
    } catch (apiError) {
      setMessage({
        tone: "danger",
        text: apiError instanceof Error ? apiError.message : "No se pudo emitir el remito.",
      });
    } finally {
      setProcessing(false);
    }
  }

  const activeDeliveryQty = activeDelivery ? sumDeliveryQty(activeDelivery) : 0;
  const workflowActions = (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        disabled={!activeOrder || processing}
        onClick={addDelivery}
        className="min-h-10 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
      >
        Agregar entrega
      </button>
      <button
        type="button"
        disabled={!activeDelivery || activeDelivery.status !== "draft" || processing}
        onClick={fillActiveDeliveryWithMaxQty}
        className="min-h-10 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
      >
        Entregar todo
      </button>
      <button
        type="button"
        disabled={!activeDelivery || activeDelivery.status !== "draft" || activeDeliveryQty <= 0 || processing}
        onClick={() => void confirmActiveDelivery()}
        className="min-h-10 rounded border border-primary/30 bg-primary/10 px-3 text-[12px] font-semibold text-primaryHover transition hover:bg-primary/15 focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
      >
        Confirmar entrega
      </button>
      <button
        type="button"
        disabled={!activeDelivery || activeDelivery.status !== "reserved" || processing}
        onClick={() => void sendActiveDeliveryToPrepare()}
        className="min-h-10 rounded border border-primary/30 bg-primary/10 px-3 text-[12px] font-semibold text-primaryHover transition hover:bg-primary/15 focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
      >
        Enviar a preparar
      </button>
      <button
        type="button"
        disabled={!activeDelivery || activeDelivery.status !== "preparing" || processing}
        onClick={() => void markActiveDeliveryPrepared()}
        className="min-h-10 rounded border border-primary/30 bg-primary/10 px-3 text-[12px] font-semibold text-primaryHover transition hover:bg-primary/15 focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
      >
        Marcar preparada
      </button>
      <button
        type="button"
        disabled={!activeDelivery || activeDelivery.status !== "prepared" || activeDeliveryQty <= 0 || processing}
        onClick={() => void generateRemitoPdf()}
        className="min-h-10 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:bg-softStart disabled:text-secondaryText"
      >
        Generar remito
      </button>
    </div>
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-3">
      <header className="shrink-0">
        <div className="min-w-0">
          <h1 className="text-[20px] font-semibold text-night">Expedicion de entregas</h1>
        </div>
      </header>

      {error && <div className="shrink-0 rounded border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700">{error}</div>}

      <section className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(0,0.8fr)_minmax(0,1.7fr)_minmax(0,1fr)] gap-3 overflow-hidden xl:grid-cols-[320px_minmax(0,1fr)_360px] xl:grid-rows-1">
        <aside className="flex min-h-0 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="shrink-0 border-b border-borderSoft px-3 py-2">
            <h2 className="text-[13px] font-semibold text-night">Pedidos para expedicion</h2>
          </div>
          <form className="grid shrink-0 gap-2 border-b border-borderSoft bg-softMid px-3 py-2" onSubmit={executeSearch}>
            <div className="grid grid-cols-3 gap-1 rounded border border-borderSoft bg-white p-1" role="group" aria-label="Tipo de busqueda">
              {(Object.keys(searchModeLabels) as SearchMode[]).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => updateSearch("mode", mode)}
                  className={`min-h-8 rounded px-2 text-[11px] font-semibold transition focus:outline-none focus:ring-2 focus:ring-primary/20 ${
                    search.mode === mode ? "bg-primary text-white" : "text-secondaryText hover:bg-softStart hover:text-night"
                  }`}
                >
                  {searchModeLabels[mode]}
                </button>
              ))}
            </div>
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Busqueda
              <input
                value={search.value}
                onChange={(event) => updateSearch("value", event.target.value)}
                className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                placeholder={searchModePlaceholders[search.mode]}
              />
            </label>
            <button
              type="submit"
              disabled={loading}
              className="min-h-9 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:bg-softStart disabled:text-secondaryText"
            >
              {loading ? "Buscando..." : "Buscar pendientes"}
            </button>
          </form>
          <div className="min-h-0 flex-1 overflow-auto">
            {orders.map((order) => (
              <button
                key={order.id}
                type="button"
                onClick={() => selectOrder(order)}
                className={`block w-full border-b border-borderSoft px-3 py-3 text-left transition hover:bg-softStart focus:outline-none focus:ring-2 focus:ring-inset focus:ring-primary/30 ${
                  order.id === activeOrder?.id ? "bg-white" : "bg-surface"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-mono text-[13px] font-semibold text-night">{order.orderNumber}</div>
                    <div className="mt-1 truncate text-[12px] text-secondaryText">{order.customerName}</div>
                  </div>
                  <StatusBadge label={order.status} tone={orderStatusTone[order.status] ?? "neutral"} />
                </div>
                <div className="mt-2 flex flex-wrap gap-1 text-[11px] text-secondaryText">
                  <span className="rounded border border-borderSoft bg-softMid px-2 py-1 font-mono">{order.warehouse}</span>
                  <span className="rounded border border-borderSoft bg-softMid px-2 py-1">{order.deliveryType}</span>
                  <span className="rounded border border-borderSoft bg-softMid px-2 py-1">{order.priority}</span>
                </div>
              </button>
            ))}
            {!orders.length && (
              <div className="px-3 py-6 text-[12px] text-secondaryText">
                {loading
                  ? "Buscando pedidos pendientes..."
                  : submittedSearch
                    ? "No hay pedidos pendientes para la busqueda indicada."
                    : "Ingresa una busqueda para listar pedidos pendientes."}
              </div>
            )}
          </div>
        </aside>

        <main className="flex min-h-0 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          {activeOrder ? (
            <>
              <div className="shrink-0 border-b border-borderSoft px-3 py-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[11px] font-semibold uppercase text-secondaryText">Pedido seleccionado</p>
                  <h2 className="mt-1 font-mono text-[18px] font-semibold text-night">{activeOrder.orderNumber}</h2>
                  <p className="mt-1 max-w-3xl text-[12px] leading-5 text-secondaryText">
                    {activeOrder.customerName} / {activeOrder.address}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-2 text-[11px] md:grid-cols-4">
                  <div>
                    <div className="font-semibold text-secondaryText">Cliente</div>
                    <div className="mt-1 font-mono text-night">{activeOrder.customerRef}</div>
                  </div>
                  <div>
                    <div className="font-semibold text-secondaryText">Deposito</div>
                    <div className="mt-1 font-mono text-night">{activeOrder.warehouse}</div>
                  </div>
                  <div>
                    <div className="font-semibold text-secondaryText">Base</div>
                    <div className="mt-1 font-mono text-night">{activeOrder.base}</div>
                  </div>
                  <div>
                    <div className="font-semibold text-secondaryText">Solicitado</div>
                    <div className="mt-1 font-mono text-night">{activeOrder.requestedDate}</div>
                  </div>
                  {activeOrder.customerDni && (
                    <div>
                      <div className="font-semibold text-secondaryText">DNI</div>
                      <div className="mt-1 font-mono text-night">{activeOrder.customerDni}</div>
                    </div>
                  )}
                </div>
                </div>
              </div>

              <section className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-borderSoft bg-white px-3 py-2">
                <div className="min-w-0 text-[12px] text-secondaryText">
                  {activeDelivery ? (
                    <>
                      Entrega activa <span className="font-mono font-semibold text-night">{activeDelivery.number}</span> /
                      cantidad total <span className="font-mono font-semibold text-night">{formatQty(activeDeliveryQty)}</span>
                    </>
                  ) : (
                    "Crea una entrega para asignar cantidades."
                  )}
                </div>
                {workflowActions}
              </section>

              <section className="grid shrink-0 gap-2 border-b border-borderSoft bg-softMid px-3 py-2 md:grid-cols-4">
                <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
                  Modalidad
                  <input
                    disabled={!canEditActiveDelivery}
                    value={activeDelivery?.mode ?? ""}
                    onChange={(event) => updateDeliveryField("mode", event.target.value)}
                    className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
                  />
                </label>
                <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
                  Fecha
                  <input
                    disabled={!canEditActiveDelivery}
                    type="date"
                    value={activeDelivery?.plannedDate ?? ""}
                    onChange={(event) => updateDeliveryField("plannedDate", event.target.value)}
                    className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
                  />
                </label>
                <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
                  Receptor
                  <input
                    disabled={!canEditActiveDelivery}
                    value={activeDelivery?.receiver ?? ""}
                    onChange={(event) => updateDeliveryField("receiver", event.target.value)}
                    className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
                  />
                </label>
                <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
                  Referencia
                  <input
                    disabled={!canEditActiveDelivery}
                    value={activeDelivery?.reference ?? ""}
                    onChange={(event) => updateDeliveryField("reference", event.target.value)}
                    className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
                  />
                </label>
              </section>

              <div className="min-h-0 flex-1 overflow-auto">
                <table className="w-full border-collapse text-left text-[12px]">
                  <thead className="sticky top-0 z-10 bg-deep text-white">
                    <tr>
                      <th className="px-3 py-2 font-semibold">Item</th>
                      <th className="px-3 py-2 font-semibold">Descripcion</th>
                      <th className="px-3 py-2 font-semibold">Pedido</th>
                      <th className="px-3 py-2 font-semibold">Reservado</th>
                      <th className="px-3 py-2 font-semibold">Preparado</th>
                      <th className="px-3 py-2 font-semibold">Disponible</th>
                      <th className="px-3 py-2 font-semibold">A entregar</th>
                      <th className="px-3 py-2 font-semibold">Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeOrder.lines.map((line) => {
                      const maxQty = getMaxDispatchableQty(line, activeDelivery);
                      const plannedQty = getDeliveryLineQty(activeDelivery, line.id);
                      const issue = plannedQty > maxQty;
                      const stockToneValue: StatusTone = maxQty <= 0 ? "danger" : issue ? "warning" : "success";

                      return (
                        <tr key={line.id} className="border-b border-borderSoft bg-white hover:bg-softStart">
                          <td className="whitespace-nowrap px-3 py-2 font-mono font-semibold text-night">{line.itemRef}</td>
                          <td className="min-w-64 px-3 py-2 text-night">
                            <div>{line.description}</div>
                            <div className="mt-1 text-[11px] text-secondaryText">
                              Ubicacion {line.location} / planificado {formatQty(line.plannedQty, line.uom)}
                            </div>
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{formatQty(line.orderedQty, line.uom)}</td>
                          <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{formatQty(line.reservedQty, line.uom)}</td>
                          <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{formatQty(line.preparedQty, line.uom)}</td>
                          <td className="whitespace-nowrap px-3 py-2 font-mono text-primaryHover">{formatQty(maxQty, line.uom)}</td>
                          <td className="whitespace-nowrap px-3 py-2">
                            <label className="sr-only" htmlFor={`qty-${line.id}`}>
                              Cantidad a entregar {line.itemRef}
                            </label>
                            <input
                              id={`qty-${line.id}`}
                              disabled={!canEditActiveDelivery || activeDelivery?.status !== "draft"}
                              type="number"
                              min={0}
                              step={1}
                              value={plannedQty}
                              onChange={(event) => updateLineQty(line.id, event.target.value)}
                              className={`h-9 w-24 rounded border bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:bg-softStart ${
                                issue ? "border-red-300" : "border-borderSoft"
                              }`}
                            />
                          </td>
                          <td className="whitespace-nowrap px-3 py-2">
                            <StatusBadge label={maxQty <= 0 ? "bloqueado" : issue ? "revisar" : "ok"} tone={stockToneValue} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="shrink-0 border-t border-borderSoft px-3 py-2 text-[12px] text-secondaryText">
                <div className="text-[12px] text-secondaryText">
                  {activeDelivery ? (
                    <>
                      Entrega activa <span className="font-mono font-semibold text-night">{activeDelivery.number}</span> /
                      cantidad total <span className="font-mono font-semibold text-night">{formatQty(activeDeliveryQty)}</span>
                    </>
                  ) : (
                    "Crea una entrega para asignar cantidades."
                  )}
                </div>
              </div>
              {message && (
                <div className="shrink-0 border-t border-borderSoft bg-white px-3 py-2 text-[12px]" role="status" aria-live="polite">
                  <StatusBadge label={message.tone === "danger" ? "revision" : "estado"} tone={message.tone} />
                  <span className="ml-2 text-secondaryText">{message.text}</span>
                </div>
              )}
            </>
          ) : (
            <div className="min-h-0 overflow-auto p-6 text-[12px] text-secondaryText">
              <div className="mt-4">
                {loading
                  ? "Buscando pedidos pendientes en TMS/WMS..."
                  : submittedSearch
                    ? "No hay pedidos pendientes para revisar."
                    : "Busca un pedido VENT8, ID cliente o DNI cliente para iniciar la expedicion."}
              </div>
              <div>
                <div className="mb-2 text-[11px] font-semibold uppercase text-secondaryText">Acciones de entrega</div>
                {workflowActions}
              </div>
            </div>
          )}
        </main>

        <aside className="flex min-h-0 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="flex shrink-0 items-start justify-between gap-3 border-b border-borderSoft px-3 py-2">
            <div>
              <h2 className="text-[13px] font-semibold text-night">Entregas del pedido</h2>
              <p className="mt-1 text-[11px] text-secondaryText">Un pedido puede tener multiples entregas y remitos.</p>
            </div>
            {activeDelivery && <StatusBadge label={statusLabel[activeDelivery.status]} tone={statusTone[activeDelivery.status]} />}
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {visibleDeliveries.length ? (
              visibleDeliveries.map((delivery) => (
                <button
                  key={delivery.id}
                  type="button"
                  onClick={() => {
                    setActiveDeliveryId(delivery.id);
                    setMessage(null);
                  }}
                  className={`block w-full border-b border-borderSoft px-3 py-3 text-left transition hover:bg-softStart focus:outline-none focus:ring-2 focus:ring-inset focus:ring-primary/30 ${
                    delivery.id === activeDelivery?.id ? "bg-white" : "bg-surface"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="font-mono text-[13px] font-semibold text-night">{delivery.number}</div>
                      <div className="mt-1 text-[11px] text-secondaryText">{delivery.plannedDate || "sin fecha"} / {delivery.mode}</div>
                    </div>
                    <StatusBadge label={delivery.source === "draft" ? "borrador local" : statusLabel[delivery.status]} tone={statusTone[delivery.status]} />
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-secondaryText">
                    <div>
                      <span className="font-semibold">Cantidad</span>
                      <div className="font-mono text-night">{formatQty(sumDeliveryQty(delivery))}</div>
                    </div>
                    <div>
                      <span className="font-semibold">Remito</span>
                      <div className="font-mono text-night">{delivery.remitoNumber ?? "pendiente"}</div>
                    </div>
                    {delivery.preparationAssignee && (
                      <div className="col-span-2">
                        <span className="font-semibold">Preparador</span>
                        <div className="font-mono text-night">{delivery.preparationAssignee}</div>
                      </div>
                    )}
                  </div>
                </button>
              ))
            ) : (
              <div className="px-3 py-6 text-[12px] text-secondaryText">Este pedido todavia no tiene entregas generadas.</div>
            )}
          </div>

          <div className="shrink-0 border-t border-borderSoft bg-white px-3 py-3">
            <h3 className="text-[12px] font-semibold uppercase text-secondaryText">Resumen de remito</h3>
            {activeDelivery ? (
              <dl className="mt-3 grid grid-cols-2 gap-2 text-[12px]">
                <dt className="font-semibold text-secondaryText">Entrega</dt>
                <dd className="font-mono text-night">{activeDelivery.number}</dd>
                <dt className="font-semibold text-secondaryText">Estado</dt>
                <dd>
                  <StatusBadge label={statusLabel[activeDelivery.status]} tone={statusTone[activeDelivery.status]} />
                </dd>
                <dt className="font-semibold text-secondaryText">Receptor</dt>
                <dd className="text-night">{activeDelivery.receiver}</dd>
                <dt className="font-semibold text-secondaryText">Preparador</dt>
                <dd className="font-mono text-night">{activeDelivery.preparationAssignee ?? "sin asignar"}</dd>
                <dt className="font-semibold text-secondaryText">PDF</dt>
                <dd className="font-mono text-night">{activeDelivery.remitoNumber ?? "no emitido"}</dd>
              </dl>
            ) : (
              <p className="mt-3 text-[12px] text-secondaryText">Selecciona una entrega para revisar el remito.</p>
            )}
          </div>
        </aside>
      </section>
    </div>
  );
}
