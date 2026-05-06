import { AlertTriangle, ClipboardList, FilterX, PackageX, RefreshCw, Search, Send, Warehouse } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fetchInventoryStockReport, type InventoryStockReportRow } from "../../api/inventory";
import { createWriteOff, fetchWriteOffs, type WriteOffRecord } from "../../api/writeOffs";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { notify } from "../../shared/components/toast";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";

type FormState = {
  quantity: string;
  reasonCode: "breakage" | "loss";
  reason: string;
};

const emptyForm: FormState = {
  quantity: "",
  reasonCode: "breakage",
  reason: "",
};

function asNumber(value: string | number | undefined) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatNumber(value: string | number | undefined) {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 3 }).format(asNumber(value));
}

function rowDisplayLocation(row: InventoryStockReportRow) {
  return row.warehouse_location_ref || row.location_ref || "";
}

function rowSourceLocation(row: InventoryStockReportRow) {
  return row.location_ref || "";
}

function packedQty(row: InventoryStockReportRow) {
  return asNumber(row.quantities?.packed);
}

function writeOffQuantity(row: WriteOffRecord) {
  return row.lines?.reduce((total, line) => total + asNumber(line.posted_qty || line.quantity), 0) ?? asNumber(row.quantity);
}

export function BreakagesLossesPage() {
  const { warehouseRef, authorizedWarehouses } = useWorkspaceStore();
  const [rows, setRows] = useState<InventoryStockReportRow[]>([]);
  const [writeOffs, setWriteOffs] = useState<WriteOffRecord[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [search, setSearch] = useState("");
  const [form, setForm] = useState<FormState>(emptyForm);
  const [loading, setLoading] = useState(false);
  const [posting, setPosting] = useState(false);

  const activeWarehouse = warehouseRef || authorizedWarehouses[0] || "";

  async function loadData() {
    if (!activeWarehouse) {
      setRows([]);
      setWriteOffs([]);
      return;
    }
    setLoading(true);
    try {
      const [stockPayload, writeOffPayload] = await Promise.all([
        fetchInventoryStockReport({ warehouse: activeWarehouse, state: "packed", search, limit: search ? 500 : 300 }),
        fetchWriteOffs({ warehouse: activeWarehouse, limit: 100 }),
      ]);
      const stockRows = (stockPayload.results ?? []).filter((row) => row.warehouse_ref === activeWarehouse && packedQty(row) > 0);
      setRows(stockRows);
      setWriteOffs(writeOffPayload.results ?? []);
      setSelectedId((current) => (current && stockRows.some((row) => row.id === current) ? current : stockRows[0]?.id ?? ""));
    } catch (apiError) {
      setRows([]);
      setWriteOffs([]);
      setSelectedId("");
      notify({ message: apiError instanceof Error ? apiError.message : "Roturas no cargadas.", tone: "error" });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, [activeWarehouse]);

  const visibleRows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) =>
      [row.item_ref, row.item_name, rowDisplayLocation(row), row.lot_ref, row.uom].some((value) => (value ?? "").toLowerCase().includes(needle)),
    );
  }, [rows, search]);
  const selectedRow = visibleRows.find((row) => row.id === selectedId) ?? visibleRows[0];
  const selectedAvailable = selectedRow ? packedQty(selectedRow) : 0;
  const postedQty = writeOffs.reduce((total, row) => total + writeOffQuantity(row), 0);

  function updateForm(key: keyof FormState, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function submitWriteOff() {
    if (!selectedRow) {
      notify({ message: "Sin stock seleccionado.", tone: "error" });
      return;
    }
    const quantity = asNumber(form.quantity);
    if (quantity <= 0) {
      notify({ message: "Cantidad invalida.", tone: "error" });
      return;
    }
    if (quantity > selectedAvailable) {
      notify({ message: "Stock insuficiente.", tone: "error" });
      return;
    }
    if (!form.reason.trim()) {
      notify({ message: "Motivo requerido.", tone: "error" });
      return;
    }
    setPosting(true);
    try {
      const result = await createWriteOff({
        warehouse_ref: activeWarehouse,
        reason_code: form.reasonCode,
        reason: form.reason,
        source_location_ref: rowSourceLocation(selectedRow),
        lines: [
          {
            item_ref: selectedRow.item_ref,
            quantity: form.quantity,
            uom: selectedRow.uom,
            lot_ref: selectedRow.lot_ref || "",
          },
        ],
      });
      notify({ message: `${result.write_off_number ?? "Baja"} posteada.`, tone: "success" });
      setForm(emptyForm);
      await loadData();
    } catch (apiError) {
      notify({ message: apiError instanceof Error ? apiError.message : "Baja no posteada.", tone: "error" });
    } finally {
      setPosting(false);
    }
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-2 overflow-hidden p-2 xl:grid-cols-[minmax(0,1fr)_340px]">
      <section className="flex min-h-0 min-w-0 flex-col gap-2 overflow-hidden">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <h1 className="text-[18px] font-semibold text-night">Roturas y perdidas</h1>
          </div>
          <button
            type="button"
            onClick={() => void loadData()}
            disabled={loading}
            className="inline-flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
            Actualizar
          </button>
        </header>

        <section className="grid shrink-0 grid-cols-2 gap-2 lg:grid-cols-4" aria-label="Indicadores de roturas y perdidas">
          <div className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase text-secondaryText">Almacen</span>
              <StatusBadge label="activo" tone={activeWarehouse ? "success" : "danger"} />
            </div>
            <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{activeWarehouse || "-"}</div>
          </div>
          <div className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase text-secondaryText">Stock afectable</span>
              <StatusBadge label="packed" tone="info" />
            </div>
            <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{visibleRows.length}</div>
          </div>
          <div className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase text-secondaryText">Posteadas</span>
              <StatusBadge label="historial" tone="neutral" />
            </div>
            <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{writeOffs.length}</div>
          </div>
          <div className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase text-secondaryText">Cantidad baja</span>
              <StatusBadge label="scrapped" tone={postedQty ? "danger" : "neutral"} />
            </div>
            <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{formatNumber(postedQty)}</div>
          </div>
        </section>

        <section className="shrink-0 rounded border border-borderSoft bg-softMid p-2 shadow-panel" aria-label="Filtros de stock para baja">
          <div className="grid gap-2 md:grid-cols-[minmax(260px,1fr)_auto]">
            <label className="grid min-w-0 gap-1 text-[11px] font-semibold text-secondaryText">
              Buscar stock
              <span className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-secondaryText" aria-hidden="true" />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  className="h-8 w-full rounded border border-borderSoft bg-white pl-8 pr-2 text-[12px] font-medium text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                  placeholder="Articulo, ubicacion o lote"
                />
              </span>
            </label>
            <button
              type="button"
              onClick={() => {
                setSearch("");
                void loadData();
              }}
              className="inline-flex min-h-8 items-end justify-center gap-2 self-end rounded border border-borderSoft bg-white px-3 pb-1.5 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20"
            >
              <FilterX className="h-4 w-4" aria-hidden="true" />
              Limpiar
            </button>
          </div>
        </section>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
            <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
              <PackageX className="h-4 w-4 text-primaryHover" aria-hidden="true" />
              {loading ? "Cargando..." : `${visibleRows.length} buckets disponibles`}
            </div>
            <div className="text-[11px] text-secondaryText">PACKED</div>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full min-w-[820px] border-collapse text-left text-[12px]">
              <thead className="sticky top-0 z-10 bg-deep text-white">
                <tr>
                  <th className="w-[130px] px-3 py-2 font-semibold">Ubicacion</th>
                  <th className="px-3 py-2 font-semibold">Producto</th>
                  <th className="w-[100px] px-3 py-2 font-semibold">Lote</th>
                  <th className="w-[120px] px-3 py-2 text-right font-semibold">Disponible</th>
                  <th className="w-[70px] px-3 py-2 font-semibold">UOM</th>
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
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{rowDisplayLocation(row) || "-"}</td>
                      <td className="px-3 py-2">
                        <div className="font-mono font-semibold text-night">{row.item_ref}</div>
                        {row.item_name ? <div className="max-w-[320px] truncate text-[11px] text-secondaryText">{row.item_name}</div> : null}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-secondaryText">{row.lot_ref || "-"}</td>
                      <td className="px-3 py-2 text-right font-mono font-semibold text-night">{formatNumber(packedQty(row))}</td>
                      <td className="px-3 py-2 font-mono text-secondaryText">{row.uom}</td>
                    </tr>
                  );
                })}
                {!visibleRows.length && (
                  <tr>
                    <td colSpan={5} className="px-3 py-10 text-center text-[12px] text-secondaryText">
                      {loading ? "Cargando..." : "Sin stock."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <aside className="min-h-0 overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
        <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
            <ClipboardList className="h-4 w-4 text-primaryHover" aria-hidden="true" />
            Registrar baja
          </div>
          <StatusBadge label="impacta stock" tone="danger" />
        </div>
        <div className="flex h-full min-h-0 flex-col overflow-auto p-3">
          {selectedRow ? (
            <section className="grid gap-2 border-b border-borderSoft pb-3 text-[12px]">
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded border border-borderSoft bg-softMid px-2 py-2">
                  <div className="flex items-center gap-2 text-[11px] font-semibold text-secondaryText">
                    <Warehouse className="h-4 w-4" aria-hidden="true" />
                    Origen
                  </div>
                  <div className="mt-1 font-mono font-semibold text-night">{rowDisplayLocation(selectedRow) || "-"}</div>
                </div>
                <div className="rounded border border-borderSoft bg-softMid px-2 py-2">
                  <div className="text-[11px] font-semibold text-secondaryText">Disponible</div>
                  <div className="mt-1 font-mono font-semibold text-night">
                    {formatNumber(selectedAvailable)} {selectedRow.uom}
                  </div>
                </div>
              </div>
              <div>
                <div className="font-mono text-[14px] font-semibold text-night">{selectedRow.item_ref}</div>
                {selectedRow.item_name ? <div className="text-secondaryText">{selectedRow.item_name}</div> : null}
              </div>
            </section>
          ) : (
            <div className="mb-3 flex min-h-24 items-center justify-center rounded border border-borderSoft bg-softMid px-4 text-center text-[12px] text-secondaryText">
              Sin renglon seleccionado.
            </div>
          )}

          <section className="grid gap-3 border-b border-borderSoft py-3">
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Tipo
              <select
                value={form.reasonCode}
                onChange={(event) => updateForm("reasonCode", event.target.value)}
                className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
              >
                <option value="breakage">Rotura</option>
                <option value="loss">Perdida</option>
              </select>
            </label>
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Cantidad
              <input
                value={form.quantity}
                onChange={(event) => updateForm("quantity", event.target.value)}
                inputMode="decimal"
                className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                placeholder="0"
              />
            </label>
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Motivo
              <textarea
                value={form.reason}
                onChange={(event) => updateForm("reason", event.target.value)}
                className="min-h-24 rounded border border-borderSoft bg-white px-2 py-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                placeholder="Detalle operativo"
              />
            </label>
            <button
              type="button"
              onClick={() => void submitWriteOff()}
              disabled={posting || !selectedRow || !activeWarehouse}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:bg-slate-300"
            >
              <Send className="h-4 w-4" aria-hidden="true" />
              {posting ? "Posteando..." : "Confirmar baja"}
            </button>
          </section>

          <section className="min-h-0 py-3">
            <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold text-night">
              <AlertTriangle className="h-4 w-4 text-primaryHover" aria-hidden="true" />
              Historial reciente
            </div>
            <div className="grid gap-2">
              {writeOffs.slice(0, 8).map((row) => (
                <div key={row.id} className="rounded border border-borderSoft bg-white px-2 py-2 text-[12px]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono font-semibold text-night">{row.write_off_number ?? row.id}</span>
                    <StatusBadge label={row.reason_code === "loss" ? "perdida" : "rotura"} tone={row.reason_code === "loss" ? "warning" : "danger"} />
                  </div>
                  <div className="mt-1 text-secondaryText">{row.reason}</div>
                  <div className="mt-1 font-mono text-[11px] text-secondaryText">
                    {formatNumber(writeOffQuantity(row))} unidades / {row.target_location_ref || row.location_ref || "-"}
                  </div>
                </div>
              ))}
              {!writeOffs.length ? (
                <div className="rounded border border-borderSoft bg-softMid px-3 py-2 text-[12px] text-secondaryText">Sin bajas registradas.</div>
              ) : null}
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}
