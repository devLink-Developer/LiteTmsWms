import { useEffect, useMemo, useState } from "react";

import {
  fetchPreparationTasks,
  markPreparationTaskPrepared,
  type ApiPreparationTaskListItem,
} from "../../api/fulfillment";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { notify } from "../../shared/components/toast";
import { eventsAffectOperationalStatuses, useLiveStatusRefresh } from "../../shared/hooks/useLiveStatusEvents";
import { formatAppDateTime } from "../../shared/utils/dateFormat";
import type { StatusTone } from "../../types/operations";

type TaskFilter = "open" | "assigned" | "preparing" | "prepared" | "all";

const filterLabels: Record<TaskFilter, string> = {
  open: "Abiertas",
  assigned: "Asignadas",
  preparing: "En preparacion",
  prepared: "Preparadas",
  all: "Todas",
};

const taskStatusLabel: Record<string, string> = {
  assigned: "asignada",
  preparing: "en preparacion",
  prepared: "preparada",
  cancelled: "cancelada",
};

const taskStatusTone: Record<string, StatusTone> = {
  assigned: "info",
  preparing: "warning",
  prepared: "success",
  cancelled: "danger",
};

function asNumber(value: string | number | null | undefined) {
  const numberValue = Number(value ?? 0);
  return Number.isFinite(numberValue) ? numberValue : 0;
}

function formatQty(value: string | number | null | undefined) {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 }).format(asNumber(value));
}

export function PreparationTasksPage() {
  const [tasks, setTasks] = useState<ApiPreparationTaskListItem[]>([]);
  const [activeTaskId, setActiveTaskId] = useState("");
  const [filter, setFilter] = useState<TaskFilter>("open");
  const [loading, setLoading] = useState(false);
  const [processingTaskId, setProcessingTaskId] = useState("");

  async function loadTasks(nextFilter = filter, { silent = false } = {}) {
    if (!silent) {
      setLoading(true);
    }
    try {
      const results = await fetchPreparationTasks(nextFilter, { globalLoading: !silent });
      setTasks(results);
      setActiveTaskId((current) => {
        if (current && results.some((task) => task.id === current)) {
          return current;
        }
        return results[0]?.id ?? "";
      });
    } catch (apiError) {
      const text = apiError instanceof Error ? apiError.message : "Tareas no cargadas.";
      if (!silent) {
        notify({ message: text, tone: "error" });
      }
      setTasks([]);
      setActiveTaskId("");
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    void loadTasks(filter);
    const interval = window.setInterval(() => {
      void loadTasks(filter, { silent: true });
    }, 60000);
    return () => window.clearInterval(interval);
  }, [filter]);

  useLiveStatusRefresh((events) => {
    if (eventsAffectOperationalStatuses(events)) {
      void loadTasks(filter, { silent: true });
    }
  });

  const activeTask = useMemo(
    () => tasks.find((task) => task.id === activeTaskId) ?? tasks[0],
    [activeTaskId, tasks],
  );

  async function markPrepared(task: ApiPreparationTaskListItem) {
    setProcessingTaskId(task.id);
    try {
      await markPreparationTaskPrepared(task.id);
      await loadTasks(filter, { silent: true });
      notify({ message: `${task.delivery.delivery_number} marcada como preparada.`, tone: "success" });
    } catch (apiError) {
      const text = apiError instanceof Error ? apiError.message : "Tarea no marcada.";
      notify({ message: text, tone: "error" });
    } finally {
      setProcessingTaskId("");
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-3">
      <header className="flex shrink-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[20px] font-semibold text-night">Tareas de preparacion</h1>
        </div>
        <button
          type="button"
          onClick={() => void loadTasks(filter)}
          disabled={loading}
          className="min-h-9 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
        >
          {loading ? "Actualizando..." : "Actualizar"}
        </button>
      </header>

      <section className="flex shrink-0 flex-wrap gap-1 overflow-x-auto rounded border border-borderSoft bg-white p-1" aria-label="Filtro de tareas">
        {(Object.keys(filterLabels) as TaskFilter[]).map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => {
              setFilter(option);
            }}
            className={`min-h-9 rounded px-3 text-[12px] font-semibold transition focus:outline-none focus:ring-2 focus:ring-primary/20 ${
              filter === option ? "bg-primary text-white" : "text-secondaryText hover:bg-softStart hover:text-night"
            }`}
          >
            {filterLabels[option]}
          </button>
        ))}
      </section>

      <section className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(0,1.4fr)_minmax(0,1fr)] gap-3 overflow-hidden xl:grid-cols-[minmax(0,1fr)_360px] xl:grid-rows-1">
        <main className="min-h-0 overflow-auto rounded border border-borderSoft bg-surface shadow-panel">
          <table className="w-full border-collapse text-left text-[12px]">
            <thead className="sticky top-0 z-10 bg-deep text-white">
              <tr>
                <th className="px-3 py-2 font-semibold">Tarea</th>
                <th className="px-3 py-2 font-semibold">Pedido</th>
                <th className="px-3 py-2 font-semibold">Entrega</th>
                <th className="px-3 py-2 font-semibold">Deposito</th>
                <th className="px-3 py-2 font-semibold">Preparador</th>
                <th className="px-3 py-2 font-semibold">Cantidad</th>
                <th className="px-3 py-2 font-semibold">Estado</th>
                <th className="px-3 py-2 font-semibold">Accion</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr
                  key={task.id}
                  className={`border-b border-borderSoft bg-white hover:bg-softStart ${
                    task.id === activeTask?.id ? "outline outline-2 outline-primary/20" : ""
                  }`}
                  onClick={() => setActiveTaskId(task.id)}
                >
                  <td className="whitespace-nowrap px-3 py-2 font-mono font-semibold text-night">{task.id.slice(0, 8)}</td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <div className="font-mono font-semibold text-night">{task.order.sales_order_number}</div>
                    <div className="mt-1 text-[11px] text-secondaryText">{task.order.customer_ref}</div>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{task.delivery.delivery_number}</td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{task.warehouse_ref}</td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{task.assigned_employee_ref}</td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{formatQty(task.total_qty)}</td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <StatusBadge label={taskStatusLabel[task.status] ?? task.status} tone={taskStatusTone[task.status] ?? "neutral"} />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <button
                      type="button"
                      disabled={!["assigned", "preparing"].includes(task.status) || processingTaskId === task.id}
                      onClick={(event) => {
                        event.stopPropagation();
                        void markPrepared(task);
                      }}
                      className="min-h-9 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:bg-softStart disabled:text-secondaryText"
                    >
                      {processingTaskId === task.id ? "Marcando..." : "Marcar preparada"}
                    </button>
                  </td>
                </tr>
              ))}
              {!tasks.length && (
                <tr>
                  <td colSpan={8} className="px-3 py-6 text-[12px] text-secondaryText">
                    {loading ? "Cargando..." : "Sin tareas."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </main>

        <aside className="flex min-h-0 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="shrink-0 border-b border-borderSoft px-3 py-2">
            <h2 className="text-[13px] font-semibold text-night">Detalle de tarea</h2>
          </div>
          {activeTask ? (
            <>
              <dl className="grid shrink-0 grid-cols-2 gap-2 border-b border-borderSoft px-3 py-3 text-[12px]">
                <dt className="font-semibold text-secondaryText">Pedido</dt>
                <dd className="font-mono text-night">{activeTask.order.sales_order_number}</dd>
                <dt className="font-semibold text-secondaryText">Entrega</dt>
                <dd className="font-mono text-night">{activeTask.delivery.delivery_number}</dd>
                <dt className="font-semibold text-secondaryText">Asignada</dt>
                <dd className="text-night">{formatAppDateTime(activeTask.assigned_at)}</dd>
                <dt className="font-semibold text-secondaryText">Preparador</dt>
                <dd className="font-mono text-night">{activeTask.assigned_employee_ref}</dd>
                <dt className="font-semibold text-secondaryText">Estado</dt>
                <dd>
                  <StatusBadge
                    label={taskStatusLabel[activeTask.status] ?? activeTask.status}
                    tone={taskStatusTone[activeTask.status] ?? "neutral"}
                  />
                </dd>
              </dl>
              <div className="min-h-0 flex-1 overflow-auto">
                <table className="w-full border-collapse text-left text-[12px]">
                  <thead className="sticky top-0 bg-softMid text-secondaryText">
                    <tr>
                      <th className="px-3 py-2 font-semibold">Item</th>
                      <th className="px-3 py-2 font-semibold">Cantidad</th>
                      <th className="px-3 py-2 font-semibold">Deposito</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeTask.lines.map((line) => (
                      <tr key={line.id} className="border-b border-borderSoft bg-white">
                        <td className="px-3 py-2 font-mono font-semibold text-night">{line.item_ref}</td>
                        <td className="px-3 py-2 font-mono text-night">
                          {formatQty(line.planned_qty)} {line.uom}
                        </td>
                        <td className="px-3 py-2 font-mono text-night">{line.warehouse_ref}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div className="px-3 py-6 text-[12px] text-secondaryText">Sin tarea seleccionada.</div>
          )}
        </aside>
      </section>
    </div>
  );
}
