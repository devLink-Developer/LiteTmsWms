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
        </div>
      </header>

      <section className="rounded border border-borderSoft bg-surface px-3 py-3 shadow-panel">
        <h2 className="text-[13px] font-semibold text-night">Estado operativo</h2>
      </section>
    </div>
  );
}
