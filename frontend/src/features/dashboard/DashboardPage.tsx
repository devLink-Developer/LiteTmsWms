import { Link } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";

import { fetchOperationRows, fetchOperationalOverview } from "../../api/operations";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { dashboardOperationModules } from "../../shared/data/modules";
import type { OperationModule, OperationRow, StatusTone } from "../../types/operations";

type ModuleErrorMap = Record<string, string>;

type OperationalMetric = {
  label: string;
  value: string;
  detail: string;
  tone: StatusTone;
};

type ModuleSummary = {
  module: OperationModule;
  loaded: boolean;
  error?: string;
  total: number;
  active: number;
  issues: number;
  focus: string;
  badgeLabel: string;
  badgeTone: StatusTone;
};

type AlertRow = {
  module: OperationModule;
  row: OperationRow;
  tone: StatusTone;
};

const TERMINAL_STATUSES = new Set([
  "cancelled",
  "closed",
  "delivered",
  "delivered_complete",
  "received",
  "returned",
]);

const DANGER_STATUSES = new Set(["blocked", "cancelled", "discrepant", "failed", "scrapped", "with_incident"]);
const WARNING_STATUSES = new Set([
  "adjustment",
  "attempted",
  "delivered_partial",
  "partial",
  "partial_received",
  "partially_delivered",
  "rescheduled",
  "returned",
  "reversal",
]);

const ROUTED_DELIVERY_STATUSES = new Set([
  "assigned",
  "cancelled",
  "delivered",
  "delivered_complete",
  "in_route",
  "loaded",
  "planned",
  "returned",
]);

const ACTIVE_ROUTE_STATUSES = new Set(["assigned", "capacity_checked", "in_transit", "loading", "planned"]);
const RESERVED_STOCK_STATES = new Set(["in_transit", "packed", "picking", "reserved"]);

const metricToneClasses: Record<StatusTone, string> = {
  neutral: "border-borderSoft bg-white text-night",
  info: "border-primary/20 bg-white text-primaryHover",
  warning: "border-amber-300 bg-amber-50 text-amber-900",
  success: "border-emerald-300 bg-emerald-50 text-emerald-900",
  danger: "border-red-300 bg-red-50 text-red-900",
};

const barToneClasses: Record<StatusTone, string> = {
  neutral: "bg-secondaryText",
  info: "bg-primary",
  warning: "bg-amber-500",
  success: "bg-emerald-600",
  danger: "bg-red-600",
};

function messageFor(error: unknown) {
  return error instanceof Error ? error.message : "No se pudo cargar el modulo.";
}

function hasLoadedRows(rowsByModule: Record<string, OperationRow[]>, key: string) {
  return Object.prototype.hasOwnProperty.call(rowsByModule, key);
}

function statusOf(row: OperationRow) {
  return row.status.trim().toLowerCase();
}

function rawText(row: OperationRow, key: string) {
  const value = row.raw?.[key];
  return value === null || value === undefined ? "" : String(value).trim();
}

function rawNumber(row: OperationRow, key: string) {
  const value = rawText(row, key).replace(",", ".");
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function countStatus(rows: OperationRow[], statuses: Iterable<string>) {
  const lookup = new Set(Array.from(statuses, (status) => status.toLowerCase()));
  return rows.filter((row) => lookup.has(statusOf(row))).length;
}

function sumRawNumber(rows: OperationRow[], key: string) {
  return rows.reduce((total, row) => total + rawNumber(row, key), 0);
}

function isOpen(row: OperationRow) {
  return !TERMINAL_STATUSES.has(statusOf(row));
}

function issueToneFor(row: OperationRow): StatusTone | null {
  const status = statusOf(row);
  if (row.statusTone === "danger" || DANGER_STATUSES.has(status)) {
    return "danger";
  }
  if (row.statusTone === "warning" || WARNING_STATUSES.has(status)) {
    return "warning";
  }
  return null;
}

function isPastDue(row: OperationRow) {
  if (!isOpen(row)) {
    return false;
  }
  const dateText = rawText(row, "planned_date") || rawText(row, "requested_date") || rawText(row, "posted_at") || row.sla;
  const dateKey = dateText.slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateKey)) {
    return false;
  }
  return dateKey < new Date().toISOString().slice(0, 10);
}

function formatCount(value: number) {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(value);
}

function formatQuantity(value: number) {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: Number.isInteger(value) ? 0 : 1 }).format(value);
}

function plural(value: number, singular: string, pluralLabel: string) {
  return value === 1 ? singular : pluralLabel;
}

function moduleIssueTone(rows: OperationRow[]) {
  if (rows.some((row) => issueToneFor(row) === "danger")) {
    return "danger";
  }
  if (rows.some((row) => issueToneFor(row) === "warning")) {
    return "warning";
  }
  return "success";
}

function activeCountFor(moduleKey: string, rows: OperationRow[]) {
  if (moduleKey === "stock") {
    return rows.filter((row) => rawNumber(row, "quantity") > 0).length;
  }
  if (moduleKey === "stock-movements") {
    return rows.length;
  }
  return rows.filter(isOpen).length;
}

function focusFor(moduleKey: string, rows: OperationRow[]) {
  if (!rows.length) {
    return "Sin registros cargados";
  }

  if (moduleKey === "orders") {
    return `${formatCount(countStatus(rows, ["pending", "allocated", "preparing"]))} en flujo / ${formatCount(
      countStatus(rows, ["ready_for_dispatch"]),
    )} listas despacho`;
  }
  if (moduleKey === "deliveries") {
    return `${formatCount(countStatus(rows, ["preparing", "prepared", "loaded"]))} prep/carga / ${formatCount(
      rows.filter(isPastDue).length,
    )} vencidas`;
  }
  if (moduleKey === "tasks") {
    return `${formatCount(countStatus(rows, ["assigned"]))} asignadas / ${formatCount(
      countStatus(rows, ["preparing"]),
    )} en preparacion`;
  }
  if (moduleKey === "distribution") {
    const pendingRoute = rows.filter((row) => !ROUTED_DELIVERY_STATUSES.has(statusOf(row))).length;
    return `${formatCount(pendingRoute)} por rutear / ${formatCount(countStatus(rows, ["in_route", "loaded"]))} en ruta`;
  }
  if (moduleKey === "receipts") {
    return `${formatCount(countStatus(rows, ["expected", "partial_received", "receiving"]))} por recibir / ${formatCount(
      countStatus(rows, ["with_incident"]),
    )} incidencias`;
  }
  if (moduleKey === "transfers") {
    return `${formatCount(countStatus(rows, ["dispatched", "in_transit", "picking"]))} en transito / ${formatCount(
      countStatus(rows, ["discrepant", "partial_received"]),
    )} diferencias`;
  }
  if (moduleKey === "returns") {
    return `${formatCount(countStatus(rows, ["returned"]))} devueltas / ${formatCount(rows.filter(isOpen).length)} abiertas`;
  }
  if (moduleKey === "routes") {
    const activeRoutes = rows.filter((row) => ACTIVE_ROUTE_STATUSES.has(statusOf(row))).length;
    return `${formatCount(activeRoutes)} activas / ${formatQuantity(sumRawNumber(rows, "planned_weight_kg"))} kg`;
  }
  if (moduleKey === "stock") {
    const onHand = rows.filter((row) => statusOf(row) === "on_hand");
    const reserved = rows.filter((row) => RESERVED_STOCK_STATES.has(statusOf(row)));
    return `${formatQuantity(sumRawNumber(onHand, "quantity"))} disp. / ${formatQuantity(
      sumRawNumber(reserved, "quantity"),
    )} reservado`;
  }
  if (moduleKey === "stock-movements") {
    return `${formatCount(rows.filter((row) => rawText(row, "direction") === "increase").length)} entradas / ${formatCount(
      rows.filter((row) => rawText(row, "direction") === "decrease").length,
    )} salidas`;
  }
  return `${formatCount(rows.filter(isOpen).length)} activos`;
}

function buildModuleSummary(
  module: OperationModule,
  rowsByModule: Record<string, OperationRow[]>,
  moduleErrors: ModuleErrorMap,
  loading: boolean,
): ModuleSummary {
  const rows = rowsByModule[module.key] ?? [];
  const error = moduleErrors[module.key];
  const loaded = hasLoadedRows(rowsByModule, module.key);
  const issues = rows.filter(issueToneFor).length;
  const issueTone = moduleIssueTone(rows);
  const badgeTone = error ? "danger" : loading && !loaded ? "neutral" : issueTone;

  return {
    module,
    loaded,
    error,
    total: rows.length,
    active: activeCountFor(module.key, rows),
    issues,
    focus: error ? "Sin datos por error de API" : focusFor(module.key, rows),
    badgeLabel: error ? "Error" : loading && !loaded ? "Cargando" : issues > 0 ? "Atencion" : "OK",
    badgeTone,
  };
}

function MetricCard({ metric }: { metric: OperationalMetric }) {
  return (
    <article className={`min-h-[78px] rounded border px-2.5 py-2 shadow-panel ${metricToneClasses[metric.tone]}`}>
      <div className="text-[11px] font-semibold uppercase leading-4 text-secondaryText">{metric.label}</div>
      <div className="mt-1 font-mono text-[22px] font-semibold leading-7 text-night">{metric.value}</div>
      <div className="mt-1 text-[11px] leading-4 text-secondaryText">{metric.detail}</div>
    </article>
  );
}

export function DashboardPage() {
  const [rowsByModule, setRowsByModule] = useState<Record<string, OperationRow[]>>({});
  const [moduleErrors, setModuleErrors] = useState<ModuleErrorMap>({});
  const [principles, setPrinciples] = useState<string[]>([]);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setOverviewError(null);
    setModuleErrors({});

    const overviewRequest = fetchOperationalOverview()
      .then((overview) => {
        if (!cancelled) {
          setPrinciples(overview.principles ?? []);
        }
      })
      .catch((apiError: unknown) => {
        if (!cancelled) {
          setPrinciples([]);
          setOverviewError(messageFor(apiError));
        }
      });

    const moduleRequests = dashboardOperationModules.map((module) =>
      fetchOperationRows(module)
        .then((rows) => ({ module, rows, error: null }))
        .catch((apiError: unknown) => ({ module, rows: [], error: messageFor(apiError) })),
    );

    Promise.all([overviewRequest, Promise.all(moduleRequests)])
      .then(([, moduleResults]) => {
        if (cancelled) {
          return;
        }

        const nextRowsByModule: Record<string, OperationRow[]> = {};
        const nextErrors: ModuleErrorMap = {};

        moduleResults.forEach((result) => {
          if (result.error) {
            nextErrors[result.module.key] = result.error;
            return;
          }
          nextRowsByModule[result.module.key] = result.rows;
        });

        setRowsByModule(nextRowsByModule);
        setModuleErrors(nextErrors);
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const summaries = useMemo(
    () => dashboardOperationModules.map((module) => buildModuleSummary(module, rowsByModule, moduleErrors, loading)),
    [loading, moduleErrors, rowsByModule],
  );

  const operationalMetrics: OperationalMetric[] = useMemo(() => {
    const rowsFor = (key: string) => rowsByModule[key] ?? [];
    const orders = rowsFor("orders");
    const deliveries = rowsFor("deliveries");
    const tasks = rowsFor("tasks");
    const distribution = rowsFor("distribution");
    const receipts = rowsFor("receipts");
    const transfers = rowsFor("transfers");
    const returns = rowsFor("returns");
    const routes = rowsFor("routes");
    const stock = rowsFor("stock");
    const movements = rowsFor("stock-movements");

    const ordersOpen = orders.filter(isOpen).length;
    const deliveryIssues = deliveries.filter(issueToneFor).length;
    const taskIssues = tasks.filter((row) => issueToneFor(row) || isPastDue(row)).length;
    const pendingRoute = distribution.filter((row) => !ROUTED_DELIVERY_STATUSES.has(statusOf(row))).length;
    const inboundRows = [...receipts, ...transfers];
    const inboundIssues = inboundRows.filter(issueToneFor).length + returns.length;
    const activeRoutes = routes.filter((row) => ACTIVE_ROUTE_STATUSES.has(statusOf(row))).length;
    const onHandRows = stock.filter((row) => statusOf(row) === "on_hand");
    const reservedRows = stock.filter((row) => RESERVED_STOCK_STATES.has(statusOf(row)));
    const loadedModules = dashboardOperationModules.filter((module) => hasLoadedRows(rowsByModule, module.key)).length;
    const failedModules = Object.keys(moduleErrors).length;

    return [
      {
        label: "Pedidos abiertos",
        value: formatCount(ordersOpen),
        detail: `${formatCount(orders.length)} cargados / ${formatCount(
          countStatus(orders, ["ready_for_dispatch"]),
        )} listos despacho`,
        tone: orders.some((row) => issueToneFor(row) === "danger") ? "danger" : "info",
      },
      {
        label: "Entregas activas",
        value: formatCount(deliveries.filter(isOpen).length),
        detail: `${formatCount(deliveries.filter(isPastDue).length)} vencidas / ${formatCount(
          deliveryIssues,
        )} con atencion`,
        tone: deliveryIssues > 0 ? "warning" : "success",
      },
      {
        label: "Tareas preparacion",
        value: formatCount(tasks.filter(isOpen).length),
        detail: `${formatQuantity(sumRawNumber(tasks, "total_qty"))} unidades / ${formatCount(taskIssues)} alertas`,
        tone: taskIssues > 0 ? "warning" : tasks.length ? "info" : "neutral",
      },
      {
        label: "Reparto para ruteo",
        value: formatCount(pendingRoute),
        detail: `${formatCount(distribution.length)} reparto / ${formatCount(
          countStatus(distribution, ["in_route", "loaded"]),
        )} en ruta`,
        tone: pendingRoute > 0 ? "warning" : "success",
      },
      {
        label: "Ingresos abiertos",
        value: formatCount(inboundRows.filter(isOpen).length),
        detail: `${formatCount(receipts.length)} OC / ${formatCount(transfers.length)} TR / ${formatCount(
          inboundIssues,
        )} alertas`,
        tone: inboundIssues > 0 ? "warning" : "success",
      },
      {
        label: "Hojas activas",
        value: formatCount(activeRoutes),
        detail: `${formatQuantity(sumRawNumber(routes, "planned_weight_kg"))} kg / ${formatQuantity(
          sumRawNumber(routes, "planned_volume_m3"),
        )} m3 plan`,
        tone: activeRoutes > 0 ? "info" : "neutral",
      },
      {
        label: "Stock disponible",
        value: formatQuantity(sumRawNumber(onHandRows, "quantity")),
        detail: `${formatQuantity(sumRawNumber(reservedRows, "quantity"))} reservado/prep / ${formatCount(
          stock.length,
        )} buckets`,
        tone: stock.some((row) => issueToneFor(row) === "danger") ? "danger" : "success",
      },
      {
        label: "Movimientos ledger",
        value: formatCount(movements.length),
        detail: `${formatCount(movements.filter((row) => rawText(row, "direction") === "increase").length)} entradas / ${formatCount(
          movements.filter((row) => rawText(row, "direction") === "decrease").length,
        )} salidas`,
        tone: movements.some((row) => issueToneFor(row)) ? "warning" : "info",
      },
      {
        label: "Modulos API",
        value: `${formatCount(loadedModules)}/${formatCount(dashboardOperationModules.length)}`,
        detail: `${formatCount(failedModules)} con error / ${loading ? "cargando" : "actualizado"}`,
        tone: failedModules > 0 ? "danger" : loading ? "info" : "success",
      },
    ];
  }, [moduleErrors, rowsByModule, loading]);

  const alerts: AlertRow[] = useMemo(() => {
    return dashboardOperationModules
      .flatMap((module) =>
        (rowsByModule[module.key] ?? []).flatMap((row) => {
          const tone = issueToneFor(row);
          return tone ? [{ module, row, tone }] : [];
        }),
      )
      .sort((left, right) => (left.tone === right.tone ? 0 : left.tone === "danger" ? -1 : 1))
      .slice(0, 8);
  }, [rowsByModule]);

  const loadedModules = summaries.filter((summary) => summary.loaded).length;
  const failedModules = summaries.filter((summary) => summary.error).length;
  const totalRows = summaries.reduce((total, summary) => total + summary.total, 0);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-3">
      <section className="flex shrink-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[20px] font-semibold text-night">Dashboard operativo</h1>
          <p className="mt-1 max-w-4xl text-[12px] leading-5 text-secondaryText">
            KPIs TMS/WMS derivados de pedidos, entrega, reparto, ingresos, hojas de ruta, stock y ledger.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge label={loading ? "cargando API" : `${loadedModules}/${dashboardOperationModules.length} modulos`} tone={loading ? "info" : failedModules ? "warning" : "success"} />
          <StatusBadge label={`${formatCount(totalRows)} registros`} tone="info" />
          <StatusBadge label="legacy read-only" tone="neutral" />
        </div>
      </section>

      {(failedModules > 0 || overviewError) && (
        <div className="grid shrink-0 grid-cols-1 gap-2 text-[12px] leading-5 md:grid-cols-2">
          {failedModules > 0 && (
            <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-amber-900">
              Carga parcial: {formatCount(failedModules)} {plural(failedModules, "modulo con error", "modulos con error")}.
              Los KPIs usan los datos disponibles.
            </div>
          )}
          {overviewError && (
            <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-red-700">
              Principios operativos no disponibles: {overviewError}
            </div>
          )}
        </div>
      )}

      <section className="grid shrink-0 grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-8" aria-label="KPIs TMS/WMS">
        {operationalMetrics.map((metric) => (
          <MetricCard key={metric.label} metric={metric} />
        ))}
      </section>

      <section className="grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-hidden xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.55fr)]">
        <div className="flex min-h-0 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="flex min-h-11 items-center justify-between border-b border-borderSoft px-3">
            <h2 className="text-[13px] font-semibold text-night">Pulso por modulo</h2>
            <div className="text-[11px] text-secondaryText">
              {loading ? "Sincronizando..." : `${formatCount(loadedModules)} cargados / ${formatCount(failedModules)} con error`}
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full border-collapse text-left text-[12px]">
              <thead className="sticky top-0 z-10 bg-deep text-white">
                <tr>
                  <th className="min-w-[220px] px-3 py-2 font-semibold">Modulo</th>
                  <th className="px-3 py-2 font-semibold">Estado</th>
                  <th className="px-3 py-2 text-right font-semibold">Reg.</th>
                  <th className="min-w-[150px] px-3 py-2 font-semibold">Activos</th>
                  <th className="px-3 py-2 text-right font-semibold">Alertas</th>
                  <th className="min-w-[220px] px-3 py-2 font-semibold">Foco operativo</th>
                  <th className="px-3 py-2 font-semibold">Accion</th>
                </tr>
              </thead>
              <tbody>
                {summaries.map((summary) => {
                  const activeWidth = summary.total ? Math.round((summary.active / summary.total) * 100) : 0;
                  return (
                    <tr key={summary.module.key} className="border-b border-borderSoft bg-white hover:bg-softStart">
                      <td className="px-3 py-2">
                        <div className="font-semibold text-night">{summary.module.label}</div>
                        <div className="mt-0.5 max-w-[460px] text-[11px] leading-4 text-secondaryText">
                          {summary.module.description}
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <StatusBadge label={summary.badgeLabel} tone={summary.badgeTone} />
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-night">{formatCount(summary.total)}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className="w-9 shrink-0 text-right font-mono text-night">{formatCount(summary.active)}</span>
                          <div className="h-1.5 w-24 overflow-hidden rounded bg-softMid" aria-hidden="true">
                            <div
                              className={`h-full ${barToneClasses[summary.badgeTone]}`}
                              style={{ width: `${activeWidth}%` }}
                            />
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-night">{formatCount(summary.issues)}</td>
                      <td className="px-3 py-2 text-secondaryText">
                        <div>{summary.focus}</div>
                        {summary.error && <div className="mt-1 text-[11px] text-red-700">{summary.error}</div>}
                      </td>
                      <td className="px-3 py-2">
                        <Link className="font-semibold text-primaryHover hover:text-primary" to={summary.module.path}>
                          Abrir
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        <aside className="grid min-h-0 grid-rows-[minmax(0,1fr)_auto] overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="min-h-0 overflow-auto p-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-[13px] font-semibold text-night">Alertas operativas</h2>
              <StatusBadge label={`${formatCount(alerts.length)} foco`} tone={alerts.length ? "warning" : "success"} />
            </div>
            <div className="mt-3 space-y-2">
              {Object.entries(moduleErrors).map(([moduleKey, error]) => {
                const module = dashboardOperationModules.find((entry) => entry.key === moduleKey);
                return (
                  <div key={moduleKey} className="rounded border border-red-200 bg-red-50 px-2.5 py-2 text-[12px] leading-5 text-red-800">
                    <div className="font-semibold">{module?.label ?? moduleKey}</div>
                    <div>{error}</div>
                  </div>
                );
              })}

              {alerts.length ? (
                alerts.map(({ module, row, tone }) => (
                  <Link
                    key={`${module.key}-${row.id}`}
                    to={module.path}
                    className="block rounded border border-borderSoft bg-white px-2.5 py-2 transition hover:border-primary hover:bg-softStart focus:outline-none focus:ring-2 focus:ring-primary/20"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-[12px] font-semibold text-night">{row.ref}</span>
                      <StatusBadge label={row.status} tone={tone} />
                    </div>
                    <div className="mt-1 text-[11px] leading-4 text-secondaryText">
                      {module.label} / {row.warehouse} / {row.owner}
                    </div>
                  </Link>
                ))
              ) : (
                <div className="rounded border border-borderSoft bg-white px-2.5 py-2 text-[12px] leading-5 text-secondaryText">
                  Sin alertas con los datos cargados.
                </div>
              )}
            </div>
          </div>

          <div className="border-t border-borderSoft p-3">
            <h2 className="text-[13px] font-semibold text-night">Principios activos</h2>
            <ul className="mt-2 space-y-1.5 text-[12px] leading-5 text-secondaryText">
              {principles.length ? (
                principles.map((principle) => <li key={principle}>{principle}</li>)
              ) : (
                <li>Sin datos de principios operativos desde API.</li>
              )}
            </ul>
          </div>
        </aside>
      </section>
    </div>
  );
}
