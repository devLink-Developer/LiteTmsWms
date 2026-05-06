import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import {
  fetchOperationalDashboard,
  type DashboardCountDatum,
  type DashboardLedgerDay,
  type DashboardQuantityByUom,
  type DashboardRouteLoad,
  type DashboardStockState,
  type OperationalDashboard,
  type OperationalDashboardKpi,
  type OperationalDashboardModule,
} from "../../api/operations";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { notify } from "../../shared/components/toast";
import type { StatusTone } from "../../types/operations";

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
  return error instanceof Error ? error.message : "Dashboard no cargado.";
}

function numberValue(value: number | string) {
  const parsed = typeof value === "number" ? value : Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatCount(value: number | string) {
  if (typeof value === "string" && Number.isNaN(Number(value))) {
    return value;
  }
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(numberValue(value));
}

function formatQuantity(value: string | number) {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 3 }).format(numberValue(value));
}

function formatDate(value: string) {
  if (!value) return "-";
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("es-AR", { day: "2-digit", month: "2-digit" }).format(date);
}

function formatDateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "-"
    : new Intl.DateTimeFormat("es-AR", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function quantityText(rows: DashboardQuantityByUom[]) {
  if (!rows.length) {
    return "-";
  }
  return rows.slice(0, 3).map((row) => `${formatQuantity(row.quantity)} ${row.uom}`).join(" / ");
}

function chartRows(data: DashboardCountDatum[], showZeros = false) {
  const visible = showZeros ? data : data.filter((row) => row.count > 0);
  return visible.length ? visible : data.slice(0, 5);
}

function MetricCard({ metric }: { metric: OperationalDashboardKpi }) {
  return (
    <article className={`min-h-[82px] rounded border px-2.5 py-2 shadow-panel ${metricToneClasses[metric.tone]}`}>
      <div className="text-[11px] font-semibold uppercase leading-4 text-secondaryText">{metric.label}</div>
      <div className="mt-1 font-mono text-[22px] font-semibold leading-7 text-night">{formatCount(metric.value)}</div>
    </article>
  );
}

function ChartPanel({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="min-h-[220px] rounded border border-borderSoft bg-surface shadow-panel">
      <div className="flex min-h-11 items-center justify-between gap-3 border-b border-borderSoft px-3">
        <h2 className="text-[13px] font-semibold text-night">{title}</h2>
        {aside && <div className="text-[11px] text-secondaryText">{aside}</div>}
      </div>
      <div className="p-3">{children}</div>
    </section>
  );
}

function HorizontalBarChart({
  data,
  ariaLabel,
  showZeros = false,
  tone = "info",
}: {
  data: DashboardCountDatum[];
  ariaLabel: string;
  showZeros?: boolean;
  tone?: StatusTone;
}) {
  const rows = chartRows(data, showZeros);
  const max = Math.max(1, ...rows.map((row) => row.count));

  return (
    <div className="space-y-2" aria-label={ariaLabel}>
      {rows.map((row) => {
        const width = Math.round((row.count / max) * 100);
        return (
          <div key={row.key} className="grid grid-cols-[minmax(112px,0.55fr)_minmax(120px,1fr)_56px] items-center gap-2">
            <div className="min-w-0 text-[12px] font-semibold leading-4 text-night">{row.label}</div>
            <div className="h-3 overflow-hidden rounded bg-softMid" aria-hidden="true">
              <div className={`h-full ${barToneClasses[row.count ? tone : "neutral"]}`} style={{ width: `${width}%` }} />
            </div>
            <div className="text-right font-mono text-[12px] font-semibold text-night">{formatCount(row.count)}</div>
          </div>
        );
      })}
    </div>
  );
}

function StockStateChart({ data }: { data: DashboardStockState[] }) {
  const rows = data.filter((row) => row.buckets > 0);
  const visibleRows = rows.length ? rows : data.slice(0, 5);
  const max = Math.max(1, ...visibleRows.map((row) => row.buckets));

  return (
    <div className="space-y-2" aria-label="Stock positivo por estado">
      {visibleRows.map((row) => {
        const width = Math.round((row.buckets / max) * 100);
        return (
          <div key={row.key} className="grid grid-cols-[minmax(120px,0.5fr)_minmax(120px,1fr)_72px] items-center gap-2">
            <div className="min-w-0">
              <div className="text-[12px] font-semibold leading-4 text-night">{row.label}</div>
              <div className="text-[11px] leading-4 text-secondaryText">{quantityText(row.quantity_by_uom)}</div>
            </div>
            <div className="h-3 overflow-hidden rounded bg-softMid" aria-hidden="true">
              <div className={`h-full ${row.key === "scrapped" ? "bg-red-600" : "bg-emerald-600"}`} style={{ width: `${width}%` }} />
            </div>
            <div className="text-right font-mono text-[12px] font-semibold text-night">{formatCount(row.buckets)}</div>
          </div>
        );
      })}
    </div>
  );
}

function LedgerChart({ data }: { data: DashboardLedgerDay[] }) {
  const max = Math.max(1, ...data.map((row) => row.increase_count + row.decrease_count));
  const plotHeight = 92;
  const baseline = 118;
  const step = 84;
  const firstX = 46;
  const totalPoint = (row: DashboardLedgerDay, index: number) => {
    const total = row.increase_count + row.decrease_count;
    const x = firstX + index * step + 18;
    const y = baseline - Math.round((total / max) * plotHeight);
    return `${x},${y}`;
  };

  return (
    <div aria-label="Movimientos de ledger por dia">
      <svg className="h-[168px] w-full" viewBox="0 0 620 168" role="img" aria-label="Entradas y salidas de ledger en los ultimos 7 dias">
        <title>Ledger ultimos 7 dias</title>
        <line x1="34" x2="590" y1={baseline} y2={baseline} className="stroke-borderSoft" strokeWidth="1" />
        <polyline
          points={data.map(totalPoint).join(" ")}
          className="fill-none stroke-night"
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {data.map((row, index) => {
          const x = firstX + index * step;
          const increaseHeight = Math.round((row.increase_count / max) * plotHeight);
          const decreaseHeight = Math.round((row.decrease_count / max) * plotHeight);
          return (
            <g key={row.date}>
              <rect x={x} y={baseline - increaseHeight} width="16" height={increaseHeight} rx="2" className="fill-primary" />
              <rect x={x + 20} y={baseline - decreaseHeight} width="16" height={decreaseHeight} rx="2" className="fill-amber-500" />
              <circle cx={x + 18} cy={baseline - Math.round(((row.increase_count + row.decrease_count) / max) * plotHeight)} r="3" className="fill-night" />
              <text x={x + 18} y="144" textAnchor="middle" className="fill-secondaryText text-[10px]">
                {formatDate(row.date)}
              </text>
              <text x={x + 18} y="158" textAnchor="middle" className="fill-night text-[10px] font-semibold">
                {formatCount(row.increase_count + row.decrease_count)}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="grid grid-cols-2 gap-2 text-[11px] leading-4 text-secondaryText">
        <div><span className="font-semibold text-primaryHover">Entradas</span></div>
        <div><span className="font-semibold text-amber-700">Salidas</span></div>
      </div>
    </div>
  );
}

function RouteLoadPanel({ routes }: { routes: DashboardRouteLoad[] }) {
  if (!routes.length) {
    return <div className="rounded border border-borderSoft bg-white px-3 py-2 text-[12px] text-secondaryText">Sin hojas activas.</div>;
  }

  return (
    <div className="overflow-auto">
      <table className="w-full border-collapse text-left text-[12px]">
        <thead className="bg-deep text-white">
          <tr>
            <th className="px-3 py-2 font-semibold">Hoja</th>
            <th className="px-3 py-2 font-semibold">Estado</th>
            <th className="px-3 py-2 text-right font-semibold">Paradas</th>
            <th className="px-3 py-2 text-right font-semibold">Kg</th>
            <th className="px-3 py-2 text-right font-semibold">m3</th>
          </tr>
        </thead>
        <tbody>
          {routes.map((route) => (
            <tr key={route.route_number} className="border-b border-borderSoft bg-white">
              <td className="px-3 py-2 font-mono font-semibold text-night">{route.route_number}</td>
              <td className="px-3 py-2 text-secondaryText">{route.status}</td>
              <td className="px-3 py-2 text-right font-mono text-night">{formatCount(route.stops)}</td>
              <td className="px-3 py-2 text-right font-mono text-night">{formatQuantity(route.planned_weight_kg)}</td>
              <td className="px-3 py-2 text-right font-mono text-night">{formatQuantity(route.planned_volume_m3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ModuleTable({ modules }: { modules: OperationalDashboardModule[] }) {
  return (
    <div className="overflow-auto">
      <table className="w-full border-collapse text-left text-[12px]">
        <thead className="sticky top-0 bg-deep text-white">
          <tr>
            <th className="min-w-[180px] px-3 py-2 font-semibold">Modulo</th>
            <th className="px-3 py-2 text-right font-semibold">Reg.</th>
            <th className="px-3 py-2 text-right font-semibold">Activos</th>
            <th className="px-3 py-2 text-right font-semibold">Alertas</th>
            <th className="px-3 py-2 font-semibold">Estado</th>
          </tr>
        </thead>
        <tbody>
          {modules.map((module) => (
            <tr key={module.key} className="border-b border-borderSoft bg-white hover:bg-softStart">
              <td className="px-3 py-2">
                <Link className="font-semibold text-primaryHover hover:text-primary" to={module.path}>
                  {module.label}
                </Link>
              </td>
              <td className="px-3 py-2 text-right font-mono text-night">{formatCount(module.count)}</td>
              <td className="px-3 py-2 text-right font-mono text-night">{formatCount(module.active)}</td>
              <td className="px-3 py-2 text-right font-mono text-night">{formatCount(module.issues)}</td>
              <td className="px-3 py-2">
                <StatusBadge label={module.issues ? "Atencion" : module.count ? "OK" : "Cero"} tone={module.issues ? "warning" : module.count ? "success" : "neutral"} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AlertsPanel({ dashboard }: { dashboard: OperationalDashboard }) {
  return (
    <div className="space-y-2">
      {dashboard.alerts.length ? (
        dashboard.alerts.map((alert) => (
          <div key={alert.key} className={`rounded border px-2.5 py-2 text-[12px] leading-5 ${metricToneClasses[alert.tone]}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold text-night">{alert.label}</span>
              <span className="font-mono font-semibold text-night">{formatCount(alert.value)}</span>
            </div>
          </div>
        ))
      ) : (
        <div className="rounded border border-borderSoft bg-white px-2.5 py-2 text-[12px] leading-5 text-secondaryText">
          Sin alertas.
        </div>
      )}
    </div>
  );
}

export function DashboardPage() {
  const [dashboard, setDashboard] = useState<OperationalDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchOperationalDashboard()
      .then((payload) => {
        if (!cancelled) {
          setDashboard(payload);
        }
      })
      .catch((apiError: unknown) => {
        if (!cancelled) {
          const message = messageFor(apiError);
          setError(message);
          notify({ message, tone: "error" });
        }
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

  const moduleTotal = useMemo(
    () => dashboard?.modules.reduce((total, module) => total + module.count, 0) ?? 0,
    [dashboard],
  );
  const moduleIssues = useMemo(
    () => dashboard?.modules.reduce((total, module) => total + module.issues, 0) ?? 0,
    [dashboard],
  );

  if (!dashboard && loading) {
    return (
      <div className="flex h-full items-center justify-center p-4">
        <div className="rounded border border-borderSoft bg-surface px-4 py-3 text-[13px] font-semibold text-secondaryText shadow-panel">
          Cargando...
        </div>
      </div>
    );
  }

  if (!dashboard) {
    return (
      <div className="flex h-full items-center justify-center p-4">
        <div className="max-w-lg rounded border border-red-200 bg-red-50 px-4 py-3 text-[13px] leading-5 text-red-800 shadow-panel">
          <div className="font-semibold">Dashboard no cargado.</div>
          <div className="mt-1">{error}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full min-h-0 overflow-auto p-3">
      <div className="flex min-h-full flex-col gap-3">
        <section className="flex shrink-0 flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-[20px] font-semibold text-night">Dashboard operativo</h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge label={loading ? "actualizando" : dashboard.scope.warehouse_ref} tone={loading ? "info" : "success"} />
            <StatusBadge label={`${formatCount(moduleTotal)} registros`} tone="info" />
            <StatusBadge label={`${formatCount(moduleIssues)} alertas`} tone={moduleIssues ? "warning" : "success"} />
          </div>
        </section>

        <section className="grid shrink-0 grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-9" aria-label="KPIs TMS/WMS">
          {dashboard.kpis.map((metric) => (
            <MetricCard key={metric.key} metric={metric} />
          ))}
        </section>

        <section className="grid grid-cols-1 gap-3 xl:grid-cols-2 2xl:grid-cols-4">
          <ChartPanel title="Pedidos por estado" aside={formatDateTime(dashboard.generated_at)}>
            <HorizontalBarChart data={dashboard.charts.fulfillment_status} ariaLabel="Pedidos por estado" tone="info" />
          </ChartPanel>

          <ChartPanel title="Entregas por estado">
            <HorizontalBarChart data={dashboard.charts.delivery_pipeline} ariaLabel="Entregas por estado" tone="success" />
          </ChartPanel>

          <ChartPanel title="Stock por estado">
            <StockStateChart data={dashboard.charts.stock_by_state} />
          </ChartPanel>

          <ChartPanel title="Ledger 7 dias">
            <LedgerChart data={dashboard.charts.ledger_by_day} />
          </ChartPanel>
        </section>

        <section className="grid min-h-[360px] grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.7fr)]">
          <ChartPanel title="Hojas activas">
            <RouteLoadPanel routes={dashboard.charts.route_load} />
          </ChartPanel>

          <ChartPanel title="Alertas operativas" aside={`${formatCount(dashboard.alerts.length)} foco`}>
            <AlertsPanel dashboard={dashboard} />
          </ChartPanel>
        </section>

        <section className="grid min-h-[380px] grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
          <ChartPanel title="Cobertura por modulo">
            <ModuleTable modules={dashboard.modules} />
          </ChartPanel>

          <ChartPanel title="Modulos con cero">
            <HorizontalBarChart data={dashboard.charts.module_coverage} ariaLabel="Cobertura de modulos" showZeros tone="neutral" />
          </ChartPanel>
        </section>
      </div>
    </div>
  );
}
