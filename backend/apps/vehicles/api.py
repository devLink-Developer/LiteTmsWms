from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from apps.common.api import error_response, json_response, parse_json_body, require_idempotency_key
from apps.vehicles.models import Driver, Vehicle, VehicleCapacityProfile
from apps.vehicles.services import (
    VehicleRuleError,
    serialize_capacity_profile,
    serialize_driver,
    serialize_vehicle,
    upsert_capacity_profile,
    upsert_driver,
    upsert_vehicle,
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


def _vehicle_error_response(exc: Exception):
    if isinstance(exc, VehicleRuleError):
        return error_response("business_rule_violation", str(exc), status=422)
    if isinstance(exc, (Vehicle.DoesNotExist, VehicleCapacityProfile.DoesNotExist, Driver.DoesNotExist)):
        return error_response("not_found", "Recurso de flota no encontrado.", status=404)
    if isinstance(exc, ValueError):
        return error_response("validation_error", str(exc), status=400)
    return error_response("server_error", str(exc), status=500)


def _include_inactive(request) -> bool:
    return request.GET.get("include_inactive", "").strip().casefold() in {"1", "true", "yes", "si", "s"}


@csrf_exempt
@require_http_methods(["GET", "POST"])
def vehicles(request):
    if request.method == "POST":
        try:
            result = upsert_vehicle(
                payload=parse_json_body(request),
                idempotency_key=require_idempotency_key(request),
                actor=_request_actor(request),
            )
            return json_response(result.payload, status=result.status)
        except Exception as exc:
            return _vehicle_error_response(exc)

    rows = Vehicle.objects.select_related("capacity_profile").order_by("code")
    if not _include_inactive(request):
        rows = rows.filter(active=True)
    status = request.GET.get("status", "").strip()
    if status:
        rows = rows.filter(status=status)
    rows = rows[:300]
    return json_response(
        {
            "results": [serialize_vehicle(row) for row in rows]
        }
    )


@csrf_exempt
@require_http_methods(["PATCH"])
def vehicle_detail(request, vehicle_id):
    try:
        result = upsert_vehicle(
            payload=parse_json_body(request),
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request),
            vehicle_id=str(vehicle_id),
        )
        return json_response(result.payload, status=result.status)
    except Exception as exc:
        return _vehicle_error_response(exc)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def capacity_profiles(request):
    if request.method == "POST":
        try:
            result = upsert_capacity_profile(
                payload=parse_json_body(request),
                idempotency_key=require_idempotency_key(request),
                actor=_request_actor(request),
            )
            return json_response(result.payload, status=result.status)
        except Exception as exc:
            return _vehicle_error_response(exc)
    rows = VehicleCapacityProfile.objects.order_by("name")[:300]
    return json_response({"results": [serialize_capacity_profile(row) for row in rows]})


@csrf_exempt
@require_http_methods(["PATCH"])
def capacity_profile_detail(request, profile_id):
    try:
        result = upsert_capacity_profile(
            payload=parse_json_body(request),
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request),
            profile_id=str(profile_id),
        )
        return json_response(result.payload, status=result.status)
    except Exception as exc:
        return _vehicle_error_response(exc)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def drivers(request):
    if request.method == "POST":
        try:
            result = upsert_driver(
                payload=parse_json_body(request),
                idempotency_key=require_idempotency_key(request),
                actor=_request_actor(request),
            )
            return json_response(result.payload, status=result.status)
        except Exception as exc:
            return _vehicle_error_response(exc)
    rows = Driver.objects.order_by("code")
    if not _include_inactive(request):
        rows = rows.filter(active=True)
    status = request.GET.get("status", "").strip()
    if status:
        rows = rows.filter(status=status)
    rows = rows[:300]
    return json_response({"results": [serialize_driver(row) for row in rows]})


@csrf_exempt
@require_http_methods(["PATCH"])
def driver_detail(request, driver_id):
    try:
        result = upsert_driver(
            payload=parse_json_body(request),
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request),
            driver_id=str(driver_id),
        )
        return json_response(result.payload, status=result.status)
    except Exception as exc:
        return _vehicle_error_response(exc)
