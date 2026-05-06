import { useMemo } from "react";

import type { OperationModule, OperationRow } from "../../types/operations";
import { formatMaybeDateValue } from "../utils/dateFormat";
import { StatusBadge } from "./StatusBadge";
import { TraceabilitySection } from "./TraceabilitySection";

type DrawerPanelProps = {
  module: OperationModule;
  row?: OperationRow;
  onClose: () => void;
};

type RawRecord = Record<string, unknown>;

function asRecord(value: unknown): RawRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as RawRecord) : {};
}

function asArray(value: unknown): RawRecord[] {
  return Array.isArray(value) ? value.map(asRecord) : [];
}

function display(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return String(value);
}

const deliveryStatusLabels: Record<string, string> = {
  created: "creada",
  confirmed: "confirmada",
  planned: "planificada",
  assigned: "asignada",
  preparing: "enviada a preparar",
  prepared: "preparada",
  loaded: "cargada",
  in_route: "en ruta",
  attempted: "intentada",
  delivered_partial: "entregada parcial",
  delivered_complete: "entregada",
  returned: "devuelta",
  cancelled: "cancelada",
};

function deliveryStatusTone(status: string) {
  if (["delivered_complete", "delivered_partial"].includes(status)) return "success";
  if (["in_route", "loaded", "assigned"].includes(status)) return "info";
  if (["confirmed", "preparing", "prepared"].includes(status)) return "warning";
  if (["returned", "cancelled", "attempted"].includes(status)) return "danger";
  return "neutral";
}

function deliveryDocuments(delivery: RawRecord) {
  return asArray(delivery.documents);
}

function deliveryRemitos(delivery: RawRecord) {
  return deliveryDocuments(delivery).filter((document) => display(document.document_type, "").toLowerCase() === "remito");
}

function hasRemito(delivery: RawRecord) {
  return deliveryRemitos(delivery).length > 0;
}

function deliveryStatus(delivery: RawRecord) {
  return display(delivery.status, "sin estado");
}

function deliveryLabel(delivery: RawRecord) {
  return deliveryStatusLabels[deliveryStatus(delivery)] ?? deliveryStatus(delivery);
}

function deliveryTotals(delivery: RawRecord) {
  const totals = asRecord(delivery.totals);
  const units = display(totals.delivery_unit_qty, "");
  const weight = display(totals.planned_weight_kg, "");
  const volume = display(totals.planned_volume_m3, "");
  return [
    units ? `${units} unid.` : "",
    weight ? `${weight} kg` : "",
    volume ? `${volume} m3` : "",
  ]
    .filter(Boolean)
    .join(" / ");
}

function deliveryRoute(delivery: RawRecord) {
  const route = asRecord(delivery.route_sheet);
  const routeNumber = display(route.route_number, "");
  const routeStatus = display(route.status, "");
  return routeNumber ? `${routeNumber}${routeStatus ? ` / ${routeStatus}` : ""}` : "";
}

function DeliveryList({ title, deliveries, emptyText }: { title: string; deliveries: RawRecord[]; emptyText: string }) {
  return (
    <section className="rounded border border-borderSoft bg-white p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[12px] font-semibold uppercase text-secondaryText">{title}</h3>
        <span className="rounded border border-borderSoft bg-softMid px-2 py-0.5 font-mono text-[10px] text-secondaryText">{deliveries.length}</span>
      </div>
      {deliveries.length ? (
        <div className="mt-2 grid gap-2">
          {deliveries.map((delivery) => {
            const status = deliveryStatus(delivery);
            const remitos = deliveryRemitos(delivery);
            const route = deliveryRoute(delivery);
            const totals = deliveryTotals(delivery);
            return (
              <div key={display(delivery.id, display(delivery.delivery_number))} className="rounded border border-borderSoft bg-softMid px-2 py-2 text-[11px]">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="font-mono text-[12px] font-semibold text-night">{display(delivery.delivery_number)}</div>
                    <div className="mt-1 text-secondaryText">{display(delivery.delivery_mode, "sin modalidad")}</div>
                  </div>
                  <StatusBadge label={deliveryLabel(delivery)} tone={deliveryStatusTone(status)} />
                </div>
                <div className="mt-2 grid gap-1 text-secondaryText">
                  <div>
                    Fecha <span className="font-mono text-night">{formatMaybeDateValue("planned_date", delivery.planned_date)}</span>
                  </div>
                  {route && (
                    <div>
                      Ruta <span className="font-mono text-night">{route}</span>
                    </div>
                  )}
                  {totals && <div>{totals}</div>}
                  {remitos.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {remitos.map((document) => (
                        <span key={display(document.id, display(document.document_number))} className="rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 font-mono text-emerald-800">
                          {display(document.document_number)} / {display(document.status)}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="mt-2 text-[12px] text-secondaryText">{emptyText}</p>
      )}
    </section>
  );
}

export function DrawerPanel({ module, row, onClose }: DrawerPanelProps) {
  const deliveries = useMemo(() => asArray(row?.raw?.deliveries), [row]);
  const pendingDeliveries = useMemo(
    () => deliveries.filter((delivery) => !hasRemito(delivery) && !["delivered_complete", "delivered_partial"].includes(deliveryStatus(delivery))),
    [deliveries],
  );
  const remittedDeliveries = useMemo(
    () => deliveries.filter((delivery) => hasRemito(delivery) || ["delivered_complete", "delivered_partial"].includes(deliveryStatus(delivery))),
    [deliveries],
  );
  const showDeliverySections = module.key === "orders" && row;

  return (
    <>
      <aside className="flex min-h-0 w-full flex-col overflow-hidden border-l border-borderSoft bg-surface shadow-panel lg:w-[360px]" aria-label="Detalle operativo">
        <div className="flex shrink-0 items-start justify-between gap-3 border-b border-borderSoft px-4 py-3">
          <div>
            <p className="text-[11px] font-semibold uppercase text-secondaryText">{module.label}</p>
            <h2 className="mt-1 text-[16px] font-semibold text-night">{row?.ref ?? "Sin seleccion"}</h2>
          </div>
          <button
            type="button"
            className="h-8 rounded border border-borderSoft px-2 text-[12px] font-semibold text-night hover:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            onClick={onClose}
          >
            Cerrar
          </button>
        </div>
        {row ? (
          <div className="min-h-0 flex-1 space-y-4 overflow-auto px-4 py-3">
            <section className="grid grid-cols-2 gap-2 text-[12px]">
              <div>
                <div className="text-[11px] font-semibold text-secondaryText">Estado</div>
                <div className="mt-1"><StatusBadge label={row.status} tone={row.statusTone} /></div>
              </div>
              <div>
                <div className="text-[11px] font-semibold text-secondaryText">Warehouse</div>
                <div className="mt-1 font-mono text-night">{row.warehouse}</div>
              </div>
              <div>
                <div className="text-[11px] font-semibold text-secondaryText">Responsable</div>
                <div className="mt-1 text-night">{row.owner}</div>
              </div>
              <div>
                <div className="text-[11px] font-semibold text-secondaryText">SLA</div>
                <div className="mt-1 font-mono text-primaryHover">{row.sla}</div>
              </div>
            </section>
            {showDeliverySections && (
              <>
                <DeliveryList
                  title="Entregas pendientes"
                  deliveries={pendingDeliveries}
                  emptyText="Sin pendientes."
                />
                <DeliveryList
                  title="Entregas con remito"
                  deliveries={remittedDeliveries}
                  emptyText="Sin remitos."
                />
              </>
            )}
            <TraceabilitySection events={row.timeline ?? []} recordRef={row.ref} />
            <section className="rounded border border-borderSoft bg-white p-3">
              <h3 className="text-[12px] font-semibold text-night">Referencias cruzadas</h3>
              <dl className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-secondaryText">
                {Object.entries(row.raw ?? {})
                  .slice(0, 6)
                  .map(([key, value]) => (
                    <div key={key} className="contents">
                      <dt>{key}</dt>
                      <dd className="break-all font-mono text-night">{formatMaybeDateValue(key, value)}</dd>
                    </div>
                  ))}
              </dl>
            </section>
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-auto px-4 py-6 text-[12px] text-secondaryText">Sin seleccion.</div>
        )}
      </aside>
    </>
  );
}
