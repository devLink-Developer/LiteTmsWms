import { Link } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";

import { buildKpis, fetchOperationRows, fetchOperationalOverview } from "../../api/operations";
import { KpiStrip } from "../../shared/components/KpiStrip";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { operationModules } from "../../shared/data/modules";
import type { Kpi, OperationRow } from "../../types/operations";

export function DashboardPage() {
  const [rowsByModule, setRowsByModule] = useState<Record<string, OperationRow[]>>({});
  const [principles, setPrinciples] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    Promise.all([
      fetchOperationalOverview(),
      Promise.all(
        operationModules.map(async (module) => ({
          key: module.key,
          rows: await fetchOperationRows(module),
        })),
      ),
    ])
      .then(([overview, moduleRows]) => {
        if (cancelled) {
          return;
        }
        setPrinciples(overview.principles ?? []);
        setRowsByModule(Object.fromEntries(moduleRows.map((entry) => [entry.key, entry.rows])));
      })
      .catch((apiError: unknown) => {
        if (!cancelled) {
          setRowsByModule({});
          setPrinciples([]);
          setError(apiError instanceof Error ? apiError.message : "No se pudo cargar dashboard desde API.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const executiveKpis: Kpi[] = useMemo(() => {
    const rows = Object.values(rowsByModule).flat();
    return buildKpis(rows);
  }, [rowsByModule]);

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <section className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-semibold text-night">Dashboard operativo</h1>
          <p className="mt-1 max-w-3xl text-[12px] leading-5 text-secondaryText">
            Priorizacion de recepciones, transferencias, fulfillment, rutas, auditorias y despacho con foco en estados criticos.
          </p>
        </div>
        <div className="flex gap-2">
          <StatusBadge label="legacy read-only" tone="info" />
          <StatusBadge label="ledger activo" tone="success" />
        </div>
      </section>
      {error && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700">{error}</div>}
      <KpiStrip items={executiveKpis} />
      <section className="grid min-h-0 flex-1 grid-cols-1 gap-3 xl:grid-cols-[1.3fr_0.7fr]">
        <div className="min-h-0 overflow-auto rounded border border-borderSoft bg-surface shadow-panel">
          <div className="border-b border-borderSoft px-3 py-2">
            <h2 className="text-[13px] font-semibold text-night">Cola priorizada</h2>
          </div>
          <table className="w-full text-left text-[12px]">
            <thead className="sticky top-0 bg-deep text-white">
              <tr>
                <th className="px-3 py-2">Modulo</th>
                <th className="px-3 py-2">Critico</th>
                <th className="px-3 py-2">Estado</th>
                <th className="px-3 py-2">Accion</th>
              </tr>
            </thead>
            <tbody>
              {operationModules.slice(0, 8).map((module) => {
                const rows = rowsByModule[module.key] ?? [];
                const kpis = buildKpis(rows);
                return (
                <tr key={module.key} className="border-b border-borderSoft bg-white hover:bg-softStart">
                  <td className="px-3 py-2 font-semibold text-night">{module.label}</td>
                  <td className="px-3 py-2 text-secondaryText">{module.description}</td>
                  <td className="px-3 py-2"><StatusBadge label={`${kpis[0].value} registros`} tone={kpis[2].tone} /></td>
                  <td className="px-3 py-2">
                    <Link className="font-semibold text-primaryHover hover:text-primary" to={module.path}>
                      Abrir
                    </Link>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <aside className="rounded border border-borderSoft bg-surface p-3 shadow-panel">
          <h2 className="text-[13px] font-semibold text-night">Principios activos</h2>
          <ul className="mt-3 space-y-2 text-[12px] leading-5 text-secondaryText">
            {principles.length ? (
              principles.map((principle) => <li key={principle}>{principle}</li>)
            ) : (
              <li>Sin datos de principios operativos desde API.</li>
            )}
          </ul>
        </aside>
      </section>
    </div>
  );
}
