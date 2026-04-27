import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, ClipboardList, PackageCheck, Send, Warehouse } from "lucide-react";

import { createTransfer, fetchTransfers, transferCommand, type TransferOrder } from "../../api/transfers";
import { StatusBadge } from "../../shared/components/StatusBadge";
import type { StatusTone } from "../../types/operations";

type TransferTab = "request" | "prepare" | "dispatch" | "receive" | "adjust";

const tabs: Array<{ key: TransferTab; label: string }> = [
  { key: "request", label: "Solicitud" },
  { key: "prepare", label: "Preparacion" },
  { key: "dispatch", label: "Despacho" },
  { key: "receive", label: "Recepcion" },
  { key: "adjust", label: "Ajustes" },
];

const statusTone: Record<string, StatusTone> = {
  requested: "neutral",
  approved: "info",
  picking: "warning",
  dispatched: "info",
  in_transit: "info",
  partial_received: "warning",
  received: "success",
  discrepant: "warning",
  closed: "success",
  cancelled: "danger",
};

function formatQty(value: string | number | undefined) {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 }).format(Number(value ?? 0));
}

export function TransfersPage() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<TransferTab>("request");
  const [activeId, setActiveId] = useState("");
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [itemRef, setItemRef] = useState("");
  const [qty, setQty] = useState("1");
  const [uom, setUom] = useState("UN");
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  const transfersQuery = useQuery({ queryKey: ["transfers-operational"], queryFn: fetchTransfers });
  const transfers = transfersQuery.data ?? [];
  const activeTransfer = useMemo(
    () => transfers.find((transfer) => transfer.id === activeId) ?? transfers[0],
    [activeId, transfers],
  );

  const createMutation = useMutation({
    mutationFn: () =>
      createTransfer({
        origin_warehouse_ref: origin,
        destination_warehouse_ref: destination,
        reason,
        lines: [{ item_ref: itemRef, requested_qty: qty, uom }],
      }),
    onSuccess: (transfer) => {
      setMessage(`${transfer.transfer_number} creada.`);
      setActiveId(transfer.id);
      void queryClient.invalidateQueries({ queryKey: ["transfers-operational"] });
    },
  });

  const commandMutation = useMutation({
    mutationFn: ({ transfer, command }: { transfer: TransferOrder; command: "approve" | "prepare" | "dispatch" | "receive" | "close" }) => {
      const payload =
        command === "receive"
          ? { lines: transfer.lines?.map((line) => ({ line_id: line.id, received_qty: line.shipped_qty })) ?? [] }
          : command === "close"
            ? { reason: transfer.reason || "Cierre operativo" }
            : {};
      return transferCommand(transfer.id, command, payload);
    },
    onSuccess: (transfer) => {
      setMessage(`${transfer.transfer_number} actualizado.`);
      setActiveId(transfer.id);
      void queryClient.invalidateQueries({ queryKey: ["transfers-operational"] });
    },
  });

  const busy = transfersQuery.isLoading || createMutation.isPending || commandMutation.isPending;
  const error = transfersQuery.error || createMutation.error || commandMutation.error;

  function run(command: "approve" | "prepare" | "dispatch" | "receive" | "close") {
    if (!activeTransfer) return;
    commandMutation.mutate({ transfer: activeTransfer, command });
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-3">
      <header className="flex shrink-0 flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-semibold text-night">Transferencias entre sucursales</h1>
          <p className="mt-1 text-[12px] text-secondaryText">Solicitud, preparacion, despacho, recepcion y cierre con diferencias.</p>
        </div>
        {activeTransfer && <StatusBadge label={activeTransfer.status} tone={statusTone[activeTransfer.status] ?? "neutral"} />}
      </header>

      {(error || message) && (
        <div className={`shrink-0 rounded border px-3 py-2 text-[12px] ${error ? "border-red-200 bg-red-50 text-red-700" : "border-blue-200 bg-blue-50 text-blue-800"}`}>
          {error instanceof Error ? error.message : message}
        </div>
      )}

      <section className="flex shrink-0 gap-1 overflow-x-auto rounded border border-borderSoft bg-white p-1" aria-label="Etapas de transferencia">
        {tabs.map((entry) => (
          <button
            key={entry.key}
            type="button"
            onClick={() => setTab(entry.key)}
            className={`min-h-9 rounded px-3 text-[12px] font-semibold transition focus:outline-none focus:ring-2 focus:ring-primary/20 ${
              tab === entry.key ? "bg-primary text-white" : "text-secondaryText hover:bg-softStart hover:text-night"
            }`}
          >
            {entry.label}
          </button>
        ))}
      </section>

      <section className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(0,1fr)_minmax(0,0.9fr)] gap-3 overflow-hidden xl:grid-cols-[minmax(0,1fr)_380px] xl:grid-rows-1">
        <main className="min-h-0 overflow-auto rounded border border-borderSoft bg-surface shadow-panel">
          <table className="w-full border-collapse text-left text-[12px]">
            <thead className="sticky top-0 z-10 bg-deep text-white">
              <tr>
                <th className="px-3 py-2 font-semibold">Transferencia</th>
                <th className="px-3 py-2 font-semibold">Origen</th>
                <th className="px-3 py-2 font-semibold">Destino</th>
                <th className="px-3 py-2 font-semibold">Lineas</th>
                <th className="px-3 py-2 font-semibold">Estado</th>
              </tr>
            </thead>
            <tbody>
              {transfers.map((transfer) => (
                <tr
                  key={transfer.id}
                  onClick={() => setActiveId(transfer.id)}
                  className={`cursor-pointer border-b border-borderSoft bg-white hover:bg-softStart ${
                    activeTransfer?.id === transfer.id ? "outline outline-2 outline-primary/20" : ""
                  }`}
                >
                  <td className="whitespace-nowrap px-3 py-2 font-mono font-semibold text-night">{transfer.transfer_number}</td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{transfer.origin_warehouse_ref}</td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{transfer.destination_warehouse_ref}</td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{transfer.lines_count ?? transfer.lines?.length ?? 0}</td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <StatusBadge label={transfer.status} tone={statusTone[transfer.status] ?? "neutral"} />
                  </td>
                </tr>
              ))}
              {!transfers.length && (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-[12px] text-secondaryText">
                    {busy ? "Cargando transferencias..." : "No hay transferencias registradas."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </main>

        <aside className="flex min-h-0 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="shrink-0 border-b border-borderSoft bg-white p-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-[13px] font-semibold text-night">{tabs.find((entry) => entry.key === tab)?.label}</h2>
              {tab === "request" && <ClipboardList size={18} className="text-primary" />}
              {tab === "prepare" && <PackageCheck size={18} className="text-primary" />}
              {tab === "dispatch" && <Send size={18} className="text-primary" />}
              {tab === "receive" && <Warehouse size={18} className="text-primary" />}
              {tab === "adjust" && <Check size={18} className="text-primary" />}
            </div>
          </div>

          {tab === "request" ? (
            <div className="grid gap-3 overflow-auto p-3 text-[12px]">
              <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-2">
                <label className="grid gap-1 font-semibold text-secondaryText">
                  Origen
                  <input value={origin} onChange={(event) => setOrigin(event.target.value)} className="h-9 rounded border border-borderSoft px-2 text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
                </label>
                <ArrowRight className="mb-2 text-secondaryText" size={18} />
                <label className="grid gap-1 font-semibold text-secondaryText">
                  Destino
                  <input value={destination} onChange={(event) => setDestination(event.target.value)} className="h-9 rounded border border-borderSoft px-2 text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
                </label>
              </div>
              <label className="grid gap-1 font-semibold text-secondaryText">
                Articulo
                <input value={itemRef} onChange={(event) => setItemRef(event.target.value)} className="h-9 rounded border border-borderSoft px-2 font-mono text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className="grid gap-1 font-semibold text-secondaryText">
                  Cantidad
                  <input value={qty} type="number" min="0" onChange={(event) => setQty(event.target.value)} className="h-9 rounded border border-borderSoft px-2 font-mono text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
                </label>
                <label className="grid gap-1 font-semibold text-secondaryText">
                  Unidad
                  <input value={uom} onChange={(event) => setUom(event.target.value)} className="h-9 rounded border border-borderSoft px-2 font-mono text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
                </label>
              </div>
              <label className="grid gap-1 font-semibold text-secondaryText">
                Motivo
                <textarea value={reason} onChange={(event) => setReason(event.target.value)} className="min-h-20 rounded border border-borderSoft px-2 py-2 text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
              </label>
              <button
                type="button"
                disabled={busy || !origin || !destination || !itemRef || !qty}
                onClick={() => createMutation.mutate()}
                className="min-h-9 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover disabled:bg-softStart disabled:text-secondaryText"
              >
                Crear solicitud
              </button>
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="grid shrink-0 grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-2 border-b border-borderSoft bg-white p-3 text-[12px]">
                <dt className="font-semibold text-secondaryText">Transferencia</dt>
                <dd className="font-mono text-night">{activeTransfer?.transfer_number ?? "sin seleccion"}</dd>
                <dt className="font-semibold text-secondaryText">Estado</dt>
                <dd>{activeTransfer && <StatusBadge label={activeTransfer.status} tone={statusTone[activeTransfer.status] ?? "neutral"} />}</dd>
                <dt className="font-semibold text-secondaryText">Ruta</dt>
                <dd className="font-mono text-night">
                  {activeTransfer ? `${activeTransfer.origin_warehouse_ref} -> ${activeTransfer.destination_warehouse_ref}` : "-"}
                </dd>
              </div>
              <div className="min-h-0 flex-1 overflow-auto">
                <table className="w-full border-collapse text-left text-[11px]">
                  <thead className="sticky top-0 bg-softMid text-secondaryText">
                    <tr>
                      <th className="px-3 py-2 font-semibold">Item</th>
                      <th className="px-3 py-2 font-semibold">Solicitado</th>
                      <th className="px-3 py-2 font-semibold">Despachado</th>
                      <th className="px-3 py-2 font-semibold">Recibido</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(activeTransfer?.lines ?? []).map((line) => (
                      <tr key={line.id} className="border-b border-borderSoft bg-white">
                        <td className="px-3 py-2 font-mono font-semibold text-night">{line.item_ref}</td>
                        <td className="px-3 py-2 font-mono text-night">{formatQty(line.requested_qty)} {line.uom}</td>
                        <td className="px-3 py-2 font-mono text-night">{formatQty(line.shipped_qty)} {line.uom}</td>
                        <td className="px-3 py-2 font-mono text-night">{formatQty(line.received_qty)} {line.uom}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="grid shrink-0 grid-cols-2 gap-2 border-t border-borderSoft bg-white p-3">
                <button type="button" disabled={!activeTransfer || busy || activeTransfer.status !== "requested"} onClick={() => run("approve")} className="min-h-9 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night hover:border-primary hover:text-primaryHover disabled:bg-softStart">Aprobar</button>
                <button type="button" disabled={!activeTransfer || busy || !["requested", "approved"].includes(activeTransfer.status)} onClick={() => run("prepare")} className="min-h-9 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night hover:border-primary hover:text-primaryHover disabled:bg-softStart">Preparar</button>
                <button type="button" disabled={!activeTransfer || busy || !["approved", "picking"].includes(activeTransfer.status)} onClick={() => run("dispatch")} className="min-h-9 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night hover:border-primary hover:text-primaryHover disabled:bg-softStart">Despachar</button>
                <button type="button" disabled={!activeTransfer || busy || !["in_transit", "partial_received", "discrepant"].includes(activeTransfer.status)} onClick={() => run("receive")} className="min-h-9 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night hover:border-primary hover:text-primaryHover disabled:bg-softStart">Recibir</button>
                <button type="button" disabled={!activeTransfer || busy || !["received", "partial_received", "discrepant"].includes(activeTransfer.status)} onClick={() => run("close")} className="col-span-2 min-h-9 rounded bg-primary px-3 text-[12px] font-semibold text-white hover:bg-primaryHover disabled:bg-softStart disabled:text-secondaryText">Cerrar</button>
              </div>
            </div>
          )}
        </aside>
      </section>
    </div>
  );
}
