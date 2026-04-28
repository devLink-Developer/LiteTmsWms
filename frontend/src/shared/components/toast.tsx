import { useEffect, useState } from "react";

type ToastTone = "error" | "success" | "info";

type ToastInput = {
  durationMs?: number;
  message: string;
  title?: string;
  tone?: ToastTone;
};

type ToastNotification = {
  createdAt: number;
  durationMs: number;
  id: string;
  message: string;
  title: string;
  tone: ToastTone;
};

const defaultTitles: Record<ToastTone, string> = {
  error: "Atencion",
  success: "Confirmado",
  info: "Aviso",
};

let sequence = 0;
let notifications: ToastNotification[] = [];
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function notify(input: string | ToastInput): string {
  const normalizedInput = typeof input === "string" ? { message: input } : input;
  const message = String(normalizedInput.message || "").trim();
  if (!message) {
    return "";
  }

  const tone = normalizedInput.tone || "info";
  const id = `toast-${Date.now()}-${sequence}`;
  sequence += 1;
  notifications = [
    ...notifications,
    {
      createdAt: Date.now(),
      durationMs: normalizedInput.durationMs ?? (tone === "error" ? 7000 : 4800),
      id,
      message,
      title: normalizedInput.title || defaultTitles[tone],
      tone,
    },
  ].slice(-4);
  emit();
  return id;
}

export function dismissToast(id: string) {
  notifications = notifications.filter((notification) => notification.id !== id);
  emit();
}

function toneClass(tone: ToastTone) {
  if (tone === "error") {
    return "border-rose-300 text-rose-900 before:bg-rose-500";
  }
  if (tone === "success") {
    return "border-emerald-300 text-emerald-900 before:bg-emerald-500";
  }
  return "border-[#b7d0ea] text-[#071a2e] before:bg-[#1f6bb4]";
}

export function ToastViewport() {
  const [visibleNotifications, setVisibleNotifications] = useState<ToastNotification[]>(notifications);

  useEffect(() => subscribe(() => setVisibleNotifications([...notifications])), []);

  useEffect(() => {
    const timeoutIds = visibleNotifications.map((notification) =>
      window.setTimeout(() => dismissToast(notification.id), notification.durationMs),
    );

    return () => {
      timeoutIds.forEach((timeoutId) => window.clearTimeout(timeoutId));
    };
  }, [visibleNotifications]);

  if (visibleNotifications.length === 0) {
    return null;
  }

  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-3 left-3 z-[120] flex w-[min(calc(100vw-1.5rem),24rem)] flex-col gap-2 sm:bottom-4 sm:left-4 sm:w-[24rem]"
    >
      {visibleNotifications.map((notification) => (
        <div
          className={`pointer-events-auto relative overflow-hidden rounded-lg border bg-white px-3.5 py-3 pl-4 shadow-[0_18px_42px_rgba(8,37,63,0.18)] before:absolute before:inset-y-0 before:left-0 before:w-1 ${toneClass(
            notification.tone,
          )}`}
          key={notification.id}
          role={notification.tone === "error" ? "alert" : "status"}
        >
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em]">{notification.title}</p>
              <p className="mt-1 text-sm leading-5 text-[#4c5563]">{notification.message}</p>
            </div>
            <button
              aria-label="Cerrar notificacion"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[#d6e2ef] text-sm font-semibold text-[#4c6480] transition hover:bg-[#f3f8fd] hover:text-[#071a2e]"
              onClick={() => dismissToast(notification.id)}
              type="button"
            >
              x
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

