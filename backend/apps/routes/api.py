from __future__ import annotations

from django.conf import settings
from django.db.models import Count
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.common.api import error_response, json_response, parse_json_body, require_idempotency_key
from apps.fulfillment.models import DeliveryOrder
from apps.logistics.parquet_master_data import MasterDataSourceError, employee_delivery_permissions
from apps.routes.models import RouteSheet, RouteStop
from apps.routes.services import (
    RouteCapacityError,
    RouteRuleError,
    close_route,
    confirm_route,
    create_route_sheet,
    depart_route,
    execute_delivery_stop,
    optimize_route,
    pending_reparto_deliveries,
    serialize_route_sheet,
    start_loading_route,
    update_route_stops,
)


def _request_actor(request) -> str:
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user.get_username()
    return (
        request.headers.get("X-Actor", "")
        or request.headers.get("X-User", "")
        or request.headers.get("X-User-Email", "")
        or settings.TMSWMS_DEFAULT_ACTOR
        or "system"
    ).strip()


def _authorized_warehouses(request) -> list[str]:
    return employee_delivery_permissions(_request_actor(request)).get("authorized_warehouses", [])


def _authorized_warehouse_set(request) -> set[str]:
    return {str(warehouse).strip() for warehouse in _authorized_warehouses(request) if str(warehouse).strip()}


def _forbidden_without_warehouse(authorized_warehouses: set[str]):
    if authorized_warehouses:
        return None
    return error_response(
        "forbidden",
        "El usuario no tiene depositos autorizados para operar reparto.",
        status=403,
    )


def _forbidden_for_warehouse(warehouse_ref: str, authorized_warehouses: set[str]):
    forbidden = _forbidden_without_warehouse(authorized_warehouses)
    if forbidden:
        return forbidden
    if str(warehouse_ref or "").strip() not in authorized_warehouses:
        return error_response(
            "forbidden",
            "El usuario no tiene permiso para operar reparto en este deposito.",
            status=403,
        )
    return None


def _delivery_ids_from_payload(payload: dict) -> list[str]:
    delivery_ids = []
    for row in payload.get("deliveries") or []:
        raw_id = (row.get("delivery_id") or row.get("id")) if isinstance(row, dict) else row
        delivery_id = str(raw_id or "").strip()
        if delivery_id:
            delivery_ids.append(delivery_id)
    return delivery_ids


def _forbidden_for_payload_deliveries(payload: dict, authorized_warehouses: set[str]):
    delivery_ids = _delivery_ids_from_payload(payload)
    if not delivery_ids:
        return None
    unauthorized_exists = DeliveryOrder.objects.filter(id__in=delivery_ids).exclude(warehouse_ref__in=authorized_warehouses).exists()
    if unauthorized_exists:
        return error_response(
            "forbidden",
            "El usuario no tiene permiso para rutear entregas de otro deposito.",
            status=403,
        )
    return None


def _route_warehouse_forbidden(request, route_id: str):
    try:
        authorized_warehouses = _authorized_warehouse_set(request)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    try:
        route = RouteSheet.objects.only("warehouse_ref").get(id=route_id)
    except RouteSheet.DoesNotExist:
        return error_response("not_found", "Hoja de ruta no encontrada.", status=404)
    return _forbidden_for_warehouse(route.warehouse_ref, authorized_warehouses)


def _route_stop_warehouse_forbidden(request, route_stop_id: str):
    try:
        authorized_warehouses = _authorized_warehouse_set(request)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    try:
        stop = RouteStop.objects.select_related("route").only("route__warehouse_ref").get(id=route_stop_id)
    except RouteStop.DoesNotExist:
        return error_response("not_found", "Parada de ruta no encontrada.", status=404)
    return _forbidden_for_warehouse(stop.route.warehouse_ref, authorized_warehouses)


def _route_error_response(exc: Exception):
    if isinstance(exc, RouteCapacityError):
        return error_response("capacity_violation", str(exc), status=422)
    if isinstance(exc, RouteRuleError):
        return error_response("business_rule_violation", str(exc), status=422)
    if isinstance(exc, (RouteSheet.DoesNotExist, DeliveryOrder.DoesNotExist)):
        return error_response("not_found", "Recurso logistico no encontrado.", status=404)
    if isinstance(exc, ValueError):
        return error_response("validation_error", str(exc), status=400)
    return error_response("server_error", str(exc), status=500)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def route_sheets(request):
    if request.method == "POST":
        return create_sheet(request)
    try:
        authorized_warehouses = _authorized_warehouse_set(request)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    forbidden = _forbidden_without_warehouse(authorized_warehouses)
    if forbidden:
        return forbidden
    rows = RouteSheet.objects.select_related("vehicle", "vehicle__capacity_profile").order_by("-planned_date", "-created_at")
    planned_date = parse_date(request.GET.get("planned_date", ""))
    warehouse_ref = request.GET.get("warehouse_ref", "").strip() or request.GET.get("warehouse", "").strip()
    status_filter = [
        status.strip()
        for status in request.GET.get("status", "").split(",")
        if status.strip()
    ]
    rows = rows.filter(warehouse_ref__in=authorized_warehouses)
    if planned_date:
        rows = rows.filter(planned_date=planned_date)
    if warehouse_ref:
        if warehouse_ref not in authorized_warehouses:
            return json_response({"results": []})
        rows = rows.filter(warehouse_ref=warehouse_ref)
    driver_ref = request.GET.get("driver_ref", "").strip() or request.GET.get("driver", "").strip()
    if driver_ref:
        rows = rows.filter(driver_ref=driver_ref)
    if status_filter:
        rows = rows.filter(status__in=status_filter)
    rows = rows.annotate(stops_total=Count("stops"))[:100]
    return json_response(
        {
            "results": [
                {
                    "id": str(row.id),
                    "route_number": row.route_number,
                    "status": row.status,
                    "planned_date": row.planned_date.isoformat(),
                    "warehouse_ref": row.warehouse_ref,
                    "vehicle": row.vehicle.code if row.vehicle else None,
                    "driver_ref": row.driver_ref,
                    "planned_weight_kg": str(row.planned_weight_kg),
                    "planned_volume_m3": str(row.planned_volume_m3),
                    "total_distance_km": str(row.total_distance_km),
                    "total_time_minutes": row.total_time_minutes,
                    "stops_count": row.stops_total,
                }
                for row in rows
            ]
        }
    )


@require_GET
def route_sheet_detail(request, route_id):
    forbidden = _route_warehouse_forbidden(request, str(route_id))
    if forbidden:
        return forbidden
    try:
        route = RouteSheet.objects.get(id=route_id)
    except RouteSheet.DoesNotExist:
        return error_response("not_found", "Hoja de ruta no encontrada.", status=404)
    return json_response({"result": serialize_route_sheet(route)})


@require_GET
def pending_deliveries(request):
    planned_date = parse_date(request.GET.get("planned_date", ""))
    try:
        authorized_warehouses = _authorized_warehouse_set(request)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    forbidden = _forbidden_without_warehouse(authorized_warehouses)
    if forbidden:
        return forbidden
    warehouse_ref = request.GET.get("warehouse_ref", "").strip() or request.GET.get("warehouse", "").strip()
    if warehouse_ref and warehouse_ref not in authorized_warehouses:
        return json_response({"results": []})
    return json_response(
        {
            "results": pending_reparto_deliveries(
                warehouse_ref=warehouse_ref,
                planned_date=planned_date,
                authorized_warehouses=authorized_warehouses,
            )
        }
    )


@csrf_exempt
@require_POST
def optimize(request):
    try:
        payload = parse_json_body(request)
        authorized_warehouses = _authorized_warehouse_set(request)
        forbidden = _forbidden_for_warehouse(str(payload.get("warehouse_ref") or "").strip(), authorized_warehouses)
        if forbidden:
            return forbidden
        forbidden = _forbidden_for_payload_deliveries(payload, authorized_warehouses)
        if forbidden:
            return forbidden
        result = optimize_route(
            payload=payload,
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request),
        )
        return json_response(result.payload, status=result.status)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    except Exception as exc:
        return _route_error_response(exc)


@csrf_exempt
@require_POST
def create_sheet(request):
    try:
        payload = parse_json_body(request)
        authorized_warehouses = _authorized_warehouse_set(request)
        forbidden = _forbidden_for_warehouse(str(payload.get("warehouse_ref") or "").strip(), authorized_warehouses)
        if forbidden:
            return forbidden
        forbidden = _forbidden_for_payload_deliveries(payload, authorized_warehouses)
        if forbidden:
            return forbidden
        result = create_route_sheet(
            payload=payload,
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request),
        )
        return json_response(result.payload, status=result.status)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    except Exception as exc:
        return _route_error_response(exc)


@csrf_exempt
@require_http_methods(["PATCH"])
def patch_stops(request, route_id):
    try:
        forbidden = _route_warehouse_forbidden(request, str(route_id))
        if forbidden:
            return forbidden
        result = update_route_stops(
            route_id=str(route_id),
            payload=parse_json_body(request),
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request),
        )
        return json_response(result.payload, status=result.status)
    except Exception as exc:
        return _route_error_response(exc)


@csrf_exempt
@require_http_methods(["PUT"])
def confirm(request, route_id):
    try:
        forbidden = _route_warehouse_forbidden(request, str(route_id))
        if forbidden:
            return forbidden
        result = confirm_route(
            route_id=str(route_id),
            payload=parse_json_body(request),
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request),
        )
        return json_response(result.payload, status=result.status)
    except Exception as exc:
        return _route_error_response(exc)


@csrf_exempt
@require_POST
def send_to_preparation(request, route_id):
    try:
        forbidden = _route_warehouse_forbidden(request, str(route_id))
        if forbidden:
            return forbidden
        result = confirm_route(
            route_id=str(route_id),
            payload={**parse_json_body(request), "reviewed": True},
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request),
        )
        return json_response(result.payload, status=result.status)
    except Exception as exc:
        return _route_error_response(exc)


@csrf_exempt
@require_POST
def start_loading(request, route_id):
    try:
        forbidden = _route_warehouse_forbidden(request, str(route_id))
        if forbidden:
            return forbidden
        result = start_loading_route(
            route_id=str(route_id),
            payload=parse_json_body(request),
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request),
        )
        return json_response(result.payload, status=result.status)
    except Exception as exc:
        return _route_error_response(exc)


@csrf_exempt
@require_POST
def depart(request, route_id):
    try:
        forbidden = _route_warehouse_forbidden(request, str(route_id))
        if forbidden:
            return forbidden
        result = depart_route(
            route_id=str(route_id),
            payload=parse_json_body(request),
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request),
        )
        return json_response(result.payload, status=result.status)
    except Exception as exc:
        return _route_error_response(exc)


@csrf_exempt
@require_POST
def close(request, route_id):
    try:
        forbidden = _route_warehouse_forbidden(request, str(route_id))
        if forbidden:
            return forbidden
        result = close_route(
            route_id=str(route_id),
            payload=parse_json_body(request),
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request),
        )
        return json_response(result.payload, status=result.status)
    except Exception as exc:
        return _route_error_response(exc)


@csrf_exempt
@require_POST
def execute_delivery(request):
    try:
        payload = parse_json_body(request)
        forbidden = _route_stop_warehouse_forbidden(request, str(payload.get("route_stop_id") or "").strip())
        if forbidden:
            return forbidden
        result = execute_delivery_stop(
            payload=payload,
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request),
        )
        return json_response(result.payload, status=result.status)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    except Exception as exc:
        return _route_error_response(exc)
