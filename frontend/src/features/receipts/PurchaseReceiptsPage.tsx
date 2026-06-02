import { ClipboardList, PackagePlus, Plus, RefreshCw, Send, Trash2, Warehouse } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { createPurchaseReceipt, fetchPurchaseReceipts, type PurchaseReceipt } from "../../api/inventory";
import { newIdempotencyKey } from "../../api/client";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { notify } from "../../shared/components/toast";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";
import type { StatusTone } from "../../types/operations";

type ReceiptLineForm = {
  clientId: string;
  itemRef: string;
  expectedQty: string;
  receivedQty: string;
  uom: string;
  locationRef: string;
  lotRef: string;
};

type ReceiptForm = {
  warehouseRef: string;
  purchaseOrderRef: string;
  supplierRef: string;
  targetLocationRef: string;
  reason: string;
};

const statusTone: Record<string, StatusTone> = {
  received: "success",
  partial_received: "warning",
  with_incident: "warning",
  receiving: "info",
  draft: "neutral",
  cancelled: "danger",
};

function emptyLine(): ReceiptLineForm {
  return {
    clientId: newIdempotencyKey(),
    itemRef: "",
    expectedQty: "",
    receivedQty: "",
    uom: "UN",
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

function receiptQuantity(receipt: PurchaseReceipt) {
  return receipt.lines?.reduce((total, line) => total + asNumber(line.received_qty), 0) ?? 0;
}

function trim(value: string) {
  return value.trim();
}

export function PurchaseReceiptsPage() {
  const { warehouseRef, authorizedWarehouses } = useWorkspaceStore();
  const activeWarehouse = warehouseRef || authorizedWarehouses[0] || "";
  const [form, setForm] = useState<ReceiptForm>({
    warehouseRef: activeWarehouse,
    purchaseOrderRef: "",
    supplierRef: "",
    targetLocationRef: "",
    reason: "",
  });
  const [lines, setLines] = useState<ReceiptLineForm[]>([emptyLine()]);
  const [receipts, setReceipts] = useState<PurchaseReceipt[]>([]);
  const [loading, setLoading] = useState(false);
  const [posting, setPosting] = useState(false);
  const submitKeyRef = useRef(newIdempotencyKey());

  const warehouse = trim(form.warehouseRef) || activeWarehouse;
  const totalReceived = lines.reduce((total, line) => total + asNumber(line.receivedQty), 0);

  useEffect(() => {
    if (activeWarehouse && !form.warehouseRef) {
      setForm((current) => ({ ...current, warehouseRef: activeWarehouse }));
    }
  }, [activeWarehouse, form.warehouseRef]);

  async function loadReceipts() {
    if (!warehouse) {
      setReceipts([]);
      return;
    }
    setLoading(true);
    try {
      const payload = await fetchPurchaseReceipts({ warehouse, limit: 100 });
      setReceipts(payload.results ?? []);
    } catch (apiError) {
      setReceipts([]);
      notify({ message: apiError instanceof Error ? apiError.message : "Recepciones no cargadas.", tone: "error" });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadReceipts();
  }, [warehouse]);

  function updateForm(key: keyof ReceiptForm, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function updateLine(clientId: string, key: keyof Omit<ReceiptLineForm, "clientId">, value: string) {
    setLines((current) => current.map((line) => (line.clientId === clientId ? { ...line, [key]: value } : line)));
  }

  function removeLine(clientId: string) {
    setLines((current) => (current.length > 1 ? current.filter((line) => line.clientId !== clientId) : current));
  }

  async function submitReceipt() {
    const purchaseOrderRef = trim(form.purchaseOrderRef);
    const supplierRef = trim(form.supplierRef);
    const targetLocationRef = trim(form.targetLocationRef);
    const reason = trim(form.reason);
    const validLines = lines
      .map((line) => ({
        item_ref: trim(line.itemRef),
        expected_qty: trim(line.expectedQty),
        received_qty: trim(line.receivedQty),
        uom: trim(line.uom) || "UN",
        location_ref: trim(line.locationRef) || targetLocationRef,
        lot_ref: trim(line.lotRef),
      }))
      .filter((line) => line.item_ref || line.received_qty);

    if (!warehouse) {
      notify({ message: "Almacen requerido.", tone: "error" });
      return;
    }
    if (!purchaseOrderRef) {
      notify({ message: "OC requerida.", tone: "error" });
      return;
    }
    if (!validLines.length || validLines.some((line) => !line.item_ref || asNumber(line.received_qty) <= 0)) {
      notify({ message: "Cada renglon requiere articulo y cantidad recibida positiva.", tone: "error" });
      return;
    }

    setPosting(true);
    try {
      const receipt = await createPurchaseReceipt(
        {
          warehouse_ref: warehouse,
          purchase_order_ref: purchaseOrderRef,
          supplier_ref: supplierRef,
          target_location_ref: targetLocationRef,
          reason,
          lines: validLines,
        },
        submitKeyRef.current,
      );
      notify({ message: `OC ${receipt.purchase_order_ref} recibida.`, tone: "success" });
      submitKeyRef.current = newIdempotencyKey();
      setForm((current) => ({ ...current, purchaseOrderRef: "", supplierRef: "", reason: "" }));
      setLines([emptyLine()]);
      await loadReceipts();
    } catch (apiError) {
      notify({ message: apiError instanceof Error ? apiError.message : "Recepcion no posteada.", tone: "error" });
    } finally {
      setPosting(false);
    }
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-2 overflow-hidden p-2 xl:grid-cols-[minmax(0,1fr)_360px]">
      <section className="flex min-h-0 min-w-0 flex-col gap-2 overflow-hidden">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <h1 className="text-[18px] font-semibold text-night">Ingresos por OC</h1>
          </div>
          <button
            type="button"
            onClick={() => void loadReceipts()}
            disabled={loading || !warehouse}
            className="inline-flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
            Actualizar
          </button>
        </header>

        <section className="grid shrink-0 grid-cols-2 gap-2 lg:grid-cols-4" aria-label="Indicadores de recepcion">
          <div className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase text-secondaryText">Almacen</span>
              <StatusBadge label={warehouse ? "activo" : "sin scope"} tone={warehouse ? "success" : "danger"} />
            </div>
            <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{warehouse || "-"}</div>
          </div>
          <div className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase text-secondaryText">Lineas</span>
              <StatusBadge label="formulario" tone="info" />
            </div>
            <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{lines.length}</div>
          </div>
          <div className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase text-secondaryText">Cantidad</span>
              <StatusBadge label="packed" tone={totalReceived ? "success" : "neutral"} />
            </div>
            <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{formatNumber(totalReceived)}</div>
          </div>
          <div className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase text-secondaryText">Recepciones</span>
              <StatusBadge label="historial" tone="neutral" />
            </div>
            <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{receipts.length}</div>
          </div>
        </section>

        <section className="shrink-0 rounded border border-borderSoft bg-softMid p-2 shadow-panel" aria-label="Cabecera de recepcion">
          <div className="grid gap-2 md:grid-cols-[120px_minmax(160px,1fr)_minmax(140px,1fr)_minmax(160px,1fr)]">
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Almacen
              <input
                value={form.warehouseRef}
                onChange={(event) => updateForm("warehouseRef", event.target.value)}
                className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                placeholder="W001"
              />
            </label>
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              OC
              <input
                value={form.purchaseOrderRef}
                onChange={(event) => updateForm("purchaseOrderRef", event.target.value)}
                className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                placeholder="OC-100"
              />
            </label>
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Proveedor
              <input
                value={form.supplierRef}
                onChange={(event) => updateForm("supplierRef", event.target.value)}
                className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                placeholder="SUP-1"
              />
            </label>
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Ubicacion destino
              <input
                value={form.targetLocationRef}
                onChange={(event) => updateForm("targetLocationRef", event.target.value)}
                className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                placeholder="W001-DSP-GEN"
              />
            </label>
          </div>
        </section>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
            <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
              <PackagePlus className="h-4 w-4 text-primaryHover" aria-hidden="true" />
              Lineas recibidas
            </div>
            <button
              type="button"
              onClick={() => setLines((current) => [...current, emptyLine()])}
              className="inline-flex min-h-7 items-center gap-1 rounded border border-borderSoft bg-white px-2 text-[11px] font-semibold text-night transition hover:border-primary hover:text-primaryHover"
            >
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              Agregar
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full min-w-[900px] border-collapse text-left text-[12px]">
              <thead className="sticky top-0 z-10 bg-deep text-white">
                <tr>
                  <th className="w-[190px] px-3 py-2 font-semibold">Articulo</th>
                  <th className="w-[110px] px-3 py-2 text-right font-semibold">Esperado</th>
                  <th className="w-[110px] px-3 py-2 text-right font-semibold">Recibido</th>
                  <th className="w-[80px] px-3 py-2 font-semibold">UOM</th>
                  <th className="w-[170px] px-3 py-2 font-semibold">Ubicacion</th>
                  <th className="w-[130px] px-3 py-2 font-semibold">Lote</th>
                  <th className="w-[54px] px-3 py-2 text-right font-semibold">Quitar</th>
                </tr>
              </thead>
              <tbody>
                {lines.map((line, index) => (
                  <tr key={line.clientId} className="border-b border-borderSoft bg-white">
                    <td className="px-3 py-2">
                      <label className="sr-only" htmlFor={`receipt-item-${line.clientId}`}>{`Articulo linea ${index + 1}`}</label>
                      <input
                        id={`receipt-item-${line.clientId}`}
                        aria-label={`Articulo linea ${index + 1}`}
                        value={line.itemRef}
                        onChange={(event) => updateLine(line.clientId, "itemRef", event.target.value)}
                        className="h-8 w-full rounded border border-borderSoft px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <input
                        aria-label={`Cantidad esperada linea ${index + 1}`}
                        value={line.expectedQty}
                        onChange={(event) => updateLine(line.clientId, "expectedQty", event.target.value)}
                        inputMode="decimal"
                        className="h-8 w-full rounded border border-borderSoft px-2 text-right font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                        placeholder="0"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <input
                        aria-label={`Cantidad recibida linea ${index + 1}`}
                        value={line.receivedQty}
                        onChange={(event) => updateLine(line.clientId, "receivedQty", event.target.value)}
                        inputMode="decimal"
                        className="h-8 w-full rounded border border-borderSoft px-2 text-right font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                        placeholder="0"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <input
                        aria-label={`Unidad linea ${index + 1}`}
                        value={line.uom}
                        onChange={(event) => updateLine(line.clientId, "uom", event.target.value)}
                        className="h-8 w-full rounded border border-borderSoft px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <input
                        aria-label={`Ubicacion linea ${index + 1}`}
                        value={line.locationRef}
                        onChange={(event) => updateLine(line.clientId, "locationRef", event.target.value)}
                        className="h-8 w-full rounded border border-borderSoft px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                        placeholder={form.targetLocationRef || "destino"}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <input
                        aria-label={`Lote linea ${index + 1}`}
                        value={line.lotRef}
                        onChange={(event) => updateLine(line.clientId, "lotRef", event.target.value)}
                        className="h-8 w-full rounded border border-borderSoft px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                      />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => removeLine(line.clientId)}
                        disabled={lines.length === 1}
                        className="inline-flex h-8 w-8 items-center justify-center rounded border border-borderSoft bg-white text-secondaryText transition hover:border-red-300 hover:text-red-700 disabled:bg-softStart"
                        aria-label={`Quitar linea ${index + 1}`}
                      >
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

      <aside className="min-h-0 overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
        <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
            <ClipboardList className="h-4 w-4 text-primaryHover" aria-hidden="true" />
            Cierre de recepcion
          </div>
          <StatusBadge label="packed" tone="info" />
        </div>
        <div className="flex h-full min-h-0 flex-col overflow-auto p-3">
          <section className="grid gap-3 border-b border-borderSoft pb-3">
            <div className="rounded border border-borderSoft bg-softMid px-2 py-2 text-[12px]">
              <div className="flex items-center gap-2 text-[11px] font-semibold text-secondaryText">
                <Warehouse className="h-4 w-4" aria-hidden="true" />
                Destino default
              </div>
              <div className="mt-1 font-mono font-semibold text-night">{form.targetLocationRef || "definido por almacen"}</div>
            </div>
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Motivo
              <textarea
                value={form.reason}
                onChange={(event) => updateForm("reason", event.target.value)}
                className="min-h-20 rounded border border-borderSoft bg-white px-2 py-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                placeholder="Referencia operativa"
              />
            </label>
            <button
              type="button"
              onClick={() => void submitReceipt()}
              disabled={posting || !warehouse}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:bg-slate-300"
            >
              <Send className="h-4 w-4" aria-hidden="true" />
              {posting ? "Posteando..." : "Confirmar recepcion"}
            </button>
          </section>

          <section className="min-h-0 py-3">
            <div className="mb-2 text-[12px] font-semibold text-night">Recepciones recientes</div>
            <div className="grid gap-2">
              {receipts.slice(0, 10).map((receipt) => (
                <div key={receipt.id} className="rounded border border-borderSoft bg-white px-2 py-2 text-[12px]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono font-semibold text-night">{receipt.purchase_order_ref}</span>
                    <StatusBadge label={receipt.status} tone={statusTone[receipt.status] ?? "neutral"} />
                  </div>
                  <div className="mt-1 font-mono text-[11px] text-secondaryText">
                    {receipt.lines_count ?? receipt.lines?.length ?? 0} lineas / {formatNumber(receiptQuantity(receipt))} recibidos
                  </div>
                  <div className="mt-1 text-[11px] text-secondaryText">{receipt.supplier_ref || "sin proveedor"}</div>
                </div>
              ))}
              {!receipts.length ? (
                <div className="rounded border border-borderSoft bg-softMid px-3 py-2 text-[12px] text-secondaryText">
                  {loading ? "Cargando..." : "Sin recepciones."}
                </div>
              ) : null}
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}
