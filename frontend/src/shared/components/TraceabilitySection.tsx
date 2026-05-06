import { useId, useState } from "react";

import type { TimelineEvent } from "../../types/operations";
import { Timeline } from "./Timeline";

type TraceabilitySectionProps = {
  events: TimelineEvent[];
  recordRef: string;
  className?: string;
};

export function TraceabilitySection({ events, recordRef, className = "rounded border border-borderSoft bg-white p-3" }: TraceabilitySectionProps) {
  const [open, setOpen] = useState(false);
  const titleId = useId();
  const hasEvents = events.length > 0;

  return (
    <>
      <section className={className}>
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-[12px] font-semibold uppercase text-secondaryText">Trazabilidad</h3>
          <button
            type="button"
            className="h-8 rounded border border-borderSoft px-2 text-[12px] font-semibold text-primaryHover transition hover:border-primary hover:bg-softMid focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:text-secondaryText"
            disabled={!hasEvents}
            onClick={() => setOpen(true)}
          >
            Ver trazabilidad
          </button>
        </div>
        <p className="mt-2 text-[12px] text-secondaryText">{hasEvents ? `${events.length} movimientos` : "Sin movimientos."}</p>
      </section>

      {open && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-deep/40 px-4 py-6"
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setOpen(false);
            }
          }}
        >
          <section className="flex max-h-[86vh] w-full max-w-3xl flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
            <div className="flex shrink-0 items-start justify-between gap-3 border-b border-borderSoft px-4 py-3">
              <div>
                <p className="text-[11px] font-semibold uppercase text-secondaryText">Trazabilidad</p>
                <h2 id={titleId} className="mt-1 text-[16px] font-semibold text-night">
                  {recordRef}
                </h2>
              </div>
              <button
                type="button"
                className="h-8 rounded border border-borderSoft px-2 text-[12px] font-semibold text-night hover:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                onClick={() => setOpen(false)}
              >
                Cerrar
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-auto px-4 py-3">{hasEvents ? <Timeline events={events} /> : <p className="text-[12px] text-secondaryText">Sin movimientos.</p>}</div>
          </section>
        </div>
      )}
    </>
  );
}
