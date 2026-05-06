import { useEffect, useRef } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";

import { fetchLiveStatusEvents, type LiveStatusEvent } from "../../api/live";
import { withoutGlobalLoading } from "../../stores/useGlobalLoadingStore";

const LIVE_STATUS_EVENT_NAME = "tmswms:live-status-events";
const POLL_INTERVAL_MS = 3000;

type LiveStatusEventsOptions = {
  enabled?: boolean;
  onEvents?: (events: LiveStatusEvent[]) => void;
};

function hasAny(events: LiveStatusEvent[], types: LiveStatusEvent["entity_type"][]) {
  return events.some((event) => types.includes(event.entity_type));
}

async function invalidateLiveQueries(queryClient: QueryClient, events: LiveStatusEvent[]) {
  const invalidate = [];
  if (hasAny(events, ["delivery_order", "delivery_document", "delivery_preparation_task", "fulfillment_order", "route_sheet", "route_stop"])) {
    invalidate.push(
      queryClient.invalidateQueries({ queryKey: ["reparto-confirmation"] }),
      queryClient.invalidateQueries({ queryKey: ["routing-deliveries"] }),
    );
  }
  if (hasAny(events, ["delivery_order", "delivery_preparation_task"])) {
    invalidate.push(
      queryClient.invalidateQueries({ queryKey: ["reparto-preparation-deliveries"] }),
      queryClient.invalidateQueries({ queryKey: ["reparto-preparation-tasks"] }),
    );
  }
  if (hasAny(events, ["route_sheet", "route_stop"])) {
    invalidate.push(
      queryClient.invalidateQueries({ queryKey: ["routing-open-routes"] }),
      queryClient.invalidateQueries({ queryKey: ["routing-route-detail"] }),
      queryClient.invalidateQueries({ queryKey: ["driver-routes"] }),
      queryClient.invalidateQueries({ queryKey: ["driver-route-detail"] }),
    );
  }
  await Promise.all(invalidate);
}

export function emitLiveStatusEvents(events: LiveStatusEvent[]) {
  if (!events.length || typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(LIVE_STATUS_EVENT_NAME, { detail: events }));
}

export function useLiveStatusEvents({ enabled = true, onEvents }: LiveStatusEventsOptions = {}) {
  const queryClient = useQueryClient();
  const cursorRef = useRef(new Date().toISOString());
  const runningRef = useRef(false);
  const onEventsRef = useRef(onEvents);

  useEffect(() => {
    onEventsRef.current = onEvents;
  }, [onEvents]);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;

    async function poll() {
      if (runningRef.current) return;
      runningRef.current = true;
      try {
        const payload = await fetchLiveStatusEvents(cursorRef.current);
        if (cancelled) return;
        cursorRef.current = payload.cursor || cursorRef.current;
        if (payload.results.length) {
          emitLiveStatusEvents(payload.results);
          onEventsRef.current?.(payload.results);
          await withoutGlobalLoading(() => invalidateLiveQueries(queryClient, payload.results));
        }
      } catch {
        // Live refresh is opportunistic; foreground actions still surface their own errors.
      } finally {
        runningRef.current = false;
      }
    }

    const interval = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [enabled, queryClient]);
}

export function useLiveStatusRefresh(handler: (events: LiveStatusEvent[]) => void, enabled = true) {
  const handlerRef = useRef(handler);
  useEffect(() => {
    handlerRef.current = handler;
  }, [handler]);

  useEffect(() => {
    if (!enabled) return undefined;
    function onLiveEvents(event: Event) {
      handlerRef.current((event as CustomEvent<LiveStatusEvent[]>).detail ?? []);
    }
    window.addEventListener(LIVE_STATUS_EVENT_NAME, onLiveEvents);
    return () => window.removeEventListener(LIVE_STATUS_EVENT_NAME, onLiveEvents);
  }, [enabled]);
}

export function eventsAffectOperationalStatuses(events: LiveStatusEvent[]) {
  return hasAny(events, ["delivery_order", "delivery_document", "delivery_preparation_task", "fulfillment_order", "route_sheet", "route_stop"]);
}
