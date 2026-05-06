from __future__ import annotations

import json
import hashlib
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.core.models import AuditTrail, DomainEventOutbox, IdempotencyKey, StatusHistory
from apps.core.sequences import allocate_sequence_number
from apps.fulfillment.delivery_modes import is_shipping_delivery_mode, shipping_delivery_mode_q
from apps.fulfillment.models import DeliveryDocument, DeliveryExecution, DeliveryOrder, DeliveryOrderLine, FulfillmentOrder
from apps.fulfillment.services import (
    FulfillmentRuleError,
    IdempotentResult,
    issue_remito,
    physical_delivery_lines,
    physical_delivery_lines_from_snapshots,
    refresh_delivery_capacity_from_master,
    _resolve_line_item_snapshots,
)
from apps.inventory.models import InventoryLedgerEntry, StockState
from apps.inventory.services import move_prepared_stock_to_state, move_transit_stock_to_state
from apps.logistics.parquet_master_data import warehouse_origin_snapshot
from apps.routes.models import RouteOptimizationRun, RouteRendition, RouteRenditionLine, RouteSheet, RouteStop, RouteStopLine
from apps.vehicles.models import Vehicle


ROUTE_SEQUENCE_NAME = "Hojas de Ruta"
ROUTABLE_DELIVERY_STATUSES = [
    DeliveryOrder.DeliveryStatus.CONFIRMED,
    DeliveryOrder.DeliveryStatus.PREPARED,
]


class RouteRuleError(ValueError):
    pass


class RouteCapacityError(RouteRuleError):
    pass


ZERO = Decimal("0")


@dataclass(frozen=True)
class RouteStopDraft:
    source_type: str
    source_ref: str
    stop_type: str
    customer_ref: str
    address_snapshot: dict
    latitude: Decimal
    longitude: Decimal
    planned_weight_kg: Decimal
    planned_volume_m3: Decimal
    lines: list[dict]


def _decimal(value, default: str = "0") -> Decimal:
    if value in [None, ""]:
        try:
            return Decimal(default)
        except (InvalidOperation, ValueError):
            return ZERO
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _hash_payload(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _start_idempotent_command(
    *,
    key: str,
    operation_type: str,
    reference_type: str,
    reference_id: str,
    payload: dict,
) -> tuple[IdempotencyKey, bool]:
    request_hash = _hash_payload(payload)
    existing = IdempotencyKey.objects.filter(key=key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise RouteRuleError("La Idempotency-Key ya fue usada con otro payload.")
        return existing, True
    return (
        IdempotencyKey.objects.create(
            key=key,
            operation_type=operation_type,
            reference_type=reference_type,
            reference_id=reference_id,
            request_hash=request_hash,
        ),
        False,
    )


def _finish_idempotent_command(record: IdempotencyKey, result: IdempotentResult) -> IdempotentResult:
    record.response_payload = result.payload
    record.response_status = result.status
    record.status = IdempotencyKey.ProcessingStatus.SUCCEEDED
    record.save(update_fields=["response_payload", "response_status", "status", "updated_at"])
    return result


def _actor_payload(actor: str, reason: str = "") -> dict:
    return {"actor": actor, "reason": reason}


def _status_history(entity_type: str, entity_id: str, from_status: str, to_status: str, actor: str, reason: str, payload=None) -> None:
    StatusHistory.objects.create(
        entity_type=entity_type,
        entity_id=entity_id,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        reason=reason,
        payload=payload or {},
    )


def _address_coordinates(address: dict) -> tuple[Decimal | None, Decimal | None]:
    lat = _decimal(address.get("latitude") or address.get("lat"), "")
    lng = _decimal(address.get("longitude") or address.get("lng") or address.get("lon"), "")
    if lat == ZERO and lng == ZERO and not any(address.get(key) for key in ["latitude", "lat", "longitude", "lng", "lon"]):
        return None, None
    return lat, lng


def _configured_warehouse_origin(warehouse_ref: str) -> tuple[tuple[Decimal, Decimal] | None, dict]:
    origins = getattr(settings, "WAREHOUSE_ORIGINS", {}) or {}
    if not isinstance(origins, dict):
        return None, {}
    warehouse_key = str(warehouse_ref or "").strip()
    candidates = [warehouse_key, warehouse_key.upper(), warehouse_key.lower()]
    snapshot = next((origins.get(candidate) for candidate in candidates if candidate in origins), None)
    if not isinstance(snapshot, dict):
        return None, {}
    snapshot = dict(snapshot)
    snapshot.setdefault("warehouse_ref", warehouse_key)
    snapshot.setdefault("source", "settings.WAREHOUSE_ORIGINS")
    origin = _address_coordinates(snapshot)
    if origin[0] is None or origin[1] is None:
        return None, snapshot
    snapshot["latitude"] = str(origin[0])
    snapshot["longitude"] = str(origin[1])
    snapshot.setdefault("geo_source", snapshot.get("source") or "settings.WAREHOUSE_ORIGINS")
    return (origin[0], origin[1]), snapshot


def _clean_origin_street(value: str) -> str:
    text = str(value or "").strip()
    if " - " in text:
        return text.rsplit(" - ", 1)[-1].strip()
    if text.lower().startswith("unimaco") and "-" in text:
        return text.split("-", 1)[-1].strip()
    return text


def _origin_geocode_text(snapshot: dict) -> str:
    street = _clean_origin_street(str(snapshot.get("street") or ""))
    street_number = str(snapshot.get("street_number") or "").strip()
    city = str(snapshot.get("city") or "").strip()
    state = str(snapshot.get("state_name") or snapshot.get("state") or "").strip()
    zip_code = str(snapshot.get("zip_code") or snapshot.get("zip") or "").strip()
    country = str(snapshot.get("country") or "ARG").strip()
    street_line = " ".join(part for part in [street, street_number] if part)
    parts = [street_line, city, state, zip_code, country]
    return ", ".join(part for part in parts if part)


def _geocode_origin_snapshot(snapshot: dict) -> tuple[Decimal | None, Decimal | None]:
    query = _origin_geocode_text(snapshot)
    if not settings.ORS_API_KEY or not query:
        return None, None
    url = f"{settings.ORS_BASE_URL.rstrip('/')}/geocode/search?{urllib.parse.urlencode({'text': query, 'boundary.country': 'ARG', 'size': '1'})}"
    request = urllib.request.Request(
        url,
        headers={"Authorization": settings.ORS_API_KEY, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        coordinates = payload.get("features", [{}])[0].get("geometry", {}).get("coordinates", [])
        if len(coordinates) < 2:
            return None, None
        lng = _decimal(coordinates[0], "")
        lat = _decimal(coordinates[1], "")
        if lat == ZERO and lng == ZERO:
            return None, None
        snapshot["latitude"] = str(lat)
        snapshot["longitude"] = str(lng)
        snapshot["geo_source"] = "ors_geocode"
        snapshot["geocode_query"] = query
        return lat, lng
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError, IndexError, json.JSONDecodeError):
        snapshot["geo_source"] = "unresolved"
        snapshot["geocode_query"] = query
        return None, None


def _warehouse_origin(warehouse_ref: str) -> tuple[tuple[Decimal, Decimal] | None, dict]:
    configured_origin, configured_snapshot = _configured_warehouse_origin(warehouse_ref)
    if configured_origin is not None:
        return configured_origin, configured_snapshot
    snapshot = warehouse_origin_snapshot(warehouse_ref)
    origin = _address_coordinates(snapshot)
    if origin[0] is None or origin[1] is None:
        origin = _geocode_origin_snapshot(snapshot)
    if origin[0] is None or origin[1] is None:
        return None, snapshot
    snapshot["latitude"] = str(origin[0])
    snapshot["longitude"] = str(origin[1])
    return (origin[0], origin[1]), snapshot


def _origin_payload(origin: tuple[Decimal, Decimal] | None, snapshot: dict) -> dict:
    payload = dict(snapshot or {})
    if origin is not None:
        payload["lat"] = str(origin[0])
        payload["lng"] = str(origin[1])
    return payload


def _clean_text(value) -> str:
    return str(value or "").strip()


def _delivery_customer_name(delivery: DeliveryOrder | None, fallback: str = "") -> str:
    if delivery is None:
        return fallback
    customer_ref = _clean_text(getattr(delivery.fulfillment, "customer_ref", "")) or fallback
    snapshots = [delivery.fulfillment.address_snapshot or {}, delivery.address_snapshot or {}]
    for snapshot in snapshots:
        for key in ["customer_name", "name", "receiver", "attention_to"]:
            value = _clean_text(snapshot.get(key))
            if value and value != customer_ref:
                return value
    return customer_ref


def _delivery_is_reparto(delivery: DeliveryOrder) -> bool:
    return is_shipping_delivery_mode(delivery.delivery_mode)


def _delivery_stop_draft(delivery: DeliveryOrder, payload_stop: dict | None = None) -> RouteStopDraft | None:
    payload_stop = payload_stop or {}
    address = dict(delivery.address_snapshot or {})
    if payload_stop.get("address_snapshot"):
        address.update(payload_stop["address_snapshot"])
    lat = _decimal(payload_stop.get("lat") or payload_stop.get("latitude"), "")
    lng = _decimal(payload_stop.get("lng") or payload_stop.get("longitude"), "")
    if lat == ZERO and lng == ZERO:
        address_lat, address_lng = _address_coordinates(address)
        lat = address_lat if address_lat is not None else lat
        lng = address_lng if address_lng is not None else lng
    if lat == ZERO and lng == ZERO:
        return None
    refresh_delivery_capacity_from_master(delivery, actor="routing")
    lines = []
    planned_weight = ZERO
    planned_volume = ZERO
    delivery_lines = physical_delivery_lines(list(delivery.lines.select_related("fulfillment_line").all()))
    for line in delivery_lines:
        weight = _decimal(line.planned_weight_kg)
        volume = _decimal(line.planned_volume_m3)
        planned_weight += weight
        planned_volume += volume
        lines.append(
            {
                "delivery_ref": str(delivery.id),
                "source_line_ref": str(line.id),
                "quantity": line.planned_qty,
                "uom": line.uom,
                "weight_kg": weight,
                "volume_m3": volume,
                "item_ref": line.item_ref,
                "warehouse_ref": line.warehouse_ref or delivery.warehouse_ref,
                "legacy_sales_order_number": line.legacy_sales_order_number,
                "legacy_line_id": line.legacy_line_id,
            }
        )
    if not lines:
        return None
    return RouteStopDraft(
        source_type="delivery_order",
        source_ref=str(delivery.id),
        stop_type=RouteStop.StopType.DELIVERY,
        customer_ref=delivery.fulfillment.customer_ref,
        address_snapshot=address,
        latitude=lat,
        longitude=lng,
        planned_weight_kg=planned_weight,
        planned_volume_m3=planned_volume,
        lines=lines,
    )


def _distance_km(a: tuple[Decimal, Decimal], b: tuple[Decimal, Decimal]) -> Decimal:
    lat1 = float(a[0])
    lon1 = float(a[1])
    lat2 = float(b[0])
    lon2 = float(b[1])
    radius = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    h = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return Decimal(str(2 * radius * math.atan2(math.sqrt(h), math.sqrt(1 - h)))).quantize(Decimal("0.001"))


def _nearest_neighbor(origin: tuple[Decimal, Decimal] | None, stops: list[RouteStopDraft]) -> list[RouteStopDraft]:
    if not stops:
        return []
    if origin is None:
        return sorted(stops, key=lambda stop: (stop.latitude, stop.longitude, stop.source_ref))
    remaining = stops[:]
    ordered = []
    current = origin
    while remaining:
        next_stop = min(remaining, key=lambda stop: _distance_km(current, (stop.latitude, stop.longitude)))
        ordered.append(next_stop)
        remaining.remove(next_stop)
        current = (next_stop.latitude, next_stop.longitude)
    return ordered


def _fallback_ordered_route(
    origin: tuple[Decimal, Decimal] | None,
    ordered,
    *,
    routing_status: str = "fallback_no_ors_key",
) -> dict:
    distance = ZERO
    current = origin
    coordinates = []
    if origin is not None:
        coordinates.append([float(origin[1]), float(origin[0])])
    for stop in ordered:
        if stop.latitude is None or stop.longitude is None:
            continue
        point = (stop.latitude, stop.longitude)
        coordinates.append([float(stop.longitude), float(stop.latitude)])
        if current is not None:
            distance += _distance_km(current, point)
        current = point
    service_minutes = int(settings.ROUTING_SERVICE_MINUTES_PER_STOP) * len(ordered)
    travel_minutes = int((distance / Decimal("40") * Decimal("60")).quantize(Decimal("1"))) if distance else 0
    return {
        "ordered": ordered,
        "distance_km": distance,
        "time_minutes": travel_minutes + service_minutes,
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "provider": "manual",
        "routing_status": routing_status,
    }


def _geometry_with_origin_coordinate(geometry: dict, origin: tuple[Decimal, Decimal] | None) -> dict:
    if origin is None or geometry.get("type") != "LineString":
        return geometry
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        return geometry
    origin_coordinate = [float(origin[1]), float(origin[0])]
    if not coordinates:
        return {**geometry, "coordinates": [origin_coordinate]}
    return {**geometry, "coordinates": [origin_coordinate, *coordinates[1:]]}


def _fallback_route(origin: tuple[Decimal, Decimal] | None, stops: list[RouteStopDraft]) -> dict:
    ordered = _nearest_neighbor(origin, stops)
    return _fallback_ordered_route(origin, ordered)


def _ors_ordered_route(origin: tuple[Decimal, Decimal] | None, ordered) -> dict:
    if not settings.ORS_API_KEY:
        return _fallback_ordered_route(origin, ordered, routing_status="fallback_no_ors_key")
    coordinates = []
    if origin is not None:
        coordinates.append([float(origin[1]), float(origin[0])])
    coordinates.extend(
        [[float(stop.longitude), float(stop.latitude)] for stop in ordered if stop.latitude is not None and stop.longitude is not None]
    )
    if len(coordinates) < 2:
        return _fallback_ordered_route(origin, ordered, routing_status="fallback_insufficient_points")
    request = urllib.request.Request(
        f"{settings.ORS_BASE_URL.rstrip('/')}/v2/directions/driving-car/geojson",
        data=json.dumps({"coordinates": coordinates}).encode("utf-8"),
        headers={"Authorization": settings.ORS_API_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        summary = payload.get("features", [{}])[0].get("properties", {}).get("summary", {})
        distance = (Decimal(str(summary.get("distance", 0))) / Decimal("1000")).quantize(Decimal("0.001"))
        travel_minutes = int(Decimal(str(summary.get("duration", 0))) / Decimal("60"))
        return {
            "ordered": ordered,
            "distance_km": distance,
            "time_minutes": travel_minutes + int(settings.ROUTING_SERVICE_MINUTES_PER_STOP) * len(ordered),
            "geometry": _geometry_with_origin_coordinate(payload.get("features", [{}])[0].get("geometry", {}), origin),
            "provider": "ors",
            "routing_status": "optimized",
        }
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError, IndexError):
        return _fallback_ordered_route(origin, ordered, routing_status="fallback_ors_unavailable")


def _ors_route(origin: tuple[Decimal, Decimal] | None, stops: list[RouteStopDraft]) -> dict:
    ordered = _nearest_neighbor(origin, stops)
    return _ors_ordered_route(origin, ordered)


def _geometry_coordinate_count(route: RouteSheet) -> int:
    geometry = route.route_geometry or {}
    if geometry.get("type") != "LineString":
        return 0
    coordinates = geometry.get("coordinates") or []
    return len(coordinates) if isinstance(coordinates, list) else 0


def _route_geometry_needs_refresh(route: RouteSheet, stops: list[RouteStop]) -> bool:
    if not settings.ORS_API_KEY or len(stops) < 2:
        return False
    routing_status = str((route.preview_payload or {}).get("routing_status") or "")
    coordinate_count = _geometry_coordinate_count(route)
    return coordinate_count <= len(stops) or routing_status.startswith("fallback")


def _refresh_route_geometry_if_needed(route_id: str) -> None:
    if not settings.ORS_API_KEY:
        return
    with transaction.atomic():
        route = RouteSheet.objects.select_for_update().get(id=route_id)
        if route.status not in [
            RouteSheet.RouteStatus.DRAFT,
            RouteSheet.RouteStatus.PLANNED,
            RouteSheet.RouteStatus.ASSIGNED,
            RouteSheet.RouteStatus.LOADING,
            RouteSheet.RouteStatus.IN_TRANSIT,
            RouteSheet.RouteStatus.SETTLEMENT_PENDING,
        ]:
            return
        stops = list(route.stops.select_for_update().order_by("sequence"))
        if not _route_geometry_needs_refresh(route, stops):
            return
        _refresh_route_metrics_from_stops(route)
        route.save(update_fields=[
            "planned_weight_kg",
            "planned_volume_m3",
            "total_distance_km",
            "total_time_minutes",
            "routing_provider",
            "route_geometry",
            "preview_payload",
            "updated_at",
        ])


def _serialize_route(route: RouteSheet) -> dict:
    _refresh_route_geometry_if_needed(str(route.id))
    route = (
        RouteSheet.objects.select_related("vehicle", "vehicle__capacity_profile")
        .prefetch_related("stops__lines")
        .get(id=route.id)
    )
    stops = list(route.stops.all().order_by("sequence"))
    delivery_ids = [
        stop.source_ref
        for stop in stops
        if stop.source_type == "delivery_order" and stop.source_ref
    ]
    deliveries_by_id = {
        str(delivery.id): delivery
        for delivery in DeliveryOrder.objects.select_related("fulfillment").filter(id__in=delivery_ids)
    }
    route_lines = [line for stop in stops for line in stop.lines.all()]
    delivery_line_ids = [line.source_line_ref for line in route_lines if line.source_line_ref]
    delivery_lines_by_id = {
        str(line.id): line
        for line in DeliveryOrderLine.objects.filter(id__in=delivery_line_ids).only("id", "item_snapshot")
    }
    return {
        "id": str(route.id),
        "route_number": route.route_number,
        "status": route.status,
        "branch_ref": route.branch_ref,
        "warehouse_ref": route.warehouse_ref,
        "vehicle_id": str(route.vehicle_id) if route.vehicle_id else None,
        "vehicle": route.vehicle.code if route.vehicle else None,
        "driver_ref": route.driver_ref,
        "planned_date": route.planned_date.isoformat(),
        "planned_weight_kg": str(route.planned_weight_kg),
        "planned_volume_m3": str(route.planned_volume_m3),
        "loaded_weight_kg": str(route.loaded_weight_kg),
        "loaded_volume_m3": str(route.loaded_volume_m3),
        "total_distance_km": str(route.total_distance_km),
        "total_time_minutes": route.total_time_minutes,
        "routing_provider": route.routing_provider,
        "reviewed_at": route.reviewed_at.isoformat() if route.reviewed_at else None,
        "route_geometry": route.route_geometry,
        "preview_payload": route.preview_payload,
        "stops": [
            {
                "id": str(stop.id),
                "sequence": stop.sequence,
                "status": stop.status,
                "stop_type": stop.stop_type,
                "source_type": stop.source_type,
                "source_ref": stop.source_ref,
                "source_label": (
                    deliveries_by_id.get(stop.source_ref).delivery_number
                    if deliveries_by_id.get(stop.source_ref)
                    else stop.source_ref
                ),
                "delivery_number": (
                    deliveries_by_id.get(stop.source_ref).delivery_number
                    if deliveries_by_id.get(stop.source_ref)
                    else ""
                ),
                "sales_order_number": (
                    deliveries_by_id.get(stop.source_ref).legacy_sales_order_number
                    if deliveries_by_id.get(stop.source_ref)
                    else stop.legacy_sales_order_number
                ),
                "delivery_mode": (
                    deliveries_by_id.get(stop.source_ref).delivery_mode
                    if deliveries_by_id.get(stop.source_ref)
                    else ""
                ),
                "customer_ref": stop.customer_ref,
                "customer_name": _delivery_customer_name(deliveries_by_id.get(stop.source_ref), stop.customer_ref),
                "address_snapshot": stop.address_snapshot,
                "lat": str(stop.latitude) if stop.latitude is not None else None,
                "lng": str(stop.longitude) if stop.longitude is not None else None,
                "planned_weight_kg": str(stop.planned_weight_kg),
                "planned_volume_m3": str(stop.planned_volume_m3),
                "outcome_status": stop.outcome_status,
                "outcome_reason": stop.outcome_reason,
                "lines": [
                    {
                        "id": str(line.id),
                        "delivery_ref": line.delivery_ref,
                        "source_line_ref": line.source_line_ref,
                        "item_ref": line.item_ref,
                        "item_name": (delivery_lines_by_id.get(line.source_line_ref).item_snapshot or {}).get("name", "")
                        if delivery_lines_by_id.get(line.source_line_ref)
                        else "",
                        "quantity": str(line.quantity),
                        "delivered_qty": str(line.delivered_qty),
                        "returned_qty": str(line.returned_qty),
                        "difference_qty": str(line.difference_qty),
                        "uom": line.uom,
                        "warehouse_ref": line.warehouse_ref,
                    }
                    for line in stop.lines.all()
                ],
            }
            for stop in stops
        ],
    }


def serialize_route_sheet(route: RouteSheet) -> dict:
    return _serialize_route(route)


def pending_reparto_deliveries(*, warehouse_ref: str = "", planned_date=None, authorized_warehouses=None) -> list[dict]:
    authorized_warehouse_set = {
        str(warehouse).strip()
        for warehouse in (authorized_warehouses or [])
        if str(warehouse).strip()
    }
    qs = (
        DeliveryOrder.objects.select_related("fulfillment")
        .prefetch_related("lines__fulfillment_line")
        .filter(status__in=ROUTABLE_DELIVERY_STATUSES)
        .filter(shipping_delivery_mode_q())
        .order_by("planned_date", "delivery_number")
    )
    if warehouse_ref:
        qs = qs.filter(warehouse_ref=warehouse_ref)
    elif authorized_warehouse_set:
        qs = qs.filter(warehouse_ref__in=authorized_warehouse_set)
    if planned_date:
        qs = qs.filter(planned_date=planned_date)
    deliveries = list(qs[:200])
    delivery_ids = [str(delivery.id) for delivery in deliveries]
    all_lines = [line for delivery in deliveries for line in list(delivery.lines.all())]
    item_snapshots = _resolve_line_item_snapshots([line.fulfillment_line for line in all_lines])
    results = []
    routed_delivery_ids = set(
        RouteStopLine.objects.filter(delivery_ref__in=delivery_ids)
        .exclude(stop__route__status__in=[RouteSheet.RouteStatus.CANCELLED, RouteSheet.RouteStatus.CLOSED])
        .values_list("delivery_ref", flat=True)
    )
    for delivery in deliveries:
        if not _delivery_is_reparto(delivery) or str(delivery.id) in routed_delivery_ids:
            continue
        delivery_lines = physical_delivery_lines_from_snapshots(list(delivery.lines.all()), item_snapshots)
        if not delivery_lines:
            continue
        lat, lng = _address_coordinates(delivery.address_snapshot or {})
        results.append(
            {
                "id": str(delivery.id),
                "delivery_number": delivery.delivery_number,
                "status": delivery.status,
                "delivery_mode": delivery.delivery_mode,
                "planned_date": delivery.planned_date.isoformat() if delivery.planned_date else None,
                "warehouse_ref": delivery.warehouse_ref,
                "customer_ref": delivery.fulfillment.customer_ref,
                "sales_order_number": delivery.legacy_sales_order_number,
                "address_snapshot": delivery.address_snapshot,
                "lat": str(lat) if lat is not None else None,
                "lng": str(lng) if lng is not None else None,
                "planned_weight_kg": str(sum((line.planned_weight_kg for line in delivery_lines), ZERO)),
                "planned_volume_m3": str(sum((line.planned_volume_m3 for line in delivery_lines), ZERO)),
            }
        )
    return results


@transaction.atomic
def validate_route_capacity(route: RouteSheet, *, allow_override: bool = False) -> RouteSheet:
    if not route.vehicle:
        raise RouteCapacityError("La hoja de ruta no tiene vehiculo asignado.")
    profile = route.vehicle.capacity_profile
    stops = route.stops.select_for_update().all()
    planned_weight = sum((stop.planned_weight_kg for stop in stops), ZERO)
    planned_volume = sum((stop.planned_volume_m3 for stop in stops), ZERO)
    route.planned_weight_kg = planned_weight
    route.planned_volume_m3 = planned_volume
    if (planned_weight > profile.max_weight_kg or planned_volume > profile.max_volume_m3) and not allow_override:
        route.save(update_fields=["planned_weight_kg", "planned_volume_m3", "updated_at"])
        raise RouteCapacityError("La hoja de ruta excede la capacidad del vehiculo.")
    route.status = RouteSheet.RouteStatus.CAPACITY_CHECKED
    route.save(update_fields=["planned_weight_kg", "planned_volume_m3", "status", "updated_at"])
    return route


def _source_deliveries_from_payload(payload: dict) -> tuple[list[RouteStopDraft], list[dict]]:
    delivery_payloads = payload.get("deliveries") or []
    delivery_ids = [str(row.get("delivery_id") or row.get("id") or row) for row in delivery_payloads]
    delivery_payload_by_id = {
        str(row.get("delivery_id") or row.get("id")): row
        for row in delivery_payloads
        if isinstance(row, dict)
    }
    deliveries = (
        DeliveryOrder.objects.select_for_update()
        .select_related("fulfillment")
        .prefetch_related("lines")
        .filter(id__in=delivery_ids)
    )
    drafts = []
    excluded = []
    for delivery in deliveries:
        if delivery.status not in ROUTABLE_DELIVERY_STATUSES:
            raise RouteRuleError("Solo entregas confirmadas o preparadas pueden rutearse.")
        if not _delivery_is_reparto(delivery):
            raise RouteRuleError("Solo entregas de reparto pueden rutearse.")
        draft = _delivery_stop_draft(delivery, delivery_payload_by_id.get(str(delivery.id)))
        if draft is None:
            excluded.append(
                {
                    "source_type": "delivery_order",
                    "source_ref": str(delivery.id),
                    "delivery_number": delivery.delivery_number,
                    "reason": "missing_coordinates",
                }
            )
            continue
        drafts.append(draft)
    return drafts, excluded


def _delivery_id_from_payload(row) -> str:
    if isinstance(row, dict):
        return str(row.get("delivery_id") or row.get("id") or "").strip()
    return str(row or "").strip()


def _merge_delivery_payloads(*payload_groups: list[dict]) -> list[dict]:
    delivery_payload_by_id: dict[str, dict] = {}
    ordered_ids = []
    for payloads in payload_groups:
        for row in payloads:
            delivery_id = _delivery_id_from_payload(row)
            if not delivery_id:
                continue
            if delivery_id not in delivery_payload_by_id:
                ordered_ids.append(delivery_id)
                delivery_payload_by_id[delivery_id] = {"delivery_id": delivery_id}
            if isinstance(row, dict):
                delivery_payload_by_id[delivery_id].update(row)
            else:
                delivery_payload_by_id[delivery_id]["delivery_id"] = delivery_id
    return [delivery_payload_by_id[delivery_id] for delivery_id in ordered_ids]


def _draft_route_delivery_payloads(*, warehouse_ref: str, planned_date) -> tuple[list[RouteSheet], list[dict]]:
    draft_routes = list(
        RouteSheet.objects.select_for_update()
        .prefetch_related("stops")
        .filter(
            warehouse_ref=warehouse_ref,
            planned_date=planned_date,
            status=RouteSheet.RouteStatus.DRAFT,
        )
        .order_by("created_at")
    )
    delivery_payloads = []
    for route in draft_routes:
        for stop in route.stops.all():
            if stop.source_type != "delivery_order" or not stop.source_ref:
                continue
            delivery_payloads.append(
                {
                    "delivery_id": stop.source_ref,
                    "lat": str(stop.latitude) if stop.latitude is not None else None,
                    "lng": str(stop.longitude) if stop.longitude is not None else None,
                }
            )
    return draft_routes, delivery_payloads


def _cancel_superseded_draft_routes(*, draft_routes: list[RouteSheet], superseded_by: RouteSheet, actor: str) -> None:
    for draft_route in draft_routes:
        draft_route.status = RouteSheet.RouteStatus.CANCELLED
        draft_route.updated_by = actor
        preview_payload = dict(draft_route.preview_payload or {})
        preview_payload["superseded_by"] = str(superseded_by.id)
        draft_route.preview_payload = preview_payload
        draft_route.save(update_fields=["status", "preview_payload", "updated_by", "updated_at"])
        _status_history(
            "route_sheet",
            str(draft_route.id),
            RouteSheet.RouteStatus.DRAFT,
            RouteSheet.RouteStatus.CANCELLED,
            actor,
            "Reoptimizacion de reparto",
            {"superseded_by": str(superseded_by.id)},
        )


def _write_route_stops(route: RouteSheet, ordered_stops: list[RouteStopDraft], *, actor: str) -> None:
    route.stops.all().delete()
    for sequence, draft in enumerate(ordered_stops, start=1):
        stop = RouteStop.objects.create(
            route=route,
            sequence=sequence,
            status=RouteStop.StopStatus.PLANNED,
            stop_type=draft.stop_type,
            source_type=draft.source_type,
            source_ref=draft.source_ref,
            customer_ref=draft.customer_ref,
            address_snapshot=draft.address_snapshot,
            latitude=draft.latitude,
            longitude=draft.longitude,
            service_time_minutes=int(settings.ROUTING_SERVICE_MINUTES_PER_STOP),
            planned_weight_kg=draft.planned_weight_kg,
            planned_volume_m3=draft.planned_volume_m3,
            warehouse_ref=route.warehouse_ref,
            created_by=actor,
        )
        for line in draft.lines:
            RouteStopLine.objects.create(
                stop=stop,
                delivery_ref=line.get("delivery_ref", ""),
                source_line_ref=line.get("source_line_ref", ""),
                quantity=line["quantity"],
                uom=line["uom"],
                weight_kg=line.get("weight_kg", ZERO),
                volume_m3=line.get("volume_m3", ZERO),
                item_ref=line.get("item_ref", ""),
                warehouse_ref=line.get("warehouse_ref", route.warehouse_ref),
                legacy_sales_order_number=line.get("legacy_sales_order_number", ""),
                legacy_line_id=line.get("legacy_line_id", ""),
                created_by=actor,
            )


def _origin_from_route(route: RouteSheet) -> tuple[Decimal, Decimal] | None:
    preview_payload = route.preview_payload or {}
    origin_payload = (preview_payload.get("input") or {}).get("origin") or {}
    if origin_payload.get("lat") not in [None, ""] and origin_payload.get("lng") not in [None, ""]:
        return (_decimal(origin_payload.get("lat")), _decimal(origin_payload.get("lng")))
    return None


def _refresh_route_metrics_from_stops(route: RouteSheet) -> None:
    stops = list(route.stops.all().order_by("sequence"))
    route_result = _ors_ordered_route(_origin_from_route(route), stops)
    preview_payload = dict(route.preview_payload or {})
    preview_payload["routing_status"] = route_result["routing_status"]
    route.planned_weight_kg = sum((stop.planned_weight_kg for stop in stops), ZERO)
    route.planned_volume_m3 = sum((stop.planned_volume_m3 for stop in stops), ZERO)
    route.total_distance_km = route_result["distance_km"]
    route.total_time_minutes = route_result["time_minutes"]
    route.routing_provider = route_result["provider"]
    route.route_geometry = route_result["geometry"]
    route.preview_payload = preview_payload


@transaction.atomic
def optimize_route(*, payload: dict, idempotency_key: str, actor: str) -> IdempotentResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="route.optimize",
        reference_type="route_sheet",
        reference_id="preview",
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)
    planned_date = parse_date(str(payload.get("planned_date") or "")) or timezone.localdate()
    warehouse_ref = str(payload.get("warehouse_ref") or "").strip()
    if not warehouse_ref:
        raise RouteRuleError("warehouse_ref es obligatorio.")
    branch_ref = str(payload.get("branch_ref") or warehouse_ref).strip()
    vehicle = Vehicle.objects.filter(id=payload.get("vehicle_id")).first() if payload.get("vehicle_id") else None
    origin_payload = payload.get("origin") or {}
    origin = None
    origin_snapshot = {}
    if origin_payload.get("lat") not in [None, ""] and origin_payload.get("lng") not in [None, ""]:
        origin = (_decimal(origin_payload.get("lat")), _decimal(origin_payload.get("lng")))
        origin_snapshot = dict(origin_payload)
    else:
        origin, origin_snapshot = _warehouse_origin(warehouse_ref)

    superseded_drafts, draft_delivery_payloads = _draft_route_delivery_payloads(
        warehouse_ref=warehouse_ref,
        planned_date=planned_date,
    )
    effective_payload = {
        **payload,
        "origin": _origin_payload(origin, origin_snapshot),
        "deliveries": _merge_delivery_payloads(draft_delivery_payloads, payload.get("deliveries") or []),
    }

    drafts, excluded = _source_deliveries_from_payload(effective_payload)
    if not drafts:
        raise RouteRuleError("No hay entregas con coordenadas para rutear.")
    route_result = _ors_route(origin, drafts)
    route = RouteSheet.objects.create(
        route_number=allocate_sequence_number(ROUTE_SEQUENCE_NAME, actor=actor),
        status=RouteSheet.RouteStatus.DRAFT,
        branch_ref=branch_ref,
        warehouse_ref=warehouse_ref,
        vehicle=vehicle,
        driver_ref=str(payload.get("driver_ref") or "").strip(),
        planned_date=planned_date,
        planned_weight_kg=sum((draft.planned_weight_kg for draft in route_result["ordered"]), ZERO),
        planned_volume_m3=sum((draft.planned_volume_m3 for draft in route_result["ordered"]), ZERO),
        total_distance_km=route_result["distance_km"],
        total_time_minutes=route_result["time_minutes"],
        routing_provider=route_result["provider"],
        route_geometry=route_result["geometry"],
        preview_payload={
            "excluded": excluded,
            "routing_status": route_result["routing_status"],
            "input": effective_payload,
            "superseded_draft_routes": [str(draft_route.id) for draft_route in superseded_drafts],
        },
        generated_by="auto",
        created_by=actor,
    )
    _write_route_stops(route, route_result["ordered"], actor=actor)
    _cancel_superseded_draft_routes(draft_routes=superseded_drafts, superseded_by=route, actor=actor)
    RouteOptimizationRun.objects.create(
        route=route,
        algorithm=f"{route_result['provider']}_nearest_neighbor_v1",
        input_payload=effective_payload,
        output_payload=_serialize_route(route),
        accepted=False,
        created_by=actor,
    )
    AuditTrail.objects.create(
        entity_type="route_sheet",
        entity_id=str(route.id),
        action="preview_created",
        actor=actor,
        after={"route_number": route.route_number, "stops": len(route_result["ordered"]), "excluded": len(excluded)},
    )
    result = IdempotentResult({"result": _serialize_route(route)}, 201)
    return _finish_idempotent_command(idempotency, result)


@transaction.atomic
def create_route_sheet(*, payload: dict, idempotency_key: str, actor: str) -> IdempotentResult:
    return optimize_route(payload={**payload, "manual": True}, idempotency_key=idempotency_key, actor=actor)


@transaction.atomic
def update_route_stops(*, route_id: str, payload: dict, idempotency_key: str, actor: str) -> IdempotentResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="route.update_stops",
        reference_type="route_sheet",
        reference_id=route_id,
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)
    route = RouteSheet.objects.select_for_update().get(id=route_id)
    if route.status != RouteSheet.RouteStatus.DRAFT:
        raise RouteRuleError("Solo se pueden editar paradas de una ruta en borrador.")
    stops_by_id = {str(row["id"]): row for row in payload.get("stops", []) if row.get("id")}
    sequence_by_id = {stop_id: int(row["sequence"]) for stop_id, row in stops_by_id.items() if row.get("sequence") is not None}
    remove_stop_ids = {str(stop_id) for stop_id in payload.get("remove_stop_ids", []) if str(stop_id).strip()}
    if not sequence_by_id and not remove_stop_ids:
        raise RouteRuleError("Debe informar paradas con id y sequence o remove_stop_ids.")

    existing_stops = list(route.stops.select_for_update().all())
    existing_stop_ids = {str(stop.id) for stop in existing_stops}
    unknown_remove_ids = remove_stop_ids - existing_stop_ids
    if unknown_remove_ids:
        raise RouteRuleError("Una o mas paradas a quitar no pertenecen a la hoja de ruta.")
    if remove_stop_ids:
        route.stops.filter(id__in=remove_stop_ids).delete()

    remaining_stops = [stop for stop in existing_stops if str(stop.id) not in remove_stop_ids]
    if sequence_by_id:
        touched_stops = [stop for stop in remaining_stops if str(stop.id) in sequence_by_id]
        for offset, stop in enumerate(touched_stops, start=1):
            stop.sequence = 100000 + offset
            stop.save(update_fields=["sequence"])

    for stop in remaining_stops:
        update_fields = ["updated_by", "updated_at"]
        stop_payload = stops_by_id.get(str(stop.id), {})
        if str(stop.id) in sequence_by_id:
            stop.sequence = sequence_by_id[str(stop.id)]
            update_fields.append("sequence")
        if stop_payload.get("lat") not in [None, ""] and stop_payload.get("lng") not in [None, ""]:
            stop.latitude = _decimal(stop_payload.get("lat"))
            stop.longitude = _decimal(stop_payload.get("lng"))
            update_fields.extend(["latitude", "longitude"])
        if len(update_fields) > 2:
            stop.updated_by = actor
            stop.save(update_fields=update_fields)

    ordered_stops = list(route.stops.select_for_update().order_by("sequence", "created_at"))
    for index, stop in enumerate(ordered_stops, start=1):
        if stop.sequence == index:
            continue
        stop.sequence = index
        stop.updated_by = actor
        stop.save(update_fields=["sequence", "updated_by", "updated_at"])

    _refresh_route_metrics_from_stops(route)
    route.reviewed_at = timezone.now()
    route.reviewed_by = actor
    route.planning_version += 1
    route.updated_by = actor
    route.save(update_fields=[
        "planned_weight_kg",
        "planned_volume_m3",
        "total_distance_km",
        "total_time_minutes",
        "routing_provider",
        "route_geometry",
        "preview_payload",
        "reviewed_at",
        "reviewed_by",
        "planning_version",
        "updated_by",
        "updated_at",
    ])
    AuditTrail.objects.create(
        entity_type="route_sheet",
        entity_id=str(route.id),
        action="stops_updated",
        actor=actor,
        after={"stops": payload.get("stops", []), "remove_stop_ids": list(remove_stop_ids)},
    )
    result = IdempotentResult({"result": _serialize_route(route)})
    return _finish_idempotent_command(idempotency, result)


@transaction.atomic
def confirm_route(*, route_id: str, payload: dict, idempotency_key: str, actor: str) -> IdempotentResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="route.confirm",
        reference_type="route_sheet",
        reference_id=route_id,
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)
    route = RouteSheet.objects.select_for_update().get(id=route_id)
    if route.status not in [RouteSheet.RouteStatus.DRAFT, RouteSheet.RouteStatus.CAPACITY_CHECKED]:
        raise RouteRuleError("La hoja de ruta no puede confirmarse en su estado actual.")
    if not route.reviewed_at and not payload.get("reviewed"):
        raise RouteRuleError("No se puede confirmar una ruta sin revision previa en mapa.")
    if payload.get("vehicle_id"):
        route.vehicle = Vehicle.objects.get(id=payload["vehicle_id"])
    if payload.get("driver_ref") is not None:
        route.driver_ref = str(payload.get("driver_ref") or "").strip()
    if not route.vehicle:
        raise RouteRuleError("La hoja de ruta requiere vehiculo asignado.")
    validate_route_capacity(route, allow_override=bool(payload.get("allow_capacity_override")))
    from_status = route.status
    route.status = RouteSheet.RouteStatus.PLANNED
    route.reviewed_at = route.reviewed_at or timezone.now()
    route.reviewed_by = route.reviewed_by or actor
    route.updated_by = actor
    route.save(update_fields=["status", "vehicle", "driver_ref", "reviewed_at", "reviewed_by", "updated_by", "updated_at"])
    route.optimization_runs.update(accepted=True)
    for stop in route.stops.select_for_update().all():
        stop.status = RouteStop.StopStatus.ALLOCATED
        stop.updated_by = actor
        stop.save(update_fields=["status", "updated_by", "updated_at"])
        if stop.source_type == "delivery_order":
            DeliveryOrder.objects.filter(id=stop.source_ref).update(status=DeliveryOrder.DeliveryStatus.ASSIGNED, updated_by=actor)
    _status_history("route_sheet", str(route.id), from_status, route.status, actor, "Confirmacion de hoja de ruta")
    result = IdempotentResult({"result": _serialize_route(route)})
    return _finish_idempotent_command(idempotency, result)


def _move_line_stock(
    *,
    idempotency_key: str,
    index: int,
    line: DeliveryOrderLine,
    from_state: str,
    to_state: str,
    quantity: Decimal,
    document_type: str,
    document_ref: str,
    actor: str,
    reason: str,
) -> None:
    if quantity <= ZERO:
        return
    warehouse_ref = line.warehouse_ref or line.delivery.warehouse_ref
    if from_state == StockState.PACKED:
        move_prepared_stock_to_state(
            warehouse_ref=warehouse_ref,
            item_ref=line.item_ref,
            quantity=quantity,
            uom=line.uom,
            to_state=to_state,
            target_location_purpose="transit",
            source_type="delivery_order",
            source_ref=str(line.delivery_id),
            document_type=document_type,
            document_ref=document_ref,
            actor=actor,
            idempotency_key=f"{idempotency_key}:{index}",
            reason=reason,
            legacy_sales_order_number=line.legacy_sales_order_number,
            legacy_line_id=line.legacy_line_id,
            movement_type=InventoryLedgerEntry.MovementType.DISPATCH,
        )
        return
    if from_state == StockState.IN_TRANSIT:
        move_transit_stock_to_state(
            source_warehouse_ref=warehouse_ref,
            item_ref=line.item_ref,
            quantity=quantity,
            uom=line.uom,
            to_state=to_state,
            target_location_purpose="available" if to_state == StockState.PACKED else "transit",
            document_type=document_type,
            document_ref=document_ref,
            actor=actor,
            idempotency_key=f"{idempotency_key}:{index}",
            reason=reason,
            legacy_sales_order_number=line.legacy_sales_order_number,
            legacy_line_id=line.legacy_line_id,
            movement_type=InventoryLedgerEntry.MovementType.DISPATCH,
        )
        return
    raise RouteRuleError("Movimiento de stock de ruta no soportado.")


@transaction.atomic
def start_loading_route(*, route_id: str, payload: dict, idempotency_key: str, actor: str) -> IdempotentResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="route.start_loading",
        reference_type="route_sheet",
        reference_id=route_id,
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)
    route = RouteSheet.objects.select_for_update().prefetch_related("stops__lines").get(id=route_id)
    if route.status not in [RouteSheet.RouteStatus.PLANNED, RouteSheet.RouteStatus.ASSIGNED]:
        raise RouteRuleError("La ruta debe estar planificada para iniciar carga.")
    from_status = route.status
    loaded_weight = ZERO
    loaded_volume = ZERO
    movement_index = 1
    for stop in route.stops.select_for_update().all():
        if stop.source_type != "delivery_order":
            continue
        delivery = DeliveryOrder.objects.select_for_update().prefetch_related("lines").get(id=stop.source_ref)
        if delivery.status not in [DeliveryOrder.DeliveryStatus.ASSIGNED, DeliveryOrder.DeliveryStatus.PREPARED, DeliveryOrder.DeliveryStatus.LOADED]:
            raise RouteRuleError("Todas las entregas deben estar preparadas/asignadas para cargar.")
        issue_remito(
            delivery_id=str(delivery.id),
            idempotency_key=f"{idempotency_key}:remito:{delivery.id}",
            actor=actor,
            authorized_warehouses=[delivery.warehouse_ref],
            allow_route_delivery=True,
        )
        for line in delivery.lines.select_for_update().all():
            qty = max(ZERO, line.planned_qty - line.dispatched_qty)
            _move_line_stock(
                idempotency_key=f"{idempotency_key}:load:{line.id}",
                index=movement_index,
                line=line,
                from_state=StockState.PACKED,
                to_state=StockState.IN_TRANSIT,
                quantity=qty,
                document_type="route_sheet",
                document_ref=str(route.id),
                actor=actor,
                reason="Carga de reparto",
            )
            line.dispatched_qty += qty
            line.updated_by = actor
            line.save(update_fields=["dispatched_qty", "updated_by", "updated_at"])
            movement_index += 1
        delivery.status = DeliveryOrder.DeliveryStatus.LOADED
        delivery.updated_by = actor
        delivery.save(update_fields=["status", "updated_by", "updated_at"])
        stop.status = RouteStop.StopStatus.LOADED
        stop.updated_by = actor
        stop.save(update_fields=["status", "updated_by", "updated_at"])
        loaded_weight += stop.planned_weight_kg
        loaded_volume += stop.planned_volume_m3
    route.status = RouteSheet.RouteStatus.LOADING
    route.loaded_weight_kg = loaded_weight
    route.loaded_volume_m3 = loaded_volume
    route.updated_by = actor
    route.save(update_fields=["status", "loaded_weight_kg", "loaded_volume_m3", "updated_by", "updated_at"])
    _status_history("route_sheet", str(route.id), from_status, route.status, actor, "Inicio de carga")
    result = IdempotentResult({"result": _serialize_route(route)})
    return _finish_idempotent_command(idempotency, result)


@transaction.atomic
def depart_route(*, route_id: str, payload: dict, idempotency_key: str, actor: str) -> IdempotentResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="route.depart",
        reference_type="route_sheet",
        reference_id=route_id,
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)
    route = RouteSheet.objects.select_for_update().get(id=route_id)
    if route.status != RouteSheet.RouteStatus.LOADING:
        raise RouteRuleError("La ruta debe estar en carga para salir.")
    from_status = route.status
    route.status = RouteSheet.RouteStatus.IN_TRANSIT
    route.updated_by = actor
    route.save(update_fields=["status", "updated_by", "updated_at"])
    for stop in route.stops.select_for_update().all():
        stop.status = RouteStop.StopStatus.EN_ROUTE
        stop.updated_by = actor
        stop.save(update_fields=["status", "updated_by", "updated_at"])
        if stop.source_type == "delivery_order":
            DeliveryOrder.objects.filter(id=stop.source_ref).update(status=DeliveryOrder.DeliveryStatus.IN_ROUTE, updated_by=actor)
    _status_history("route_sheet", str(route.id), from_status, route.status, actor, "Salida a reparto")
    result = IdempotentResult({"result": _serialize_route(route)})
    return _finish_idempotent_command(idempotency, result)


def _line_execution_quantities(stop: RouteStop, payload: dict) -> dict[str, Decimal]:
    line_payload = {
        str(row.get("delivery_line_id") or row.get("source_line_ref") or ""): _decimal(row.get("delivered_qty"))
        for row in payload.get("lines", [])
    }
    if payload.get("status") == DeliveryExecution.ExecutionStatus.DELIVERED_COMPLETE:
        return {line.source_line_ref: line.quantity for line in stop.lines.all()}
    if payload.get("status") == DeliveryExecution.ExecutionStatus.NOT_DELIVERED:
        return {line.source_line_ref: ZERO for line in stop.lines.all()}
    return {line.source_line_ref: line_payload.get(line.source_line_ref, ZERO) for line in stop.lines.all()}


@transaction.atomic
def execute_delivery_stop(*, payload: dict, idempotency_key: str, actor: str) -> IdempotentResult:
    route_stop_id = str(payload.get("route_stop_id") or "").strip()
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="delivery.execute",
        reference_type="route_stop",
        reference_id=route_stop_id,
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)
    stop = RouteStop.objects.select_for_update().prefetch_related("lines").get(id=route_stop_id)
    if stop.route.status != RouteSheet.RouteStatus.IN_TRANSIT:
        raise RouteRuleError("La hoja de ruta debe estar en transito para ejecutar entregas.")
    status = str(payload.get("status") or "").strip()
    if status not in DeliveryExecution.ExecutionStatus.values:
        raise RouteRuleError("Estado de ejecucion invalido.")
    quantities = _line_execution_quantities(stop, payload)
    lines_by_ref = {line.source_line_ref: line for line in stop.lines.all()}
    for source_line_ref, delivered_qty in quantities.items():
        route_line = lines_by_ref.get(source_line_ref)
        if route_line is None:
            raise RouteRuleError("La linea informada no pertenece a la parada.")
        if delivered_qty < ZERO or delivered_qty > route_line.quantity:
            raise RouteRuleError("La cantidad entregada debe estar entre cero y la cantidad planificada.")
    total_delivered = sum(quantities.values(), ZERO)
    total_planned = sum((line.quantity for line in stop.lines.all()), ZERO)
    returned = max(ZERO, total_planned - total_delivered)
    delivery = DeliveryOrder.objects.get(id=stop.source_ref)
    execution = DeliveryExecution.objects.create(
        delivery=delivery,
        route_stop_ref=str(stop.id),
        status=status,
        reason=str(payload.get("reason") or "").strip(),
        delivered_qty=total_delivered,
        returned_qty=returned,
        executed_at=parse_datetime(str(payload.get("timestamp") or "")) or timezone.now(),
        observations=str(payload.get("observations") or "").strip(),
        evidence_payload=payload.get("evidence") or {},
        payload={"lines": {key: str(value) for key, value in quantities.items()}},
        warehouse_ref=delivery.warehouse_ref,
        created_by=actor,
    )
    line_details = {}
    for route_line in stop.lines.select_for_update().all():
        delivered_qty = quantities.get(route_line.source_line_ref, ZERO)
        returned_qty = max(ZERO, route_line.quantity - delivered_qty)
        route_line.delivered_qty = delivered_qty
        route_line.returned_qty = returned_qty
        route_line.difference_qty = route_line.quantity - delivered_qty - returned_qty
        route_line.updated_by = actor
        route_line.save(update_fields=["delivered_qty", "returned_qty", "difference_qty", "updated_by", "updated_at"])
        line_details[route_line.source_line_ref] = {
            "item_ref": route_line.item_ref,
            "planned_qty": str(route_line.quantity),
            "delivered_qty": str(delivered_qty),
            "rejected_qty": str(returned_qty),
            "uom": route_line.uom,
        }

    stop.outcome_status = status
    stop.outcome_reason = execution.reason
    stop.outcome_payload = {
        "execution_id": str(execution.id),
        "lines": {key: str(value) for key, value in quantities.items()},
        "line_details": line_details,
        "observations": execution.observations,
    }
    stop.completed_at = execution.executed_at
    stop.status = RouteStop.StopStatus.DELIVERED if total_delivered > ZERO else RouteStop.StopStatus.FAILED
    stop.updated_by = actor
    stop.save(update_fields=["outcome_status", "outcome_reason", "outcome_payload", "completed_at", "status", "updated_by", "updated_at"])
    _status_history("route_stop", str(stop.id), RouteStop.StopStatus.EN_ROUTE, stop.status, actor, "Ejecucion de parada", stop.outcome_payload)
    result = IdempotentResult({"result": _serialize_route(stop.route)})
    return _finish_idempotent_command(idempotency, result)


def _close_delivery_document(delivery: DeliveryOrder, *, actor: str) -> None:
    document = delivery.documents.filter(document_type=DeliveryDocument.DocumentType.REMITO, status=DeliveryDocument.DocumentStatus.OPEN).first()
    if not document:
        return
    document.status = DeliveryDocument.DocumentStatus.CLOSED
    document.updated_by = actor
    document.save(update_fields=["status", "updated_by", "updated_at"])
    _status_history("delivery_document", str(document.id), DeliveryDocument.DocumentStatus.OPEN, document.status, actor, "Cierre por rendicion")


def _apply_stop_rendition(stop: RouteStop, *, actor: str, idempotency_key: str) -> tuple[Decimal, Decimal, Decimal]:
    delivery = DeliveryOrder.objects.select_for_update().select_related("fulfillment").prefetch_related("lines__fulfillment_line").get(id=stop.source_ref)
    delivered_by_line = {
        str(key): _decimal(value)
        for key, value in (stop.outcome_payload.get("lines") or {}).items()
    }
    total_delivered = ZERO
    total_returned = ZERO
    movement_index = 1
    for route_line in stop.lines.select_for_update().all():
        delivery_line = DeliveryOrderLine.objects.select_for_update().select_related("fulfillment_line", "delivery").get(id=route_line.source_line_ref)
        delivered_qty = min(route_line.quantity, delivered_by_line.get(route_line.source_line_ref, ZERO))
        returned_qty = max(ZERO, route_line.quantity - delivered_qty)
        if delivered_qty > ZERO:
            _move_line_stock(
                idempotency_key=f"{idempotency_key}:delivered:{delivery_line.id}",
                index=movement_index,
                line=delivery_line,
                from_state=StockState.IN_TRANSIT,
                to_state=StockState.DELIVERED,
                quantity=delivered_qty,
                document_type="route_rendition",
                document_ref=str(stop.route_id),
                actor=actor,
                reason="Rendicion de reparto entregado",
            )
            movement_index += 1
        if returned_qty > ZERO:
            _move_line_stock(
                idempotency_key=f"{idempotency_key}:returned:{delivery_line.id}",
                index=movement_index,
                line=delivery_line,
                from_state=StockState.IN_TRANSIT,
                to_state=StockState.PACKED,
                quantity=returned_qty,
                document_type="route_rendition",
                document_ref=str(stop.route_id),
                actor=actor,
                reason="Rendicion de reparto devuelto",
            )
            movement_index += 1
        route_line.delivered_qty = delivered_qty
        route_line.returned_qty = returned_qty
        route_line.difference_qty = route_line.quantity - delivered_qty - returned_qty
        route_line.updated_by = actor
        route_line.save(update_fields=["delivered_qty", "returned_qty", "difference_qty", "updated_by", "updated_at"])

        delivery_line.delivered_qty += delivered_qty
        delivery_line.updated_by = actor
        delivery_line.save(update_fields=["delivered_qty", "updated_by", "updated_at"])

        fulfillment_line = delivery_line.fulfillment_line
        fulfillment_line.prepared_qty = max(ZERO, fulfillment_line.prepared_qty - route_line.quantity)
        fulfillment_line.delivered_qty = min(fulfillment_line.ordered_qty, fulfillment_line.delivered_qty + delivered_qty)
        fulfillment_line.updated_by = actor
        fulfillment_line.save(update_fields=["prepared_qty", "delivered_qty", "updated_by", "updated_at"])
        total_delivered += delivered_qty
        total_returned += returned_qty

    if total_delivered >= sum((line.quantity for line in stop.lines.all()), ZERO):
        delivery.status = DeliveryOrder.DeliveryStatus.DELIVERED_COMPLETE
    elif total_delivered > ZERO:
        delivery.status = DeliveryOrder.DeliveryStatus.DELIVERED_PARTIAL
    else:
        delivery.status = DeliveryOrder.DeliveryStatus.RETURNED
    delivery.updated_by = actor
    delivery.save(update_fields=["status", "updated_by", "updated_at"])
    fulfillment = delivery.fulfillment
    has_pending = fulfillment.lines.filter(delivered_qty__lt=F("ordered_qty")).exists()
    fulfillment.status = (
        FulfillmentOrder.FulfillmentStatus.PARTIALLY_DELIVERED
        if has_pending
        else FulfillmentOrder.FulfillmentStatus.DELIVERED
    )
    fulfillment.updated_by = actor
    fulfillment.save(update_fields=["status", "updated_by", "updated_at"])
    _close_delivery_document(delivery, actor=actor)
    return total_delivered, total_returned, sum((line.difference_qty for line in stop.lines.all()), ZERO)

@transaction.atomic
def close_route(*, route_id: str, payload: dict, idempotency_key: str, actor: str) -> IdempotentResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="route.close",
        reference_type="route_sheet",
        reference_id=route_id,
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)
    route = RouteSheet.objects.select_for_update().prefetch_related("stops__lines").get(id=route_id)
    if route.status != RouteSheet.RouteStatus.IN_TRANSIT:
        raise RouteRuleError("La ruta debe estar en transito para rendirse.")
    non_terminal = route.stops.exclude(status__in=[RouteStop.StopStatus.DELIVERED, RouteStop.StopStatus.FAILED, RouteStop.StopStatus.RESCHEDULED, RouteStop.StopStatus.CANCELLED])
    if non_terminal.exists():
        raise RouteRuleError("Todas las paradas deben estar ejecutadas antes de rendir la ruta.")
    existing = route.renditions.filter(status=RouteRendition.RenditionStatus.POSTED).first()
    if existing:
        return _finish_idempotent_command(idempotency, IdempotentResult({"result": _serialize_route(route), "rendition_id": str(existing.id)}))
    rendition = RouteRendition.objects.create(
        route=route,
        status=RouteRendition.RenditionStatus.POSTED,
        closed_by=actor,
        closed_at=timezone.now(),
        notes=str(payload.get("notes") or "").strip(),
        created_by=actor,
    )
    has_incidents = False
    for stop in route.stops.select_for_update().all():
        delivered, returned, difference = _apply_stop_rendition(stop, actor=actor, idempotency_key=f"{idempotency_key}:stop:{stop.id}")
        has_incidents = has_incidents or returned > ZERO or difference != ZERO or stop.status == RouteStop.StopStatus.FAILED
        RouteRenditionLine.objects.create(
            rendition=rendition,
            stop=stop,
            status=stop.outcome_status or stop.status,
            reason=stop.outcome_reason,
            delivered_qty=delivered,
            returned_qty=returned,
            difference_qty=difference,
            observations=str((stop.outcome_payload or {}).get("observations") or ""),
            payload=stop.outcome_payload,
            created_by=actor,
        )
    rendition.has_incidents = has_incidents
    rendition.payload = {"notes": payload.get("notes", "")}
    rendition.save(update_fields=["has_incidents", "payload", "updated_at"])
    from_status = route.status
    route.status = RouteSheet.RouteStatus.CLOSED_WITH_INCIDENT if has_incidents else RouteSheet.RouteStatus.CLOSED
    route.updated_by = actor
    route.save(update_fields=["status", "updated_by", "updated_at"])
    _status_history("route_sheet", str(route.id), from_status, route.status, actor, "Rendicion de hoja de ruta", {"rendition_id": str(rendition.id)})
    AuditTrail.objects.create(
        entity_type="route_sheet",
        entity_id=str(route.id),
        action="closed",
        actor=actor,
        after={"status": route.status, "rendition_id": str(rendition.id), "has_incidents": has_incidents},
    )
    DomainEventOutbox.objects.create(
        event_type="route.closed",
        aggregate_type="route_sheet",
        aggregate_id=str(route.id),
        payload={"status": route.status, "has_incidents": has_incidents},
    )
    result = IdempotentResult({"result": _serialize_route(route), "rendition_id": str(rendition.id)})
    return _finish_idempotent_command(idempotency, result)
