import { AlertTriangle, Boxes, ChevronLeft, ChevronRight, FilterX, Layers3, PackageSearch, RefreshCw, Search, Warehouse } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { fetchInventoryStockReport, type InventoryStockReportRow } from "../../api/inventory";
import { fetchWarehouseOptionsForStore, type WarehouseOption } from "../../api/routing";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { notify } from "../../shared/components/toast";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";
import type { StatusTone } from "../../types/operations";

type QuantityState = "on_hand" | "reserved" | "picking" | "packed" | "in_transit" | "scrapped";
type FilterKey = "warehouse" | "location" | "item" | "supplier" | "category" | "lot" | "pallet" | "quality" | "search";

type StockFilters = Record<FilterKey, string>;

type QuantityColumn = {
  key: QuantityState;
  label: string;
  shortLabel: string;
  tone: StatusTone;
};

type KpiTile = {
  label: string;
  value: string;
  hint: string;
  tone: StatusTone;
};

const quantityColumns: QuantityColumn[] = [
  { key: "packed", label: "Disponible entrega", shortLabel: "Entrega", tone: "success" },
  { key: "reserved", label: "Reservado", shortLabel: "Reservado", tone: "warning" },
  { key: "picking", label: "En preparacion", shortLabel: "Preparacion", tone: "warning" },
  { key: "on_hand", label: "Disponible fisico", shortLabel: "Fisico", tone: "info" },
  { key: "in_transit", label: "En transito", shortLabel: "Transito", tone: "info" },
  { key: "scrapped", label: "Roto/Merma", shortLabel: "Merma", tone: "danger" },
];

const emptyFilters: StockFilters = {
  warehouse: "",
  location: "",
  item: "",
  supplier: "",
  category: "",
  lot: "",
  pallet: "",
  quality: "",
  search: "",
};

function asNumber(value: string | number | undefined) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatNumber(value: string | number | undefined) {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 3 }).format(asNumber(value));
}

function formatQuantity(value: string | number | undefined, uom: string) {
  return `${formatNumber(value)} ${uom}`.trim();
}

function compactValue(value?: string) {
  return value?.trim() || "-";
}

function rowLocation(row: InventoryStockReportRow) {
  return row.warehouse_location_ref || row.location_ref || "";
}

function rowCategory(row: InventoryStockReportRow) {
  return row.category_ref || row.rubro_ref || row.category || "";
}

function warehouseLabel(code: string, warehouses: WarehouseOption[]) {
  const match = warehouses.find((warehouse) => warehouse.warehouse_code === code);
  return match?.warehouse_name ? `${code} / ${match.warehouse_name}` : code;
}

function uniqueSorted(values: string[]) {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b));
}

function matches(value: string | undefined, filter: string) {
  return !filter || (value ?? "").toLowerCase().includes(filter.toLowerCase());
}

function rowQuantity(row: InventoryStockReportRow, state: QuantityState) {
  return asNumber(row.quantities?.[state]);
}

function rowTotal(row: InventoryStockReportRow) {
  return quantityColumns.reduce((total, column) => total + rowQuantity(row, column.key), 0);
}

function buildKpis(rows: InventoryStockReportRow[], visibleRows: InventoryStockReportRow[], allowedWarehouses: string[]): KpiTile[] {
  const totalStock = visibleRows.reduce((total, row) => total + rowTotal(row), 0);
  return [
    {
      label: "Posiciones",
      value: String(visibleRows.length),
      hint: `${uniqueSorted(visibleRows.map((row) => row.item_ref)).length} productos`,
      tone: "info",
    },
    {
      label: "Almacenes",
      value: String(allowedWarehouses.length || uniqueSorted(rows.map((row) => row.warehouse_ref)).length),
      hint: "scope operativo",
      tone: "success",
    },
    {
      label: "Stock total",
      value: formatNumber(totalStock),
      hint: "todos los estados",
      tone: totalStock ? "success" : "neutral",
    },
    {
      label: "Ubicaciones",
      value: String(uniqueSorted(visibleRows.map(rowLocation)).length),
      hint: "visibles",
      tone: visibleRows.length ? "success" : "neutral",
    },
  ];
}

function applyFilters(rows: InventoryStockReportRow[], filters: StockFilters) {
  const query = filters.search.trim().toLowerCase();
  return rows.filter((row) => {
    const category = rowCategory(row);
    const location = rowLocation(row);
    if (filters.warehouse && row.warehouse_ref !== filters.warehouse) return false;
    if (!matches(location, filters.location)) return false;
    if (!matches(row.item_ref, filters.item) && !matches(row.item_name, filters.item)) return false;
    if (!matches(row.supplier_ref, filters.supplier)) return false;
    if (!matches(category, filters.category)) return false;
    if (!matches(row.lot_ref, filters.lot)) return false;
    if (!matches(row.pallet_ref, filters.pallet)) return false;
    if (!matches(row.quality_status, filters.quality)) return false;
    if (!query) return true;
    return [
      row.item_ref,
      row.item_name,
      row.warehouse_ref,
      location,
      row.location_name,
      row.zone_ref,
      row.aisle,
      row.floor,
      row.level,
      row.position,
      row.supplier_ref,
      category,
      row.lot_ref,
      row.pallet_ref,
      row.quality_status,
    ]
      .filter(Boolean)
      .some((value) => value?.toLowerCase().includes(query));
  });
}

function filterCount(filters: StockFilters) {
  return Object.values(filters).filter(Boolean).length;
}

function hasReportFilters(filters: StockFilters, serverSearch: string) {
  return Boolean(
    filters.warehouse ||
      filters.location ||
      filters.item ||
      filters.supplier ||
      filters.category ||
      filters.lot ||
      filters.pallet ||
      filters.quality ||
      serverSearch.trim(),
  );
}

function selectOptions(rows: InventoryStockReportRow[], key: "location" | "supplier" | "category" | "lot" | "pallet" | "quality") {
  const accessors = {
    location: rowLocation,
    supplier: (row: InventoryStockReportRow) => row.supplier_ref || "",
    category: rowCategory,
    lot: (row: InventoryStockReportRow) => row.lot_ref || "",
    pallet: (row: InventoryStockReportRow) => row.pallet_ref || "",
    quality: (row: InventoryStockReportRow) => row.quality_status || "",
  };
  return uniqueSorted(rows.map(accessors[key]));
}

type FilterFieldProps = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children?: ReactNode;
  placeholder?: string;
};

function TextFilter({ label, value, onChange, placeholder }: FilterFieldProps) {
  return (
    <label className="grid min-w-0 gap-1 text-[11px] font-semibold text-secondaryText">
      {label}
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 min-w-0 rounded border border-borderSoft bg-white px-2 text-[12px] font-medium text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
        placeholder={placeholder}
      />
    </label>
  );
}

function SelectFilter({ label, value, onChange, children }: FilterFieldProps) {
  return (
    <label className="grid min-w-0 gap-1 text-[11px] font-semibold text-secondaryText">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 min-w-0 rounded border border-borderSoft bg-white px-2 text-[12px] font-medium text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
      >
        {children}
      </select>
    </label>
  );
}

type QuantityCellProps = {
  value: number;
  uom: string;
  tone: StatusTone;
};

function QuantityCell({ value, uom, tone }: QuantityCellProps) {
  const toneClasses: Record<StatusTone, string> = {
    neutral: "border-slate-200 bg-slate-50 text-slate-700",
    info: "border-blue-200 bg-blue-50 text-blue-800",
    warning: "border-amber-300 bg-amber-50 text-amber-900",
    success: "border-emerald-300 bg-emerald-50 text-emerald-900",
    danger: "border-red-300 bg-red-50 text-red-800",
  };
  const active = value > 0;
  return (
    <span
      className={`inline-flex min-h-6 w-full min-w-[72px] items-center justify-end rounded border px-2 font-mono text-[12px] font-semibold ${
        active ? toneClasses[tone] : "border-transparent bg-transparent text-secondaryText"
      }`}
    >
      {active ? formatQuantity(value, uom) : "-"}
    </span>
  );
}

function selectedItemLocationRows(rows: InventoryStockReportRow[], selectedRow: InventoryStockReportRow) {
  return rows
    .filter((row) => row.warehouse_ref === selectedRow.warehouse_ref && row.item_ref === selectedRow.item_ref)
    .sort((left, right) => {
      const locationCompare = rowLocation(left).localeCompare(rowLocation(right));
      if (locationCompare) return locationCompare;
      const lotCompare = (left.lot_ref || "").localeCompare(right.lot_ref || "");
      if (lotCompare) return lotCompare;
      return left.uom.localeCompare(right.uom);
    });
}

function quantitySummary(rows: InventoryStockReportRow[], state: QuantityState) {
  const grouped = new Map<string, number>();
  rows.forEach((row) => {
    grouped.set(row.uom, (grouped.get(row.uom) ?? 0) + rowQuantity(row, state));
  });
  return Array.from(grouped.entries()).map(([uom, value]) => ({ uom, value }));
}

function formatQuantitySummary(rows: InventoryStockReportRow[], state: QuantityState) {
  const summary = quantitySummary(rows, state).filter((entry) => entry.value > 0);
  if (!summary.length) {
    return "-";
  }
  return summary.map((entry) => formatQuantity(entry.value, entry.uom)).join(" / ");
}

export function StockBalancesPage() {
  const branchRef = useWorkspaceStore((state) => state.branchRef);
  const [rows, setRows] = useState<InventoryStockReportRow[]>([]);
  const [warehouseOptions, setWarehouseOptions] = useState<WarehouseOption[]>([]);
  const [allowedWarehouses, setAllowedWarehouses] = useState<string[]>([]);
  const [filters, setFilters] = useState<StockFilters>(emptyFilters);
  const [selectedId, setSelectedId] = useState("");
  const [detailOpen, setDetailOpen] = useState(true);
  const [loading, setLoading] = useState(false);
  const [serverSearch, setServerSearch] = useState("");
  const hasActiveReportFilters = hasReportFilters(filters, serverSearch);

  async function loadReport() {
    if (!hasActiveReportFilters) {
      setRows([]);
      setAllowedWarehouses([]);
      setSelectedId("");
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const payload = await fetchInventoryStockReport({
        warehouse: filters.warehouse,
        item: filters.item,
        location: filters.location,
        supplier: filters.supplier,
        category: filters.category,
        lot: filters.lot,
        pallet: filters.pallet,
        quality: filters.quality,
        search: serverSearch,
        limit: filters.item || filters.location || filters.supplier || filters.category || filters.lot || filters.pallet || filters.quality || serverSearch ? 500 : 300,
      });
      setRows(payload.results ?? []);
      setAllowedWarehouses(payload.allowed_warehouses ?? []);
      setSelectedId((current) => {
        if (current && payload.results?.some((row) => row.id === current)) {
          return current;
        }
        return payload.results?.[0]?.id ?? "";
      });
    } catch (apiError) {
      setRows([]);
      setSelectedId("");
      notify({ message: apiError instanceof Error ? apiError.message : "Stock no cargado.", tone: "error" });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!hasActiveReportFilters) {
      setRows([]);
      setAllowedWarehouses([]);
      setSelectedId("");
      setLoading(false);
      return;
    }
    void loadReport();
  }, [filters.warehouse, filters.location, filters.item, filters.supplier, filters.category, filters.lot, filters.pallet, filters.quality, hasActiveReportFilters, serverSearch]);

  useEffect(() => {
    const handle = window.setTimeout(() => setServerSearch(filters.search), 350);
    return () => window.clearTimeout(handle);
  }, [filters.search]);

  useEffect(() => {
    const store = branchRef && !branchRef.toLowerCase().startsWith("cargando") && !branchRef.startsWith("sin-") ? branchRef : "";
    fetchWarehouseOptionsForStore(store)
      .then(setWarehouseOptions)
      .catch(() => setWarehouseOptions([]));
  }, [branchRef]);

  const visibleRows = useMemo(() => applyFilters(rows, filters), [rows, filters]);
  const selectedRow = visibleRows.find((row) => row.id === selectedId) ?? visibleRows[0];
  const selectedLocationRows = selectedRow ? selectedItemLocationRows(rows, selectedRow) : [];
  const warehouseCodes = allowedWarehouses.length
    ? allowedWarehouses
    : uniqueSorted(warehouseOptions.map((warehouse) => warehouse.warehouse_code));
  const kpis = buildKpis(rows, visibleRows, warehouseCodes);
  const activeFilters = filterCount(filters);

  function updateFilter(key: FilterKey, value: string) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  function clearFilters() {
    setFilters(emptyFilters);
  }

  return (
    <div className={`grid h-full min-h-0 grid-cols-1 gap-2 overflow-hidden p-2 ${detailOpen ? "xl:grid-cols-[minmax(0,1fr)_440px]" : ""}`}>
      <section className="flex min-h-0 min-w-0 flex-col gap-2 overflow-hidden">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <h1 className="text-[18px] font-semibold text-night">Stock por almacen</h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setDetailOpen((current) => !current)}
              className="inline-flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20"
              aria-expanded={detailOpen}
            >
              {detailOpen ? <ChevronRight className="h-4 w-4" aria-hidden="true" /> : <ChevronLeft className="h-4 w-4" aria-hidden="true" />}
              Detalle
            </button>
            <button
              type="button"
              onClick={() => void loadReport()}
              disabled={loading || !hasActiveReportFilters}
              className="inline-flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
              Actualizar
            </button>
          </div>
        </header>

        <section className="grid shrink-0 grid-cols-2 gap-2 lg:grid-cols-4" aria-label="Indicadores de stock">
          {kpis.map((item) => (
            <div key={item.label} className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold uppercase text-secondaryText">{item.label}</span>
                <StatusBadge label={item.hint} tone={item.tone} />
              </div>
              <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{item.value}</div>
            </div>
          ))}
        </section>

        <section className="shrink-0 rounded border border-borderSoft bg-softMid p-2 shadow-panel" aria-label="Filtros avanzados de stock">
          <div className="grid gap-2 md:grid-cols-4 xl:grid-cols-8">
            <SelectFilter label="Almacen" value={filters.warehouse} onChange={(value) => updateFilter("warehouse", value)}>
              <option value="">Todos</option>
              {warehouseCodes.map((code) => (
                <option key={code} value={code}>
                  {warehouseLabel(code, warehouseOptions)}
                </option>
              ))}
            </SelectFilter>
            <SelectFilter label="Ubicacion" value={filters.location} onChange={(value) => updateFilter("location", value)}>
              <option value="">Todas</option>
              {selectOptions(rows, "location").map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </SelectFilter>
            <TextFilter label="Producto" value={filters.item} onChange={(value) => updateFilter("item", value)} placeholder="Codigo o nombre" />
            <SelectFilter label="Proveedor" value={filters.supplier} onChange={(value) => updateFilter("supplier", value)}>
              <option value="">Todos</option>
              {selectOptions(rows, "supplier").map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </SelectFilter>
            <SelectFilter label="Rubro" value={filters.category} onChange={(value) => updateFilter("category", value)}>
              <option value="">Todos</option>
              {selectOptions(rows, "category").map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </SelectFilter>
            <SelectFilter label="Lote" value={filters.lot} onChange={(value) => updateFilter("lot", value)}>
              <option value="">Todos</option>
              {selectOptions(rows, "lot").map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </SelectFilter>
            <SelectFilter label="Pallet" value={filters.pallet} onChange={(value) => updateFilter("pallet", value)}>
              <option value="">Todos</option>
              {selectOptions(rows, "pallet").map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </SelectFilter>
            <SelectFilter label="Calidad" value={filters.quality} onChange={(value) => updateFilter("quality", value)}>
              <option value="">Todas</option>
              {selectOptions(rows, "quality").map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </SelectFilter>
          </div>
          <div className="mt-2 grid gap-2 md:grid-cols-[minmax(260px,1fr)_auto_auto]">
            <label className="grid min-w-0 gap-1 text-[11px] font-semibold text-secondaryText">
              Busqueda rapida
              <span className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-secondaryText" aria-hidden="true" />
                <input
                  value={filters.search}
                  onChange={(event) => updateFilter("search", event.target.value)}
                  className="h-8 w-full rounded border border-borderSoft bg-white pl-8 pr-2 text-[12px] font-medium text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                  placeholder="Articulo, ubicacion, zona, pasillo o lote"
                />
              </span>
            </label>
            <button
              type="button"
              onClick={clearFilters}
              disabled={!activeFilters}
              className="inline-flex min-h-8 items-end justify-center gap-2 self-end rounded border border-borderSoft bg-white px-3 pb-1.5 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
            >
              <FilterX className="h-4 w-4" aria-hidden="true" />
              Limpiar
            </button>
            <div className="self-end text-right text-[11px] font-semibold text-secondaryText">
              {activeFilters ? `${activeFilters} filtros activos` : "Sin filtros"}
            </div>
          </div>
        </section>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
            <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
              <PackageSearch className="h-4 w-4 text-primaryHover" aria-hidden="true" />
              {loading ? "Cargando..." : `${visibleRows.length} buckets`}
            </div>
            <div className="text-[11px] text-secondaryText">{warehouseCodes.length} almacenes habilitados</div>
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full min-w-[1540px] border-collapse text-left text-[12px]">
              <thead className="sticky top-0 z-10 bg-deep text-white">
                <tr>
                  <th className="w-[120px] px-2 py-2 font-semibold">Almacen</th>
                  <th className="w-[140px] px-2 py-2 font-semibold">Ubicacion</th>
                  <th className="w-[150px] px-2 py-2 font-semibold">Nombre</th>
                  <th className="w-[70px] px-2 py-2 font-semibold">Zona</th>
                  <th className="w-[70px] px-2 py-2 font-semibold">Pasillo</th>
                  <th className="w-[60px] px-2 py-2 font-semibold">Piso</th>
                  <th className="w-[60px] px-2 py-2 font-semibold">Nivel</th>
                  <th className="w-[70px] px-2 py-2 font-semibold">Posicion</th>
                  <th className="w-[240px] px-2 py-2 font-semibold">Producto</th>
                  <th className="w-[105px] px-2 py-2 font-semibold">Rubro</th>
                  <th className="w-[90px] px-2 py-2 font-semibold">Lote</th>
                  {quantityColumns.map((column) => (
                    <th key={column.key} className="w-[92px] px-2 py-2 text-right font-semibold" title={column.label}>
                      {column.shortLabel}
                    </th>
                  ))}
                  <th className="w-[86px] px-2 py-2 text-right font-semibold">Total</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => {
                  const selected = row.id === selectedRow?.id;
                  return (
                    <tr
                      key={row.id}
                      onClick={() => setSelectedId(row.id)}
                      className={`cursor-pointer border-b border-borderSoft hover:bg-softStart ${selected ? "bg-blue-50 outline outline-1 outline-primary/30" : "bg-white"}`}
                    >
                      <td className="whitespace-nowrap px-2 py-1.5 font-mono font-semibold text-night">{row.warehouse_ref}</td>
                      <td className="whitespace-nowrap px-2 py-1.5 font-mono text-night">{compactValue(rowLocation(row))}</td>
                      <td className="whitespace-nowrap px-2 py-1.5 text-secondaryText">{compactValue(row.location_name)}</td>
                      <td className="whitespace-nowrap px-2 py-1.5 font-mono text-secondaryText">{compactValue(row.zone_ref)}</td>
                      <td className="whitespace-nowrap px-2 py-1.5 font-mono text-secondaryText">{compactValue(row.aisle)}</td>
                      <td className="whitespace-nowrap px-2 py-1.5 font-mono text-secondaryText">{compactValue(row.floor)}</td>
                      <td className="whitespace-nowrap px-2 py-1.5 font-mono text-secondaryText">{compactValue(row.level)}</td>
                      <td className="whitespace-nowrap px-2 py-1.5 font-mono text-secondaryText">{compactValue(row.position)}</td>
                      <td className="px-2 py-1.5">
                        <div className="font-mono font-semibold text-night">{row.item_ref}</div>
                        {row.item_name ? <div className="max-w-[240px] truncate text-[11px] text-secondaryText" title={row.item_name}>{row.item_name}</div> : null}
                      </td>
                      <td className="whitespace-nowrap px-2 py-1.5 text-secondaryText">{compactValue(rowCategory(row))}</td>
                      <td className="whitespace-nowrap px-2 py-1.5 font-mono text-secondaryText">{compactValue(row.lot_ref)}</td>
                      {quantityColumns.map((column) => (
                        <td key={column.key} className="px-2 py-1.5 text-right">
                          <QuantityCell value={rowQuantity(row, column.key)} uom={row.uom} tone={column.tone} />
                        </td>
                      ))}
                      <td className="whitespace-nowrap px-2 py-1.5 text-right font-mono font-semibold text-night">{formatQuantity(rowTotal(row), row.uom)}</td>
                    </tr>
                  );
                })}
                {!visibleRows.length && (
                  <tr>
                    <td colSpan={18} className="px-3 py-12 text-center text-[12px] text-secondaryText">
                      {loading ? "Cargando..." : hasActiveReportFilters ? "Sin stock." : "Sin filtros."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {detailOpen ? (
        <aside className="min-h-0 overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
            <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
              <Layers3 className="h-4 w-4 text-primaryHover" aria-hidden="true" />
              Detalle por posiciones
            </div>
          </div>
          {selectedRow ? (
            <div className="flex h-full min-h-0 flex-col overflow-auto p-3">
              <section className="grid gap-2 border-b border-borderSoft pb-3 text-[12px]">
                <div>
                  <div className="text-[11px] font-semibold uppercase text-secondaryText">Producto</div>
                  <div className="mt-0.5 font-mono text-[15px] font-semibold text-night">{selectedRow.item_ref}</div>
                  {selectedRow.item_name ? <div className="text-[12px] text-secondaryText">{selectedRow.item_name}</div> : null}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="rounded border border-borderSoft bg-softMid px-2 py-2">
                    <div className="flex items-center gap-2 text-[11px] font-semibold text-secondaryText">
                      <Warehouse className="h-4 w-4" aria-hidden="true" />
                      Almacen
                    </div>
                    <div className="mt-1 font-mono font-semibold text-night">{selectedRow.warehouse_ref}</div>
                  </div>
                  <div className="rounded border border-borderSoft bg-softMid px-2 py-2">
                    <div className="flex items-center gap-2 text-[11px] font-semibold text-secondaryText">
                      <Boxes className="h-4 w-4" aria-hidden="true" />
                      Posiciones
                    </div>
                    <div className="mt-1 font-mono font-semibold text-night">{selectedLocationRows.length}</div>
                  </div>
                </div>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[12px]">
                  <dt className="font-semibold text-secondaryText">Rubro</dt>
                  <dd className="text-night">{compactValue(rowCategory(selectedRow))}</dd>
                  <dt className="font-semibold text-secondaryText">UOM seleccionada</dt>
                  <dd className="font-mono text-night">{selectedRow.uom}</dd>
                </dl>
              </section>

              <section className="grid gap-2 border-b border-borderSoft py-3">
                <div className="text-[12px] font-semibold text-night">Resumen del articulo</div>
                <div className="grid grid-cols-2 gap-2">
                  {quantityColumns.map((column) => (
                    <div key={column.key} className="rounded border border-borderSoft bg-white px-2 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[11px] font-semibold text-secondaryText">{column.label}</span>
                        <StatusBadge
                          label={quantitySummary(selectedLocationRows, column.key).some((entry) => entry.value > 0) ? "con saldo" : "cero"}
                          tone={quantitySummary(selectedLocationRows, column.key).some((entry) => entry.value > 0) ? column.tone : "neutral"}
                        />
                      </div>
                      <div className="mt-1 font-mono text-[14px] font-semibold text-night">{formatQuantitySummary(selectedLocationRows, column.key)}</div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="min-h-0 py-3" aria-label="Detalle por posiciones del articulo">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="text-[12px] font-semibold text-night">Ubicaciones del almacen</div>
                  <StatusBadge label={`${selectedLocationRows.length} posiciones`} tone={selectedLocationRows.length ? "info" : "neutral"} />
                </div>
                {selectedLocationRows.length ? (
                  <div className="overflow-auto rounded border border-borderSoft">
                    <table className="w-full min-w-[720px] border-collapse text-left text-[12px]">
                      <thead className="bg-softMid text-secondaryText">
                        <tr>
                          <th className="px-2 py-2 font-semibold">Ubicacion</th>
                          <th className="px-2 py-2 font-semibold">Nombre</th>
                          <th className="px-2 py-2 font-semibold">Lote</th>
                          {quantityColumns.map((column) => (
                            <th key={column.key} className="px-2 py-2 text-right font-semibold">
                              {column.shortLabel}
                            </th>
                          ))}
                          <th className="px-2 py-2 text-right font-semibold">Total</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedLocationRows.map((row) => (
                          <tr key={row.id} className={`border-t border-borderSoft ${row.id === selectedRow.id ? "bg-blue-50" : "bg-white"}`}>
                            <td className="whitespace-nowrap px-2 py-2 font-mono font-semibold text-night">{compactValue(rowLocation(row))}</td>
                            <td className="px-2 py-2 text-secondaryText">{compactValue(row.location_name)}</td>
                            <td className="whitespace-nowrap px-2 py-2 font-mono text-secondaryText">{compactValue(row.lot_ref)}</td>
                            {quantityColumns.map((column) => (
                              <td key={column.key} className="whitespace-nowrap px-2 py-2 text-right font-mono text-night">
                                {rowQuantity(row, column.key) > 0 ? formatQuantity(rowQuantity(row, column.key), row.uom) : "-"}
                              </td>
                            ))}
                            <td className="whitespace-nowrap px-2 py-2 text-right font-mono font-semibold text-night">{formatQuantity(rowTotal(row), row.uom)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="rounded border border-borderSoft bg-softMid px-3 py-2 text-[12px] text-secondaryText">Sin posiciones para el articulo seleccionado.</div>
                )}
              </section>
            </div>
          ) : (
            <div className="flex h-full min-h-64 flex-col items-center justify-center gap-2 px-6 text-center text-[12px] text-secondaryText">
              <AlertTriangle className="h-6 w-6 text-secondaryText" aria-hidden="true" />
              Sin renglon seleccionado.
            </div>
          )}
        </aside>
      ) : null}
    </div>
  );
}
