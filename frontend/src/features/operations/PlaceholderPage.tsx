import { StatusBadge } from "../../shared/components/StatusBadge";
import type { PlaceholderPageConfig } from "../../types/operations";

type PlaceholderPageProps = {
  config: PlaceholderPageConfig;
};

export function PlaceholderPage({ config }: PlaceholderPageProps) {
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3">
      <header className="flex shrink-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase text-secondaryText">{config.groupLabel}</div>
          <h1 className="mt-1 text-[20px] font-semibold text-night">{config.label}</h1>
          <p className="mt-1 max-w-4xl text-[12px] leading-5 text-secondaryText">{config.description}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge label="read-only" tone="info" />
          <StatusBadge label="sin API" tone="warning" />
        </div>
      </header>

      <section className="rounded border border-borderSoft bg-surface shadow-panel">
        <div className="border-b border-borderSoft px-3 py-2">
          <h2 className="text-[13px] font-semibold text-night">Estado operativo</h2>
        </div>
        <div className="grid gap-2 p-3 md:grid-cols-3">
          {config.checkpoints.map((checkpoint) => (
            <div key={checkpoint} className="rounded border border-borderSoft bg-white px-3 py-3">
              <div className="text-[12px] font-semibold text-night">{checkpoint}</div>
              <div className="mt-1 text-[11px] leading-5 text-secondaryText">Modulo disponible solo para consulta.</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
