import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, PackageCheck, RefreshCw, Send } from "lucide-react";

import {
  fetchPreparationTasks,
  fetchRepartoDeliveries,
  markPreparationTaskPrepared,
  sendDeliveryToPrepare,
  type ApiPreparationTaskListItem,
  type ApiRepartoDelivery,
} from "../../api/fulfillment";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { formatAppDateTime } from "../../shared/utils/dateFormat";
import { formatIdentifier } from "../../shared/utils/identifierFormat";
import type { StatusTone } from "../../types/operations";

const statusTone: Record<string, StatusTone> = {
  confirmed: "info",
  preparing: "warning",
  prepared: "success",
  assigned: "info",
  cancelled: "danger",
};

function localDateInputValue(date = new Date()) {
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return localDate.toISOString().slice(0, 10);
}

function asNumber(value: string | number | null | undefined) {
  const numberValue = Number(value ?? 0);
  return Number.isFinite(numberValue) ? numberValue : 0;
}

function formatQty(value: string | number | null | undefined) {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 }).format(asNumber(value));
}

function rowAddress(delivery: ApiRepartoDelivery) {
  const snapshot = delivery.address_snapshot ?? {};
  return [snapshot.street, snapshot.street_number, snapshot.city].filter(Boolean).join(" ") || snapshot.reference || "Sin direccion";
}

function orderRef(delivery: ApiRepartoDelivery) {
  return formatIdentifier(delivery.sales_order_number || delivery.fulfillment_number);
}

function isRepartoTask(task: ApiPreparationTaskListItem) {
  return task.delivery.delivery_mode.toLowerCase().includes("repart");
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

export function RepartoPreparationPage() {
  const queryClient = useQueryClient();
  const today = localDateInputValue();
  const [plannedDate, setPlannedDate] = useState(today);
  const [message, setMessage] = useState<string | null>(null);

  const deliveriesQuery = useQuery({
    queryKey: ["reparto-preparation-deliveries", plannedDate],
    queryFn: () =>
      fetchRepartoDeliveries({
        plannedDate,
        status: "confirmed",
      }),
  });
  const tasksQuery = useQuery({
    queryKey: ["reparto-preparation-tasks"],
    queryFn: () => fetchPreparationTasks("open"),
  });

  function handlePlannedDateChange(value: string) {
    setPlannedDate(value && value >= today ? value : today);
  }

  const deliveries = deliveriesQuery.data ?? [];
  const tasks = (tasksQuery.data ?? []).filter(isRepartoTask);
  const sendableDeliveries = deliveries.filter((delivery) => delivery.delivery_id);
  const preparableTasks = tasks.filter((task) => ["assigned", "preparing"].includes(task.status));
  const totalQty = deliveries.reduce((total, delivery) => total + asNumber(delivery.total_qty), 0);

  const sendToPrepareMutation = useMutation({
    mutationFn: async (delivery: ApiRepartoDelivery) => {
      if (!delivery.delivery_id) {
        throw new Error("La entrega debe estar confirmada antes de enviarse a preparar.");
      }
      return sendDeliveryToPrepare(delivery.delivery_id);
    },
    onSuccess: (delivery) => {
      setMessage(`${delivery.delivery_number} enviada a preparacion.`);
      void queryClient.invalidateQueries({ queryKey: ["reparto-preparation-deliveries"] });
      void queryClient.invalidateQueries({ queryKey: ["reparto-preparation-tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["routing-deliveries"] });
    },
  });

  const markPreparedMutation = useMutation({
    mutationFn: (task: ApiPreparationTaskListItem) => markPreparationTaskPrepared(task.id),
    onSuccess: (delivery) => {
      setMessage(`${delivery.delivery_number} marcada como preparada.`);
      void queryClient.invalidateQueries({ queryKey: ["reparto-preparation-tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["routing-deliveries"] });
    },
  });

  const sendAllToPrepareMutation = useMutation({
    mutationFn: (rows: ApiRepartoDelivery[]) =>
      mapWithConcurrency(rows, 4, async (delivery) => {
        if (!delivery.delivery_id) {
          throw new Error("La entrega debe estar confirmada antes de enviarse a preparar.");
        }
        return sendDeliveryToPrepare(delivery.delivery_id);
      }),
    onSuccess: (rows) => {
      setMessage(`${rows.length} entrega${rows.length === 1 ? "" : "s"} enviada${rows.length === 1 ? "" : "s"} a preparacion.`);
      void queryClient.invalidateQueries({ queryKey: ["reparto-preparation-deliveries"] });
      void queryClient.invalidateQueries({ queryKey: ["reparto-preparation-tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["routing-deliveries"] });
    },
  });

  const markAllPreparedMutation = useMutation({
    mutationFn: (rows: ApiPreparationTaskListItem[]) => mapWithConcurrency(rows, 3, (task) => markPreparationTaskPrepared(task.id)),
    onSuccess: (rows) => {
      setMessage(`${rows.length} entrega${rows.length === 1 ? "" : "s"} marcada${rows.length === 1 ? "" : "s"} como preparada${rows.length === 1 ? "" : "s"}.`);
      void queryClient.invalidateQueries({ queryKey: ["reparto-preparation-tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["routing-deliveries"] });
    },
  });

  const error =
    deliveriesQuery.error ||
    tasksQuery.error ||
    sendToPrepareMutation.error ||
    markPreparedMutation.error ||
    sendAllToPrepareMutation.error ||
    markAllPreparedMutation.error;
  const busy =
    deliveriesQuery.isLoading ||
    sendToPrepareMutation.isPending ||
    markPreparedMutation.isPending ||
    sendAllToPrepareMutation.isPending ||
    markAllPreparedMutation.isPending;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-3">
      <header className="flex shrink-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[20px] font-semibold text-night">Preparacion de reparto</h1>
          <div className="mt-1 flex flex-wrap gap-2 text-[12px] text-secondaryText">
            <span>{deliveries.length} entregas confirmadas</span>
            <span>{formatQty(totalQty)} unidades</span>
            <span>{tasks.length} tareas abiertas</span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={busy || !sendableDeliveries.length}
            onClick={() => sendAllToPrepareMutation.mutate(sendableDeliveries)}
            className="inline-flex min-h-9 items-center gap-2 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:bg-softStart disabled:text-secondaryText"
          >
            <Send size={15} />
            Enviar todas
          </button>
          <button
            type="button"
            disabled={busy || !preparableTasks.length}
            onClick={() => markAllPreparedMutation.mutate(preparableTasks)}
            className="inline-flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart disabled:text-secondaryText"
          >
            <Check size={15} />
            Marcar todas
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              void queryClient.invalidateQueries({ queryKey: ["reparto-preparation-deliveries"] });
              void queryClient.invalidateQueries({ queryKey: ["reparto-preparation-tasks"] });
            }}
            className="inline-flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
          >
            <RefreshCw size={15} />
            Actualizar
          </button>
        </div>
      </header>

      {(error || message) && (
        <div
          className={`shrink-0 rounded border px-3 py-2 text-[12px] ${
            error ? "border-red-200 bg-red-50 text-red-700" : "border-emerald-200 bg-emerald-50 text-emerald-800"
          }`}
          role="status"
        >
          {error instanceof Error ? error.message : message}
        </div>
      )}

      <section className="grid shrink-0 grid-cols-1 gap-2 rounded border border-borderSoft bg-white p-3 md:grid-cols-[180px]">
        <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
          Fecha entrega
          <input
            type="date"
            value={plannedDate}
            min={today}
            required
            onBlur={(event) => handlePlannedDateChange(event.target.value)}
            onChange={(event) => handlePlannedDateChange(event.target.value)}
            className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
          />
        </label>
      </section>

      <section className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(0,1.1fr)_minmax(0,1fr)] gap-3 overflow-hidden xl:grid-cols-[minmax(0,1.25fr)_420px] xl:grid-rows-1">
        <main className="min-h-0 overflow-auto rounded border border-borderSoft bg-surface shadow-panel">
          <table className="w-full border-collapse text-left text-[12px]">
            <thead className="sticky top-0 z-10 bg-deep text-white">
              <tr>
                <th className="px-3 py-2 font-semibold">Entrega</th>
                <th className="px-3 py-2 font-semibold">Pedido</th>
                <th className="px-3 py-2 font-semibold">Direccion</th>
                <th className="px-3 py-2 font-semibold">Cantidad</th>
                <th className="px-3 py-2 font-semibold">Estado</th>
                <th className="px-3 py-2 font-semibold">Accion</th>
              </tr>
            </thead>
            <tbody>
              {deliveries.map((delivery) => (
                <tr key={delivery.id} className="border-b border-borderSoft bg-white hover:bg-softStart">
                  <td className="whitespace-nowrap px-3 py-2 font-mono font-semibold text-night">{delivery.delivery_number}</td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <div className="font-mono font-semibold text-night">{orderRef(delivery)}</div>
                    <div className="mt-1 text-[11px] text-secondaryText">{delivery.customer_ref}</div>
                  </td>
                  <td className="max-w-[260px] truncate px-3 py-2 text-secondaryText">{rowAddress(delivery)}</td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{formatQty(delivery.total_qty)}</td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <StatusBadge label="confirmada" tone="info" />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <button
                      type="button"
                      disabled={!delivery.delivery_id || sendToPrepareMutation.isPending}
                      onClick={() => sendToPrepareMutation.mutate(delivery)}
                      className="inline-flex min-h-9 items-center gap-2 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:bg-softStart disabled:text-secondaryText"
                    >
                      <Send size={14} />
                      Enviar
                    </button>
                  </td>
                </tr>
              ))}
              {!deliveries.length && (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-[12px] text-secondaryText">
                    {deliveriesQuery.isLoading ? "Cargando entregas..." : "No hay entregas confirmadas para enviar a preparacion."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </main>

        <aside className="flex min-h-0 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="flex shrink-0 items-center justify-between border-b border-borderSoft bg-white px-3 py-2">
            <h2 className="text-[13px] font-semibold text-night">Tareas de reparto</h2>
            <PackageCheck className="text-primary" size={18} />
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {tasks.map((task) => (
              <div key={task.id} className="border-b border-borderSoft bg-white px-3 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-mono text-[12px] font-semibold text-night">{task.delivery.delivery_number}</div>
                    <div className="mt-1 truncate text-[11px] text-secondaryText">
                      {formatIdentifier(task.order.sales_order_number || task.order.fulfillment_number)}
                    </div>
                  </div>
                  <StatusBadge label={task.status} tone={statusTone[task.status] ?? "neutral"} />
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-secondaryText">
                  <span>{formatQty(task.total_qty)} unidades</span>
                  <span>{formatAppDateTime(task.assigned_at)}</span>
                </div>
                <button
                  type="button"
                  disabled={!["assigned", "preparing"].includes(task.status) || markPreparedMutation.isPending}
                  onClick={() => markPreparedMutation.mutate(task)}
                  className="mt-3 inline-flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart disabled:text-secondaryText"
                >
                  <Check size={14} />
                  Marcar preparada
                </button>
              </div>
            ))}
            {!tasks.length && (
              <div className="px-3 py-6 text-[12px] text-secondaryText">
                {tasksQuery.isLoading ? "Cargando tareas..." : "No hay tareas abiertas de reparto."}
              </div>
            )}
          </div>
        </aside>
      </section>
    </div>
  );
}
