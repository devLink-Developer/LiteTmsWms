import { useEffect, useMemo, useState } from "react";

import { buildKpis, fetchOperationRows } from "../../api/operations";
import { DataTable } from "../../shared/components/DataTable";
import { DrawerPanel } from "../../shared/components/DrawerPanel";
import { FilterBar } from "../../shared/components/FilterBar";
import { KpiStrip } from "../../shared/components/KpiStrip";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { notify } from "../../shared/components/toast";
import { storeForModule } from "../../stores/domainStores";
import type { OperationModule, OperationRow } from "../../types/operations";

type OperationalPageProps = {
  module: OperationModule;
};

export function OperationalPage({ module }: OperationalPageProps) {
  const useStore = storeForModule(module.key);
  const filters = useStore((state) => state.filters);
  const selectedIds = useStore((state) => state.selectedIds);
  const activeRecordId = useStore((state) => state.activeRecordId);
  const drawerOpen = useStore((state) => state.drawerOpen);
  const setFilter = useStore((state) => state.setFilter);
  const resetFilters = useStore((state) => state.resetFilters);
  const selectRecord = useStore((state) => state.selectRecord);
  const toggleSelection = useStore((state) => state.toggleSelection);
  const loading = useStore((state) => state.loading);
  const setLoading = useStore((state) => state.setLoading);
  const setError = useStore((state) => state.setError);
  const [rows, setRows] = useState<OperationRow[]>([]);
  const requiresSearchBeforeLoad = module.key === "orders";
  const hasSearchFilter = filters.busqueda.trim().length > 0;

  useEffect(() => {
    if (requiresSearchBeforeLoad && !hasSearchFilter) {
      setRows([]);
      setLoading(false);
      setError(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    const debounce = window.setTimeout(
      () => {
        fetchOperationRows(module, filters)
          .then((apiRows) => {
            if (!cancelled) {
              setRows(apiRows);
            }
          })
          .catch((apiError: unknown) => {
            if (!cancelled) {
              setRows([]);
              const message = apiError instanceof Error ? apiError.message : "Datos no cargados.";
              setError(message);
              notify({ message, tone: "error" });
            }
          })
          .finally(() => {
            if (!cancelled) {
              setLoading(false);
            }
          });
      },
      filters.busqueda.trim() ? 250 : 0,
    );

    return () => {
      cancelled = true;
      window.clearTimeout(debounce);
    };
  }, [filters, hasSearchFilter, module, requiresSearchBeforeLoad, setError, setLoading]);

  const filteredRows = useMemo(() => {
    return rows.filter((row) => {
      const search = filters.busqueda.trim().toLowerCase();
      const rawText = JSON.stringify(row.raw ?? {});
      const matchesSearch = !search || `${row.ref} ${row.owner} ${row.warehouse} ${rawText}`.toLowerCase().includes(search);
      const matchesStatus = !filters.estado || row.status === filters.estado;
      const matchesWarehouse = !filters.warehouse || row.warehouse.toLowerCase().includes(filters.warehouse.toLowerCase());
      return matchesSearch && matchesStatus && matchesWarehouse;
    });
  }, [filters, rows]);

  const activeRow = filteredRows.find((row) => row.id === activeRecordId) ?? rows.find((row) => row.id === activeRecordId);
  const kpis = useMemo(() => buildKpis(rows), [rows]);

  return (
    <div className="flex h-full min-h-0">
      <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-hidden p-3">
        <header className="flex shrink-0 flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-[20px] font-semibold text-night">{module.label}</h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge label={module.permissions[0]} tone="info" />
            {!module.readOnly && module.primaryAction && (
              <button
                type="button"
                className="h-9 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/30"
              >
                {module.primaryAction}
              </button>
            )}
          </div>
        </header>
        <KpiStrip items={kpis} />
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="flex min-h-11 items-center justify-between border-b border-borderSoft px-3">
            <div className="text-[12px] font-semibold text-night">
              {loading ? "Cargando..." : `${filteredRows.length} registros`}
            </div>
            <div className="text-[11px] text-secondaryText">{selectedIds.length} seleccionados</div>
          </div>
          <FilterBar filters={filters} onFilter={setFilter} onReset={resetFilters} />
          <DataTable
            rows={filteredRows}
            columns={module.columns}
            selectedIds={selectedIds}
            onSelect={toggleSelection}
            onOpen={selectRecord}
          />
        </div>
      </section>
      {drawerOpen && <DrawerPanel module={module} row={activeRow} onClose={() => selectRecord(null)} />}
    </div>
  );
}
