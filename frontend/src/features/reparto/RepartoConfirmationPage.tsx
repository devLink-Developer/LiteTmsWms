import { Fragment, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, CheckCircle2, ChevronDown, ChevronRight, Filter, PackageCheck, RefreshCw, Search, ShieldCheck } from "lucide-react";

import {
  checkDeliveryStock,
  checkFulfillmentStock,
  confirmAvailableDeliveryStock,
  confirmDeliveryStock,
  fetchRepartoDeliveries,
  splitFulfillmentDelivery,
  type ApiStockValidationResult,
  type ApiRepartoDelivery,
} from "../../api/fulfillment";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { notify, useToastError } from "../../shared/components/toast";
import { formatAppDate } from "../../shared/utils/dateFormat";
import { formatIdentifier } from "../../shared/utils/identifierFormat";
import {
  classifyStockAvailability,
  hasConfirmableStock,
} from "../../shared/utils/stockAvailability";
import type { StatusTone } from "../../types/operations";

type StatusView = "pending" | "confirmed" | "all";
type StockResultByRow = Record<string, { key: string; result: ApiStockValidationResult }>;
type AvailableConfirmationState = {
  rows: ApiRepartoDelivery[];
} | null;

const statusTone: Record<string, StatusTone> = {
  pending: "warning",
  created: "neutral",
  planned: "warning",
  confirmed: "info",
  reserved: "info",
  preparing: "warning",
  prepared: "success",
  assigned: "info",
  loaded: "warning",
  in_route: "info",
  delivered_partial: "warning",
  delivered_complete: "success",
  returned: "danger",
  cancelled: "danger",
};

const statusLabel: Record<string, string> = {
  pending: "pedido sin entrega",
  created: "creada",
  planned: "planificada",
  confirmed: "confirmada",
  reserved: "reservada",
  preparing: "en preparacion",
  prepared: "preparada",
  assigned: "asignada",
  loaded: "cargada",
  in_route: "en ruta",
  delivered_partial: "parcial",
  delivered_complete: "entregada",
  returned: "devuelta",
  cancelled: "cancelada",
};

function localDateInputValue(date = new Date()) {
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return localDate.toISOString().slice(0, 10);
}

function asNumber(value: string | number | null | undefined) {
  const numberValue = Number(value ?? 0);
  return Number.isFinite(numberValue) ? numberValue : 0;
}

function formatNumber(value: string | number | null | undefined, maximumFractionDigits = 2) {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits }).format(asNumber(value));
}

function statusParam(view: StatusView) {
  if (view === "pending") return "created,planned";
  if (view === "confirmed") return "confirmed,reserved";
  return "";
}

function canConfirm(delivery: ApiRepartoDelivery) {
  return delivery.source_type === "fulfillment" || delivery.status === "created" || delivery.status === "planned";
}

function rowAddress(delivery: ApiRepartoDelivery) {
  const snapshot = delivery.address_snapshot ?? {};
  return [snapshot.street, snapshot.street_number, snapshot.city].filter(Boolean).join(" ") || snapshot.reference || "Sin direccion";
}

function orderRef(delivery: ApiRepartoDelivery) {
  return formatIdentifier(delivery.sales_order_number || delivery.fulfillment_number);
}

function rowStockKey(delivery: ApiRepartoDelivery) {
  return [
    delivery.id,
    delivery.status,
    delivery.planned_date ?? "",
    delivery.lines.map((line) => `${line.fulfillment_line_id}:${line.split_qty}:${line.warehouse_ref}`).join("|"),
  ].join("::");
}

function lineKey(line: ApiRepartoDelivery["lines"][number]) {
  return line.delivery_line_id || line.fulfillment_line_id;
}

function stockLineFor(line: ApiRepartoDelivery["lines"][number], result: ApiStockValidationResult | null | undefined) {
  if (!result) return null;
  const ids = [line.delivery_line_id, line.fulfillment_line_id].filter(Boolean);
  return (
    result.lines.find((candidate) => ids.includes(candidate.line_id) || ids.includes(candidate.fulfillment_line_id ?? "")) ??
    result.issues.find((candidate) => ids.includes(candidate.line_id)) ??
    null
  );
}

function lineConversionFactor(line: ApiRepartoDelivery["lines"][number]) {
  return Math.max(asNumber(line.conversion_factor) || 1, 0.000001);
}

function stockAvailabilitySourcesForReparto(delivery: ApiRepartoDelivery) {
  return delivery.lines
    .map((line) => {
      const conversionFactor = lineConversionFactor(line);
      return {
        id: lineKey(line),
        fulfillmentLineId: line.fulfillment_line_id,
        deliveryLineId: line.delivery_line_id,
        itemRef: line.item_ref,
        itemName: line.item_name || line.item_long_name || "",
        warehouseRef: line.warehouse_ref || delivery.warehouse_ref,
        plannedQty: asNumber(line.split_qty),
        uom: line.uom,
        deliveryUom: line.delivery_uom || line.uom,
        conversionFactor,
        requestedDeliveryQty: asNumber(line.delivery_unit_qty ?? line.split_qty),
        wholeDeliveryUnits: true,
      };
    })
    .filter((line) => line.plannedQty > 0);
}

function stockAvailabilityForDelivery(delivery: ApiRepartoDelivery, result: ApiStockValidationResult | null | undefined) {
  return result ? classifyStockAvailability(result, stockAvailabilitySourcesForReparto(delivery)) : [];
}

function rowHasConfirmableAvailableStock(delivery: ApiRepartoDelivery, result: ApiStockValidationResult | null | undefined) {
  const availability = stockAvailabilityForDelivery(delivery, result);
  return Boolean(result && !result.can_confirm && hasConfirmableStock(availability));
}

async function mapWithConcurrency<T, R>(items: T[], limit: number, handler: (item: T) => Promise<R>) {
  const results: R[] = new Array(items.length);
  let nextIndex = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (nextIndex < items.length) {
      const currentIndex = nextIndex;
      nextIndex += 1;
      results[currentIndex] = await handler(items[currentIndex]);
    }
  });
  await Promise.all(workers);
  return results;
}

export function RepartoConfirmationPage() {
  const queryClient = useQueryClient();
  const today = useMemo(() => localDateInputValue(), []);
  const [plannedDate, setPlannedDate] = useState(localDateInputValue());
  const [query, setQuery] = useState("");
  const [statusView, setStatusView] = useState<StatusView>("pending");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [validatedRows, setValidatedRows] = useState<Record<string, string>>({});
  const [stockResults, setStockResults] = useState<StockResultByRow>({});
  const [expandedIds, setExpandedIds] = useState<string[]>([]);
  const [availableConfirmation, setAvailableConfirmation] = useState<AvailableConfirmationState>(null);

  const deliveriesQuery = useQuery({
    queryKey: ["reparto-confirmation", plannedDate, query, statusView],
    queryFn: () =>
      fetchRepartoDeliveries({
        plannedDate,
        query: query.trim(),
        status: statusParam(statusView),
      }),
  });

  const deliveries = deliveriesQuery.data ?? [];
  const confirmableDeliveries = useMemo(() => deliveries.filter(canConfirm), [deliveries]);
  const selectedDeliveries = useMemo(
    () => deliveries.filter((delivery) => selectedIds.includes(delivery.id) && canConfirm(delivery)),
    [deliveries, selectedIds],
  );
  const selectedDeliveriesValidated = selectedDeliveries.length > 0 && selectedDeliveries.every((delivery) => validatedRows[delivery.id] === rowStockKey(delivery));
  const selectedDeliveriesWithAvailableStock = useMemo(
    () =>
      selectedDeliveries.filter((delivery) => {
        const stockResult = stockResults[delivery.id]?.key === rowStockKey(delivery) ? stockResults[delivery.id].result : null;
        return rowHasConfirmableAvailableStock(delivery, stockResult);
      }),
    [selectedDeliveries, stockResults],
  );
  const availableConfirmationRows = useMemo(
    () =>
      (availableConfirmation?.rows ?? []).map((delivery) => {
        const stockResult = stockResults[delivery.id]?.key === rowStockKey(delivery) ? stockResults[delivery.id].result : null;
        return {
          delivery,
          availability: stockAvailabilityForDelivery(delivery, stockResult),
        };
      }),
    [availableConfirmation, stockResults],
  );
  const availableConfirmationHasLines = availableConfirmationRows.some((row) => row.availability.some((line) => line.confirmQty > 0));
  const pendingCount = confirmableDeliveries.length;
  const confirmedCount = deliveries.filter((delivery) => ["confirmed", "reserved"].includes(delivery.status)).length;
  const allConfirmableSelected = confirmableDeliveries.length > 0 && confirmableDeliveries.every((delivery) => selectedIds.includes(delivery.id));
  const totalQty = deliveries.reduce((total, delivery) => total + asNumber(delivery.total_qty), 0);
  const totalWeight = deliveries.reduce((total, delivery) => total + asNumber(delivery.total_weight_kg), 0);
  const totalVolume = deliveries.reduce((total, delivery) => total + asNumber(delivery.total_volume_m3), 0);

  useEffect(() => {
    setValidatedRows({});
    setStockResults({});
    setExpandedIds([]);
    setAvailableConfirmation(null);
  }, [plannedDate, query, statusView]);

  function handlePlannedDateChange(value: string) {
    setPlannedDate(value && value >= today ? value : today);
  }

  const validateStockMutation = useMutation({
    mutationFn: async (rows: ApiRepartoDelivery[]) => {
      return mapWithConcurrency(rows, 4, async (row) => {
        const result =
          row.source_type === "fulfillment"
            ? await checkFulfillmentStock(
                row.fulfillment_id,
                row.lines.map((line) => ({
                  fulfillment_line_id: line.fulfillment_line_id,
                  split_qty: asNumber(line.split_qty),
                })),
              )
            : row.delivery_id
              ? await checkDeliveryStock(row.delivery_id)
              : null;
        if (!result) {
          throw new Error("Fila sin entrega.");
        }
        return { id: row.id, key: rowStockKey(row), result };
      });
    },
    onSuccess: (validated) => {
      const okRows = validated.filter((row) => row.result.can_confirm);
      const blockedRows = validated.length - okRows.length;
      setValidatedRows((current) => {
        const next = { ...current };
        validated.forEach((row) => {
          delete next[row.id];
        });
        okRows.forEach((row) => {
          next[row.id] = row.key;
        });
        return next;
      });
      setStockResults((current) => ({
        ...current,
        ...Object.fromEntries(validated.map((row) => [row.id, { key: row.key, result: row.result }])),
      }));
      setExpandedIds((current) => Array.from(new Set([...current, ...validated.map((row) => row.id)])));
      notify({
        message: blockedRows
          ? `${okRows.length} con stock / ${blockedRows} sin stock.`
          : `${validated.length} pedido${validated.length === 1 ? "" : "s"} con stock.`,
        tone: blockedRows ? "warning" : "success",
      });
    },
  });

  const confirmMutation = useMutation({
    mutationFn: async (rows: ApiRepartoDelivery[]) => {
      const missingValidation = rows.find((row) => validatedRows[row.id] !== rowStockKey(row));
      if (missingValidation) {
        throw new Error(`Stock sin validar ${orderRef(missingValidation)}.`);
      }
      return mapWithConcurrency(rows, 3, async (row) => {
        if (row.source_type === "fulfillment") {
          const delivery = await splitFulfillmentDelivery(row.fulfillment_id, {
            delivery_mode: row.delivery_mode,
            planned_date: row.planned_date || plannedDate,
            reason: "Confirmacion reparto desde cola operativa",
            lines: row.lines.map((line) => ({
              fulfillment_line_id: line.fulfillment_line_id,
              split_qty: asNumber(line.split_qty),
            })),
          });
          return confirmDeliveryStock(delivery.id);
        } else if (row.delivery_id) {
          return confirmDeliveryStock(row.delivery_id);
        }
        throw new Error("Fila sin entrega.");
      });
    },
    onSuccess: (confirmed) => {
      setSelectedIds([]);
      setValidatedRows({});
      setStockResults({});
      setExpandedIds([]);
      setAvailableConfirmation(null);
      notify({
        message: `${confirmed.length} entrega${confirmed.length === 1 ? "" : "s"} confirmada${confirmed.length === 1 ? "" : "s"}.`,
        tone: "success",
      });
      void queryClient.invalidateQueries({ queryKey: ["reparto-confirmation"] });
    },
  });

  const confirmAvailableMutation = useMutation({
    mutationFn: async (rows: ApiRepartoDelivery[]) => {
      return mapWithConcurrency(rows, 3, async (row) => {
        const stockResult = stockResults[row.id]?.key === rowStockKey(row) ? stockResults[row.id].result : null;
        const availability = stockAvailabilityForDelivery(row, stockResult);
        const availableLines = availability.filter((line) => line.confirmQty > 0);
        if (!stockResult || !availableLines.length) {
          throw new Error(`Sin stock disponible validado ${orderRef(row)}.`);
        }
        if (row.source_type === "fulfillment") {
          const lines = availableLines.map((line) => ({
            fulfillment_line_id: line.fulfillmentLineId || line.id,
            split_qty: line.confirmQty,
          }));
          const revalidated = await checkFulfillmentStock(row.fulfillment_id, lines);
          if (!revalidated.can_confirm) {
            throw new Error(`El stock disponible cambio ${orderRef(row)}.`);
          }
          const delivery = await splitFulfillmentDelivery(row.fulfillment_id, {
            delivery_mode: row.delivery_mode,
            planned_date: row.planned_date || plannedDate,
            reason: "Confirmacion parcial de reparto por stock disponible",
            lines,
          });
          return confirmDeliveryStock(delivery.id);
        }
        if (row.delivery_id) {
          return confirmAvailableDeliveryStock(row.delivery_id, {
            lines: availableLines
              .filter((line) => line.deliveryLineId)
              .map((line) => ({ delivery_line_id: String(line.deliveryLineId), planned_qty: line.confirmQty })),
          });
        }
        throw new Error("Fila sin entrega.");
      });
    },
    onSuccess: (confirmed) => {
      setSelectedIds([]);
      setValidatedRows({});
      setStockResults({});
      setExpandedIds([]);
      setAvailableConfirmation(null);
      notify({
        message: `${confirmed.length} entrega${confirmed.length === 1 ? "" : "s"} parcial${confirmed.length === 1 ? "" : "es"} confirmada${confirmed.length === 1 ? "" : "s"}.`,
        tone: "success",
      });
      void queryClient.invalidateQueries({ queryKey: ["reparto-confirmation"] });
    },
  });

  function toggleSelection(id: string) {
    setSelectedIds((current) => (current.includes(id) ? current.filter((candidate) => candidate !== id) : [...current, id]));
  }

  function selectAllConfirmable() {
    setSelectedIds(confirmableDeliveries.map((delivery) => delivery.id));
  }

  function clearSelection() {
    setSelectedIds([]);
  }

  function toggleExpanded(id: string) {
    setExpandedIds((current) => (current.includes(id) ? current.filter((candidate) => candidate !== id) : [...current, id]));
  }

  const busy =
    deliveriesQuery.isLoading ||
    deliveriesQuery.isFetching ||
    validateStockMutation.isPending ||
    confirmMutation.isPending ||
    confirmAvailableMutation.isPending;
  const error = deliveriesQuery.error || validateStockMutation.error || confirmMutation.error || confirmAvailableMutation.error;
  useToastError(error);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-3">
      <header className="flex shrink-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[20px] font-semibold text-night">Confirmacion de reparto</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge label={`${pendingCount} pendientes`} tone={pendingCount ? "warning" : "success"} />
          <StatusBadge label={`${confirmedCount} confirmadas`} tone="info" />
          <button
            type="button"
            disabled={!selectedDeliveries.length || busy}
            onClick={() => validateStockMutation.mutate(selectedDeliveries)}
            className="inline-flex min-h-9 items-center gap-2 rounded border border-emerald-200 bg-emerald-50 px-3 text-[12px] font-semibold text-emerald-800 transition hover:bg-emerald-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 disabled:bg-softStart disabled:text-secondaryText"
          >
            <ShieldCheck size={15} />
            Validar Stock seleccionadas
          </button>
          <button
            type="button"
            disabled={!selectedDeliveriesValidated || busy}
            onClick={() => confirmMutation.mutate(selectedDeliveries)}
            className="inline-flex min-h-9 items-center gap-2 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:bg-softStart disabled:text-secondaryText"
          >
            <CheckCircle2 size={15} />
            Confirmar seleccionadas
          </button>
          <button
            type="button"
            disabled={!selectedDeliveriesWithAvailableStock.length || busy}
            onClick={() => setAvailableConfirmation({ rows: selectedDeliveriesWithAvailableStock })}
            className="inline-flex min-h-9 items-center gap-2 rounded border border-amber-300 bg-amber-50 px-3 text-[12px] font-semibold text-amber-800 transition hover:bg-amber-100 focus:outline-none focus:ring-2 focus:ring-amber-500/20 disabled:bg-softStart disabled:text-secondaryText"
          >
            <PackageCheck size={15} />
            Confirmar disponibles seleccionadas
          </button>
        </div>
      </header>

      <section className="grid shrink-0 gap-2 rounded border border-borderSoft bg-white p-3 shadow-panel lg:grid-cols-[180px_minmax(220px,1fr)_auto]">
        <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
          Fecha entrega
          <span className="relative">
            <CalendarDays className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-secondaryText" size={15} />
            <input
              type="date"
              value={plannedDate}
              min={today}
              required
              onBlur={(event) => handlePlannedDateChange(event.target.value)}
              onChange={(event) => handlePlannedDateChange(event.target.value)}
              className="h-10 w-full rounded border border-borderSoft bg-white pl-8 pr-2 text-[13px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
            />
          </span>
        </label>
        <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
          Buscar
          <span className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-secondaryText" size={15} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Pedido, entrega o cliente"
              className="h-10 w-full rounded border border-borderSoft bg-white pl-8 pr-2 text-[13px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
            />
          </span>
        </label>
        <div className="grid gap-1 text-[11px] font-semibold text-secondaryText">
          Estado
          <div className="grid h-10 grid-cols-3 rounded border border-borderSoft bg-softMid p-1">
            {[
              ["pending", "Pendientes"],
              ["confirmed", "Confirmadas"],
              ["all", "Todas"],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => {
                  setStatusView(value as StatusView);
                  setSelectedIds([]);
                }}
                className={`rounded px-2 text-[12px] font-semibold transition focus:outline-none focus:ring-2 focus:ring-primary/20 ${
                  statusView === value ? "bg-primary text-white" : "text-secondaryText hover:bg-white hover:text-night"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="grid shrink-0 grid-cols-2 gap-2 md:grid-cols-6">
        <div className="rounded border border-borderSoft bg-surface px-3 py-2">
          <div className="text-[11px] font-semibold uppercase text-secondaryText">Fecha</div>
          <div className="mt-1 font-mono text-[14px] font-semibold text-night">{formatAppDate(plannedDate)}</div>
        </div>
        <div className="rounded border border-borderSoft bg-surface px-3 py-2">
          <div className="text-[11px] font-semibold uppercase text-secondaryText">Pedidos</div>
          <div className="mt-1 font-mono text-[14px] font-semibold text-night">{deliveries.length}</div>
        </div>
        <div className="rounded border border-borderSoft bg-surface px-3 py-2">
          <div className="text-[11px] font-semibold uppercase text-secondaryText">Unidades</div>
          <div className="mt-1 font-mono text-[14px] font-semibold text-night">{formatNumber(totalQty)}</div>
        </div>
        <div className="rounded border border-borderSoft bg-surface px-3 py-2">
          <div className="text-[11px] font-semibold uppercase text-secondaryText">Peso</div>
          <div className="mt-1 font-mono text-[14px] font-semibold text-night">{formatNumber(totalWeight)} kg</div>
        </div>
        <div className="rounded border border-borderSoft bg-surface px-3 py-2">
          <div className="text-[11px] font-semibold uppercase text-secondaryText">Volumen</div>
          <div className="mt-1 font-mono text-[14px] font-semibold text-night">{formatNumber(totalVolume, 4)} m3</div>
        </div>
        <div className="rounded border border-borderSoft bg-surface px-3 py-2">
          <div className="text-[11px] font-semibold uppercase text-secondaryText">Seleccion</div>
          <div className="mt-1 font-mono text-[14px] font-semibold text-night">{selectedDeliveries.length}</div>
        </div>
      </section>

      <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
        <div className="flex min-h-11 shrink-0 items-center justify-between border-b border-borderSoft bg-white px-3">
          <div className="inline-flex items-center gap-2 text-[12px] font-semibold text-night">
            <PackageCheck size={15} className="text-primary" />
            Pedidos de reparto
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={selectAllConfirmable}
              disabled={!confirmableDeliveries.length || allConfirmableSelected || busy}
              className="inline-flex min-h-8 items-center gap-2 rounded border border-borderSoft bg-white px-2 text-[12px] font-semibold text-night transition hover:bg-softStart focus:outline-none focus:ring-2 focus:ring-primary/20"
            >
              <CheckCircle2 size={14} />
              Seleccionar todas
            </button>
            <button
              type="button"
              onClick={clearSelection}
              disabled={!selectedIds.length || busy}
              className="inline-flex min-h-8 items-center gap-2 rounded border border-borderSoft bg-white px-2 text-[12px] font-semibold text-night transition hover:bg-softStart focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:text-secondaryText"
            >
              <Filter size={14} />
              Limpiar
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void deliveriesQuery.refetch()}
              className="inline-flex min-h-8 items-center gap-2 rounded border border-borderSoft bg-white px-2 text-[12px] font-semibold text-night transition hover:bg-softStart focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:text-secondaryText"
            >
              <RefreshCw size={14} />
              Actualizar
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-auto">
          <table className="w-full border-collapse text-left text-[12px]">
            <thead className="sticky top-0 z-10 border-b border-borderSoft bg-softMid text-[11px] uppercase text-secondaryText">
              <tr>
                <th className="w-10 px-3 py-2">
                  <span className="sr-only">Seleccion</span>
                </th>
                <th className="px-3 py-2 font-semibold">Pedido / entrega</th>
                <th className="px-3 py-2 font-semibold">Cliente</th>
                <th className="px-3 py-2 font-semibold">Estado</th>
                <th className="px-3 py-2 font-semibold">Carga</th>
                <th className="px-3 py-2 font-semibold">Direccion</th>
                <th className="px-3 py-2 text-right font-semibold">Accion</th>
              </tr>
            </thead>
            <tbody>
              {deliveries.map((delivery) => {
                const confirmable = canConfirm(delivery);
                const selected = selectedIds.includes(delivery.id);
                const stockResult = stockResults[delivery.id]?.key === rowStockKey(delivery) ? stockResults[delivery.id].result : null;
                const stockValidated = validatedRows[delivery.id] === rowStockKey(delivery) && stockResult?.can_confirm !== false;
                const stockBlocked = stockResult?.can_confirm === false;
                const stockAvailability = stockAvailabilityForDelivery(delivery, stockResult);
                const stockAvailabilityByLine = new Map(stockAvailability.map((line) => [line.id, line]));
                const stockPartial = Boolean(stockBlocked && hasConfirmableStock(stockAvailability));
                const expanded = expandedIds.includes(delivery.id) || !!stockResult;
                return (
                  <Fragment key={delivery.id}>
                  <tr className="border-b border-borderSoft bg-white transition hover:bg-softStart">
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          aria-label={`${expanded ? "Ocultar" : "Ver"} lineas ${orderRef(delivery)}`}
                          onClick={() => toggleExpanded(delivery.id)}
                          className="inline-flex h-7 w-7 items-center justify-center rounded border border-borderSoft bg-white text-secondaryText transition hover:text-night focus:outline-none focus:ring-2 focus:ring-primary/20"
                        >
                          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </button>
                        <input
                          type="checkbox"
                          aria-label={`Seleccionar ${orderRef(delivery)}`}
                          checked={selected}
                          disabled={!confirmable}
                          onChange={() => toggleSelection(delivery.id)}
                          className="h-4 w-4 rounded border-borderSoft text-primary focus:ring-primary/30 disabled:opacity-40"
                        />
                      </div>
                    </td>
                    <td className="min-w-48 px-3 py-2">
                      <div className="font-mono text-[12px] font-semibold text-night">
                        {orderRef(delivery)}
                      </div>
                      {delivery.source_type === "fulfillment" && (
                        <div className="mt-1 text-[11px] font-semibold text-amber-700">sin entrega generada</div>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{delivery.customer_ref}</td>
                    <td className="whitespace-nowrap px-3 py-2">
                      <div className="flex flex-col items-start gap-1">
                        <StatusBadge label={statusLabel[delivery.status] ?? delivery.status} tone={statusTone[delivery.status] ?? "neutral"} />
                        {confirmable && (
                          <span className={`text-[11px] font-semibold ${stockValidated ? "text-emerald-700" : stockPartial ? "text-amber-700" : stockBlocked ? "text-red-700" : "text-amber-700"}`}>
                            {stockValidated ? "stock validado" : stockPartial ? "stock parcial" : stockBlocked ? "sin stock" : "stock pendiente"}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-night">
                      <div>{formatNumber(delivery.total_qty)} un</div>
                      <div className="mt-1 text-[11px] text-secondaryText">
                        {formatNumber(delivery.total_weight_kg)} kg / {formatNumber(delivery.total_volume_m3, 4)} m3
                      </div>
                      <div className="mt-1 text-[11px] text-secondaryText">{delivery.lines_count} lineas</div>
                    </td>
                    <td className="min-w-56 px-3 py-2 text-secondaryText">{rowAddress(delivery)}</td>
                    <td className="px-3 py-2 text-right">
                      <div className="inline-flex flex-wrap justify-end gap-2">
                        <button
                          type="button"
                          disabled={!confirmable || busy}
                          onClick={() => validateStockMutation.mutate([delivery])}
                          className="inline-flex min-h-8 items-center gap-2 rounded border border-emerald-200 bg-emerald-50 px-3 text-[12px] font-semibold text-emerald-800 transition hover:bg-emerald-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 disabled:bg-softStart disabled:text-secondaryText"
                        >
                          <ShieldCheck size={14} />
                          Validar Stock
                        </button>
                        <button
                          type="button"
                          disabled={!confirmable || !stockValidated || busy}
                          onClick={() => confirmMutation.mutate([delivery])}
                          className="inline-flex min-h-8 items-center gap-2 rounded bg-deep px-3 text-[12px] font-semibold text-white transition hover:bg-night focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:bg-softStart disabled:text-secondaryText"
                        >
                          <CheckCircle2 size={14} />
                          {delivery.source_type === "fulfillment" ? "Crear y confirmar" : "Confirmar"}
                        </button>
                        <button
                          type="button"
                          disabled={!confirmable || !stockPartial || busy}
                          onClick={() => setAvailableConfirmation({ rows: [delivery] })}
                          className="inline-flex min-h-8 items-center gap-2 rounded border border-amber-300 bg-amber-50 px-3 text-[12px] font-semibold text-amber-800 transition hover:bg-amber-100 focus:outline-none focus:ring-2 focus:ring-amber-500/20 disabled:bg-softStart disabled:text-secondaryText"
                        >
                          <PackageCheck size={14} />
                          Confirmar Disponibles
                        </button>
                      </div>
                    </td>
                  </tr>
                  {expanded && (
                    <tr className="border-b border-borderSoft bg-[#f8fbfe]">
                      <td colSpan={7} className="px-3 py-2">
                        <div className="grid gap-1">
                          {delivery.lines.map((line) => {
                            const validationLine = stockLineFor(line, stockResult);
                            const availabilityLine = stockAvailabilityByLine.get(lineKey(line));
                            const requestedQty = validationLine?.planned_qty ?? line.split_qty;
                            const availableQty = availabilityLine ? String(availabilityLine.confirmQty) : validationLine?.available_qty ?? line.max_dispatchable_qty ?? line.stock_available ?? "";
                            const lineStockStatus = availabilityLine?.status ?? null;
                            const lineHasStock = stockResult ? lineStockStatus === "ok" : null;
                            const linePartial = lineStockStatus === "partial";
                            return (
                              <div
                                key={lineKey(line)}
                                className={`grid items-center gap-2 rounded border px-2 py-1 text-[11px] md:grid-cols-[minmax(180px,1.3fr)_120px_170px_130px_100px] ${
                                  linePartial
                                    ? "border-amber-200 bg-amber-50"
                                    : lineStockStatus === "missing"
                                      ? "border-red-200 bg-red-50"
                                      : lineStockStatus === "ok"
                                        ? "border-emerald-200 bg-emerald-50"
                                        : "border-borderSoft bg-white"
                                }`}
                              >
                                <div className="min-w-0">
                                  <div className="truncate font-mono font-semibold text-night">{line.item_ref}</div>
                                  <div className="truncate text-secondaryText">{line.item_name || line.item_long_name || "sin descripcion"}</div>
                                </div>
                                <div className="font-mono text-night">
                                  {formatNumber(line.delivery_unit_qty ?? line.split_qty)} {line.delivery_uom || line.uom}
                                </div>
                                <div className="font-mono text-night">
                                  {stockResult ? (
                                    <>
                                      {formatNumber(requestedQty)} / {formatNumber(availableQty)} {validationLine?.uom ?? line.uom}
                                      {linePartial && availabilityLine && (
                                        <div className="mt-1 text-amber-700">
                                          disp. {formatNumber(availabilityLine.availableDeliveryQty)} {availabilityLine.deliveryUom || availabilityLine.uom}
                                        </div>
                                      )}
                                    </>
                                  ) : (
                                    <span className="text-secondaryText">sin validar</span>
                                  )}
                                </div>
                                <div className="font-mono text-secondaryText">
                                  {formatNumber(line.planned_weight_kg)} kg / {formatNumber(line.planned_volume_m3, 4)} m3
                                </div>
                                <div>
                                  {lineHasStock === null ? (
                                    <span className="rounded border border-borderSoft bg-softMid px-2 py-1 font-semibold text-secondaryText">pendiente</span>
                                  ) : lineHasStock ? (
                                    <span className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1 font-semibold text-emerald-800">con stock</span>
                                  ) : linePartial ? (
                                    <span className="rounded border border-amber-200 bg-amber-50 px-2 py-1 font-semibold text-amber-800">parcial</span>
                                  ) : (
                                    <span className="rounded border border-red-200 bg-red-50 px-2 py-1 font-semibold text-red-700">sin stock</span>
                                  )}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </td>
                    </tr>
                  )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>

          {!deliveries.length && (
            <div className="px-3 py-10 text-center text-[12px] text-secondaryText">
              {deliveriesQuery.isLoading
                ? "Cargando..."
                : "Sin pedidos."}
            </div>
          )}
        </div>
      </section>
      {availableConfirmation && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-deep/45 px-4 py-6"
          role="dialog"
          aria-modal="true"
          aria-labelledby="reparto-available-title"
          aria-describedby="reparto-available-description"
          onKeyDown={(event) => {
            if (event.key === "Escape" && !busy) {
              setAvailableConfirmation(null);
            }
          }}
        >
          <div className="w-full max-w-3xl rounded border border-borderSoft bg-white shadow-panel">
            <div className="border-b border-borderSoft px-4 py-3">
              <p className="text-[11px] font-semibold uppercase text-amber-700">Confirmacion requerida</p>
              <h2 id="reparto-available-title" className="mt-1 text-[16px] font-semibold text-night">
                Confirmar disponibles
              </h2>
            </div>
            <div className="grid max-h-[70vh] gap-3 overflow-auto px-4 py-3">
              <p id="reparto-available-description" className="text-[13px] leading-5 text-secondaryText">
                Se van a confirmar entregas parciales con las cantidades disponibles. Las lineas sin cantidad entregable quedan pendientes.
              </p>
              {availableConfirmationRows.map(({ delivery, availability }) => {
                const confirmLines = availability.filter((line) => line.confirmQty > 0);
                const pendingLines = availability.filter((line) => line.status === "missing");
                return (
                  <section key={delivery.id} className="rounded border border-borderSoft bg-softMid px-3 py-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="font-mono text-[13px] font-semibold text-night">{orderRef(delivery)}</h3>
                      <StatusBadge label={delivery.source_type === "fulfillment" ? "crea entrega parcial" : "ajusta entrega"} tone="warning" />
                    </div>
                    <div className="mt-2 grid gap-2">
                      {confirmLines.map((line) => (
                        <div key={line.id} className="grid gap-1 rounded border border-amber-200 bg-white px-2 py-2 text-[12px] md:grid-cols-[minmax(160px,1fr)_auto]">
                          <div className="min-w-0">
                            <div className="font-mono font-semibold text-night">{line.itemRef}</div>
                            <div className="truncate text-secondaryText">{line.itemName || "sin descripcion"}</div>
                          </div>
                          <div className="font-mono text-night">
                            {formatNumber(line.availableDeliveryQty)} {line.deliveryUom || line.uom}
                            {line.status === "partial" && (
                              <span className="ml-2 text-amber-700">
                                falta {formatNumber(line.missingDeliveryQty)} {line.deliveryUom || line.uom}
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                      {!confirmLines.length && <div className="text-[12px] text-secondaryText">Sin lineas disponibles.</div>}
                    </div>
                    {!!pendingLines.length && (
                      <div className="mt-2 rounded border border-rose-200 bg-rose-50 px-2 py-2">
                        <div className="text-[12px] font-semibold text-rose-900">Quedan pendientes</div>
                        <div className="mt-1 grid gap-1">
                          {pendingLines.map((line) => (
                            <div key={line.id} className="flex flex-wrap justify-between gap-2 text-[11px]">
                              <span className="font-mono text-night">{line.itemRef}</span>
                              <span className="font-mono text-rose-700">
                                solicitado {formatNumber(line.requestedDeliveryQty)} {line.deliveryUom || line.uom} / disponible 0
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </section>
                );
              })}
            </div>
            <div className="flex flex-wrap justify-end gap-2 border-t border-borderSoft px-4 py-3">
              <button
                type="button"
                disabled={busy}
                onClick={() => setAvailableConfirmation(null)}
                className="min-h-10 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:bg-softStart disabled:text-secondaryText"
              >
                Cancelar
              </button>
              <button
                type="button"
                disabled={busy || !availableConfirmationHasLines}
                onClick={() => confirmAvailableMutation.mutate(availableConfirmation.rows)}
                className="min-h-10 rounded bg-amber-600 px-3 text-[12px] font-semibold text-white transition hover:bg-amber-700 focus:outline-none focus:ring-2 focus:ring-amber-500/30 disabled:cursor-not-allowed disabled:bg-softStart disabled:text-secondaryText"
              >
                {confirmAvailableMutation.isPending ? "Confirmando..." : "Confirmar Disponibles"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
