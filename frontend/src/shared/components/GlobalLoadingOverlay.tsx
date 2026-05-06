import { useEffect, useMemo, useState } from "react";

import { useGlobalLoadingStore } from "../../stores/useGlobalLoadingStore";

const SHOW_DELAY_MS = 180;
const HIDE_DELAY_MS = 120;

export function GlobalLoadingOverlay() {
  const operations = useGlobalLoadingStore((state) => state.operations);
  const activeCount = Object.keys(operations).length;
  const [visible, setVisible] = useState(false);
  const label = useMemo(() => {
    const latest = Object.values(operations).sort((a, b) => b.startedAt - a.startedAt)[0];
    return latest?.label ?? "Procesando...";
  }, [operations]);

  useEffect(() => {
    const timer = window.setTimeout(
      () => setVisible(activeCount > 0),
      activeCount > 0 ? SHOW_DELAY_MS : HIDE_DELAY_MS,
    );
    return () => window.clearTimeout(timer);
  }, [activeCount]);

  if (!visible) return null;

  return (
    <div
      aria-busy="true"
      aria-live="polite"
      className="fixed inset-0 z-[9998] flex items-center justify-center bg-night/30 px-4 backdrop-blur-[2px]"
      role="status"
    >
      <div className="w-full max-w-[340px] rounded border border-borderSoft bg-white px-4 py-3 shadow-[0_24px_70px_rgba(7,26,46,0.24)]">
        <div className="flex items-center gap-3">
          <span className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-borderSoft border-t-primary" aria-hidden="true" />
          <div className="min-w-0">
            <div className="truncate text-[13px] font-semibold text-night">{label}</div>
            <div className="text-[11px] font-semibold text-secondaryText">Espere un momento</div>
          </div>
        </div>
      </div>
    </div>
  );
}
