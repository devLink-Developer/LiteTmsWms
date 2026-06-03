import {
  ArrowDown,
  ArrowRightLeft,
  ArrowUp,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  FilterX,
  ListTree,
  RefreshCw,
  Search,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { fetchInventoryLedgerEntries, type InventoryLedgerEntry } from "../../api/inventory";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { notify } from "../../shared/components/toast";
import { formatAppDateTime } from "../../shared/utils/dateFormat";
import { translateStatusLabel } from "../../shared/utils/statusLabels";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";
import type { StatusTone } from "../../types/operations";

type MovementFilterKey =
  | "search"
  | "warehouse"
  | "item"
  | "movementType"
  | "direction"
  | "stockState"
  | "location"
  | "lot"
  | "documentType"
  | "documentRef"
  | "dateFrom"
  | "dateTo";

type MovementFilters = Record<MovementFilterKey, string>;

type StockMovementRow = {
  id: string;
  postedAt: string;
  movementType: string;
  direction: "paired" | "increase" | "decrease";
  warehouseRef: string;
  itemRef: string;
  lotRef: string;
  quantity: string;
  uom: string;
  documentType: string;
  documentRef: string;
  responsible: string;
  sourceLocation: string;
  sourceState: string;
  targetLocation: string;
  targetState: string;
  entries: InventoryLedgerEntry[];
};

type KpiTile = {
  label: string;
  value: string;
  hint: string;
  tone: StatusTone;
};

type FilterFieldProps = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children?: ReactNode;
  placeholder?: string;
  type?: "text" | "date" | "datetime-local";
};

const emptyFilters: MovementFilters = {
  search: "",
  warehouse: "",
  item: "",
  movementType: "",
  direction: "",
  stockState: "",
  location: "",
  lot: "",
  documentType: "",
  documentRef: "",
  dateFrom: "",
  dateTo: "",
};

const movementTypes = [
  "inbound_receipt",
  "reservation_hold",
  "reservation_release",
  "pick",
  "dispatch",
  "transfer_out",
  "transfer_in",
  "adjustment",
  "transformation_in",
  "transformation_out",
  "location_transfer",
  "write_off",
  "reversal",
];

const stockStates = [
  "on_hand",
  "reserved",
  "picking",
  "packed",
  "in_transit",
  "delivered",
  "adjusted",
  "scrapped",
  "converted",
];

const pairWindowMs = 10000;

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

function compact(value: string | undefined, fallback = "-") {
  return value?.trim() || fallback;
}

function shortId(value: string) {
  return value.length > 12 ? value.slice(0, 8) : value;
}

function responsibleUser(value: string | undefined, fallback = "-") {
  const label = value?.trim();
  if (!label) return fallback;
  return label.split("@")[0] || fallback;
}

function documentTypeLabel(value: string) {
  return translateStatusLabel(value);
}

function timestamp(entry: InventoryLedgerEntry) {
  const parsed = entry.posted_at ? Date.parse(entry.posted_at) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : 0;
}

function movementFamily(movementType: string) {
  if (movementType === "transfer_out" || movementType === "transfer_in") return "transfer";
  if (movementType === "transformation_out" || movementType === "transformation_in") return "transformation";
  return movementType;
}

function pairScope(entry: InventoryLedgerEntry) {
  return [
    entry.document_type,
    entry.document_ref,
    movementFamily(entry.movement_type),
    entry.warehouse_ref,
    entry.item_ref,
    entry.lot_ref || "",
    entry.quantity,
    entry.uom,
  ].join("|");
}

function movementTypeLabel(entries: InventoryLedgerEntry[]) {
  const labels = Array.from(new Set(entries.map((entry) => entry.movement_type)));
  return labels.length === 1 ? labels[0] : labels.join(" -> ");
}

function movementResponsible(entries: InventoryLedgerEntry[]) {
  return Array.from(new Set(entries.map((entry) => responsibleUser(entry.created_by, "")).filter(Boolean))).join(" / ");
}

function rowPostedAt(entries: InventoryLedgerEntry[]) {
  return entries.reduce((latest, entry) => (timestamp(entry) > timestamp(latest) ? entry : latest), entries[0]).posted_at ?? "";
}

function buildMovementRows(entries: InventoryLedgerEntry[]) {
  const sorted = [...entries].sort((left, right) => timestamp(left) - timestamp(right));
  const used = new Set<string>();
  const rows: StockMovementRow[] = [];

  sorted.forEach((entry, index) => {
    if (used.has(entry.id)) return;
    let pair: InventoryLedgerEntry | undefined;
    let pairDistance = Number.POSITIVE_INFINITY;
    sorted.forEach((candidate, candidateIndex) => {
      if (candidateIndex === index || used.has(candidate.id)) return;
      if (candidate.direction === entry.direction) return;
      if (pairScope(candidate) !== pairScope(entry)) return;
      const distance = Math.abs(timestamp(candidate) - timestamp(entry));
      if (distance <= pairWindowMs && distance < pairDistance) {
        pair = candidate;
        pairDistance = distance;
      }
    });

    const rowEntries = pair ? [entry, pair] : [entry];
    rowEntries.forEach((rowEntry) => used.add(rowEntry.id));
    const source = rowEntries.find((rowEntry) => rowEntry.direction === "decrease");
    const target = rowEntries.find((rowEntry) => rowEntry.direction === "increase");
    const base = target ?? source ?? entry;

    rows.push({
      id: rowEntries.map((rowEntry) => rowEntry.id).sort().join("|"),
      postedAt: rowPostedAt(rowEntries),
      movementType: movementTypeLabel(rowEntries),
      direction: rowEntries.length > 1 ? "paired" : entry.direction === "decrease" ? "decrease" : "increase",
      warehouseRef: base.warehouse_ref,
      itemRef: base.item_ref,
      lotRef: base.lot_ref || "",
      quantity: base.quantity,
      uom: base.uom,
      documentType: base.document_type,
      documentRef: base.document_ref,
      responsible: movementResponsible(rowEntries),
      sourceLocation: source?.location_ref || "",
      sourceState: source?.stock_state || "",
      targetLocation: target?.location_ref || "",
      targetState: target?.stock_state || "",
      entries: [...rowEntries].sort((left, right) => timestamp(right) - timestamp(left)),
    });
  });

  return rows.sort((left, right) => Date.parse(right.postedAt || "") - Date.parse(left.postedAt || ""));
}

function filterCount(filters: MovementFilters) {
  return Object.values(filters).filter(Boolean).length;
}

function buildKpis(rows: StockMovementRow[], entries: InventoryLedgerEntry[], allowedWarehouses: string[]): KpiTile[] {
  const documents = new Set(rows.map((row) => `${row.documentType}|${row.documentRef}`).filter((value) => value !== "|"));
  const paired = rows.filter((row) => row.direction === "paired").length;
  return [
    { label: "Movimientos", value: String(rows.length), hint: "vista WMS", tone: rows.length ? "info" : "neutral" },
    { label: "Impactos ledger", value: String(entries.length), hint: `${paired} agrupados`, tone: entries.length ? "success" : "neutral" },
    { label: "Documentos", value: String(documents.size), hint: "referencias", tone: documents.size ? "info" : "neutral" },
    { label: "Almacenes", value: String(allowedWarehouses.length || new Set(rows.map((row) => row.warehouseRef)).size), hint: "scope", tone: "success" },
  ];
}

function directionTone(direction: StockMovementRow["direction"]): StatusTone {
  if (direction === "increase") return "success";
  if (direction === "decrease") return "warning";
  return "info";
}

function directionLabel(direction: StockMovementRow["direction"]) {
  if (direction === "paired") return "Movimiento WMS";
  return direction;
}

function directionIcon(direction: StockMovementRow["direction"]) {
  if (direction === "increase") return <ArrowUp className="h-4 w-4" aria-hidden="true" />;
  if (direction === "decrease") return <ArrowDown className="h-4 w-4" aria-hidden="true" />;
  return <ArrowRightLeft className="h-4 w-4" aria-hidden="true" />;
}

function flowText(row: StockMovementRow) {
  const source = [compact(row.sourceLocation), translateStatusLabel(row.sourceState, "")].filter(Boolean).join(" / ");
  const target = [compact(row.targetLocation), translateStatusLabel(row.targetState, "")].filter(Boolean).join(" / ");
  if (row.direction === "paired") return `${source} -> ${target}`;
  if (row.direction === "increase") return `Entrada a ${target || compact(row.targetLocation)}`;
  return `Salida desde ${source || compact(row.sourceLocation)}`;
}

function signedQuantity(row: StockMovementRow) {
  if (row.direction === "paired") return formatQuantity(row.quantity, row.uom);
  const sign = row.direction === "increase" ? "+" : "-";
  return `${sign}${formatQuantity(row.quantity, row.uom)}`;
}

function TextFilter({ label, value, onChange, placeholder, type = "text" }: FilterFieldProps) {
  return (
    <label className="grid min-w-0 gap-1 text-[11px] font-semibold text-secondaryText">
      {label}
      <input
        type={type}
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

export function StockMovementsPage() {
  const allowedWarehouses = useWorkspaceStore((state) => state.authorizedWarehouses);
  const [filters, setFilters] = useState<MovementFilters>(emptyFilters);
  const [entries, setEntries] = useState<InventoryLedgerEntry[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detailOpen, setDetailOpen] = useState(true);
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const rows = useMemo(() => buildMovementRows(entries), [entries]);
  const selectedRow = rows.find((row) => row.id === selectedId) ?? rows[0];
  const kpis = buildKpis(rows, entries, allowedWarehouses);
  const activeFilters = filterCount(filters);

  function updateFilter(key: MovementFilterKey, value: string) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  function clearFilters() {
    setFilters(emptyFilters);
  }

  async function loadMovements(nextFilters = filters) {
    setLoading(true);
    try {
      const payload = await fetchInventoryLedgerEntries({
        search: nextFilters.search.trim(),
        warehouse: nextFilters.warehouse.trim(),
        item: nextFilters.item.trim(),
        movementType: nextFilters.movementType,
        direction: nextFilters.direction,
        stockState: nextFilters.stockState,
        location: nextFilters.location.trim(),
        lot: nextFilters.lot.trim(),
        documentType: nextFilters.documentType.trim(),
        documentRef: nextFilters.documentRef.trim(),
        dateFrom: nextFilters.dateFrom,
        dateTo: nextFilters.dateTo,
        limit: 500,
      });
      const nextEntries = payload.results ?? [];
      const nextRows = buildMovementRows(nextEntries);
      setEntries(nextEntries);
      setSelectedId((current) => (current && nextRows.some((row) => row.id === current) ? current : nextRows[0]?.id ?? ""));
    } catch (apiError) {
      setEntries([]);
      setSelectedId("");
      notify({ message: apiError instanceof Error ? apiError.message : "Movimientos no cargados.", tone: "error" });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const debounce = window.setTimeout(() => void loadMovements(filters), filters.search.trim() || filters.item.trim() || filters.documentRef.trim() ? 250 : 0);
    return () => window.clearTimeout(debounce);
  }, [
    filters.search,
    filters.warehouse,
    filters.item,
    filters.movementType,
    filters.direction,
    filters.stockState,
    filters.location,
    filters.lot,
    filters.documentType,
    filters.documentRef,
    filters.dateFrom,
    filters.dateTo,
  ]);

  return (
    <div className={`grid h-full min-h-0 grid-cols-1 gap-2 overflow-hidden p-2 ${detailOpen ? "xl:grid-cols-[minmax(0,1fr)_430px]" : ""}`}>
      <section className="flex min-h-0 min-w-0 flex-col gap-2 overflow-hidden">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <h1 className="text-[18px] font-semibold text-night">Movimientos de Stock</h1>
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
              onClick={() => void loadMovements()}
              disabled={loading}
              className="inline-flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
              Actualizar
            </button>
          </div>
        </header>

        <section className="grid shrink-0 grid-cols-2 gap-2 lg:grid-cols-4" aria-label="Indicadores de movimientos">
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

        <section className="shrink-0 rounded border border-borderSoft bg-softMid p-2 shadow-panel" aria-label="Filtros de movimientos de stock">
          <div className="grid items-end gap-2 md:grid-cols-[minmax(150px,1fr)_minmax(190px,220px)_minmax(190px,220px)_auto_auto]">
            <TextFilter label="ID articulo" value={filters.item} onChange={(value) => updateFilter("item", value)} placeholder="100100" />
            <TextFilter label="Desde" type="datetime-local" value={filters.dateFrom} onChange={(value) => updateFilter("dateFrom", value)} />
            <TextFilter label="Hasta" type="datetime-local" value={filters.dateTo} onChange={(value) => updateFilter("dateTo", value)} />
            <button
              type="button"
              onClick={clearFilters}
              disabled={!activeFilters}
              className="inline-flex min-h-8 items-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
            >
              <FilterX className="h-4 w-4" aria-hidden="true" />
              Limpiar
            </button>
            <button
              type="button"
              onClick={() => setFiltersExpanded((current) => !current)}
              className="inline-flex h-8 w-8 items-center justify-center rounded border border-borderSoft bg-white text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20"
              aria-expanded={filtersExpanded}
              aria-controls="stock-movement-advanced-filters"
              aria-label={filtersExpanded ? "Contraer filtros" : "Expandir filtros"}
              title={filtersExpanded ? "Contraer filtros" : "Expandir filtros"}
            >
              {filtersExpanded ? <ChevronUp className="h-4 w-4" aria-hidden="true" /> : <ChevronDown className="h-4 w-4" aria-hidden="true" />}
            </button>
          </div>
          {filtersExpanded ? (
            <div id="stock-movement-advanced-filters" className="mt-2 grid gap-2 border-t border-borderSoft pt-2 md:grid-cols-4 xl:grid-cols-6">
              <label className="grid min-w-0 gap-1 text-[11px] font-semibold text-secondaryText md:col-span-2">
                Busqueda rapida
                <span className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-secondaryText" aria-hidden="true" />
                  <input
                    value={filters.search}
                    onChange={(event) => updateFilter("search", event.target.value)}
                    className="h-8 w-full rounded border border-borderSoft bg-white pl-8 pr-2 text-[12px] font-medium text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                    placeholder="Articulo, documento, ubicacion o motivo"
                  />
                </span>
              </label>
              <TextFilter label="Almacen" value={filters.warehouse} onChange={(value) => updateFilter("warehouse", value)} placeholder="PR03DP" />
              <SelectFilter label="Tipo" value={filters.movementType} onChange={(value) => updateFilter("movementType", value)}>
                <option value="">Todos</option>
                {movementTypes.map((type) => (
                  <option key={type} value={type}>
                    {translateStatusLabel(type)}
                  </option>
                ))}
              </SelectFilter>
              <SelectFilter label="Direccion" value={filters.direction} onChange={(value) => updateFilter("direction", value)}>
                <option value="">Todas</option>
                <option value="increase">Entrada</option>
                <option value="decrease">Salida</option>
              </SelectFilter>
              <SelectFilter label="Estado stock" value={filters.stockState} onChange={(value) => updateFilter("stockState", value)}>
                <option value="">Todos</option>
                {stockStates.map((state) => (
                  <option key={state} value={state}>
                    {translateStatusLabel(state)}
                  </option>
                ))}
              </SelectFilter>
              <TextFilter label="Ubicacion" value={filters.location} onChange={(value) => updateFilter("location", value)} placeholder="PRE, RSV, DSP" />
              <TextFilter label="Lote" value={filters.lot} onChange={(value) => updateFilter("lot", value)} placeholder="Lote" />
              <TextFilter label="Tipo doc." value={filters.documentType} onChange={(value) => updateFilter("documentType", value)} placeholder="delivery_order" />
              <TextFilter label="Documento" value={filters.documentRef} onChange={(value) => updateFilter("documentRef", value)} placeholder="Referencia" />
            </div>
          ) : null}
        </section>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
            <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
              <ListTree className="h-4 w-4 text-primaryHover" aria-hidden="true" />
              {loading ? "Cargando..." : `${rows.length} movimientos`}
            </div>
            <div className="text-[11px] text-secondaryText">{entries.length} impactos de ledger</div>
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full min-w-[1540px] border-collapse text-left text-[12px]">
              <thead className="sticky top-0 z-10 bg-deep text-white">
                <tr>
                  <th className="w-[126px] px-2 py-2 font-semibold">Fecha</th>
                  <th className="w-[150px] px-2 py-2 font-semibold">Movimiento</th>
                  <th className="w-[136px] px-2 py-2 font-semibold">Direccion</th>
                  <th className="w-[140px] px-2 py-2 font-semibold">Articulo</th>
                  <th className="w-[96px] px-2 py-2 font-semibold">Almacen</th>
                  <th className="w-[360px] px-2 py-2 font-semibold">Flujo</th>
                  <th className="w-[110px] px-2 py-2 text-right font-semibold">Cantidad</th>
                  <th className="w-[140px] px-2 py-2 font-semibold">Responsable</th>
                  <th className="w-[260px] px-2 py-2 font-semibold">Documento</th>
                  <th className="w-[104px] px-2 py-2 font-semibold">Asiento</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const selected = row.id === selectedRow?.id;
                  return (
                    <tr
                      key={row.id}
                      onClick={() => setSelectedId(row.id)}
                      className={`cursor-pointer border-b border-borderSoft hover:bg-softStart ${selected ? "bg-blue-50 outline outline-1 outline-primary/30" : "bg-white"}`}
                    >
                      <td className="whitespace-nowrap px-2 py-1.5 font-mono text-primaryHover">{formatAppDateTime(row.postedAt, "-")}</td>
                      <td className="px-2 py-1.5">
                        <StatusBadge label={row.movementType} tone="info" />
                      </td>
                      <td className="px-2 py-1.5">
                        <span className="inline-flex items-center gap-2">
                          {directionIcon(row.direction)}
                          <StatusBadge label={directionLabel(row.direction)} tone={directionTone(row.direction)} />
                        </span>
                      </td>
                      <td className="px-2 py-1.5">
                        <div className="font-mono font-semibold text-night">{row.itemRef}</div>
                        <div className="text-[11px] text-secondaryText">Lote {compact(row.lotRef)}</div>
                      </td>
                      <td className="whitespace-nowrap px-2 py-1.5 font-mono font-semibold text-night">{row.warehouseRef}</td>
                      <td className="px-2 py-1.5 font-mono text-night">{flowText(row)}</td>
                      <td className="whitespace-nowrap px-2 py-1.5 text-right font-mono font-semibold text-night">{signedQuantity(row)}</td>
                      <td className="whitespace-nowrap px-2 py-1.5 font-mono text-secondaryText">{compact(row.responsible)}</td>
                      <td className="px-2 py-1.5">
                        <div className="font-semibold text-night">{documentTypeLabel(row.documentType)}</div>
                      </td>
                      <td className="whitespace-nowrap px-2 py-1.5 font-mono text-secondaryText">
                        {row.entries.length > 1 ? `${row.entries.length} impactos` : shortId(row.entries[0]?.id ?? "")}
                      </td>
                    </tr>
                  );
                })}
                {!rows.length && (
                  <tr>
                    <td colSpan={10} className="px-3 py-12 text-center text-[12px] text-secondaryText">
                      {loading ? "Cargando..." : "Sin movimientos."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {detailOpen ? (
        <aside className="min-h-0 overflow-hidden rounded border border-borderSoft bg-surface shadow-panel" aria-label="Detalle de movimiento de stock">
          <div className="flex min-h-11 items-start justify-between gap-3 border-b border-borderSoft px-3 py-2">
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase text-secondaryText">Detalle WMS</p>
              <h2 className="truncate font-mono text-[15px] font-semibold text-night">{selectedRow?.documentRef ?? "Sin seleccion"}</h2>
            </div>
            <button
              type="button"
              onClick={() => setDetailOpen(false)}
              className="h-8 rounded border border-borderSoft px-2 text-[12px] font-semibold text-night hover:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            >
              Cerrar
            </button>
          </div>
          {selectedRow ? (
            <div className="flex h-full min-h-0 flex-col overflow-auto p-3">
              <section className="grid gap-2 border-b border-borderSoft pb-3 text-[12px]">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge label={selectedRow.movementType} tone="info" />
                  <StatusBadge label={directionLabel(selectedRow.direction)} tone={directionTone(selectedRow.direction)} />
                  {selectedRow.entries.some((entry) => entry.is_reversal) ? <StatusBadge label="reversal" tone="warning" /> : null}
                </div>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
                  <dt className="font-semibold text-secondaryText">Fecha</dt>
                  <dd className="font-mono text-night">{formatAppDateTime(selectedRow.postedAt, "-")}</dd>
                  <dt className="font-semibold text-secondaryText">Articulo</dt>
                  <dd className="font-mono text-night">{selectedRow.itemRef}</dd>
                  <dt className="font-semibold text-secondaryText">Almacen</dt>
                  <dd className="font-mono text-night">{selectedRow.warehouseRef}</dd>
                  <dt className="font-semibold text-secondaryText">Cantidad</dt>
                  <dd className="font-mono text-night">{signedQuantity(selectedRow)}</dd>
                  <dt className="font-semibold text-secondaryText">Documento</dt>
                  <dd className="break-all font-mono text-night">{selectedRow.documentRef}</dd>
                  <dt className="font-semibold text-secondaryText">Tipo doc.</dt>
                  <dd className="text-night">{documentTypeLabel(selectedRow.documentType)}</dd>
                  <dt className="font-semibold text-secondaryText">Responsable</dt>
                  <dd className="font-mono text-night">{compact(selectedRow.responsible)}</dd>
                  <dt className="font-semibold text-secondaryText">Flujo</dt>
                  <dd className="col-span-1 font-mono text-night">{flowText(selectedRow)}</dd>
                </dl>
              </section>

              <section className="min-h-0 py-3" aria-label="Impactos ledger del movimiento">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="text-[12px] font-semibold text-night">Impactos ledger</div>
                  <StatusBadge label={`${selectedRow.entries.length} asientos`} tone={selectedRow.entries.length > 1 ? "info" : "neutral"} />
                </div>
                <div className="overflow-auto rounded border border-borderSoft">
                  <table className="w-full min-w-[820px] border-collapse text-left text-[12px]">
                    <thead className="bg-softMid text-secondaryText">
                      <tr>
                        <th className="px-2 py-2 font-semibold">Fecha</th>
                        <th className="px-2 py-2 font-semibold">Direccion</th>
                        <th className="px-2 py-2 font-semibold">Estado</th>
                        <th className="px-2 py-2 font-semibold">Ubicacion</th>
                        <th className="px-2 py-2 text-right font-semibold">Cantidad</th>
                        <th className="px-2 py-2 font-semibold">Responsable</th>
                        <th className="px-2 py-2 font-semibold">Asiento</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedRow.entries.map((entry) => (
                        <tr key={entry.id} className="border-t border-borderSoft bg-white">
                          <td className="whitespace-nowrap px-2 py-2 font-mono text-primaryHover">{formatAppDateTime(entry.posted_at, "-")}</td>
                          <td className="px-2 py-2">
                            <StatusBadge label={entry.direction} tone={entry.direction === "increase" ? "success" : "warning"} />
                          </td>
                          <td className="whitespace-nowrap px-2 py-2 text-night">{translateStatusLabel(entry.stock_state)}</td>
                          <td className="whitespace-nowrap px-2 py-2 font-mono text-night">{compact(entry.location_ref)}</td>
                          <td className="whitespace-nowrap px-2 py-2 text-right font-mono font-semibold text-night">
                            {entry.direction === "increase" ? "+" : "-"}
                            {formatQuantity(entry.quantity, entry.uom)}
                          </td>
                          <td className="whitespace-nowrap px-2 py-2 font-mono text-secondaryText">{responsibleUser(entry.created_by)}</td>
                          <td className="whitespace-nowrap px-2 py-2 font-mono text-secondaryText">{shortId(entry.id)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="grid gap-2 border-t border-borderSoft pt-3 text-[12px]">
                <div className="text-[12px] font-semibold text-night">Auditoria</div>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
                  <dt className="font-semibold text-secondaryText">Usuario</dt>
                  <dd className="font-mono text-night">{compact(selectedRow.responsible)}</dd>
                  <dt className="font-semibold text-secondaryText">Motivo</dt>
                  <dd className="text-night">{compact(selectedRow.entries.find((entry) => entry.reason)?.reason)}</dd>
                  <dt className="font-semibold text-secondaryText">Transaccion</dt>
                  <dd className="break-all font-mono text-night">{compact(selectedRow.entries.find((entry) => entry.legacy_transaction_number)?.legacy_transaction_number)}</dd>
                  <dt className="font-semibold text-secondaryText">Pedido legacy</dt>
                  <dd className="break-all font-mono text-night">{compact(selectedRow.entries.find((entry) => entry.legacy_sales_order_number)?.legacy_sales_order_number)}</dd>
                </dl>
              </section>
            </div>
          ) : (
            <div className="flex h-full min-h-64 items-center justify-center px-6 text-center text-[12px] text-secondaryText">Sin renglon seleccionado.</div>
          )}
        </aside>
      ) : null}
    </div>
  );
}
