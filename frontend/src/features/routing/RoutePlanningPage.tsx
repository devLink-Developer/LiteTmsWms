import { useEffect, useMemo, useState } from "react";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { AlertTriangle, Check, ClipboardCheck, MapPin, Navigation, Play, Route, Trash2, Truck } from "lucide-react";
import { MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";

import {
  confirmRoute,
  executeStop,
  fetchRouteSheet,
  fetchRouteSheets,
  fetchRoutingDeliveries,
  fetchVehicles,
  fetchWarehouseOptions,
  optimizeRoute,
  routeCommand,
  updateRouteStopOrder,
  type RouteSheet,
  type RouteSheetSummary,
  type RouteStop,
  type RoutingDelivery,
  type WarehouseOption,
} from "../../api/routing";
import { fetchDrivers } from "../../api/fleet";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { notify, useToastError } from "../../shared/components/toast";
import { translateStatusLabel } from "../../shared/utils/statusLabels";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";
import type { StatusTone } from "../../types/operations";

type StopExecutionStatus = "delivered_complete" | "delivered_partial" | "not_delivered";

const routeStatusTone: Record<string, StatusTone> = {
  draft: "neutral",
  planned: "info",
  assigned: "info",
  loading: "warning",
  in_transit: "info",
  closed: "success",
  closed_with_incident: "warning",
  cancelled: "danger",
};

const stopStatusTone: Record<string, StatusTone> = {
  planned: "neutral",
  allocated: "info",
  loaded: "warning",
  en_route: "info",
  delivered: "success",
  failed: "danger",
  rescheduled: "warning",
};

function asNumber(value: string | number | null | undefined) {
  const numberValue = Number(value ?? 0);
  return Number.isFinite(numberValue) ? numberValue : 0;
}

function formatNumber(value: string | number | null | undefined, maximumFractionDigits = 2) {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits }).format(asNumber(value));
}

function capacityPercent(used: string | number | null | undefined, limit: string | number | null | undefined) {
  const limitValue = asNumber(limit);
  if (limitValue <= 0) return 0;
  return (asNumber(used) / limitValue) * 100;
}

function barTone(percent: number) {
  if (percent > 100) return "bg-red-600";
  if (percent >= 90) return "bg-amber-500";
  return "bg-emerald-600";
}

function stopDisplayCode(stop: RouteStop) {
  return stop.delivery_number || stop.source_label || stop.sales_order_number || stop.source_ref.slice(0, 8);
}

function stopSecondaryCode(stop: RouteStop) {
  return stop.sales_order_number || stop.customer_ref || "";
}

function addressPart(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function stopAddressText(stop: RouteStop) {
  const address = stop.address_snapshot ?? {};
  const formatted = addressPart(address.formatted) || addressPart(address.description) || addressPart(address.reference);
  if (formatted) return formatted;
  const streetLine = [addressPart(address.street), addressPart(address.street_number)].filter(Boolean).join(" ");
  return [streetLine, addressPart(address.city), addressPart(address.state), addressPart(address.zip_code)].filter(Boolean).join(", ");
}

function stopCustomerName(stop: RouteStop) {
  const address = stop.address_snapshot ?? {};
  const candidates = [
    stop.customer_name,
    address.customer_name,
    address.name,
    address.receiver,
    address.attention_to,
    stop.customer_ref,
  ];
  return candidates.map(addressPart).find((value) => value && value !== stop.customer_ref) || stop.customer_ref || "Sin cliente";
}

function stopPosition(stop: RouteStop): [number, number] | null {
  const lat = Number(stop.lat);
  const lng = Number(stop.lng);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return [lat, lng];
}

function deliveryPosition(delivery: RoutingDelivery): [number, number] | null {
  const lat = Number(delivery.lat);
  const lng = Number(delivery.lng);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return [lat, lng];
}

function routeGeometryPositions(route: RouteSheet | null): [number, number][] {
  if (!route?.route_geometry || route.route_geometry.type !== "LineString") return [];
  return (route.route_geometry.coordinates ?? [])
    .map((coordinate) => {
      const lng = Number(coordinate[0]);
      const lat = Number(coordinate[1]);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
      return [lat, lng] as [number, number];
    })
    .filter(Boolean) as [number, number][];
}

function routeOriginPosition(route: RouteSheet | null): [number, number] | null {
  const origin = route?.preview_payload?.input?.origin;
  if (!origin || typeof origin !== "object") return null;
  const rawOrigin = origin as Record<string, unknown>;
  const lat = Number(rawOrigin.lat ?? rawOrigin.latitude);
  const lng = Number(rawOrigin.lng ?? rawOrigin.longitude);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return [lat, lng];
}

function markerIcon(label: number | string, tone: "planned" | "pending" | "done" | "failed") {
  const palette = {
    planned: "bg-primary text-white border-white",
    pending: "bg-amber-500 text-white border-white",
    done: "bg-emerald-600 text-white border-white",
    failed: "bg-red-600 text-white border-white",
  };
  return L.divIcon({
    className: "",
    html: `<div class="grid h-7 w-7 place-items-center rounded-full border-2 text-[11px] font-bold shadow ${palette[tone]}">${label}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

function StopMapLabel({ stop }: { stop: RouteStop }) {
  const customerName = stopCustomerName(stop);
  const address = stopAddressText(stop);
  return (
    <span className="block max-w-[260px]">
      <span className="block font-mono text-[11px] font-semibold text-night">
        {stop.sequence}. {stopDisplayCode(stop)}
      </span>
      <span className="mt-0.5 block text-[11px] font-semibold text-night">{customerName}</span>
      <span className="mt-0.5 block whitespace-normal text-[11px] leading-snug text-secondaryText">{address || "Sin direccion"}</span>
    </span>
  );
}

function BoundsSync({ route, deliveries }: { route: RouteSheet | null; deliveries: RoutingDelivery[] }) {
  const map = useMap();
  useEffect(() => {
    const routeStops = (route?.stops.map(stopPosition).filter(Boolean) ?? []) as [number, number][];
    const routeLine = routeGeometryPositions(route);
    const positions = route
      ? [...routeStops, ...routeLine]
      : (deliveries.map(deliveryPosition).filter(Boolean) as [number, number][]);
    if (positions.length) {
      map.fitBounds(positions, { padding: [32, 32], maxZoom: 14 });
    }
  }, [deliveries, map, route]);
  return null;
}

function SortableStopRow({
  stop,
  active,
  onSelect,
}: {
  stop: RouteStop;
  active: boolean;
  onSelect: (stop: RouteStop) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: stop.id });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };
  const address = stopAddressText(stop);
  const customerName = stopCustomerName(stop);
  return (
    <button
      ref={setNodeRef}
      style={style}
      type="button"
      onClick={() => onSelect(stop)}
      className={`flex w-full items-start gap-2 border-b border-borderSoft px-3 py-2 text-left transition hover:bg-softStart focus:outline-none focus:ring-2 focus:ring-inset focus:ring-primary/30 ${
        active ? "bg-white" : "bg-surface"
      }`}
      {...attributes}
      {...listeners}
    >
      <span className="grid h-7 w-7 shrink-0 place-items-center rounded bg-deep font-mono text-[11px] font-semibold text-white">
        {stop.sequence}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-mono text-[12px] font-semibold text-night">{stopDisplayCode(stop)}</span>
        <span className="mt-1 block truncate text-[11px] text-secondaryText">
          {stopSecondaryCode(stop) ? `${stopSecondaryCode(stop)} / ` : ""}
          {customerName}
        </span>
        <span className="mt-0.5 block truncate text-[11px] text-secondaryText">
          {address || "Sin direccion"}
        </span>
      </span>
      <StatusBadge label={stop.status} tone={stopStatusTone[stop.status] ?? "neutral"} />
    </button>
  );
}

function CapacityBar({
  label,
  used,
  limit,
  percent,
  unit,
}: {
  label: string;
  used: string | number;
  limit: string | number;
  percent: number;
  unit: string;
}) {
  const visualPercent = Math.min(Math.max(percent, 0), 100);
  return (
    <div className="grid gap-1">
      <div className="flex items-center justify-between gap-2 text-[11px]">
        <span className="font-semibold text-secondaryText">{label}</span>
        <span className="font-mono text-night">
          {formatNumber(used, unit === "m3" ? 3 : 1)} / {formatNumber(limit, unit === "m3" ? 3 : 1)} {unit}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded bg-softStart" aria-label={`${label} ${formatNumber(percent, 1)}%`}>
        <div className={`h-full rounded ${barTone(percent)}`} style={{ width: `${visualPercent}%` }} />
      </div>
    </div>
  );
}

export function RoutePlanningPage() {
  const queryClient = useQueryClient();
  const { authorizedWarehouses } = useWorkspaceStore();
  const today = new Date().toISOString().slice(0, 10);
  const [warehouse, setWarehouse] = useState("");
  const [plannedDate, setPlannedDate] = useState(today);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [route, setRoute] = useState<RouteSheet | null>(null);
  const [routeLoadId, setRouteLoadId] = useState("");
  const [activeStopId, setActiveStopId] = useState("");
  const [vehicleId, setVehicleId] = useState("");
  const [driverRef, setDriverRef] = useState("");
  const [openStopLabelIds, setOpenStopLabelIds] = useState<string[]>([]);
  const [originLabelOpen, setOriginLabelOpen] = useState(false);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const deliveriesQuery = useQuery({
    queryKey: ["routing-deliveries", warehouse, plannedDate, authorizedWarehouses.join(",")],
    queryFn: () => fetchRoutingDeliveries({ warehouse, plannedDate }),
  });
  const routeSheetsQuery = useQuery({
    queryKey: ["routing-open-routes", warehouse, plannedDate],
    queryFn: () =>
      fetchRouteSheets({
        warehouse,
        plannedDate,
        status: ["draft", "planned", "loading", "in_transit", "settlement_pending"],
      }),
  });
  const routeDetailQuery = useQuery({
    queryKey: ["routing-route-detail", routeLoadId],
    queryFn: () => fetchRouteSheet(routeLoadId),
    enabled: Boolean(routeLoadId),
  });
  const vehiclesQuery = useQuery({ queryKey: ["vehicles"], queryFn: fetchVehicles });
  const driversQuery = useQuery({ queryKey: ["drivers"], queryFn: fetchDrivers });
  const warehousesQuery = useQuery({ queryKey: ["routing-warehouses"], queryFn: fetchWarehouseOptions });

  const warehouseOptions = useMemo(() => {
    const masterByCode = new Map((warehousesQuery.data ?? []).map((option) => [option.warehouse_code, option]));
    const authorizedCodes = authorizedWarehouses.length
      ? authorizedWarehouses
      : (warehousesQuery.data ?? []).map((option) => option.warehouse_code).filter(Boolean);
    return Array.from(new Set(authorizedCodes))
      .map<WarehouseOption>((code) => masterByCode.get(code) ?? { warehouse_code: code })
      .sort((left, right) => left.warehouse_code.localeCompare(right.warehouse_code));
  }, [authorizedWarehouses, warehousesQuery.data]);

  useEffect(() => {
    if (warehouse && authorizedWarehouses.length && !authorizedWarehouses.includes(warehouse)) {
      setWarehouse("");
    }
  }, [authorizedWarehouses, warehouse]);

  useEffect(() => {
    const firstOpenRoute = routeSheetsQuery.data?.[0];
    if (!route && firstOpenRoute && routeLoadId !== firstOpenRoute.id) {
      setRouteLoadId(firstOpenRoute.id);
    }
  }, [route, routeLoadId, routeSheetsQuery.data]);

  useEffect(() => {
    const nextRoute = routeDetailQuery.data;
    if (!nextRoute) return;
    setRoute(nextRoute);
    setVehicleId(nextRoute.vehicle_id ?? "");
    setDriverRef(nextRoute.driver_ref || "");
    setActiveStopId(nextRoute.stops[0]?.id ?? "");
    setOpenStopLabelIds([]);
    setOriginLabelOpen(false);
    setMessage(nextRoute.status === "draft" ? "Hoja draft recuperada." : null);
  }, [routeDetailQuery.data]);

  const hasDraftRoute = useMemo(
    () => (routeSheetsQuery.data ?? []).some((summary) => summary.status === "draft"),
    [routeSheetsQuery.data],
  );
  const selectedDeliveries = useMemo(() => {
    const deliveries = deliveriesQuery.data ?? [];
    if (!selectedIds.length || hasDraftRoute) return deliveries.filter((delivery) => delivery.lat && delivery.lng);
    return deliveries.filter((delivery) => selectedIds.includes(delivery.id));
  }, [deliveriesQuery.data, hasDraftRoute, selectedIds]);
  const optimizationWarehouse =
    warehouse ||
    selectedDeliveries[0]?.warehouse_ref ||
    route?.warehouse_ref ||
    (authorizedWarehouses.length === 1 ? authorizedWarehouses[0] : "");

  const selectedVehicle = useMemo(
    () => (vehiclesQuery.data ?? []).find((vehicle) => vehicle.id === (vehicleId || route?.vehicle_id || "")) ?? null,
    [route?.vehicle_id, vehicleId, vehiclesQuery.data],
  );
  const capacity = useMemo(() => {
    if (!route || !selectedVehicle) return null;
    const weightPercent = capacityPercent(route.planned_weight_kg, selectedVehicle.max_weight_kg);
    const volumePercent = capacityPercent(route.planned_volume_m3, selectedVehicle.max_volume_m3);
    return {
      weightPercent,
      volumePercent,
      loadPercent: Math.max(weightPercent, volumePercent),
      exceeded: weightPercent > 100 || volumePercent > 100,
    };
  }, [route, selectedVehicle]);

  const activeStop = route?.stops.find((stop) => stop.id === activeStopId) ?? route?.stops[0] ?? null;
  const routePositions = route?.stops.map(stopPosition).filter(Boolean) as [number, number][] | undefined;
  const routeLinePositions = route ? routeGeometryPositions(route) : [];
  const originPosition = routeOriginPosition(route);
  const mapCenter = routePositions?.[0] ?? routeLinePositions[0] ?? [-34.6037, -58.3816];
  const canConfirm = Boolean(route && route.status === "draft" && route.stops.length > 0 && (vehicleId || route.vehicle_id) && !capacity?.exceeded);
  const missingCoords = (deliveriesQuery.data ?? []).filter((delivery) => !delivery.lat || !delivery.lng).length;

  const optimizeMutation = useMutation({
    mutationFn: () =>
      optimizeRoute({
        warehouse_ref: optimizationWarehouse,
        branch_ref: optimizationWarehouse,
        planned_date: plannedDate,
        vehicle_id: vehicleId || undefined,
        driver_ref: driverRef || undefined,
        deliveries: selectedDeliveries.map((delivery) => ({
          delivery_id: delivery.id,
          lat: delivery.lat,
          lng: delivery.lng,
        })),
      }),
    onSuccess: (nextRoute) => {
      setRoute(nextRoute);
      setRouteLoadId(nextRoute.id);
      setVehicleId(nextRoute.vehicle_id ?? vehicleId);
      setDriverRef(nextRoute.driver_ref || driverRef);
      setActiveStopId(nextRoute.stops[0]?.id ?? "");
      setOpenStopLabelIds([]);
      setOriginLabelOpen(false);
      setMessage("Preview generado.");
      void queryClient.invalidateQueries({ queryKey: ["routing-open-routes"] });
      void queryClient.invalidateQueries({ queryKey: ["routing-deliveries"] });
    },
  });

  const reorderMutation = useMutation({
    mutationFn: (nextStops: RouteStop[]) =>
      updateRouteStopOrder(
        route?.id ?? "",
        nextStops.map((stop, index) => ({
          id: stop.id,
          sequence: index + 1,
        })),
      ),
    onSuccess: (nextRoute) => {
      setRoute(nextRoute);
      setMessage("Orden revisado y guardado.");
    },
  });

  const removeStopMutation = useMutation({
    mutationFn: (stopId: string) => {
      const nextStops = (route?.stops ?? [])
        .filter((stop) => stop.id !== stopId)
        .map((stop, index) => ({
          id: stop.id,
          sequence: index + 1,
          lat: stop.lat,
          lng: stop.lng,
        }));
      return updateRouteStopOrder(route?.id ?? "", nextStops, [stopId]);
    },
    onSuccess: (nextRoute) => {
      setRoute(nextRoute);
      setActiveStopId(nextRoute.stops[0]?.id ?? "");
      setOpenStopLabelIds((current) => current.filter((stopId) => nextRoute.stops.some((stop) => stop.id === stopId)));
      setMessage("Parada quitada.");
      void queryClient.invalidateQueries({ queryKey: ["routing-deliveries"] });
      void queryClient.invalidateQueries({ queryKey: ["routing-open-routes"] });
    },
  });

  const confirmMutation = useMutation({
    mutationFn: () => confirmRoute(route?.id ?? "", { vehicle_id: vehicleId, driver_ref: driverRef, reviewed: true }),
    onSuccess: (nextRoute) => {
      setRoute(nextRoute);
      setMessage("Hoja de ruta confirmada.");
      void queryClient.invalidateQueries({ queryKey: ["routing-deliveries"] });
      void queryClient.invalidateQueries({ queryKey: ["routing-open-routes"] });
    },
  });

  const routeCommandMutation = useMutation({
    mutationFn: (command: "start-loading" | "depart" | "close") => routeCommand(route?.id ?? "", command),
    onSuccess: (nextRoute) => {
      setRoute(nextRoute);
      setMessage("Estado de hoja de ruta actualizado.");
      void queryClient.invalidateQueries({ queryKey: ["routing-open-routes"] });
    },
  });

  const executeMutation = useMutation({
    mutationFn: (status: StopExecutionStatus) =>
      executeStop({
        route_stop_id: activeStop?.id ?? "",
        status,
        reason: status === "not_delivered" ? "customer_absent" : "",
        lines: activeStop?.lines.map((line) => ({
          source_line_ref: line.source_line_ref,
          delivered_qty: status === "delivered_complete" ? line.quantity : status === "delivered_partial" ? String(asNumber(line.quantity) / 2) : "0",
        })),
      }),
    onSuccess: (nextRoute) => {
      setRoute(nextRoute);
      setMessage("Parada registrada.");
    },
  });

  function toggleDelivery(deliveryId: string) {
    setSelectedIds((current) =>
      current.includes(deliveryId) ? current.filter((id) => id !== deliveryId) : [...current, deliveryId],
    );
  }

  function loadRouteSheet(summary: RouteSheetSummary) {
    setRouteLoadId(summary.id);
    setSelectedIds([]);
    setOpenStopLabelIds([]);
    setOriginLabelOpen(false);
    setMessage(`Cargando ${summary.route_number}.`);
  }

  function toggleStopLabel(stopId: string) {
    setOpenStopLabelIds((current) => (current.includes(stopId) ? current.filter((id) => id !== stopId) : [...current, stopId]));
  }

  function onDragEnd(event: DragEndEvent) {
    if (!route || event.active.id === event.over?.id || !event.over) return;
    const oldIndex = route.stops.findIndex((stop) => stop.id === event.active.id);
    const newIndex = route.stops.findIndex((stop) => stop.id === event.over?.id);
    if (oldIndex < 0 || newIndex < 0) return;
    const nextStops = arrayMove(route.stops, oldIndex, newIndex).map((stop, index) => ({ ...stop, sequence: index + 1 }));
    setRoute({ ...route, stops: nextStops, reviewed_at: new Date().toISOString() });
    reorderMutation.mutate(nextStops);
  }

  function updateMarker(stop: RouteStop, lat: number, lng: number) {
    if (!route) return;
    const nextStops = route.stops.map((candidate) =>
      candidate.id === stop.id ? { ...candidate, lat: String(lat), lng: String(lng) } : candidate,
    );
    setRoute({ ...route, stops: nextStops, reviewed_at: new Date().toISOString() });
    void updateRouteStopOrder(
      route.id,
      nextStops.map((candidate, index) => ({
        id: candidate.id,
        sequence: index + 1,
        lat: candidate.lat,
        lng: candidate.lng,
      })),
    ).then(setRoute);
  }

  const busy =
    deliveriesQuery.isLoading ||
    routeSheetsQuery.isLoading ||
    routeDetailQuery.isLoading ||
    driversQuery.isLoading ||
    optimizeMutation.isPending ||
    reorderMutation.isPending ||
    removeStopMutation.isPending ||
    confirmMutation.isPending ||
    routeCommandMutation.isPending ||
    executeMutation.isPending;
  const error =
    deliveriesQuery.error ||
    routeSheetsQuery.error ||
    routeDetailQuery.error ||
    driversQuery.error ||
    vehiclesQuery.error ||
    warehousesQuery.error ||
    optimizeMutation.error ||
    reorderMutation.error ||
    removeStopMutation.error ||
    confirmMutation.error ||
    routeCommandMutation.error ||
    executeMutation.error;
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
          <h1 className="text-[20px] font-semibold text-night">Planificacion de reparto</h1>
          <div className="mt-1 flex flex-wrap gap-2 text-[12px] text-secondaryText">
            <span>{selectedDeliveries.length} entregas seleccionadas</span>
            <span>{missingCoords} sin coordenadas</span>
            {route && <span>{route.total_distance_km} km estimados</span>}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {route && <StatusBadge label={route.status} tone={routeStatusTone[route.status] ?? "neutral"} />}
          <button
            type="button"
            disabled={busy || !optimizationWarehouse || (!selectedDeliveries.length && !hasDraftRoute)}
            onClick={() => optimizeMutation.mutate()}
            className="inline-flex min-h-9 items-center gap-2 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:bg-softStart disabled:text-secondaryText"
          >
            <Route size={15} />
            Optimizar
          </button>
          <button
            type="button"
            disabled={!canConfirm || busy}
            onClick={() => confirmMutation.mutate()}
            className="inline-flex min-h-9 items-center gap-2 rounded bg-deep px-3 text-[12px] font-semibold text-white transition hover:bg-night focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:bg-softStart disabled:text-secondaryText"
          >
            <Check size={15} />
            Confirmar
          </button>
        </div>
      </header>

      <section className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(0,0.8fr)_minmax(0,1.4fr)_minmax(0,1fr)] gap-3 overflow-hidden xl:grid-cols-[340px_minmax(0,1fr)_380px] xl:grid-rows-1">
        <aside className="flex min-h-0 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="grid shrink-0 gap-2 border-b border-borderSoft bg-white p-3">
            <div className="grid grid-cols-2 gap-2">
              <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
                Deposito
                <select
                  value={warehouse}
                  onChange={(event) => setWarehouse(event.target.value)}
                  className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                >
                  <option value="">Todos habilitados</option>
                  {warehouseOptions.map((option) => (
                    <option key={option.warehouse_code} value={option.warehouse_code}>
                      {option.warehouse_code}
                      {option.warehouse_name ? ` / ${option.warehouse_name}` : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
                Fecha
                <input
                  type="date"
                  value={plannedDate}
                  onChange={(event) => setPlannedDate(event.target.value)}
                  className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                />
              </label>
            </div>
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Vehiculo
              <select
                value={vehicleId}
                onChange={(event) => setVehicleId(event.target.value)}
                className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
              >
                <option value="">Sin asignar</option>
                {(vehiclesQuery.data ?? []).map((vehicle) => (
                  <option key={vehicle.id} value={vehicle.id}>
                    {vehicle.code} / {vehicle.plate}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Chofer
              <select
                value={driverRef}
                onChange={(event) => setDriverRef(event.target.value)}
                className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
              >
                <option value="">Sin asignar</option>
                {(driversQuery.data ?? [])
                  .filter((driver) => driver.active)
                  .map((driver) => (
                    <option key={driver.id} value={driver.code}>
                      {driver.code} / {driver.full_name}
                    </option>
                  ))}
              </select>
            </label>
            {(routeSheetsQuery.data ?? []).length > 0 && (
              <div className="grid gap-2 border-t border-borderSoft pt-2">
                <div className="text-[11px] font-semibold text-secondaryText">Hojas abiertas</div>
                <div className="grid max-h-28 gap-1 overflow-auto">
                  {(routeSheetsQuery.data ?? []).map((summary) => {
                    const active = route?.id === summary.id;
                    return (
                      <button
                        key={summary.id}
                        type="button"
                        onClick={() => loadRouteSheet(summary)}
                        className={`flex min-h-9 items-center justify-between gap-2 rounded border px-2 text-left text-[11px] transition focus:outline-none focus:ring-2 focus:ring-primary/30 ${
                          active
                            ? "border-primary bg-blue-50 text-primaryHover"
                            : "border-borderSoft bg-white text-night hover:border-primary"
                        }`}
                      >
                        <span className="min-w-0">
                          <span className="block truncate font-mono font-semibold">{summary.route_number}</span>
                          <span className="block truncate text-secondaryText">
                            {summary.stops_count} paradas / {formatNumber(summary.planned_weight_kg)} kg
                          </span>
                        </span>
                        <StatusBadge label={summary.status} tone={routeStatusTone[summary.status] ?? "neutral"} />
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex min-h-10 shrink-0 items-center justify-between border-b border-borderSoft px-3 text-[12px] font-semibold text-night">
              <span>Entregas por rutear</span>
              <button
                type="button"
                onClick={() => setSelectedIds((deliveriesQuery.data ?? []).filter((delivery) => delivery.lat && delivery.lng).map((delivery) => delivery.id))}
                className="text-[11px] font-semibold text-primaryHover hover:text-primary"
              >
                Con coordenadas
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
              {(deliveriesQuery.data ?? []).map((delivery) => {
                const position = deliveryPosition(delivery);
                const selected = selectedIds.includes(delivery.id);
                return (
                  <button
                    key={delivery.id}
                    type="button"
                    disabled={!position}
                    onClick={() => toggleDelivery(delivery.id)}
                    className={`block w-full border-b border-borderSoft px-3 py-3 text-left transition hover:bg-softStart focus:outline-none focus:ring-2 focus:ring-inset focus:ring-primary/30 disabled:bg-softStart disabled:text-secondaryText ${
                      selected ? "bg-white" : "bg-surface"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate font-mono text-[12px] font-semibold text-night">{delivery.delivery_number}</div>
                        <div className="mt-1 truncate text-[11px] text-secondaryText">{delivery.customer_ref}</div>
                      </div>
                      <StatusBadge label={position ? "ubicada" : "sin coord."} tone={position ? "success" : "danger"} />
                    </div>
                    <div className="mt-2 flex gap-2 font-mono text-[11px] text-secondaryText">
                      <span>{formatNumber(delivery.planned_weight_kg)} kg</span>
                      <span>{formatNumber(delivery.planned_volume_m3, 4)} m3</span>
                    </div>
                  </button>
                );
              })}
              {!deliveriesQuery.data?.length && (
                <div className="px-3 py-6 text-[12px] text-secondaryText">
                  {deliveriesQuery.isLoading
                    ? "Cargando..."
                    : (routeSheetsQuery.data ?? []).length
                      ? "En hoja abierta."
                      : "Sin entregas."}
                </div>
              )}
            </div>
          </div>
        </aside>

        <main className="relative min-h-0 overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <MapContainer center={mapCenter} zoom={11} className="h-full w-full" scrollWheelZoom>
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <BoundsSync route={route} deliveries={deliveriesQuery.data ?? []} />
            {(routeLinePositions.length > 1 || (routePositions?.length ?? 0) > 1) && (
              <Polyline
                positions={routeLinePositions.length > 1 ? routeLinePositions : routePositions ?? []}
                pathOptions={{ color: "#1f6bb4", weight: 4 }}
              />
            )}
            {originPosition && (
              <Marker
                position={originPosition}
                icon={markerIcon("D", "planned")}
                eventHandlers={{ click: () => setOriginLabelOpen((current) => !current) }}
              >
                {originLabelOpen && (
                  <Tooltip direction="right" offset={[18, 0]} opacity={1} permanent className="route-origin-tooltip">
                    Origen {route?.warehouse_ref}
                  </Tooltip>
                )}
              </Marker>
            )}
            {(deliveriesQuery.data ?? []).map((delivery, index) => {
              const position = deliveryPosition(delivery);
              if (!position || route) return null;
              return (
                <Marker key={delivery.id} position={position} icon={markerIcon(index + 1, selectedIds.includes(delivery.id) ? "planned" : "pending")}>
                  <Tooltip direction="right" offset={[18, 0]}>
                    {delivery.delivery_number}
                  </Tooltip>
                </Marker>
              );
            })}
            {route?.stops.map((stop) => {
              const position = stopPosition(stop);
              if (!position) return null;
              const tone = stop.status === "delivered" ? "done" : stop.status === "failed" ? "failed" : "planned";
              return (
                <Marker
                  key={stop.id}
                  position={position}
                  draggable={route.status === "draft"}
                  icon={markerIcon(stop.sequence, tone)}
                  eventHandlers={{
                    click: () => {
                      setActiveStopId(stop.id);
                      toggleStopLabel(stop.id);
                    },
                    dragend: (event) => {
                      const point = event.target.getLatLng();
                      updateMarker(stop, point.lat, point.lng);
                    },
                  }}
                >
                  {openStopLabelIds.includes(stop.id) && (
                    <Tooltip direction="right" offset={[18, 0]} opacity={1} permanent className="route-stop-tooltip">
                      <StopMapLabel stop={stop} />
                    </Tooltip>
                  )}
                </Marker>
              );
            })}
          </MapContainer>
          <div className="absolute right-3 top-3 z-[400] flex flex-col items-end gap-2">
            <div className="rounded border border-borderSoft bg-white px-3 py-2 text-[12px] font-semibold text-night shadow-panel">
              {route ? `${route.route_number} / ${route.routing_provider}` : "Sin preview"}
            </div>
            {route?.preview_payload.routing_status && (
              <div className="rounded border border-borderSoft bg-white px-3 py-2 text-[12px] text-secondaryText shadow-panel">
                {translateStatusLabel(route.preview_payload.routing_status)}
              </div>
            )}
          </div>
        </main>

        <aside className="flex min-h-0 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="shrink-0 border-b border-borderSoft bg-white p-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-[13px] font-semibold text-night">Hoja de ruta</h2>
                <p className="mt-1 text-[11px] text-secondaryText">
                  {route ? `${route.stops.length} paradas / ${formatNumber(route.planned_weight_kg)} kg` : "Sin preview."}
                </p>
              </div>
              <Truck className="text-primary" size={18} />
            </div>
            {route && (
              <div
                className={`mt-3 rounded border p-3 ${
                  capacity?.exceeded ? "border-red-200 bg-red-50" : "border-borderSoft bg-surface"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-semibold uppercase text-secondaryText">Carga vehiculo</span>
                  <span className={`font-mono text-[13px] font-semibold ${capacity?.exceeded ? "text-red-700" : "text-night"}`}>
                    {capacity ? `${formatNumber(capacity.loadPercent, 1)}%` : "Sin vehiculo"}
                  </span>
                </div>
                {selectedVehicle && capacity ? (
                  <div className="mt-2 grid gap-2">
                    <CapacityBar
                      label="Peso"
                      used={route.planned_weight_kg}
                      limit={selectedVehicle.max_weight_kg}
                      percent={capacity.weightPercent}
                      unit="kg"
                    />
                    <CapacityBar
                      label="Volumen"
                      used={route.planned_volume_m3}
                      limit={selectedVehicle.max_volume_m3}
                      percent={capacity.volumePercent}
                      unit="m3"
                    />
                    {capacity.exceeded && (
                      <div className="text-[11px] font-semibold text-red-700">
                        La hoja excede la capacidad del vehiculo seleccionado.
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="mt-2 text-[11px] text-secondaryText">Sin vehiculo.</div>
                )}
              </div>
            )}
            {route && (
              <div className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
                <button
                  type="button"
                  disabled={route.status !== "planned" || busy}
                  onClick={() => routeCommandMutation.mutate("start-loading")}
                  className="inline-flex min-h-9 items-center justify-center gap-1 rounded border border-borderSoft bg-white px-2 font-semibold text-night transition hover:border-primary hover:text-primaryHover disabled:bg-softStart"
                >
                  <ClipboardCheck size={14} />
                  Carga
                </button>
                <button
                  type="button"
                  disabled={route.status !== "loading" || busy}
                  onClick={() => routeCommandMutation.mutate("depart")}
                  className="inline-flex min-h-9 items-center justify-center gap-1 rounded border border-borderSoft bg-white px-2 font-semibold text-night transition hover:border-primary hover:text-primaryHover disabled:bg-softStart"
                >
                  <Navigation size={14} />
                  Salida
                </button>
                <button
                  type="button"
                  disabled={route.status !== "in_transit" || busy}
                  onClick={() => routeCommandMutation.mutate("close")}
                  className="inline-flex min-h-9 items-center justify-center gap-1 rounded border border-borderSoft bg-white px-2 font-semibold text-night transition hover:border-primary hover:text-primaryHover disabled:bg-softStart"
                >
                  <Play size={14} />
                  Rendir
                </button>
              </div>
            )}
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            {route ? (
              <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
                <SortableContext items={route.stops.map((stop) => stop.id)} strategy={verticalListSortingStrategy}>
                  {route.stops.map((stop) => (
                    <SortableStopRow key={stop.id} stop={stop} active={activeStop?.id === stop.id} onSelect={setActiveStopId ? (nextStop) => setActiveStopId(nextStop.id) : () => undefined} />
                  ))}
                </SortableContext>
              </DndContext>
            ) : (
              <div className="px-3 py-6 text-[12px] text-secondaryText">Sin ruta.</div>
            )}
          </div>

          <div className="shrink-0 border-t border-borderSoft bg-white p-3">
            {activeStop ? (
              <>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-mono text-[13px] font-semibold text-night">
                      Parada {activeStop.sequence} / {stopDisplayCode(activeStop)}
                    </div>
                    <div className="mt-1 truncate text-[11px] text-secondaryText">
                      {activeStop.sales_order_number || activeStop.customer_ref || activeStop.source_ref}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {route?.status === "draft" && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => removeStopMutation.mutate(activeStop.id)}
                        className="inline-flex min-h-8 items-center gap-1 rounded border border-red-200 bg-red-50 px-2 text-[11px] font-semibold text-red-700 transition hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-red-500/20 disabled:bg-softStart disabled:text-secondaryText"
                      >
                        <Trash2 size={13} />
                        Quitar
                      </button>
                    )}
                    <MapPin className="text-primary" size={18} />
                  </div>
                </div>
                <dl className="mt-3 grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-[12px]">
                  <dt className="font-semibold text-secondaryText">Estado</dt>
                  <dd><StatusBadge label={activeStop.status} tone={stopStatusTone[activeStop.status] ?? "neutral"} /></dd>
                  <dt className="font-semibold text-secondaryText">Cliente</dt>
                  <dd className="min-w-0 text-night">{stopCustomerName(activeStop)}</dd>
                  <dt className="font-semibold text-secondaryText">Direccion</dt>
                  <dd className="min-w-0 text-night">{stopAddressText(activeStop) || "Sin direccion"}</dd>
                  <dt className="font-semibold text-secondaryText">Peso</dt>
                  <dd className="font-mono text-night">{formatNumber(activeStop.planned_weight_kg)} kg</dd>
                  <dt className="font-semibold text-secondaryText">Volumen</dt>
                  <dd className="font-mono text-night">{formatNumber(activeStop.planned_volume_m3, 4)} m3</dd>
                  <dt className="font-semibold text-secondaryText">Lineas</dt>
                  <dd className="font-mono text-night">{activeStop.lines.length}</dd>
                </dl>
                <div className="mt-3 grid grid-cols-3 gap-2">
                  <button
                    type="button"
                    disabled={route?.status !== "in_transit" || busy}
                    onClick={() => executeMutation.mutate("delivered_complete")}
                    className="min-h-9 rounded bg-primary px-2 text-[11px] font-semibold text-white transition hover:bg-primaryHover disabled:bg-softStart disabled:text-secondaryText"
                  >
                    Completa
                  </button>
                  <button
                    type="button"
                    disabled={route?.status !== "in_transit" || busy}
                    onClick={() => executeMutation.mutate("delivered_partial")}
                    className="min-h-9 rounded border border-borderSoft bg-white px-2 text-[11px] font-semibold text-night transition hover:border-primary hover:text-primaryHover disabled:bg-softStart"
                  >
                    Parcial
                  </button>
                  <button
                    type="button"
                    disabled={route?.status !== "in_transit" || busy}
                    onClick={() => executeMutation.mutate("not_delivered")}
                    className="inline-flex min-h-9 items-center justify-center gap-1 rounded border border-red-200 bg-red-50 px-2 text-[11px] font-semibold text-red-700 transition hover:bg-red-100 disabled:bg-softStart disabled:text-secondaryText"
                  >
                    <AlertTriangle size={13} />
                    Fallida
                  </button>
                </div>
              </>
            ) : (
              <div className="text-[12px] text-secondaryText">Sin parada.</div>
            )}
          </div>
        </aside>
      </section>
    </div>
  );
}
