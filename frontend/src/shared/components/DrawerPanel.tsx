import type { OperationModule, OperationRow } from "../../types/operations";
import { formatMaybeDateValue } from "../utils/dateFormat";
import { StatusBadge } from "./StatusBadge";
import { Timeline } from "./Timeline";

type DrawerPanelProps = {
  module: OperationModule;
  row?: OperationRow;
  onClose: () => void;
};

export function DrawerPanel({ module, row, onClose }: DrawerPanelProps) {
  return (
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
          <section>
            <h3 className="mb-2 text-[12px] font-semibold uppercase text-secondaryText">Trazabilidad</h3>
            {row.timeline?.length ? (
              <Timeline events={row.timeline} />
            ) : (
              <div className="text-[12px] text-secondaryText">El endpoint no expone eventos de trazabilidad para este registro.</div>
            )}
          </section>
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
        <div className="min-h-0 flex-1 overflow-auto px-4 py-6 text-[12px] text-secondaryText">Selecciona una fila para revisar lineas, eventos e incidencias.</div>
      )}
    </aside>
  );
}
