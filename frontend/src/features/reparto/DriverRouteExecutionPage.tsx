import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { AlertTriangle, Check, Download, MapPin, RefreshCw, Truck } from "lucide-react";
import { MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";

import { fetchDrivers } from "../../api/fleet";
import { executeStop, fetchRouteSheet, fetchRouteSheets, routeCommand, type RouteSheet, type RouteStop } from "../../api/routing";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { notify, useToastError } from "../../shared/components/toast";
import type { StatusTone } from "../../types/operations";
import {
  offlineRouteList,
  queuedExecutions,
  queueExecution,
  removeQueuedExecution,
  saveOfflineRoute,
  updateOfflineRouteExecution,
  type OfflineExecutionPayload,
} from "./offlineRouteStore";

type ExecutionStatus = "delivered_complete" | "delivered_partial" | "not_delivered";

const stopStatusTone: Record<string, StatusTone> = {
  allocated: "info",
  loaded: "warning",
  en_route: "info",
  delivered: "success",
  failed: "danger",
  rescheduled: "warning",
};

const markerIcon = (sequence: number, tone: "pending" | "done" | "failed" | "gps") =>
  L.divIcon({
    className: "",
    html:
      tone === "gps"
        ? '<div class="grid h-5 w-5 place-items-center rounded-full border-2 border-white bg-emerald-600 shadow-panel"><div class="h-2 w-2 rounded-full bg-white"></div></div>'
        : `<div class="grid h-7 w-7 place-items-center rounded-full border-2 border-white ${
            tone === "done" ? "bg-emerald-600" : tone === "failed" ? "bg-red-600" : "bg-primary"
          } font-mono text-[11px] font-semibold text-white shadow-panel">${sequence}</div>`,
    iconSize: tone === "gps" ? [20, 20] : [28, 28],
    iconAnchor: tone === "gps" ? [10, 10] : [14, 14],
  });

function asNumber(value: string | number | null | undefined) {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function formatNumber(value: string | number | null | undefined, maximumFractionDigits = 2) {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits }).format(asNumber(value));
}

function stopPosition(stop: RouteStop): [number, number] | null {
  const lat = Number(stop.lat);
  const lng = Number(stop.lng);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return [lat, lng];
}

function routeLine(route: RouteSheet | null): [number, number][] {
  const geometry = route?.route_geometry?.coordinates ?? [];
  if (geometry.length > 1) {
    return geometry.map(([lng, lat]) => [lat, lng] as [number, number]);
  }
  return (route?.stops.map(stopPosition).filter(Boolean) ?? []) as [number, number][];
}

function stopCode(stop: RouteStop) {
  return stop.delivery_number || stop.source_label || stop.source_ref.slice(0, 8);
}

function BoundsSync({ route, gps }: { route: RouteSheet | null; gps: [number, number] | null }) {
  const map = useMap();
  useEffect(() => {
    const positions = [...routeLine(route), ...(gps ? [gps] : [])];
    if (positions.length) map.fitBounds(positions, { padding: [30, 30], maxZoom: 15 });
  }, [gps, map, route]);
  return null;
}

export function DriverRouteExecutionPage() {
  const queryClient = useQueryClient();
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine));
  const [driverRef, setDriverRef] = useState(() => (typeof window === "undefined" ? "" : window.localStorage.getItem("tmswms.driver_ref") ?? ""));
  const [routeId, setRouteId] = useState("");
  const [route, setRoute] = useState<RouteSheet | null>(null);
  const [activeStopId, setActiveStopId] = useState("");
  const [mode, setMode] = useState<ExecutionStatus>("delivered_complete");
  const [reason, setReason] = useState("");
  const [observations, setObservations] = useState("");
  const [lineValues, setLineValues] = useState<Record<string, string>>({});
  const [gps, setGps] = useState<[number, number] | null>(null);
  const [offlineRoutes, setOfflineRoutes] = useState(() => offlineRouteList());
  const [pendingCount, setPendingCount] = useState(() => queuedExecutions().length);

  const driversQuery = useQuery({ queryKey: ["drivers"], queryFn: fetchDrivers });
  const routesQuery = useQuery({
    queryKey: ["driver-routes", driverRef],
    queryFn: () => fetchRouteSheets({ driverRef, status: ["planned", "loading", "in_transit", "settlement_pending"] }),
    enabled: online,
  });
  const routeQuery = useQuery({
    queryKey: ["driver-route-detail", routeId],
    queryFn: () => fetchRouteSheet(routeId),
    enabled: online && Boolean(routeId),
  });

  const activeStop = route?.stops.find((stop) => stop.id === activeStopId) ?? route?.stops[0] ?? null;
  const routePositions = routeLine(route);
  const mapCenter = routePositions[0] ?? [-27.37057255, -55.91326641];
  const canExecute = route?.status === "in_transit" && activeStop && !["delivered", "failed"].includes(activeStop.status);

  useEffect(() => {
    const onOnline = () => setOnline(true);
    const onOffline = () => setOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);

  useEffect(() => {
    if (driverRef && typeof window !== "undefined") window.localStorage.setItem("tmswms.driver_ref", driverRef);
  }, [driverRef]);

  useEffect(() => {
    if (!driverRef && driversQuery.data?.[0]) setDriverRef(driversQuery.data[0].code);
  }, [driverRef, driversQuery.data]);

  useEffect(() => {
    const firstRoute = routesQuery.data?.[0];
    if (!routeId && firstRoute) setRouteId(firstRoute.id);
  }, [routeId, routesQuery.data]);

  useEffect(() => {
    if (!routeQuery.data) return;
    setRoute(routeQuery.data);
    setActiveStopId(routeQuery.data.stops[0]?.id ?? "");
  }, [routeQuery.data]);

  useEffect(() => {
    if (!routeId || online) return;
    const cached = offlineRoutes.find((candidate) => candidate.id === routeId);
    if (cached) {
      setRoute(cached);
      setActiveStopId(cached.stops[0]?.id ?? "");
    }
  }, [offlineRoutes, online, routeId]);

  useEffect(() => {
    if (!activeStop) return;
    setLineValues(
      Object.fromEntries(
        activeStop.lines.map((line) => [
          line.source_line_ref,
          mode === "not_delivered" ? "0" : mode === "delivered_complete" ? line.quantity : line.delivered_qty !== "0.000000" ? line.delivered_qty : line.quantity,
        ]),
      ),
    );
    setReason(mode === "not_delivered" ? "customer_absent" : "");
    setObservations("");
  }, [activeStop?.id, mode]);

  useEffect(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) return;
    const watch = navigator.geolocation.watchPosition(
      (position) => setGps([position.coords.latitude, position.coords.longitude]),
      () => undefined,
      { enableHighAccuracy: true, maximumAge: 10000, timeout: 10000 },
    );
    return () => navigator.geolocation.clearWatch(watch);
  }, []);

  const commandMutation = useMutation({
    mutationFn: (command: "start-loading" | "depart") => routeCommand(route?.id ?? "", command),
    onSuccess: (nextRoute) => {
      setRoute(nextRoute);
      saveOfflineRoute(nextRoute);
      setOfflineRoutes(offlineRouteList());
      void queryClient.invalidateQueries({ queryKey: ["driver-routes"] });
    },
  });

  const syncMutation = useMutation({
    mutationFn: async () => {
      const queued = queuedExecutions();
      let lastRoute: RouteSheet | null = null;
      for (const item of queued) {
        lastRoute = await executeStop(item.payload, item.idempotencyKey);
        saveOfflineRoute(lastRoute);
        removeQueuedExecution(item.id);
      }
      return lastRoute;
    },
    onSuccess: (nextRoute) => {
      if (nextRoute) setRoute(nextRoute);
      setPendingCount(queuedExecutions().length);
      setOfflineRoutes(offlineRouteList());
      setMessage("Offline sincronizado.");
      void queryClient.invalidateQueries({ queryKey: ["driver-route-detail"] });
      void queryClient.invalidateQueries({ queryKey: ["driver-routes"] });
    },
  });

  useEffect(() => {
    if (online && queuedExecutions().length && !syncMutation.isPending) syncMutation.mutate();
  }, [online]);

  function downloadRoute() {
    if (!route) return;
    saveOfflineRoute(route);
    setOfflineRoutes(offlineRouteList());
    setMessage(`${route.route_number} offline.`);
  }

  async function submitExecution() {
    if (!route || !activeStop) return;
    const lines = activeStop.lines.map((line) => {
      const delivered = mode === "delivered_complete" ? line.quantity : mode === "not_delivered" ? "0" : lineValues[line.source_line_ref] || "0";
      const rejected = Math.max(0, asNumber(line.quantity) - asNumber(delivered));
      return { source_line_ref: line.source_line_ref, delivered_qty: delivered, rejected_qty: String(rejected) };
    });
    const payload: OfflineExecutionPayload = {
      route_stop_id: activeStop.id,
      status: mode,
      reason,
      observations,
      timestamp: new Date().toISOString(),
      lines,
    };
    if (!online) {
      queueExecution(route.id, payload);
      const nextRoute = updateOfflineRouteExecution(route, payload);
      setRoute(nextRoute);
      setPendingCount(queuedExecutions().length);
      setOfflineRoutes(offlineRouteList());
      setMessage("Entrega offline.");
      return;
    }
    const nextRoute = await executeStop(payload);
    setRoute(nextRoute);
    saveOfflineRoute(nextRoute);
    setOfflineRoutes(offlineRouteList());
    setMessage("Entrega registrada.");
  }

  const error = driversQuery.error || routesQuery.error || routeQuery.error || commandMutation.error || syncMutation.error;
  useToastError(error);

  function setMessage(nextMessage: string | null) {
    if (nextMessage) {
      notify({ message: nextMessage, tone: "info" });
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-3">
      <header className="flex shrink-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[20px] font-semibold text-night">Ejecucion chofer</h1>
          <div className="mt-1 flex flex-wrap gap-2 text-[12px] text-secondaryText">
            <span>{online ? "Online" : "Offline"}</span>
            <span>{pendingCount} pendientes de sincronizar</span>
            {route && <span>{route.route_number} / {route.status}</span>}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={downloadRoute} disabled={!route} className="inline-flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover disabled:bg-softStart disabled:text-secondaryText">
            <Download size={15} />
            Descargar ruta
          </button>
          <button type="button" onClick={() => syncMutation.mutate()} disabled={!online || !pendingCount || syncMutation.isPending} className="inline-flex min-h-9 items-center gap-2 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover disabled:bg-softStart disabled:text-secondaryText">
            <RefreshCw size={15} />
            Sincronizar
          </button>
        </div>
      </header>

      <section className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[auto_minmax(320px,1fr)_minmax(0,1fr)] gap-3 overflow-hidden xl:grid-cols-[330px_minmax(0,1fr)_420px] xl:grid-rows-1">
        <aside className="flex min-h-0 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="grid shrink-0 gap-2 border-b border-borderSoft bg-white p-3">
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Chofer
              <select value={driverRef} onChange={(event) => setDriverRef(event.target.value)} className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20">
                <option value="">Sin chofer</option>
                {(driversQuery.data ?? []).map((driver) => (
                  <option key={driver.id} value={driver.code}>{driver.code} / {driver.full_name}</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Rutas asignadas
              <select value={routeId} onChange={(event) => setRouteId(event.target.value)} className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20">
                <option value="">Sin ruta</option>
                {(routesQuery.data ?? []).map((summary) => (
                  <option key={summary.id} value={summary.id}>{summary.route_number} / {summary.status}</option>
                ))}
                {offlineRoutes.map((cached) => (
                  <option key={`offline-${cached.id}`} value={cached.id}>{cached.route_number} / offline</option>
                ))}
              </select>
            </label>
            {route && (
              <div className="flex gap-2">
                <button type="button" disabled={route.status !== "planned" || !online || commandMutation.isPending} onClick={() => commandMutation.mutate("start-loading")} className="min-h-9 flex-1 rounded border border-borderSoft bg-white px-2 text-[11px] font-semibold text-night transition hover:border-primary disabled:bg-softStart">
                  Iniciar carga
                </button>
                <button type="button" disabled={route.status !== "loading" || !online || commandMutation.isPending} onClick={() => commandMutation.mutate("depart")} className="min-h-9 flex-1 rounded bg-deep px-2 text-[11px] font-semibold text-white transition hover:bg-night disabled:bg-softStart disabled:text-secondaryText">
                  Salir a ruta
                </button>
              </div>
            )}
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            {route?.stops.map((stop) => (
              <button key={stop.id} type="button" onClick={() => setActiveStopId(stop.id)} className={`block w-full border-b border-borderSoft px-3 py-3 text-left transition hover:bg-softStart ${activeStop?.id === stop.id ? "bg-white" : "bg-surface"}`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-mono text-[12px] font-semibold text-night">{stop.sequence}. {stopCode(stop)}</div>
                    <div className="mt-1 truncate text-[11px] text-secondaryText">{stop.sales_order_number || stop.customer_ref}</div>
                  </div>
                  <StatusBadge label={stop.status} tone={stopStatusTone[stop.status] ?? "neutral"} />
                </div>
                <div className="mt-2 truncate text-[11px] text-secondaryText">
                  {[stop.address_snapshot.street, stop.address_snapshot.street_number, stop.address_snapshot.city].filter(Boolean).join(" ") || "Sin direccion"}
                </div>
              </button>
            ))}
            {!route && <div className="px-3 py-6 text-[12px] text-secondaryText">Sin ruta.</div>}
          </div>
        </aside>

        <main className="relative min-h-0 overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <MapContainer center={mapCenter} zoom={13} className="h-full w-full" scrollWheelZoom>
            <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            <BoundsSync route={route} gps={gps} />
            {routePositions.length > 1 && <Polyline positions={routePositions} pathOptions={{ color: "#1f6bb4", weight: 4 }} />}
            {route?.stops.map((stop) => {
              const position = stopPosition(stop);
              if (!position) return null;
              const tone = stop.status === "delivered" ? "done" : stop.status === "failed" ? "failed" : "pending";
              return (
                <Marker key={stop.id} position={position} icon={markerIcon(stop.sequence, tone)} eventHandlers={{ click: () => setActiveStopId(stop.id) }}>
                  <Tooltip>{stopCode(stop)}</Tooltip>
                </Marker>
              );
            })}
            {gps && (
              <Marker position={gps} icon={markerIcon(0, "gps")}>
                <Tooltip>Mi ubicacion</Tooltip>
              </Marker>
            )}
          </MapContainer>
          <div className="absolute left-3 top-3 z-[400] rounded border border-borderSoft bg-white px-3 py-2 text-[12px] font-semibold text-night shadow-panel">
            {gps ? "GPS activo" : "GPS sin posicion"}
          </div>
        </main>

        <aside className="flex min-h-0 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="shrink-0 border-b border-borderSoft bg-white p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <h2 className="text-[13px] font-semibold text-night">{activeStop ? `Parada ${activeStop.sequence} / ${stopCode(activeStop)}` : "Parada"}</h2>
                <p className="mt-1 truncate text-[11px] text-secondaryText">{activeStop?.sales_order_number || "Sin parada."}</p>
              </div>
              <MapPin className="text-primary" size={18} />
            </div>
          </div>

          {activeStop ? (
            <div className="min-h-0 flex-1 overflow-auto p-3">
              <div className="grid grid-cols-3 gap-2">
                {[
                  ["delivered_complete", "Completa", Check],
                  ["delivered_partial", "Parcial", Truck],
                  ["not_delivered", "Fallida", AlertTriangle],
                ].map(([value, label, Icon]) => (
                  <button key={value as string} type="button" onClick={() => setMode(value as ExecutionStatus)} className={`inline-flex min-h-10 items-center justify-center gap-1 rounded border px-2 text-[11px] font-semibold transition ${mode === value ? "border-primary bg-blue-50 text-primaryHover" : "border-borderSoft bg-white text-night hover:border-primary"}`}>
                    <Icon size={14} />
                    {label as string}
                  </button>
                ))}
              </div>

              {mode === "not_delivered" && (
                <label className="mt-3 grid gap-1 text-[11px] font-semibold text-secondaryText">
                  Motivo
                  <select value={reason} onChange={(event) => setReason(event.target.value)} className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20">
                    <option value="customer_absent">Cliente ausente</option>
                    <option value="rejected">Rechazo</option>
                    <option value="logistics_issue">Problema logistico</option>
                    <option value="other">Otro</option>
                  </select>
                </label>
              )}

              <div className="mt-3 grid gap-2">
                <div className="text-[11px] font-semibold uppercase text-secondaryText">Productos y rechazo</div>
                {activeStop.lines.map((line) => {
                  const delivered = mode === "delivered_complete" ? asNumber(line.quantity) : mode === "not_delivered" ? 0 : asNumber(lineValues[line.source_line_ref]);
                  const rejected = Math.max(0, asNumber(line.quantity) - delivered);
                  return (
                    <div key={line.id} className="rounded border border-borderSoft bg-white p-2">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate font-mono text-[12px] font-semibold text-night">{line.item_ref}</div>
                          <div className="truncate text-[11px] text-secondaryText">{line.item_name || "Sin descripcion"}</div>
                        </div>
                        <div className="font-mono text-[11px] text-secondaryText">{formatNumber(line.quantity)} {line.uom}</div>
                      </div>
                      <div className="mt-2 grid grid-cols-2 gap-2">
                        <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
                          Entregado
                          <input
                            type="number"
                            min="0"
                            max={line.quantity}
                            step="0.000001"
                            disabled={mode !== "delivered_partial"}
                            value={mode === "delivered_partial" ? lineValues[line.source_line_ref] ?? "0" : String(delivered)}
                            onChange={(event) => setLineValues({ ...lineValues, [line.source_line_ref]: event.target.value })}
                            className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
                          />
                        </label>
                        <div className="grid gap-1 text-[11px] font-semibold text-secondaryText">
                          Rechazado
                          <div className="flex h-9 items-center rounded border border-borderSoft bg-softStart px-2 font-mono text-[12px] text-night">
                            {formatNumber(rejected)} {line.uom}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <label className="mt-3 grid gap-1 text-[11px] font-semibold text-secondaryText">
                Observaciones
                <textarea value={observations} onChange={(event) => setObservations(event.target.value)} className="min-h-20 rounded border border-borderSoft bg-white px-2 py-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20" />
              </label>
            </div>
          ) : (
            <div className="px-3 py-6 text-[12px] text-secondaryText">Sin parada.</div>
          )}

          <div className="shrink-0 border-t border-borderSoft bg-white p-3">
            <button type="button" disabled={!canExecute} onClick={() => void submitExecution()} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover disabled:bg-softStart disabled:text-secondaryText">
              <Check size={15} />
              Registrar entrega
            </button>
            {!canExecute && <div className="mt-2 text-[11px] text-secondaryText">No disponible.</div>}
          </div>
        </aside>
      </section>
    </div>
  );
}
