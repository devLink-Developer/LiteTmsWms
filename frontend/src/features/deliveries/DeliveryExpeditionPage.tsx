import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import {
  checkDeliveryStock,
  checkFulfillmentStock,
  confirmDeliveryStock,
  downloadDeliveryRemitoPdf,
  fetchExpeditionQueue,
  issueDeliveryRemito,
  markDeliveryPrepared,
  reassignDeliveryWarehouse,
  sendDeliveryToPrepare,
  splitFulfillmentDelivery,
  type ApiDeliveryOrder,
  type ApiFulfillmentLine,
  type ApiStockValidationResult,
  type ExpeditionQueueSearch,
  type ApiFulfillmentOrder,
  type ApiFulfillmentImpact,
  type ApiLogisticsMovement,
} from "../../api/fulfillment";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { TraceabilitySection } from "../../shared/components/TraceabilitySection";
import { notify, type ToastTone } from "../../shared/components/toast";
import { eventsAffectOperationalStatuses, useLiveStatusRefresh } from "../../shared/hooks/useLiveStatusEvents";
import { formatAppDate, formatAppDateTime } from "../../shared/utils/dateFormat";
import { formatIdentifier } from "../../shared/utils/identifierFormat";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";
import type { StatusTone, TimelineEvent } from "../../types/operations";

type DeliveryStatus = "draft" | "reserved" | "preparing" | "prepared" | "remito";
type DeliverySource = "api" | "draft";

type DeliveryLineAllocation = {
  lineId: string;
  qty: number;
  warehouse?: string;
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
  warehouse: string;
  store: string;
  remitoNumber?: string;
  issuedAt?: string;
  preparationAssignee?: string;
  preparationTaskStatus?: string;
  routeSheet?: {
    id: string;
    routeNumber: string;
    status: string;
    stopId?: string;
    stopStatus?: string;
  } | null;
  lines: DeliveryLineAllocation[];
  movements: DeliveryMovement[];
};

type DeliveryMovement = {
  key: string;
  at: string;
  label: string;
  status: string;
  detail: string;
  actor: string;
  sourceType: string;
  sourceRef: string;
  routeNumber: string;
  documentNumber: string;
  deliveredQty: number;
  returnedQty: number;
  uom: string;
};

type ExpeditionLine = {
  id: string;
  itemRef: string;
  description: string;
  itemName: string;
  itemLongName: string;
  category: string;
  coverageGroup: string;
  orderedQty: number;
  reservedQty: number;
  preparedQty: number;
  deliveredQty: number;
  cancelledQty: number;
  returnedQty: number;
  pendingQty: number;
  plannedQty: number;
  stockAvailable: number;
  maxDispatchableQty: number;
  uom: string;
  salesUom: string;
  deliveryUom: string;
  conversionFactor: number;
  plannedDeliveryUnitQty: number;
  maxDispatchableDeliveryUnitQty: number;
  unitWeightKg: number;
  unitVolumeM3: number;
  plannedWeightKg: number;
  plannedVolumeM3: number;
  warehouse: string;
  location: string;
};

type OrderImpact = {
  id: string;
  type: "anulacion" | "devolucion";
  status: string;
  salesOrderNumber: string;
  warehouse: string;
  lines: {
    id: string;
    fulfillmentLineId: string;
    itemRef: string;
    qty: number;
    appliedQty: number;
    uom: string;
  }[];
};

type ExpeditionOrder = {
  id: string;
  orderNumber: string;
  transactionNumber: string;
  customerName: string;
  customerRef: string;
  customerDni: string;
  customerDocumentType: string;
  customerPhone: string;
  customerEmail: string;
  warehouse: string;
  base: string;
  status: string;
  priority: string;
  deliveryType: string;
  requestedDate: string;
  address: string;
  contact: string;
  pickupAuthorizedName: string;
  pickupAuthorizedReference: string;
  lines: ExpeditionLine[];
  deliveries: DeliveryDraft[];
  movements: DeliveryMovement[];
  impacts: OrderImpact[];
};

type DraftState = {
  orderId: string;
  delivery: DeliveryDraft;
} | null;

type ValidationMessage = {
  tone: StatusTone;
  text: string;
} | null;

type StockLineValidationState = {
  status: "ok" | "issue";
  plannedQty: string;
  availableQty: string;
};

type StockValidationState = {
  key: string;
  ok: boolean;
  text: string;
  lines: Record<string, StockLineValidationState>;
} | null;

type WarehouseConflict = {
  deliveryId: string;
  deliveryNumber: string;
  fulfillmentId: string;
  salesOrderNumber: string;
  sourceWarehouseRef: string;
  targetWarehouseRef: string;
  status: string;
};

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
  "remito generado": "info",
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

function lineConversionFactor(line: ApiFulfillmentLine) {
  return Math.max(asNumber(line.conversion_factor) || 1, 0.000001);
}

function lineMaxDeliveryUnits(line: ApiFulfillmentLine) {
  const explicitValue = asNumber(line.max_dispatchable_delivery_unit_qty);
  if (explicitValue > 0) {
    return explicitValue;
  }
  return Math.floor(asNumber(line.max_dispatchable_qty) / lineConversionFactor(line));
}

function formatQty(value: number, uom?: string) {
  return `${new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 }).format(value)}${uom ? ` ${uom}` : ""}`;
}

function formatMeasure(value: number, uom: string, maximumFractionDigits = 3) {
  return `${new Intl.NumberFormat("es-AR", { maximumFractionDigits }).format(value)} ${uom}`;
}

function toastTone(tone: StatusTone): ToastTone {
  if (tone === "danger") {
    return "error";
  }
  if (tone === "warning") {
    return "warning";
  }
  if (tone === "success") {
    return "success";
  }
  return "info";
}

function movementFromApi(movement: ApiLogisticsMovement): DeliveryMovement {
  return {
    key: movement.key,
    at: movement.at ?? "",
    label: movement.label,
    status: movement.status ?? "",
    detail: movement.detail ?? "",
    actor: movement.actor ?? "",
    sourceType: movement.source_type ?? "",
    sourceRef: movement.source_ref ?? "",
    routeNumber: movement.route_number ?? "",
    documentNumber: movement.document_number ?? "",
    deliveredQty: asNumber(movement.delivered_qty),
    returnedQty: asNumber(movement.returned_qty),
    uom: movement.uom ?? "",
  };
}

function movementTimelineEvent(movement: DeliveryMovement, index = 0): TimelineEvent {
  const details = [
    movement.detail,
    movement.routeNumber ? `Hoja de ruta ${movement.routeNumber}` : "",
    movement.documentNumber ? `Remito ${movement.documentNumber}` : "",
    movement.deliveredQty > 0 ? `Entregado ${formatQty(movement.deliveredQty, movement.uom)}` : "",
    movement.returnedQty > 0 ? `Devuelto ${formatQty(movement.returnedQty, movement.uom)}` : "",
  ]
    .filter(Boolean)
    .join(" / ");
  return {
    id: movement.key || movement.sourceRef || `movement-${index}`,
    label: movement.label || "Movimiento",
    actor: movement.actor || movement.sourceType || "api",
    at: formatAppDateTime(movement.at, movement.at || "-"),
    details: details || movement.status || "Movimiento",
  };
}

function impactFromApi(impact: ApiFulfillmentImpact): OrderImpact {
  return {
    id: impact.id,
    type: impact.type,
    status: impact.status,
    salesOrderNumber: impact.sales_order_number,
    warehouse: impact.warehouse_ref,
    lines: impact.lines.map((line) => ({
      id: line.id,
      fulfillmentLineId: line.fulfillment_line_id ?? "",
      itemRef: line.item_ref,
      qty: asNumber(line.quantity),
      appliedQty: asNumber(line.applied_qty),
      uom: line.uom,
    })),
  };
}

function formatStockValidationIssues(result: ApiStockValidationResult) {
  if (!result.issues.length) {
    return "Stock validado.";
  }
  const uniqueIssues = Array.from(
    new Map(
      result.issues.map((issue) => {
        const itemRef = issue.item_ref || "Articulo";
        const plannedQty = asNumber(issue.planned_qty);
        const availableQty = asNumber(issue.available_qty);
        const uom = issue.uom || "";
        return [`${itemRef}:${plannedQty}:${availableQty}:${uom}`, { itemRef, plannedQty, availableQty, uom }];
      }),
    ).values(),
  );
  const header = `Stock insuficiente en ${uniqueIssues.length} articulo${uniqueIssues.length === 1 ? "" : "s"}.`;
  const details = uniqueIssues.map(
    (issue) => `- ${issue.itemRef}: solicitado ${formatQty(issue.plannedQty, issue.uom)}; disponible ${formatQty(issue.availableQty, issue.uom)}`,
  );
  return [header, ...details].join("\n");
}

function stockValidationLines(result: ApiStockValidationResult): Record<string, StockLineValidationState> {
  const issueKeys = new Set(
    result.issues.flatMap((issue) => [
      issue.line_id,
      `${issue.item_ref}::${issue.warehouse_ref}::${issue.uom}`,
    ]),
  );
  const statuses: Record<string, StockLineValidationState> = {};

  result.lines.forEach((line) => {
    const lineId = line.fulfillment_line_id || line.line_id;
    const issue =
      issueKeys.has(line.line_id) ||
      issueKeys.has(lineId) ||
      issueKeys.has(`${line.item_ref}::${line.warehouse_ref}::${line.uom}`);
    statuses[lineId] = {
      status: issue ? "issue" : "ok",
      plannedQty: formatQty(asNumber(line.planned_qty), line.uom),
      availableQty: formatQty(asNumber(line.available_qty), line.uom),
    };
  });

  result.issues.forEach((issue) => {
    if (statuses[issue.line_id]) {
      return;
    }
    statuses[issue.line_id] = {
      status: "issue",
      plannedQty: formatQty(asNumber(issue.planned_qty), issue.uom),
      availableQty: formatQty(asNumber(issue.available_qty), issue.uom),
    };
  });

  return statuses;
}

function textDetail(details: Record<string, unknown>, key: string) {
  const value = details[key];
  return typeof value === "string" ? value : "";
}

function conflictFromError(error: unknown): WarehouseConflict | null {
  if (!(error instanceof ApiError) || error.status !== 409 || error.code !== "cross_warehouse_confirmed_delivery") {
    return null;
  }
  const details = error.details;
  const deliveryId = textDetail(details, "delivery_id");
  if (!deliveryId) {
    return null;
  }
  return {
    deliveryId,
    deliveryNumber: textDetail(details, "delivery_number") || "Entrega confirmada",
    fulfillmentId: textDetail(details, "fulfillment_id"),
    salesOrderNumber: textDetail(details, "sales_order_number"),
    sourceWarehouseRef: textDetail(details, "source_warehouse_ref"),
    targetWarehouseRef: textDetail(details, "target_warehouse_ref"),
    status: textDetail(details, "status"),
  };
}

function getDeliveryLineQty(delivery: DeliveryDraft | undefined, lineId: string) {
  return delivery?.lines.find((line) => line.lineId === lineId)?.qty ?? 0;
}

function sumDeliveryQty(delivery: DeliveryDraft) {
  return delivery.lines.reduce((total, line) => total + line.qty, 0);
}

function deliveryLineUom(order: ExpeditionOrder, lineId: string) {
  const orderLine = order.lines.find((line) => line.id === lineId);
  return orderLine?.deliveryUom || orderLine?.uom || "";
}

function formatDeliveryQty(order: ExpeditionOrder | undefined, delivery: DeliveryDraft | undefined) {
  if (!order || !delivery) {
    return formatQty(0);
  }
  const groups = new Map<string, number>();
  delivery.lines
    .filter((line) => line.qty > 0)
    .forEach((line) => {
      const uom = deliveryLineUom(order, line.lineId);
      groups.set(uom, (groups.get(uom) ?? 0) + line.qty);
    });
  if (!groups.size) {
    return formatQty(0);
  }
  if (groups.size === 1) {
    const [[uom, qty]] = Array.from(groups.entries());
    return formatQty(qty, uom);
  }
  return `${formatQty(Array.from(groups.values()).reduce((total, qty) => total + qty, 0))} unidades`;
}

function getPartialConfirmedInfo(order: ExpeditionOrder | undefined, delivery: DeliveryDraft | undefined, deliveries: DeliveryDraft[]) {
  if (!order || !delivery || delivery.status !== "reserved" || sumDeliveryQty(delivery) <= 0) {
    return null;
  }
  const remainingLines = order.lines
    .map((line) => {
      const otherOperationalQty = deliveries
        .filter((candidate) => candidate.id !== delivery.id && candidate.status !== "remito")
        .reduce((total, candidate) => total + getDeliveryLineQty(candidate, line.id), 0);
      return {
        lineId: line.id,
        qty: otherOperationalQty + Math.max(0, line.maxDispatchableDeliveryUnitQty),
        uom: line.deliveryUom || line.uom || "",
      };
    })
    .filter((line) => line.qty > 0.000001);
  if (!remainingLines.length) {
    return null;
  }
  const uoms = Array.from(new Set(remainingLines.map((line) => line.uom)));
  const remainingText =
    uoms.length === 1
      ? `Queda ${formatQty(remainingLines.reduce((total, line) => total + line.qty, 0), uoms[0])}`
      : `Queda saldo en ${remainingLines.length} lineas`;
  return { remainingText };
}

function getCommercialQty(line: ExpeditionLine, delivery?: DeliveryDraft) {
  return getDeliveryLineQty(delivery, line.id) * line.conversionFactor;
}

function getMaxDispatchableDeliveryUnitQty(line: ExpeditionLine, delivery?: DeliveryDraft) {
  const currentDeliveryQty = delivery?.source === "api" && delivery.status !== "remito" ? getDeliveryLineQty(delivery, line.id) : 0;
  return Math.max(0, Math.floor(line.maxDispatchableDeliveryUnitQty + currentDeliveryQty));
}

function getCommittedQty(line: ExpeditionLine) {
  return Math.max(line.reservedQty, line.plannedQty);
}

function orderImpactBadges(order: ExpeditionOrder | undefined) {
  if (!order) {
    return [];
  }
  const badges: { key: string; label: string; tone: StatusTone }[] = [];
  if (order.impacts.some((impact) => impact.type === "anulacion")) {
    badges.push({ key: "annulment", label: "Anulacion", tone: "danger" });
  }
  if (order.impacts.some((impact) => impact.type === "devolucion")) {
    badges.push({ key: "return", label: "Devolucion", tone: "warning" });
  }
  if (order.impacts.some((impact) => impact.type === "devolucion" && impact.lines.some((line) => line.appliedQty > 0))) {
    badges.push({ key: "return-stock", label: "Stock ingresado", tone: "success" });
  }
  return badges;
}

function getDeliveryTotals(order: ExpeditionOrder | undefined, delivery: DeliveryDraft | undefined) {
  if (!order || !delivery) {
    return {
      deliveryUnits: 0,
      commercialQty: 0,
      weightKg: 0,
      volumeM3: 0,
    };
  }
  return delivery.lines.reduce(
    (totals, allocation) => {
      const line = order.lines.find((orderLine) => orderLine.id === allocation.lineId);
      if (!line) {
        return totals;
      }
      const commercialQty = allocation.qty * line.conversionFactor;
      return {
        deliveryUnits: totals.deliveryUnits + allocation.qty,
        commercialQty: totals.commercialQty + commercialQty,
        weightKg: totals.weightKg + commercialQty * line.unitWeightKg,
        volumeM3: totals.volumeM3 + commercialQty * line.unitVolumeM3,
      };
    },
    {
      deliveryUnits: 0,
      commercialQty: 0,
      weightKg: 0,
      volumeM3: 0,
    },
  );
}

function getDeliveryLineSummaries(order: ExpeditionOrder | undefined, delivery: DeliveryDraft | undefined) {
  if (!order || !delivery) {
    return [];
  }
  return delivery.lines
    .filter((allocation) => allocation.qty > 0)
    .map((allocation) => {
      const orderLine = order.lines.find((line) => line.id === allocation.lineId);
      const commercialQty = orderLine ? allocation.qty * orderLine.conversionFactor : allocation.qty;
      return {
        id: allocation.lineId,
        itemRef: orderLine?.itemRef ?? allocation.lineId,
        itemName: orderLine?.itemName ?? allocation.lineId,
        deliveryQty: allocation.qty,
        deliveryUom: orderLine?.deliveryUom ?? orderLine?.uom ?? "",
        commercialQty,
        commercialUom: orderLine?.uom ?? "",
        conversionFactor: orderLine?.conversionFactor ?? 1,
        warehouse: allocation.warehouse || orderLine?.warehouse || delivery.warehouse || order.warehouse,
      };
    });
}

function getDeliveryWarehouse(order: ExpeditionOrder | undefined, delivery: DeliveryDraft | undefined) {
  const warehouses = Array.from(new Set(getDeliveryLineSummaries(order, delivery).map((line) => line.warehouse).filter(Boolean)));
  if (warehouses.length === 1) {
    return warehouses[0];
  }
  if (warehouses.length > 1) {
    return `Varios: ${warehouses.join(", ")}`;
  }
  return delivery?.warehouse || order?.warehouse || "s/d";
}

function getInvalidDeliveryQtyCount(order: ExpeditionOrder | undefined, delivery: DeliveryDraft | undefined) {
  if (!order || !delivery || delivery.status !== "draft") {
    return 0;
  }
  return delivery.lines.filter((allocation) => {
    if (allocation.qty <= 0) {
      return false;
    }
    const orderLine = order.lines.find((line) => line.id === allocation.lineId);
    if (!orderLine) {
      return true;
    }
    return allocation.qty > getMaxDispatchableDeliveryUnitQty(orderLine, delivery);
  }).length;
}

function isOperationalDelivery(delivery: DeliveryDraft) {
  return delivery.status !== "remito";
}

function deliveryStatusFromApi(delivery: ApiDeliveryOrder): DeliveryStatus {
  if (delivery.documents.some((document) => document.document_type === "remito" && ["issued", "open", "closed"].includes(document.status))) {
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
  if (orderFullyRemitted(order)) {
    return "remito generado";
  }
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

function orderFullyRemitted(order: ApiFulfillmentOrder) {
  const requiredLines = order.lines
    .map((line) => ({
      id: line.id,
      requiredQty: Math.max(0, asNumber(line.ordered_qty) - asNumber(line.cancelled_qty)),
    }))
    .filter((line) => line.requiredQty > 0);
  if (!requiredLines.length) {
    return false;
  }
  const remittedByLine = new Map<string, number>();
  order.deliveries
    .filter((delivery) => deliveryStatusFromApi(delivery) === "remito")
    .forEach((delivery) => {
      delivery.lines.forEach((line) => {
        remittedByLine.set(line.fulfillment_line_id, (remittedByLine.get(line.fulfillment_line_id) ?? 0) + asNumber(line.planned_qty));
      });
    });
  return requiredLines.every((line) => (remittedByLine.get(line.id) ?? 0) + 0.000001 >= line.requiredQty);
}

function deliveryFromApi(delivery: ApiDeliveryOrder): DeliveryDraft {
  const remito = delivery.documents.find((document) => document.document_type === "remito" && ["issued", "open", "closed"].includes(document.status));
  return {
    id: delivery.id,
    number: delivery.delivery_number,
    source: "api",
    status: deliveryStatusFromApi(delivery),
    mode: delivery.delivery_mode,
    plannedDate: delivery.planned_date ?? "",
    receiver: delivery.address_snapshot?.receiver ?? delivery.sales_order_number,
    reference: delivery.address_snapshot?.reference ?? delivery.delivery_number,
    warehouse: delivery.warehouse_ref || delivery.lines.find((line) => line.warehouse_ref)?.warehouse_ref || "",
    store: delivery.store_ref || "",
    remitoNumber: remito?.document_number,
    issuedAt: remito?.issued_at,
    preparationAssignee: delivery.preparation_task?.assigned_employee_ref,
    preparationTaskStatus: delivery.preparation_task?.status,
    routeSheet: delivery.route_sheet
      ? {
          id: delivery.route_sheet.id,
          routeNumber: delivery.route_sheet.route_number,
          status: delivery.route_sheet.status,
          stopId: delivery.route_sheet.stop_id,
          stopStatus: delivery.route_sheet.stop_status,
        }
      : null,
    lines: delivery.lines.map((line) => ({
      lineId: line.fulfillment_line_id,
      qty: asNumber(line.delivery_unit_qty ?? line.planned_qty),
      warehouse: line.warehouse_ref,
    })),
    movements: (delivery.movements ?? []).map(movementFromApi),
  };
}

function orderFromApi(order: ApiFulfillmentOrder): ExpeditionOrder {
  const firstDeliveryAddress = order.deliveries.find((delivery) => delivery.address_snapshot)?.address_snapshot ?? {};
  const customerAddress = order.customer?.address ?? {};
  const requestedDate = order.requested_date ?? order.created_at.slice(0, 10);
  const deliveries = order.deliveries.map(deliveryFromApi);
  const movements = order.movements ? order.movements.map(movementFromApi) : deliveries.flatMap((delivery) => delivery.movements);
  const impacts = (order.impacts ?? []).map(impactFromApi);
  return {
    id: order.id,
    orderNumber: formatIdentifier(order.sales_order_number || order.fulfillment_number),
    transactionNumber: order.transaction_number,
    customerName: order.customer?.name || order.customer_ref,
    customerRef: order.customer_ref,
    customerDni: order.customer?.document_number ?? order.customer_dni ?? order.customer_document ?? "",
    customerDocumentType: order.customer?.document_type ?? "",
    customerPhone: order.customer?.phone ?? "",
    customerEmail: order.customer?.email ?? "",
    warehouse: order.warehouse_ref,
    base: order.warehouse_ref || "S/E",
    status: orderStatusFromApi(order),
    priority: order.deliveries.length ? "En gestion" : "Nueva",
    deliveryType: order.delivery_mode || "Sin modalidad",
    requestedDate,
    address:
      order.customer?.address_text ||
      [firstDeliveryAddress.description, firstDeliveryAddress.street, firstDeliveryAddress.city]
        .filter(Boolean)
        .join(" / ") ||
      [customerAddress.description, customerAddress.street, customerAddress.street_number, customerAddress.city]
        .filter(Boolean)
        .join(" ") ||
      "Direccion no informada por snapshot TMS/WMS",
    contact: [order.customer?.phone, order.customer?.email].filter(Boolean).join(" / ") || order.customer_ref,
    pickupAuthorizedName: order.pickup_authorization?.name || order.customer?.name || order.customer_ref,
    pickupAuthorizedReference: order.pickup_authorization?.reference || "",
    lines: order.lines.map((line) => {
      const displayUom = line.sales_uom || line.uom;
      return {
        id: line.id,
        itemRef: line.item_ref,
        description: line.item_long_name || line.item_name || `Linea legacy ${line.legacy_line_id}`,
        itemName: line.item_name || line.item_long_name || line.item_ref,
        itemLongName: line.item_long_name || line.item_name || line.item_ref,
        category: line.category || "",
        coverageGroup: line.coverage_group || "",
        orderedQty: asNumber(line.ordered_qty),
        reservedQty: asNumber(line.reserved_qty),
        preparedQty: asNumber(line.prepared_qty),
        deliveredQty: asNumber(line.delivered_qty),
        cancelledQty: asNumber(line.cancelled_qty),
        returnedQty: asNumber(line.returned_qty),
        pendingQty: asNumber(line.pending_qty),
        plannedQty: asNumber(line.planned_qty),
        stockAvailable: asNumber(line.stock_available),
        maxDispatchableQty: asNumber(line.max_dispatchable_qty),
        uom: displayUom,
        salesUom: displayUom,
        deliveryUom: line.delivery_uom || displayUom,
        conversionFactor: lineConversionFactor(line),
        plannedDeliveryUnitQty: asNumber(line.planned_delivery_unit_qty),
        maxDispatchableDeliveryUnitQty: lineMaxDeliveryUnits(line),
        unitWeightKg: asNumber(line.unit_weight_kg),
        unitVolumeM3: asNumber(line.unit_volume_m3),
        plannedWeightKg: asNumber(line.planned_weight_kg),
        plannedVolumeM3: asNumber(line.planned_volume_m3),
        warehouse: line.warehouse_ref,
        location: line.warehouse_ref,
      };
    }),
    deliveries,
    movements: movements.sort((left, right) => left.at.localeCompare(right.at)),
    impacts,
  };
}

function hasDispatchableDeliveryQty(order: ExpeditionOrder) {
  return order.lines.some((line) => getMaxDispatchableDeliveryUnitQty(line) > 0);
}

export function DeliveryExpeditionPage() {
  const warehouseRef = useWorkspaceStore((state) => state.warehouseRef);
  const [orders, setOrders] = useState<ExpeditionOrder[]>([]);
  const [activeOrderId, setActiveOrderId] = useState("");
  const [activeDeliveryId, setActiveDeliveryId] = useState("");
  const [summaryDeliveryId, setSummaryDeliveryId] = useState("");
  const [draftState, setDraftState] = useState<DraftState>(null);
  const [search, setSearch] = useState<SearchState>({
    mode: "sales_order",
    value: "",
  });
  const [submittedSearch, setSubmittedSearch] = useState<ExpeditionQueueSearch | null>(null);
  const [stockValidation, setStockValidation] = useState<StockValidationState>(null);
  const [warehouseConflict, setWarehouseConflict] = useState<WarehouseConflict | null>(null);
  const [loading, setLoading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const conflictConfirmRef = useRef<HTMLButtonElement | null>(null);

  function setMessage(nextMessage: ValidationMessage) {
    if (!nextMessage) {
      return;
    }
    notify({ message: nextMessage.text, tone: toastTone(nextMessage.tone) });
  }

  async function loadQueue(nextSearch: ExpeditionQueueSearch, { silent = false } = {}) {
    if (!silent) {
      setLoading(true);
    }
    try {
      const apiOrders = await fetchExpeditionQueue(nextSearch, { globalLoading: !silent });
      const nextOrders = apiOrders.map(orderFromApi);
      setOrders(nextOrders);
      setActiveOrderId((current) => {
        if (current && nextOrders.some((order) => order.id === current)) {
          return current;
        }
        return nextOrders[0]?.id ?? "";
      });
    } catch (apiError) {
      const text = apiError instanceof Error ? apiError.message : "Cola no cargada.";
      if (!silent) {
        notify({ message: text, tone: "error" });
      }
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

  useLiveStatusRefresh(
    (events) => {
      if (submittedSearch && eventsAffectOperationalStatuses(events)) {
        void loadQueue(submittedSearch, { silent: true });
      }
    },
    Boolean(submittedSearch),
  );

  const activeOrder = orders.find((order) => order.id === activeOrderId) ?? orders[0];
  const activeWarehouseRef = warehouseRef || activeOrder?.warehouse || "";
  const expeditionCommandOptions = {
    allow_past_reparto_date: true,
    target_warehouse_ref: activeWarehouseRef,
  };
  const activeOrderCrossWarehouse =
    Boolean(activeOrder?.warehouse && activeWarehouseRef && activeOrder.warehouse !== activeWarehouseRef);
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
  const summaryDelivery = visibleDeliveries.find((delivery) => delivery.id === summaryDeliveryId) ?? activeDelivery ?? visibleDeliveries[0];
  const canEditActiveDelivery = activeDelivery?.source === "draft";

  useEffect(() => {
    if (warehouseConflict) {
      conflictConfirmRef.current?.focus();
    }
  }, [warehouseConflict]);

  useEffect(() => {
    if (!activeOrder || draftState?.orderId !== activeOrder.id) {
      return;
    }
    let changed = false;
    const nextLines = draftState.delivery.lines.map((allocation) => {
      const orderLine = activeOrder.lines.find((line) => line.id === allocation.lineId);
      const maxUnits = orderLine ? getMaxDispatchableDeliveryUnitQty(orderLine, draftState.delivery) : 0;
      const nextQty = Math.min(Math.max(0, allocation.qty), maxUnits);
      if (nextQty !== allocation.qty) {
        changed = true;
        return { ...allocation, qty: nextQty };
      }
      return allocation;
    });
    if (changed) {
      setDraftState({ orderId: activeOrder.id, delivery: { ...draftState.delivery, lines: nextLines } });
    }
  }, [activeOrder, draftState]);

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

  useEffect(() => {
    if (!activeOrder) {
      setSummaryDeliveryId("");
      return;
    }
    if (summaryDeliveryId && visibleDeliveries.some((delivery) => delivery.id === summaryDeliveryId)) {
      return;
    }
    setSummaryDeliveryId(activeDelivery?.id ?? visibleDeliveries[0]?.id ?? "");
  }, [activeDelivery, activeOrder, summaryDeliveryId, visibleDeliveries]);

  function updateSearch(key: keyof SearchState, value: string) {
    setSearch((current) => ({ ...current, [key]: value }));
  }

  function executeSearch(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const value = search.value.trim();
    if (!value) {
      setMessage({ tone: "danger", text: "Busqueda vacia." });
      setOrders([]);
      setActiveOrderId("");
      setActiveDeliveryId("");
      setSummaryDeliveryId("");
      setDraftState(null);
      setStockValidation(null);
      setWarehouseConflict(null);
      return;
    }
    const nextSearch = { mode: search.mode, value };
    setSubmittedSearch(nextSearch);
    setOrders([]);
    setActiveOrderId("");
    setActiveDeliveryId("");
    setSummaryDeliveryId("");
    setDraftState(null);
    setStockValidation(null);
    setWarehouseConflict(null);
    setMessage(null);
    void loadQueue(nextSearch);
  }

  function selectOrder(order: ExpeditionOrder) {
    const firstOperationalDeliveryId = order.deliveries.find(isOperationalDelivery)?.id ?? "";
    setActiveOrderId(order.id);
    setActiveDeliveryId(firstOperationalDeliveryId);
    setSummaryDeliveryId(firstOperationalDeliveryId || order.deliveries[0]?.id || "");
    if (draftState?.orderId !== order.id) {
      setDraftState(null);
    }
    setStockValidation(null);
    setWarehouseConflict(null);
    setMessage(null);
  }

  function addDelivery() {
    if (!activeOrder) {
      return;
    }
    if (!hasDispatchableDeliveryQty(activeOrder)) {
      setMessage({ tone: "info", text: "Sin saldo." });
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
      receiver: activeOrder.pickupAuthorizedName,
      reference: activeOrder.pickupAuthorizedReference || "Pendiente de confirmacion",
      warehouse: activeWarehouseRef || activeOrder.warehouse,
      store: "",
      lines: activeOrder.lines.map((line) => ({
        lineId: line.id,
        qty: 0,
        warehouse: activeWarehouseRef || line.warehouse,
      })),
      movements: [],
    };
    setDraftState({ orderId: activeOrder.id, delivery: draft });
    setActiveDeliveryId(draft.id);
    setSummaryDeliveryId(draft.id);
    setStockValidation(null);
    setMessage({ tone: "info", text: "Borrador creado." });
  }

  function updateDraftDelivery(updater: (delivery: DeliveryDraft) => DeliveryDraft) {
    if (!activeOrder || draftState?.orderId !== activeOrder.id) {
      return;
    }
    setDraftState({ orderId: activeOrder.id, delivery: updater(draftState.delivery) });
    setStockValidation(null);
    setMessage(null);
  }

  function updateLineQty(lineId: string, value: string) {
    if (!canEditActiveDelivery || !activeOrder) {
      return;
    }
    const qty = Number(value);
    updateDraftDelivery((delivery) => ({
      ...delivery,
      lines: delivery.lines.map((line) => {
        if (line.lineId !== lineId) {
          return line;
        }
        const orderLine = activeOrder.lines.find((candidate) => candidate.id === lineId);
        const maxUnits = orderLine ? getMaxDispatchableDeliveryUnitQty(orderLine, delivery) : 0;
        const requestedQty = Number.isFinite(qty) ? Math.max(0, qty) : 0;
        return { ...line, qty: Math.min(requestedQty, maxUnits) };
      }),
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
          qty: orderLine ? getMaxDispatchableDeliveryUnitQty(orderLine, delivery) : 0,
        };
      }),
    }));
  }

  async function persistDraftDelivery(delivery: DeliveryDraft) {
    if (!activeOrder) {
      throw new Error("Sin pedido activo.");
    }
    const lines = delivery.lines
      .filter((line) => line.qty > 0)
      .map((line) => ({ fulfillment_line_id: line.lineId, delivery_unit_qty: line.qty }));
    if (!lines.length) {
      throw new Error("Sin cantidades.");
    }
    activeOrder.lines.forEach((line) => {
      const plannedUnits = getDeliveryLineQty(delivery, line.id);
      const maxUnits = getMaxDispatchableDeliveryUnitQty(line, delivery);
      if (plannedUnits > maxUnits) {
        throw new Error(`${line.itemRef}: solicitado ${formatQty(plannedUnits, line.deliveryUom)}, disponible ${formatQty(maxUnits, line.deliveryUom)}`);
      }
    });
    const created = await splitFulfillmentDelivery(activeOrder.id, {
      delivery_mode: delivery.mode,
      planned_date: delivery.plannedDate,
      reason: delivery.reference || "Split desde pantalla de expedicion",
      receiver: delivery.receiver,
      reference: delivery.reference,
      lines,
      ...expeditionCommandOptions,
    });
    setDraftState(null);
    return created;
  }

  function handleDeliveryCommandError(apiError: unknown, fallback: string) {
    const conflict = conflictFromError(apiError);
    if (conflict) {
      setWarehouseConflict(conflict);
      setMessage({
        tone: "warning",
        text: `Confirmado en ${conflict.sourceWarehouseRef || "otro deposito"}.`,
      });
      return true;
    }
    setMessage({
      tone: "danger",
      text: apiError instanceof Error ? apiError.message : fallback,
    });
    return false;
  }

  async function validateActiveDeliveryStock(stockKey: string) {
    if (!activeOrder || !activeDelivery) {
      setMessage({ tone: "danger", text: "Sin entrega." });
      return;
    }
    if (activeDelivery.status !== "draft" && !activeDeliveryCrossWarehouse) {
      setMessage({ tone: "info", text: "Stock reservado." });
      return;
    }
    if (activeDeliveryQty <= 0) {
      setMessage({ tone: "danger", text: "Sin cantidades." });
      return;
    }
    if (activeDelivery.status === "draft" && activeDeliveryHasInvalidQty) {
      setMessage({ tone: "danger", text: "Cantidad invalida." });
      return;
    }
    setProcessing(true);
    try {
      const result =
        activeDelivery.source === "draft"
          ? await checkFulfillmentStock(
              activeOrder.id,
              activeDelivery.lines
                .filter((line) => line.qty > 0)
                .map((line) => ({ fulfillment_line_id: line.lineId, delivery_unit_qty: line.qty })),
              expeditionCommandOptions,
            )
          : await checkDeliveryStock(activeDelivery.id, expeditionCommandOptions);
      const text = formatStockValidationIssues(result);
      setStockValidation({ key: stockKey, ok: result.can_confirm, text, lines: stockValidationLines(result) });
      setWarehouseConflict(null);
      setMessage({ tone: result.can_confirm ? "success" : "danger", text });
    } catch (apiError) {
      setStockValidation(null);
      handleDeliveryCommandError(apiError, "Stock no validado.");
    } finally {
      setProcessing(false);
    }
  }

  async function confirmActiveDelivery() {
    if (!activeDelivery) {
      setMessage({ tone: "danger", text: "Sin entrega." });
      return null;
    }
    const requiresStockValidation = activeDelivery.status === "draft" || activeDeliveryCrossWarehouse;
    if (requiresStockValidation && !(stockValidation?.key === activeDeliveryStockKey && stockValidation.ok)) {
      setMessage({ tone: "danger", text: `Stock sin validar en ${activeWarehouseRef || "deposito activo"}.` });
      return null;
    }
    setProcessing(true);
    try {
      const deliveryToConfirm =
        activeDelivery.source === "draft" ? await persistDraftDelivery(activeDelivery) : ({ id: activeDelivery.id } as ApiDeliveryOrder);
      const confirmed = await confirmDeliveryStock(deliveryToConfirm.id, expeditionCommandOptions);
      if (submittedSearch) {
        await loadQueue(submittedSearch, { silent: true });
      }
      setActiveDeliveryId(confirmed.id);
      setSummaryDeliveryId(confirmed.id);
      setStockValidation(null);
      setWarehouseConflict(null);
      setMessage({ tone: "success", text: `${confirmed.delivery_number} confirmada; stock reservado.` });
      return confirmed;
    } catch (apiError) {
      handleDeliveryCommandError(apiError, "Confirmacion fallida.");
      return null;
    } finally {
      setProcessing(false);
    }
  }

  async function sendActiveDeliveryToPrepare() {
    if (!activeDelivery || activeDelivery.status !== "reserved") {
      setMessage({ tone: "danger", text: "Stock sin reserva." });
      return;
    }
    setProcessing(true);
    try {
      const preparing = await sendDeliveryToPrepare(activeDelivery.id, expeditionCommandOptions);
      if (submittedSearch) {
        await loadQueue(submittedSearch, { silent: true });
      }
      setActiveDeliveryId(preparing.id);
      setSummaryDeliveryId(preparing.id);
      setMessage({ tone: "success", text: `${preparing.delivery_number} enviada a preparar.` });
    } catch (apiError) {
      handleDeliveryCommandError(apiError, "Envio fallido.");
    } finally {
      setProcessing(false);
    }
  }

  async function markActiveDeliveryPrepared() {
    if (!activeDelivery || activeDelivery.status !== "preparing") {
      setMessage({ tone: "danger", text: "Estado invalido." });
      return;
    }
    setProcessing(true);
    try {
      const prepared = await markDeliveryPrepared(activeDelivery.id, expeditionCommandOptions);
      if (submittedSearch) {
        await loadQueue(submittedSearch, { silent: true });
      }
      setActiveDeliveryId(prepared.id);
      setSummaryDeliveryId(prepared.id);
      setMessage({ tone: "success", text: `${prepared.delivery_number} marcada como preparada.` });
    } catch (apiError) {
      handleDeliveryCommandError(apiError, "Preparacion fallida.");
    } finally {
      setProcessing(false);
    }
  }

  async function generateRemitoPdf() {
    if (!activeDelivery) {
      return;
    }
    if (activeDelivery.routeSheet) {
      setMessage({
        tone: "danger",
        text: `Hoja de ruta ${activeDelivery.routeSheet.routeNumber}.`,
      });
      return;
    }
    if (activeDelivery.status !== "prepared") {
      setMessage({ tone: "danger", text: "Entrega no preparada." });
      return;
    }
    setProcessing(true);
    try {
      const deliveryId = activeDelivery.id;
      const document = await issueDeliveryRemito(deliveryId, expeditionCommandOptions);
      await downloadDeliveryRemitoPdf(deliveryId, document.document_number);
      if (submittedSearch) {
        await loadQueue(submittedSearch, { silent: true });
      }
      setActiveDeliveryId("");
      setSummaryDeliveryId(deliveryId);
      setMessage({ tone: "info", text: `Remito ${document.document_number} generado.` });
    } catch (apiError) {
      handleDeliveryCommandError(apiError, "Remito no emitido.");
    } finally {
      setProcessing(false);
    }
  }

  async function confirmWarehouseReassignment() {
    if (!warehouseConflict) {
      return;
    }
    if (
      activeDeliveryCrossWarehouse &&
      activeDelivery?.id === warehouseConflict.deliveryId &&
      !(stockValidation?.key === activeDeliveryStockKey && stockValidation.ok)
    ) {
      setMessage({ tone: "danger", text: `Stock sin validar en ${activeWarehouseRef || "deposito activo"}.` });
      return;
    }
    setProcessing(true);
    try {
      const reassigned = await reassignDeliveryWarehouse(warehouseConflict.deliveryId, {
        allow_past_reparto_date: true,
        target_warehouse_ref: warehouseConflict.targetWarehouseRef || activeWarehouseRef,
      });
      if (submittedSearch) {
        await loadQueue(submittedSearch, { silent: true });
      }
      setActiveDeliveryId(reassigned.id);
      setSummaryDeliveryId(reassigned.id);
      setStockValidation(null);
      setWarehouseConflict(null);
      setMessage({ tone: "success", text: `${reassigned.delivery_number} reasignada a ${reassigned.warehouse_ref || activeWarehouseRef}.` });
    } catch (apiError) {
      setMessage({
        tone: "danger",
        text: apiError instanceof Error ? apiError.message : "Confirmacion fallida.",
      });
    } finally {
      setProcessing(false);
    }
  }

  const activeDeliveryTotals = getDeliveryTotals(activeOrder, activeDelivery);
  const activeDeliveryQty = activeDeliveryTotals.deliveryUnits;
  const summaryDeliveryTotals = getDeliveryTotals(activeOrder, summaryDelivery);
  const summaryDeliveryLines = getDeliveryLineSummaries(activeOrder, summaryDelivery);
  const summaryDeliveryWarehouse = getDeliveryWarehouse(activeOrder, summaryDelivery);
  const summaryHasRemito = Boolean(summaryDelivery?.remitoNumber || summaryDelivery?.status === "remito");
  const orderMovements = activeOrder?.movements ?? [];
  const orderTimelineEvents = useMemo(() => orderMovements.map(movementTimelineEvent), [orderMovements]);
  const activeDeliveryHasInvalidQty = getInvalidDeliveryQtyCount(activeOrder, activeDelivery) > 0;
  const activeDeliveryLockedByRoute = Boolean(activeDelivery?.routeSheet);
  const activeDeliveryCrossWarehouse =
    Boolean(
      activeDelivery?.source === "api" &&
        activeDelivery.status === "reserved" &&
        activeDelivery.warehouse &&
        activeWarehouseRef &&
        activeDelivery.warehouse !== activeWarehouseRef,
    );
  const hasReservedDelivery = visibleDeliveries.some((delivery) => delivery.source === "api" && delivery.status === "reserved");
  const warehouseNotice =
    activeDeliveryCrossWarehouse && activeDelivery?.warehouse
      ? {
          label: `Confirmado en ${activeDelivery.warehouse}`,
          className: "border-amber-300 bg-amber-50 text-amber-800",
        }
      : activeOrderCrossWarehouse && !hasReservedDelivery && activeOrder?.warehouse
        ? {
            label: `Origen ${activeOrder.warehouse}`,
            className: "border-borderSoft bg-softMid text-secondaryText",
          }
        : null;
  const activePartialInfo = getPartialConfirmedInfo(activeOrder, activeDelivery, visibleDeliveries);
  const summaryPartialInfo = getPartialConfirmedInfo(activeOrder, summaryDelivery, visibleDeliveries);
  const activeImpactBadges = orderImpactBadges(activeOrder);
  const activeOrderHasDispatchableQty = activeOrder ? hasDispatchableDeliveryQty(activeOrder) : false;
  const activeDeliveryStockKey =
    activeOrder && activeDelivery
      ? [
          activeOrder.id,
          activeDelivery.id,
          activeDelivery.source,
          activeDelivery.status,
          activeWarehouseRef,
          activeDelivery.mode,
          activeDelivery.plannedDate,
          activeDelivery.lines.map((line) => `${line.lineId}:${line.qty}:${line.warehouse ?? ""}`).join("|"),
        ].join("::")
      : "";
  const activeStockValidation = stockValidation?.key === activeDeliveryStockKey ? stockValidation : null;
  const canValidateActiveDeliveryStock =
    !!activeDelivery &&
    (activeDelivery.status === "draft" || activeDeliveryCrossWarehouse) &&
    activeDeliveryQty > 0 &&
    !(activeDelivery.status === "draft" && activeDeliveryHasInvalidQty);
  const canConfirmActiveDelivery =
    !!activeDelivery &&
    (activeDelivery.status === "draft" || activeDeliveryCrossWarehouse) &&
    activeDeliveryQty > 0 &&
    !(activeDelivery.status === "draft" && activeDeliveryHasInvalidQty) &&
    activeStockValidation?.ok === true;
  const workflowActions = (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        disabled={!activeOrder || !activeOrderHasDispatchableQty || processing}
        onClick={addDelivery}
        className="min-h-10 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:bg-softStart disabled:text-secondaryText"
      >
        Agregar entrega
      </button>
      <button
        type="button"
        disabled={!activeDelivery || activeDelivery.status !== "draft" || !activeOrderHasDispatchableQty || processing}
        onClick={fillActiveDeliveryWithMaxQty}
        className="min-h-10 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:bg-softStart disabled:text-secondaryText"
      >
        Entregar todo
      </button>
      <button
        type="button"
        disabled={!canValidateActiveDeliveryStock || processing}
        onClick={() => void validateActiveDeliveryStock(activeDeliveryStockKey)}
        className="min-h-10 rounded border border-emerald-200 bg-emerald-50 px-3 text-[12px] font-semibold text-emerald-800 transition hover:bg-emerald-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 disabled:bg-softStart disabled:text-secondaryText"
      >
        Validar Stock
      </button>
      <button
        type="button"
        disabled={!canConfirmActiveDelivery || processing}
        onClick={() => void confirmActiveDelivery()}
        className="min-h-10 rounded border border-primary/30 bg-primary/10 px-3 text-[12px] font-semibold text-primaryHover transition hover:bg-primary/15 focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
      >
        Confirmar entrega
      </button>
      <button
        type="button"
        disabled={!activeDelivery || activeDelivery.status !== "reserved" || activeDeliveryCrossWarehouse || processing}
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
        disabled={!activeDelivery || activeDelivery.status !== "prepared" || activeDeliveryQty <= 0 || activeDeliveryLockedByRoute || processing}
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

      <section className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(0,0.8fr)_minmax(0,1.7fr)_minmax(0,1fr)] gap-3 overflow-hidden xl:grid-cols-[320px_minmax(0,1fr)_360px] xl:grid-rows-1">
        <aside className="flex min-h-0 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="shrink-0 border-b border-borderSoft px-3 py-2">
            <h2 className="text-[13px] font-semibold text-night">Pedidos facturados</h2>
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
              {loading ? "Buscando..." : "Buscar pedido"}
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
                  ? "Buscando..."
                  : submittedSearch
                    ? "Sin resultados."
                    : "Sin busqueda."}
              </div>
            )}
          </div>
        </aside>

        <main className="flex min-h-0 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          {activeOrder ? (
            <>
              <div className="shrink-0 border-b border-borderSoft px-3 py-3">
                <div className="grid items-start gap-3 2xl:grid-cols-[minmax(0,0.9fr)_minmax(440px,1.1fr)]">
                  <div className="min-w-0 self-start">
                    <p className="text-[11px] font-semibold uppercase text-secondaryText">Pedido seleccionado</p>
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      <h2 className="font-mono text-[18px] font-semibold text-night">{activeOrder.orderNumber}</h2>
                      {warehouseNotice && (
                        <span className={`inline-flex min-h-6 items-center rounded border px-2 font-mono text-[11px] font-semibold ${warehouseNotice.className}`}>
                          {warehouseNotice.label}
                        </span>
                      )}
                      {activeImpactBadges.map((badge) => (
                        <StatusBadge key={badge.key} label={badge.label} tone={badge.tone} />
                      ))}
                    </div>
                    <p className="mt-1 max-w-3xl text-[12px] leading-5 text-secondaryText">
                      {activeOrder.customerName} / {activeOrder.address}
                    </p>
                    <p className="mt-1 max-w-3xl text-[12px] leading-5 text-secondaryText">
                      Autorizado a retirar: <span className="font-semibold text-night">{activeOrder.pickupAuthorizedName}</span>
                      {activeOrder.pickupAuthorizedReference ? ` / ${activeOrder.pickupAuthorizedReference}` : ""}
                    </p>
                  </div>

                  <div className="min-w-0">
                    <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-[11px] lg:grid-cols-4">
                      <div>
                        <div className="font-semibold text-secondaryText">Cliente</div>
                        <div className="mt-1 font-mono text-night">{activeOrder.customerRef}</div>
                      </div>
                      <div>
                        <div className="font-semibold text-secondaryText">Documento</div>
                        <div className="mt-1 font-mono text-night">
                          {[activeOrder.customerDocumentType, activeOrder.customerDni].filter(Boolean).join(" ") || "s/d"}
                        </div>
                      </div>
                      <div className="min-w-0">
                        <div className="font-semibold text-secondaryText">Contacto</div>
                        <div className="mt-1 truncate text-night">{activeOrder.contact || "s/d"}</div>
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
                        <div className="mt-1 font-mono text-night">{formatAppDate(activeOrder.requestedDate)}</div>
                      </div>
                      <div>
                        <div className="font-semibold text-secondaryText">Peso total</div>
                        <div className="mt-1 font-mono text-night">{formatMeasure(activeDeliveryTotals.weightKg, "kg")}</div>
                      </div>
                      <div>
                        <div className="font-semibold text-secondaryText">Volumen total</div>
                        <div className="mt-1 font-mono text-night">{formatMeasure(activeDeliveryTotals.volumeM3, "m3", 4)}</div>
                      </div>
                    </div>

                  </div>
                </div>
              </div>

              <section className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-borderSoft bg-white px-3 py-2">
                <div className="min-w-0 text-[12px] text-secondaryText">
                  {activeDelivery ? (
                    <div className="flex flex-wrap gap-x-4 gap-y-1">
                      <span>
                        Entrega activa <span className="font-mono font-semibold text-night">{activeDelivery.number}</span>
                      </span>
                      {activePartialInfo && <span className="font-semibold text-amber-700">parcial confirmada</span>}
                      <span>
                        Cantidad <span className="font-mono font-semibold text-night">{formatDeliveryQty(activeOrder, activeDelivery)}</span>
                      </span>
                      {activePartialInfo && <span className="font-mono font-semibold text-night">{activePartialInfo.remainingText}</span>}
                      {activeDelivery.status === "draft" && (
                        <span>
                          Stock{" "}
                          <span className={`font-semibold ${activeStockValidation?.ok ? "text-emerald-700" : "text-amber-700"}`}>
                            {activeStockValidation?.ok ? "validado" : "pendiente de validar"}
                          </span>
                        </span>
                      )}
                      {activeDelivery.routeSheet && (
                        <span className="font-semibold text-blue-800">
                          Hoja de ruta <span className="font-mono">{activeDelivery.routeSheet.routeNumber}</span>
                        </span>
                      )}
                      {activeOrder && !activeOrderHasDispatchableQty ? (
                        <span className="font-semibold text-blue-800">Pedido completo en entregas/HR</span>
                      ) : null}
                    </div>
                  ) : (
                    "Sin entrega."
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
                  Autorizado
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
                      <th className="px-3 py-2 font-semibold">Producto</th>
                      <th className="px-3 py-2 font-semibold">Rubro</th>
                      <th className="px-3 py-2 font-semibold">Unidad</th>
                      <th className="px-3 py-2 font-semibold">Pedido</th>
                      <th className="px-3 py-2 font-semibold">Reservado</th>
                      <th className="px-3 py-2 font-semibold">Preparado</th>
                      <th className="px-3 py-2 font-semibold">Disponible</th>
                      <th className="px-3 py-2 font-semibold">A entregar</th>
                      <th className="px-3 py-2 font-semibold">Peso/vol.</th>
                      <th className="px-3 py-2 font-semibold">Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeOrder.lines.map((line) => {
                      const maxUnits = getMaxDispatchableDeliveryUnitQty(line, activeDelivery);
                      const plannedUnits = getDeliveryLineQty(activeDelivery, line.id);
                      const commercialQty = getCommercialQty(line, activeDelivery);
                      const lineWeight = commercialQty * line.unitWeightKg;
                      const lineVolume = commercialQty * line.unitVolumeM3;
                      const issue = plannedUnits > maxUnits;
                      const lineStockValidation = activeStockValidation?.lines[line.id];
                      const stockToneValue: StatusTone = lineStockValidation
                        ? lineStockValidation.status === "issue"
                          ? "danger"
                          : "success"
                        : maxUnits <= 0
                          ? "danger"
                          : issue
                            ? "warning"
                            : "success";
                      const stockLabel = lineStockValidation
                        ? lineStockValidation.status === "issue"
                          ? "sin stock"
                          : "stock ok"
                        : maxUnits <= 0
                          ? "bloqueado"
                          : issue
                            ? "rev."
                            : "ok";
                      const rowClass = lineStockValidation
                        ? lineStockValidation.status === "issue"
                          ? "border-rose-200 bg-rose-50 hover:bg-rose-100"
                          : "border-emerald-200 bg-emerald-50 hover:bg-emerald-100"
                        : "border-borderSoft bg-white hover:bg-softStart";
                      const rowMarkerClass = lineStockValidation
                        ? lineStockValidation.status === "issue"
                          ? "border-l-4 border-l-rose-500"
                          : "border-l-4 border-l-emerald-500"
                        : "";
                      const availableClass = lineStockValidation
                        ? lineStockValidation.status === "issue"
                          ? "text-rose-700"
                          : "text-emerald-700"
                        : "text-primaryHover";
                      const lineInputDisabled = !canEditActiveDelivery || activeDelivery?.status !== "draft" || maxUnits <= 0;

                      return (
                        <tr key={line.id} className={`border-b ${rowClass}`}>
                          <td className={`min-w-64 px-3 py-2 text-night ${rowMarkerClass}`}>
                            <div className="font-mono font-semibold">{line.itemRef}</div>
                            <div className="mt-1 max-w-[28rem] whitespace-normal font-semibold">{line.itemName}</div>
                          </td>
                          <td className="min-w-44 px-3 py-2 text-night">
                            <div>{line.category || "Sin categoria"}</div>
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 font-mono text-night">
                            <div>{line.salesUom}</div>
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 font-mono text-night">
                            <div>{formatQty(line.orderedQty, line.uom)}</div>
                            {line.cancelledQty > 0 && <div className="mt-1 text-[11px] text-rose-700">Anulado {formatQty(line.cancelledQty, line.uom)}</div>}
                            {line.returnedQty > 0 && <div className="mt-1 text-[11px] text-amber-700">Devuelto {formatQty(line.returnedQty, line.uom)}</div>}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{formatQty(getCommittedQty(line), line.uom)}</td>
                          <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{formatQty(line.preparedQty, line.uom)}</td>
                          <td className={`whitespace-nowrap px-3 py-2 font-mono ${availableClass}`}>
                            <div>{formatQty(maxUnits, line.deliveryUom)}</div>
                            {lineStockValidation && (
                              <div className="mt-1 text-[11px]">
                                val. {lineStockValidation.availableQty}
                              </div>
                            )}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2">
                            <label className="sr-only" htmlFor={`qty-${line.id}`}>
                              Cantidad a entregar {line.itemRef}
                            </label>
                            <input
                              id={`qty-${line.id}`}
                              disabled={lineInputDisabled}
                              type="number"
                              min={0}
                              max={maxUnits}
                              step={1}
                              value={plannedUnits}
                              onChange={(event) => updateLineQty(line.id, event.target.value)}
                              className={`h-9 w-24 rounded border bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:bg-softStart ${
                                lineStockValidation?.status === "issue" ? "border-rose-300" : lineStockValidation?.status === "ok" ? "border-emerald-300" : issue ? "border-red-300" : "border-borderSoft"
                              }`}
                            />
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 font-mono text-night">
                            <div>{formatMeasure(lineWeight, "kg")}</div>
                            <div className="mt-1 text-[11px] text-secondaryText">{formatMeasure(lineVolume, "m3", 4)}</div>
                          </td>
                          <td className="whitespace-nowrap px-3 py-2">
                            <StatusBadge label={stockLabel} tone={stockToneValue} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

            </>
          ) : (
            <div className="min-h-0 overflow-auto p-6 text-[12px] text-secondaryText">
              <div className="mt-4">
                {loading
                  ? "Buscando..."
                  : submittedSearch
                    ? "Sin resultados."
                    : "Sin pedido seleccionado."}
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
            </div>
            {summaryDelivery && (
              <StatusBadge
                label={summaryPartialInfo ? "parcial confirmada" : statusLabel[summaryDelivery.status]}
                tone={summaryPartialInfo ? "warning" : statusTone[summaryDelivery.status]}
              />
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {visibleDeliveries.length ? (
              visibleDeliveries.map((delivery) => {
                const partialInfo = getPartialConfirmedInfo(activeOrder, delivery, visibleDeliveries);
                const badgeLabel = delivery.source === "draft" ? "borrador local" : partialInfo ? "parcial confirmada" : statusLabel[delivery.status];
                const badgeTone = partialInfo ? "warning" : statusTone[delivery.status];
                return (
                  <button
                    key={delivery.id}
                    type="button"
                    onClick={() => {
                      if (delivery.status !== "remito") {
                        setActiveDeliveryId(delivery.id);
                      }
                      setSummaryDeliveryId(delivery.id);
                      setMessage(null);
                    }}
                    className={`block w-full border-b border-borderSoft px-3 py-3 text-left transition hover:bg-softStart focus:outline-none focus:ring-2 focus:ring-inset focus:ring-primary/30 ${
                      delivery.id === summaryDelivery?.id ? "bg-white" : "bg-surface"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="font-mono text-[13px] font-semibold text-night">{delivery.number}</div>
                        <div className="mt-1 text-[11px] text-secondaryText">
                          {delivery.issuedAt ? formatAppDateTime(delivery.issuedAt) : formatAppDate(delivery.plannedDate)} / {delivery.mode}
                        </div>
                      </div>
                      <StatusBadge label={badgeLabel} tone={badgeTone} />
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-secondaryText">
                      <div>
                        <span className="font-semibold">Cantidad</span>
                        <div className="font-mono text-night">{formatDeliveryQty(activeOrder, delivery)}</div>
                      </div>
                      <div>
                        <span className="font-semibold">Remito</span>
                        <div className="font-mono text-night">{delivery.remitoNumber ?? "pendiente"}</div>
                      </div>
                      {partialInfo && (
                        <div className="col-span-2">
                          <span className="font-semibold">Saldo</span>
                          <div className="font-mono text-amber-700">{partialInfo.remainingText}</div>
                        </div>
                      )}
                      {delivery.preparationAssignee && (
                        <div className="col-span-2">
                          <span className="font-semibold">Preparador</span>
                          <div className="font-mono text-night">{delivery.preparationAssignee}</div>
                        </div>
                      )}
                      {delivery.routeSheet && (
                        <div className="col-span-2 rounded border border-blue-200 bg-blue-50 px-2 py-1 text-blue-800">
                          En hoja de ruta <span className="font-mono font-semibold">{delivery.routeSheet.routeNumber}</span>
                        </div>
                      )}
                    </div>
                  </button>
                );
              })
            ) : (
              <div className="px-3 py-6 text-[12px] text-secondaryText">Sin entregas.</div>
            )}
            {activeOrder && (
              <div className="border-t border-borderSoft bg-surface p-3">
                <TraceabilitySection events={orderTimelineEvents} recordRef={activeOrder.orderNumber} />
              </div>
            )}
          </div>

          <div className="shrink-0 border-t border-borderSoft bg-white px-3 py-3">
            <div className="flex items-start justify-between gap-3">
              <h3 className="text-[12px] font-semibold uppercase text-secondaryText">{summaryHasRemito ? "Resumen de remito" : "Resumen de entrega"}</h3>
              {summaryDelivery && (
                <div className="text-right">
                  <div className="text-[10px] font-semibold uppercase text-secondaryText">Remito</div>
                  <div className="mt-0.5 font-mono text-[12px] font-semibold text-night">{summaryDelivery.remitoNumber ?? "no emitido"}</div>
                </div>
              )}
            </div>
            {summaryDelivery ? (
              <>
                <dl className="mt-3 grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-[12px]">
                  <dt className="font-semibold text-secondaryText">Entrega</dt>
                  <dd className="font-mono text-night">{summaryDelivery.number}</dd>
                  <dt className="font-semibold text-secondaryText">Fecha</dt>
                  <dd className="font-mono text-night">{formatAppDateTime(summaryDelivery.issuedAt || summaryDelivery.plannedDate)}</dd>
                  <dt className="font-semibold text-secondaryText">Autorizado</dt>
                  <dd className="min-w-0 break-words text-night">{summaryDelivery.receiver || "sin informar"}</dd>
                  <dt className="font-semibold text-secondaryText">Almacen retiro</dt>
                  <dd className="font-mono text-night">{summaryDeliveryWarehouse}</dd>
                  <dt className="font-semibold text-secondaryText">Unidades</dt>
                  <dd className="font-mono text-night">{formatQty(summaryDeliveryTotals.deliveryUnits)}</dd>
                  <dt className="font-semibold text-secondaryText">Peso</dt>
                  <dd className="font-mono text-night">{formatMeasure(summaryDeliveryTotals.weightKg, "kg")}</dd>
                  <dt className="font-semibold text-secondaryText">Volumen</dt>
                  <dd className="font-mono text-night">{formatMeasure(summaryDeliveryTotals.volumeM3, "m3", 4)}</dd>
                  <dt className="font-semibold text-secondaryText">Preparador</dt>
                  <dd className="font-mono text-night">{summaryDelivery.preparationAssignee ?? "sin asignar"}</dd>
                </dl>
                <div className="mt-3 border-t border-borderSoft pt-3">
                  <h4 className="text-[11px] font-semibold uppercase text-secondaryText">
                    {summaryHasRemito ? "Articulos del remito" : "Articulos de la entrega"}
                  </h4>
                  <table className="mt-2 w-full border-collapse text-left text-[11px]">
                    <thead className="bg-softMid text-secondaryText">
                      <tr>
                        <th className="px-2 py-1 font-semibold">Articulo</th>
                        <th className="px-2 py-1 font-semibold">Cantidad</th>
                        <th className="px-2 py-1 font-semibold">Almacen</th>
                      </tr>
                    </thead>
                    <tbody>
                      {summaryDeliveryLines.map((line) => (
                        <tr key={line.id} className="border-t border-borderSoft">
                          <td className="px-2 py-1 text-night">
                            <div className="font-mono font-semibold">{line.itemRef}</div>
                            <div className="mt-0.5 leading-4">{line.itemName}</div>
                          </td>
                          <td className="px-2 py-1 font-mono text-night">
                            <div>{formatQty(line.deliveryQty, line.deliveryUom)}</div>
                            {line.conversionFactor !== 1 && (
                              <div className="mt-0.5 text-secondaryText">{formatQty(line.commercialQty, line.commercialUom)}</div>
                            )}
                          </td>
                          <td className="px-2 py-1 font-mono text-night">{line.warehouse || "s/d"}</td>
                        </tr>
                      ))}
                      {!summaryDeliveryLines.length && (
                        <tr>
                          <td className="px-2 py-2 text-secondaryText" colSpan={3}>
                            Sin articulos.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <p className="mt-3 text-[12px] text-secondaryText">Sin entrega seleccionada.</p>
            )}
          </div>
        </aside>
      </section>
      {warehouseConflict && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-deep/45 px-4 py-6"
          role="dialog"
          aria-modal="true"
          aria-labelledby="warehouse-conflict-title"
          aria-describedby="warehouse-conflict-description"
          onKeyDown={(event) => {
            if (event.key === "Escape" && !processing) {
              setWarehouseConflict(null);
            }
          }}
        >
          <div className="w-full max-w-lg rounded border border-borderSoft bg-white shadow-panel">
            <div className="border-b border-borderSoft px-4 py-3">
              <p className="text-[11px] font-semibold uppercase text-amber-700">Confirmacion requerida</p>
              <h2 id="warehouse-conflict-title" className="mt-1 text-[16px] font-semibold text-night">
                Entrega confirmada en otro deposito
              </h2>
            </div>
            <div className="px-4 py-3">
              <p id="warehouse-conflict-description" className="text-[13px] leading-5 text-secondaryText">
                <span className="font-mono font-semibold text-night">{warehouseConflict.deliveryNumber}</span> / origen{" "}
                <span className="font-mono font-semibold text-night">{warehouseConflict.sourceWarehouseRef || "otro deposito"}</span> / destino{" "}
                <span className="font-mono font-semibold text-night">{warehouseConflict.targetWarehouseRef || activeWarehouseRef}</span>
              </p>
              <dl className="mt-3 grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-2 rounded border border-borderSoft bg-softMid px-3 py-2 text-[12px]">
                <dt className="font-semibold text-secondaryText">Pedido</dt>
                <dd className="font-mono text-night">{warehouseConflict.salesOrderNumber || activeOrder?.orderNumber || "s/d"}</dd>
                <dt className="font-semibold text-secondaryText">Entrega</dt>
                <dd className="font-mono text-night">{warehouseConflict.deliveryNumber}</dd>
                <dt className="font-semibold text-secondaryText">Estado</dt>
                <dd className="font-mono text-night">{warehouseConflict.status || "confirmed"}</dd>
              </dl>
            </div>
            <div className="flex flex-wrap justify-end gap-2 border-t border-borderSoft px-4 py-3">
              <button
                type="button"
                disabled={processing}
                onClick={() => setWarehouseConflict(null)}
                className="min-h-10 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:bg-softStart disabled:text-secondaryText"
              >
                Cancelar
              </button>
              <button
                ref={conflictConfirmRef}
                type="button"
                disabled={processing}
                onClick={() => void confirmWarehouseReassignment()}
                className="min-h-10 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:cursor-not-allowed disabled:bg-softStart disabled:text-secondaryText"
              >
                {processing ? "Confirmando..." : `Confirmar en ${warehouseConflict.targetWarehouseRef || activeWarehouseRef}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
