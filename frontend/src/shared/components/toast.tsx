import { useEffect, useRef, useState } from "react";

export type ToastTone = "error" | "success" | "info" | "warning";

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
  warning: "Revision",
};

let sequence = 0;
let notifications: ToastNotification[] = [];
const listeners = new Set<() => void>();
const fallbackNodes = new Map<string, HTMLElement>();
const fallbackTimeouts = new Map<string, number>();

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
      durationMs: normalizedInput.durationMs ?? 3000,
      id,
      message,
      title: normalizedInput.title || defaultTitles[tone],
      tone,
    },
  ].slice(-4);
  emit();
  if (!listeners.size) {
    renderFallbackToast(notifications[notifications.length - 1]);
  }
  return id;
}

export function dismissToast(id: string) {
  notifications = notifications.filter((notification) => notification.id !== id);
  removeFallbackToast(id);
  emit();
}

export function clearToasts() {
  notifications = [];
  Array.from(fallbackNodes.keys()).forEach(removeFallbackToast);
  emit();
}

function errorMessage(error: unknown, fallback = "Operacion fallida.") {
  if (!error) {
    return "";
  }
  return error instanceof Error ? error.message : fallback;
}

export function notifyError(error: unknown, fallback?: string) {
  const message = errorMessage(error, fallback);
  if (message) {
    notify({ message, tone: "error" });
  }
}

export function useToastError(error: unknown, fallback?: string) {
  const lastMessageRef = useRef("");

  useEffect(() => {
    const message = errorMessage(error, fallback);
    if (!message || message === lastMessageRef.current) {
      return;
    }
    lastMessageRef.current = message;
    notify({ message, tone: "error" });
  }, [error, fallback]);
}

function toneClass(tone: ToastTone) {
  if (tone === "error") {
    return "border-rose-300 text-rose-900 before:bg-rose-500";
  }
  if (tone === "warning") {
    return "border-amber-300 text-amber-900 before:bg-amber-500";
  }
  if (tone === "success") {
    return "border-emerald-300 text-emerald-900 before:bg-emerald-500";
  }
  return "border-[#b7d0ea] text-[#071a2e] before:bg-[#1f6bb4]";
}

function viewportContainer() {
  let container = document.getElementById("toast-fallback-viewport");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-fallback-viewport";
    container.setAttribute("aria-live", "polite");
    container.className =
      "pointer-events-none fixed bottom-3 left-3 z-[120] flex w-[min(calc(100vw-1.5rem),24rem)] flex-col gap-2 sm:bottom-4 sm:left-4 sm:w-[24rem]";
    document.body.appendChild(container);
  }
  return container;
}

function removeFallbackToast(id: string) {
  const timeoutId = fallbackTimeouts.get(id);
  if (timeoutId) {
    window.clearTimeout(timeoutId);
    fallbackTimeouts.delete(id);
  }
  fallbackNodes.get(id)?.remove();
  fallbackNodes.delete(id);
  const container = document.getElementById("toast-fallback-viewport");
  if (container && !container.childElementCount) {
    container.remove();
  }
}

function renderFallbackToast(notification: ToastNotification | undefined) {
  if (!notification || typeof document === "undefined") {
    return;
  }
  const node = document.createElement("div");
  node.className = `pointer-events-auto relative overflow-hidden rounded-lg border bg-white px-3.5 py-3 pl-4 shadow-[0_18px_42px_rgba(8,37,63,0.18)] before:absolute before:inset-y-0 before:left-0 before:w-1 ${toneClass(
    notification.tone,
  )}`;
  node.setAttribute("role", notification.tone === "error" ? "alert" : "status");
  const title = document.createElement("p");
  title.className = "text-[11px] font-semibold uppercase tracking-[0.16em]";
  title.textContent = notification.title;
  const message = document.createElement("p");
  message.className = "mt-1 whitespace-pre-line break-words text-sm leading-5 text-[#4c5563]";
  message.textContent = notification.message;
  node.append(title, message);
  fallbackNodes.set(notification.id, node);
  viewportContainer().appendChild(node);
  fallbackTimeouts.set(notification.id, window.setTimeout(() => removeFallbackToast(notification.id), notification.durationMs));
}

function ToastCard({ notification }: { notification: ToastNotification }) {
  const timeoutRef = useRef<number | null>(null);
  const deadlineRef = useRef(0);
  const remainingRef = useRef(notification.durationMs);

  function clearTimer() {
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }

  function startTimer(durationMs = remainingRef.current) {
    clearTimer();
    deadlineRef.current = Date.now() + durationMs;
    remainingRef.current = durationMs;
    timeoutRef.current = window.setTimeout(() => dismissToast(notification.id), durationMs);
  }

  function pauseTimer() {
    clearTimer();
    remainingRef.current = Math.max(0, deadlineRef.current - Date.now());
  }

  useEffect(() => {
    startTimer(notification.durationMs);
    return clearTimer;
  }, [notification.id, notification.durationMs]);

  return (
    <div
      className={`pointer-events-auto relative overflow-hidden rounded-lg border bg-white px-3.5 py-3 pl-4 shadow-[0_18px_42px_rgba(8,37,63,0.18)] before:absolute before:inset-y-0 before:left-0 before:w-1 ${toneClass(
        notification.tone,
      )}`}
      key={notification.id}
      onMouseEnter={pauseTimer}
      onMouseLeave={() => startTimer()}
      role={notification.tone === "error" ? "alert" : "status"}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em]">{notification.title}</p>
          <p className="mt-1 whitespace-pre-line break-words text-sm leading-5 text-[#4c5563]">{notification.message}</p>
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
  );
}

export function ToastViewport() {
  const [visibleNotifications, setVisibleNotifications] = useState<ToastNotification[]>(notifications);

  useEffect(() => subscribe(() => setVisibleNotifications([...notifications])), []);

  if (visibleNotifications.length === 0) {
    return null;
  }

  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-3 left-3 z-[120] flex w-[min(calc(100vw-1.5rem),24rem)] flex-col gap-2 sm:bottom-4 sm:left-4 sm:w-[24rem]"
    >
      {visibleNotifications.map((notification) => (
        <ToastCard key={notification.id} notification={notification} />
      ))}
    </div>
  );
}
