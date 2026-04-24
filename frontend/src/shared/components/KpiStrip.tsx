import type { Kpi } from "../../types/operations";
import { StatusBadge } from "./StatusBadge";

type KpiStripProps = {
  items: Kpi[];
};

export function KpiStrip({ items }: KpiStripProps) {
  return (
    <section className="grid grid-cols-1 gap-2 md:grid-cols-3" aria-label="Indicadores operativos">
      {items.map((item) => (
        <div key={item.label} className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
          <div className="flex items-center justify-between gap-3">
            <span className="text-[12px] font-semibold text-secondaryText">{item.label}</span>
            <StatusBadge label={item.delta} tone={item.tone} />
          </div>
          <div className="mt-1 font-mono text-[22px] font-semibold text-night">{item.value}</div>
        </div>
      ))}
    </section>
  );
}
