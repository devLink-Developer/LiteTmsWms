import { ArrowRightLeft, Calculator, PackageSearch, Plus, RefreshCw, Send, Trash2, Warehouse } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  createInventoryExchange,
  fetchInventoryExchanges,
  fetchInventoryStockReport,
  type InventoryExchange,
  type InventoryStockReportRow,
} from "../../api/inventory";
import { newIdempotencyKey } from "../../api/client";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { notify } from "../../shared/components/toast";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";
import type { StatusTone } from "../../types/operations";

type SourceForm = {
  warehouseRef: string;
  itemRef: string;
  quantity: string;
  uom: string;
  locationRef: string;
  lotRef: string;
  reason: string;
};

type OutputForm = {
  clientId: string;
  itemRef: string;
  quantity: string;
  uom: string;
  inputConversionFactor: string;
  locationRef: string;
  lotRef: string;
};

const exchangeTone: Record<string, StatusTone> = {
  posted: "success",
  draft: "neutral",
  cancelled: "danger",
};

function emptyOutput(): OutputForm {
  return {
    clientId: newIdempotencyKey(),
    itemRef: "",
    quantity: "",
    uom: "UN",
    inputConversionFactor: "",
    locationRef: "",
    lotRef: "",
  };
}

function asNumber(value: string | number | undefined) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatNumber(value: string | number | undefined) {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 3 }).format(asNumber(value));
}

function rowLocation(row: InventoryStockReportRow) {
  return row.warehouse_location_ref || row.location_ref || "";
}

function sourceLocation(row: InventoryStockReportRow) {
  return row.location_ref || "";
}

function packedQty(row: InventoryStockReportRow) {
  return asNumber(row.quantities?.packed);
}

function trim(value: string) {
  return value.trim();
}

function exchangeQuantity(exchange: InventoryExchange, role: "input" | "output") {
  return exchange.lines?.filter((line) => line.role === role).reduce((total, line) => total + asNumber(line.quantity), 0) ?? 0;
}

export function InventoryExchangePage() {
  const { warehouseRef, authorizedWarehouses } = useWorkspaceStore();
  const activeWarehouse = warehouseRef || authorizedWarehouses[0] || "";
  const [source, setSource] = useState<SourceForm>({
    warehouseRef: activeWarehouse,
    itemRef: "",
    quantity: "",
    uom: "UN",
    locationRef: "",
    lotRef: "",
    reason: "Canje lote a saldo",
  });
  const [outputs, setOutputs] = useState<OutputForm[]>([emptyOutput()]);
  const [stockRows, setStockRows] = useState<InventoryStockReportRow[]>([]);
  const [exchanges, setExchanges] = useState<InventoryExchange[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [posting, setPosting] = useState(false);
  const submitKeyRef = useRef(newIdempotencyKey());

  const warehouse = trim(source.warehouseRef) || activeWarehouse;
  const selectedRow = stockRows.find((row) => row.id === selectedId) ?? stockRows[0];
  const consumedInput = outputs.reduce((total, output) => total + asNumber(output.quantity) * asNumber(output.inputConversionFactor), 0);
  const sourceQty = asNumber(source.quantity);
  const conservationDelta = sourceQty - consumedInput;
  const conserved = sourceQty > 0 && Math.abs(conservationDelta) <= 0.000001;

  useEffect(() => {
    if (activeWarehouse && !source.warehouseRef) {
      setSource((current) => ({ ...current, warehouseRef: activeWarehouse }));
    }
  }, [activeWarehouse, source.warehouseRef]);

  async function loadData() {
    if (!warehouse) {
      setStockRows([]);
      setExchanges([]);
      return;
    }
    setLoading(true);
    try {
      const [stockPayload, exchangePayload] = await Promise.all([
        fetchInventoryStockReport({ warehouse, state: "packed", search, locationScope: "available", limit: search ? 500 : 300 }),
        fetchInventoryExchanges({ warehouse, limit: 100 }),
      ]);
      const rows = (stockPayload.results ?? []).filter((row) => row.warehouse_ref === warehouse && packedQty(row) > 0);
      setStockRows(rows);
      setExchanges(exchangePayload.results ?? []);
      setSelectedId((current) => (current && rows.some((row) => row.id === current) ? current : rows[0]?.id ?? ""));
    } catch (apiError) {
      setStockRows([]);
      setExchanges([]);
      setSelectedId("");
      notify({ message: apiError instanceof Error ? apiError.message : "Canjes no cargados.", tone: "error" });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, [warehouse]);

  const visibleRows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return stockRows;
    return stockRows.filter((row) =>
      [row.item_ref, row.item_name, rowLocation(row), row.lot_ref, row.uom].some((value) => (value ?? "").toLowerCase().includes(needle)),
    );
  }, [search, stockRows]);

  function updateSource(key: keyof SourceForm, value: string) {
    setSource((current) => ({ ...current, [key]: value }));
  }

  function updateOutput(clientId: string, key: keyof Omit<OutputForm, "clientId">, value: string) {
    setOutputs((current) => current.map((line) => (line.clientId === clientId ? { ...line, [key]: value } : line)));
  }

  function selectSource(row: InventoryStockReportRow) {
    setSelectedId(row.id);
    setSource((current) => ({
      ...current,
      warehouseRef: row.warehouse_ref,
      itemRef: row.item_ref,
      quantity: current.quantity || String(packedQty(row)),
      uom: row.uom,
      locationRef: sourceLocation(row),
      lotRef: row.lot_ref || "",
    }));
  }

  async function submitExchange() {
    const validOutputs = outputs
      .map((output) => ({
        item_ref: trim(output.itemRef),
        quantity: trim(output.quantity),
        uom: trim(output.uom) || source.uom || "UN",
        input_conversion_factor: trim(output.inputConversionFactor),
        location_ref: trim(output.locationRef) || trim(source.locationRef),
        lot_ref: trim(output.lotRef),
      }))
      .filter((output) => output.item_ref || output.quantity || output.input_conversion_factor);

    if (!warehouse || !trim(source.itemRef) || !trim(source.locationRef)) {
      notify({ message: "Origen con almacen, articulo y ubicacion requerido.", tone: "error" });
      return;
    }
    if (sourceQty <= 0) {
      notify({ message: "Cantidad origen invalida.", tone: "error" });
      return;
    }
    if (!validOutputs.length || validOutputs.some((output) => !output.item_ref || asNumber(output.quantity) <= 0 || asNumber(output.input_conversion_factor) <= 0)) {
      notify({ message: "Cada salida requiere articulo, cantidad y factor positivo.", tone: "error" });
      return;
    }
    if (!conserved) {
      notify({ message: "El canje no conserva cantidad segun los factores.", tone: "error" });
      return;
    }

    setPosting(true);
    try {
      const exchange = await createInventoryExchange(
        {
          warehouse_ref: warehouse,
          reason: trim(source.reason) || "Canje lote a saldo",
          input: {
            item_ref: trim(source.itemRef),
            quantity: trim(source.quantity),
            uom: trim(source.uom) || "UN",
            location_ref: trim(source.locationRef),
            lot_ref: trim(source.lotRef),
          },
          outputs: validOutputs,
        },
        submitKeyRef.current,
      );
      notify({ message: `Canje ${exchange.conversion_group_id || exchange.id} posteado.`, tone: "success" });
      submitKeyRef.current = newIdempotencyKey();
      setSource((current) => ({ ...current, itemRef: "", quantity: "", lotRef: "" }));
      setOutputs([emptyOutput()]);
      await loadData();
    } catch (apiError) {
      notify({ message: apiError instanceof Error ? apiError.message : "Canje no posteado.", tone: "error" });
    } finally {
      setPosting(false);
    }
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-2 overflow-hidden p-2 xl:grid-cols-[minmax(0,1fr)_360px]">
      <section className="flex min-h-0 min-w-0 flex-col gap-2 overflow-hidden">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <h1 className="text-[18px] font-semibold text-night">Canje lote a saldo</h1>
          </div>
          <button
            type="button"
            onClick={() => void loadData()}
            disabled={loading || !warehouse}
            className="inline-flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
            Actualizar
          </button>
        </header>

        <section className="grid shrink-0 grid-cols-2 gap-2 lg:grid-cols-4" aria-label="Indicadores de canje">
          <div className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase text-secondaryText">Origen</span>
              <StatusBadge label="packed" tone={source.itemRef ? "success" : "neutral"} />
            </div>
            <div className="mt-1 truncate font-mono text-[20px] font-semibold leading-6 text-night">{source.itemRef || "-"}</div>
          </div>
          <div className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase text-secondaryText">Cantidad</span>
              <StatusBadge label={source.uom || "UN"} tone="info" />
            </div>
            <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{formatNumber(sourceQty)}</div>
          </div>
          <div className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase text-secondaryText">Consumido</span>
              <StatusBadge label={conserved ? "conserva" : "revision"} tone={conserved ? "success" : "warning"} />
            </div>
            <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{formatNumber(consumedInput)}</div>
          </div>
          <div className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase text-secondaryText">Canjes</span>
              <StatusBadge label="historial" tone="neutral" />
            </div>
            <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{exchanges.length}</div>
          </div>
        </section>

        <section className="grid shrink-0 gap-2 rounded border border-borderSoft bg-softMid p-2 shadow-panel md:grid-cols-[120px_minmax(160px,1fr)_110px_80px_minmax(160px,1fr)_110px]" aria-label="Origen de canje">
          <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
            Almacen
            <input value={source.warehouseRef} onChange={(event) => updateSource("warehouseRef", event.target.value)} className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
          </label>
          <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
            Articulo origen
            <input value={source.itemRef} onChange={(event) => updateSource("itemRef", event.target.value)} className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
          </label>
          <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
            Cantidad
            <input value={source.quantity} onChange={(event) => updateSource("quantity", event.target.value)} inputMode="decimal" className="h-9 rounded border border-borderSoft bg-white px-2 text-right font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
          </label>
          <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
            UOM
            <input value={source.uom} onChange={(event) => updateSource("uom", event.target.value)} className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
          </label>
          <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
            Ubicacion origen
            <input value={source.locationRef} onChange={(event) => updateSource("locationRef", event.target.value)} className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
          </label>
          <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
            Lote
            <input value={source.lotRef} onChange={(event) => updateSource("lotRef", event.target.value)} className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
          </label>
        </section>

        <section className="grid min-h-0 flex-1 grid-cols-1 gap-2 overflow-hidden xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="flex min-h-0 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
            <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
              <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
                <PackageSearch className="h-4 w-4 text-primaryHover" aria-hidden="true" />
                {loading ? "Cargando..." : `${visibleRows.length} buckets origen`}
              </div>
              <input
                aria-label="Buscar stock origen"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                onBlur={() => void loadData()}
                className="h-7 w-40 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                placeholder="Buscar"
              />
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
              <table className="w-full min-w-[620px] border-collapse text-left text-[12px]">
                <thead className="sticky top-0 z-10 bg-deep text-white">
                  <tr>
                    <th className="px-3 py-2 font-semibold">Ubicacion</th>
                    <th className="px-3 py-2 font-semibold">Articulo</th>
                    <th className="px-3 py-2 font-semibold">Lote</th>
                    <th className="px-3 py-2 text-right font-semibold">Packed</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((row) => (
                    <tr
                      key={row.id}
                      onClick={() => selectSource(row)}
                      className={`cursor-pointer border-b border-borderSoft hover:bg-softStart ${row.id === selectedRow?.id ? "bg-blue-50 outline outline-1 outline-primary/30" : "bg-white"}`}
                    >
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{rowLocation(row) || "-"}</td>
                      <td className="px-3 py-2">
                        <div className="font-mono font-semibold text-night">{row.item_ref}</div>
                        {row.item_name ? <div className="max-w-[280px] truncate text-[11px] text-secondaryText">{row.item_name}</div> : null}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-secondaryText">{row.lot_ref || "-"}</td>
                      <td className="px-3 py-2 text-right font-mono font-semibold text-night">{formatNumber(packedQty(row))} {row.uom}</td>
                    </tr>
                  ))}
                  {!visibleRows.length ? (
                    <tr>
                      <td colSpan={4} className="px-3 py-10 text-center text-[12px] text-secondaryText">
                        {loading ? "Cargando..." : "Sin stock packed."}
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>

          <div className="flex min-h-0 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
            <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
              <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
                <ArrowRightLeft className="h-4 w-4 text-primaryHover" aria-hidden="true" />
                Salidas
              </div>
              <button type="button" onClick={() => setOutputs((current) => [...current, emptyOutput()])} className="inline-flex min-h-7 items-center gap-1 rounded border border-borderSoft bg-white px-2 text-[11px] font-semibold text-night transition hover:border-primary hover:text-primaryHover">
                <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                Agregar
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
              <table className="w-full min-w-[780px] border-collapse text-left text-[12px]">
                <thead className="sticky top-0 z-10 bg-deep text-white">
                  <tr>
                    <th className="w-[180px] px-3 py-2 font-semibold">Articulo destino</th>
                    <th className="w-[100px] px-3 py-2 text-right font-semibold">Cantidad</th>
                    <th className="w-[70px] px-3 py-2 font-semibold">UOM</th>
                    <th className="w-[110px] px-3 py-2 text-right font-semibold">Factor</th>
                    <th className="w-[160px] px-3 py-2 font-semibold">Ubicacion</th>
                    <th className="w-[120px] px-3 py-2 font-semibold">Lote</th>
                    <th className="w-[54px] px-3 py-2 text-right font-semibold">Quitar</th>
                  </tr>
                </thead>
                <tbody>
                  {outputs.map((output, index) => (
                    <tr key={output.clientId} className="border-b border-borderSoft bg-white">
                      <td className="px-3 py-2">
                        <input aria-label={`Articulo destino linea ${index + 1}`} value={output.itemRef} onChange={(event) => updateOutput(output.clientId, "itemRef", event.target.value)} className="h-8 w-full rounded border border-borderSoft px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
                      </td>
                      <td className="px-3 py-2">
                        <input aria-label={`Cantidad destino linea ${index + 1}`} value={output.quantity} onChange={(event) => updateOutput(output.clientId, "quantity", event.target.value)} inputMode="decimal" className="h-8 w-full rounded border border-borderSoft px-2 text-right font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
                      </td>
                      <td className="px-3 py-2">
                        <input aria-label={`Unidad destino linea ${index + 1}`} value={output.uom} onChange={(event) => updateOutput(output.clientId, "uom", event.target.value)} className="h-8 w-full rounded border border-borderSoft px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
                      </td>
                      <td className="px-3 py-2">
                        <input aria-label={`Factor linea ${index + 1}`} value={output.inputConversionFactor} onChange={(event) => updateOutput(output.clientId, "inputConversionFactor", event.target.value)} inputMode="decimal" className="h-8 w-full rounded border border-borderSoft px-2 text-right font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" placeholder="0.04" />
                      </td>
                      <td className="px-3 py-2">
                        <input aria-label={`Ubicacion destino linea ${index + 1}`} value={output.locationRef} onChange={(event) => updateOutput(output.clientId, "locationRef", event.target.value)} className="h-8 w-full rounded border border-borderSoft px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" placeholder={source.locationRef || "destino"} />
                      </td>
                      <td className="px-3 py-2">
                        <input aria-label={`Lote destino linea ${index + 1}`} value={output.lotRef} onChange={(event) => updateOutput(output.clientId, "lotRef", event.target.value)} className="h-8 w-full rounded border border-borderSoft px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button type="button" onClick={() => setOutputs((current) => (current.length > 1 ? current.filter((line) => line.clientId !== output.clientId) : current))} disabled={outputs.length === 1} className="inline-flex h-8 w-8 items-center justify-center rounded border border-borderSoft bg-white text-secondaryText transition hover:border-red-300 hover:text-red-700 disabled:bg-softStart" aria-label={`Quitar salida ${index + 1}`}>
                          <Trash2 className="h-4 w-4" aria-hidden="true" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </section>

      <aside className="min-h-0 overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
        <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
            <Calculator className="h-4 w-4 text-primaryHover" aria-hidden="true" />
            Validacion
          </div>
          <StatusBadge label={conserved ? "conserva" : "pendiente"} tone={conserved ? "success" : "warning"} />
        </div>
        <div className="flex h-full min-h-0 flex-col overflow-auto p-3">
          <section className="grid gap-2 border-b border-borderSoft pb-3 text-[12px]">
            <div className="rounded border border-borderSoft bg-softMid px-2 py-2">
              <div className="flex items-center gap-2 text-[11px] font-semibold text-secondaryText">
                <Warehouse className="h-4 w-4" aria-hidden="true" />
                Ubicacion origen
              </div>
              <div className="mt-1 font-mono font-semibold text-night">{source.locationRef || "-"}</div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded border border-borderSoft bg-white px-2 py-2">
                <div className="text-[11px] font-semibold text-secondaryText">Input</div>
                <div className="mt-1 font-mono font-semibold text-night">{formatNumber(sourceQty)}</div>
              </div>
              <div className="rounded border border-borderSoft bg-white px-2 py-2">
                <div className="text-[11px] font-semibold text-secondaryText">Factorizado</div>
                <div className="mt-1 font-mono font-semibold text-night">{formatNumber(consumedInput)}</div>
              </div>
            </div>
            <div className={`rounded border px-2 py-2 ${conserved ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
              <div className="text-[11px] font-semibold text-secondaryText">Diferencia</div>
              <div className="mt-1 font-mono text-[18px] font-semibold text-night">{formatNumber(conservationDelta)}</div>
            </div>
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Motivo
              <textarea value={source.reason} onChange={(event) => updateSource("reason", event.target.value)} className="min-h-20 rounded border border-borderSoft bg-white px-2 py-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
            </label>
            <button type="button" onClick={() => void submitExchange()} disabled={posting || !warehouse} className="inline-flex min-h-10 items-center justify-center gap-2 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:bg-slate-300">
              <Send className="h-4 w-4" aria-hidden="true" />
              {posting ? "Posteando..." : "Confirmar canje"}
            </button>
          </section>

          <section className="min-h-0 py-3">
            <div className="mb-2 text-[12px] font-semibold text-night">Canjes recientes</div>
            <div className="grid gap-2">
              {exchanges.slice(0, 10).map((exchange) => (
                <div key={exchange.id} className="rounded border border-borderSoft bg-white px-2 py-2 text-[12px]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono font-semibold text-night">{exchange.conversion_group_id || exchange.id}</span>
                    <StatusBadge label={exchange.status} tone={exchangeTone[exchange.status] ?? "neutral"} />
                  </div>
                  <div className="mt-1 font-mono text-[11px] text-secondaryText">
                    {formatNumber(exchangeQuantity(exchange, "input"))} input / {formatNumber(exchangeQuantity(exchange, "output"))} output
                  </div>
                  <div className="mt-1 text-[11px] text-secondaryText">{exchange.reason || "sin motivo"}</div>
                </div>
              ))}
              {!exchanges.length ? <div className="rounded border border-borderSoft bg-softMid px-3 py-2 text-[12px] text-secondaryText">Sin canjes registrados.</div> : null}
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}
