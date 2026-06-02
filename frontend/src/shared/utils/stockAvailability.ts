import type { ApiStockValidationResult } from "../../api/fulfillment";

const EPSILON = 0.000001;

export type StockAvailabilityStatus = "ok" | "partial" | "missing";

export type StockAvailabilitySourceLine = {
  id: string;
  fulfillmentLineId?: string;
  deliveryLineId?: string | null;
  itemRef: string;
  itemName?: string;
  warehouseRef: string;
  plannedQty: number;
  uom: string;
  deliveryUom?: string;
  conversionFactor?: number;
  requestedDeliveryQty?: number;
  wholeDeliveryUnits?: boolean;
};

export type StockAvailabilityLine = StockAvailabilitySourceLine & {
  status: StockAvailabilityStatus;
  requestedQty: number;
  availableQty: number;
  confirmQty: number;
  missingQty: number;
  requestedDeliveryQty: number;
  availableDeliveryQty: number;
  missingDeliveryQty: number;
};

function asNumber(value: string | number | null | undefined) {
  const numberValue = Number(value ?? 0);
  return Number.isFinite(numberValue) ? numberValue : 0;
}

function lineIds(line: StockAvailabilitySourceLine) {
  return [line.id, line.fulfillmentLineId, line.deliveryLineId].filter(Boolean).map(String);
}

function validationLineById(result: ApiStockValidationResult) {
  const rows = [...result.lines, ...result.issues];
  const byId = new Map<string, (typeof rows)[number]>();
  rows.forEach((row) => {
    [row.line_id, "fulfillment_line_id" in row ? row.fulfillment_line_id : ""]
      .filter(Boolean)
      .forEach((id) => byId.set(String(id), row));
  });
  return byId;
}

function bucketKey(warehouseRef: string, itemRef: string, uom: string) {
  return `${warehouseRef}::${itemRef}::${uom}`;
}

function availableDeliveryQty(confirmQty: number, conversionFactor: number, wholeDeliveryUnits: boolean) {
  const rawQty = confirmQty / conversionFactor;
  return wholeDeliveryUnits ? Math.floor(rawQty + EPSILON) : rawQty;
}

export function classifyStockAvailability(
  result: ApiStockValidationResult,
  sourceLines: StockAvailabilitySourceLine[],
): StockAvailabilityLine[] {
  const byId = validationLineById(result);
  const enriched = sourceLines
    .map((sourceLine, index) => {
      const validationLine = lineIds(sourceLine).map((id) => byId.get(id)).find(Boolean);
      const requestedQty = validationLine ? asNumber(validationLine.planned_qty) : sourceLine.plannedQty;
      const availableQty = validationLine ? asNumber(validationLine.available_qty) : sourceLine.plannedQty;
      return {
        sourceLine,
        index,
        requestedQty,
        availableQty,
        bucket: bucketKey(
          validationLine?.warehouse_ref || sourceLine.warehouseRef,
          validationLine?.item_ref || sourceLine.itemRef,
          validationLine?.uom || sourceLine.uom,
        ),
      };
    })
    .filter((line) => line.requestedQty > EPSILON);

  const bucketAvailable = new Map<string, number>();
  enriched.forEach((line) => {
    bucketAvailable.set(line.bucket, Math.max(bucketAvailable.get(line.bucket) ?? 0, line.availableQty));
  });

  const remainingByBucket = new Map(bucketAvailable);
  return enriched
    .sort((left, right) => left.index - right.index)
    .map(({ sourceLine, requestedQty, bucket }) => {
      const conversionFactor = Math.max(sourceLine.conversionFactor || 1, EPSILON);
      const remaining = Math.max(0, remainingByBucket.get(bucket) ?? 0);
      const rawConfirmQty = Math.min(requestedQty, remaining);
      const nextAvailableDeliveryQty = availableDeliveryQty(rawConfirmQty, conversionFactor, Boolean(sourceLine.wholeDeliveryUnits));
      const confirmQty = Math.min(requestedQty, nextAvailableDeliveryQty * conversionFactor);
      remainingByBucket.set(bucket, Math.max(0, remaining - confirmQty));
      const requestedDeliveryQty = sourceLine.requestedDeliveryQty ?? requestedQty / conversionFactor;
      const missingQty = Math.max(0, requestedQty - confirmQty);
      const missingDeliveryQty = Math.max(0, requestedDeliveryQty - nextAvailableDeliveryQty);
      const status: StockAvailabilityStatus =
        confirmQty + EPSILON >= requestedQty ? "ok" : confirmQty > EPSILON ? "partial" : "missing";
      return {
        ...sourceLine,
        status,
        requestedQty,
        availableQty: rawConfirmQty,
        confirmQty,
        missingQty,
        requestedDeliveryQty,
        availableDeliveryQty: nextAvailableDeliveryQty,
        missingDeliveryQty,
      };
    });
}

export function hasConfirmableStock(lines: StockAvailabilityLine[]) {
  return lines.some((line) => line.confirmQty > EPSILON);
}

export function hasPartialOrMissingStock(lines: StockAvailabilityLine[]) {
  return lines.some((line) => line.status !== "ok");
}
