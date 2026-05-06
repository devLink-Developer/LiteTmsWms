from __future__ import annotations

from django.conf import settings
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET

from apps.common.api import error_response, json_response
from apps.core.models import StatusHistory
from apps.fulfillment.models import DeliveryDocument, DeliveryOrder, DeliveryPreparationTask, FulfillmentOrder
from apps.logistics.parquet_master_data import MasterDataSourceError, employee_delivery_permissions
from apps.routes.models import RouteSheet, RouteStop

LIVE_ENTITY_TYPES = {
    "delivery_order",
    "delivery_document",
    "delivery_preparation_task",
    "fulfillment_order",
    "route_sheet",
    "route_stop",
}


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


def _authorized_warehouses(request) -> set[str]:
    session_warehouses = request.session.get("authorized_warehouses") if hasattr(request, "session") else None
    if isinstance(session_warehouses, list) and session_warehouses:
        return {str(warehouse).strip() for warehouse in session_warehouses if str(warehouse).strip()}
    return {
        str(warehouse).strip()
        for warehouse in employee_delivery_permissions(_request_actor(request)).get("authorized_warehouses", [])
        if str(warehouse).strip()
    }


def _event_context(events: list[StatusHistory]) -> dict[tuple[str, str], dict]:
    ids_by_type: dict[str, set[str]] = {}
    for event in events:
        ids_by_type.setdefault(event.entity_type, set()).add(event.entity_id)

    context: dict[tuple[str, str], dict] = {}
    for row in DeliveryOrder.objects.filter(id__in=ids_by_type.get("delivery_order", set())).values("id", "warehouse_ref", "fulfillment_id"):
        context[("delivery_order", str(row["id"]))] = {
            "warehouse_ref": row["warehouse_ref"],
            "fulfillment_id": str(row["fulfillment_id"]),
        }
    for row in FulfillmentOrder.objects.filter(id__in=ids_by_type.get("fulfillment_order", set())).values("id", "warehouse_ref"):
        context[("fulfillment_order", str(row["id"]))] = {"warehouse_ref": row["warehouse_ref"]}
    for row in DeliveryPreparationTask.objects.filter(id__in=ids_by_type.get("delivery_preparation_task", set())).values("id", "warehouse_ref", "delivery_id"):
        context[("delivery_preparation_task", str(row["id"]))] = {
            "warehouse_ref": row["warehouse_ref"],
            "delivery_id": str(row["delivery_id"]),
        }
    for row in DeliveryDocument.objects.filter(id__in=ids_by_type.get("delivery_document", set())).values("id", "warehouse_ref", "delivery_id"):
        context[("delivery_document", str(row["id"]))] = {
            "warehouse_ref": row["warehouse_ref"],
            "delivery_id": str(row["delivery_id"]),
        }
    for row in RouteSheet.objects.filter(id__in=ids_by_type.get("route_sheet", set())).values("id", "warehouse_ref"):
        context[("route_sheet", str(row["id"]))] = {"warehouse_ref": row["warehouse_ref"], "route_id": str(row["id"])}
    for row in RouteStop.objects.filter(id__in=ids_by_type.get("route_stop", set())).values("id", "route_id", "route__warehouse_ref"):
        context[("route_stop", str(row["id"]))] = {
            "warehouse_ref": row["route__warehouse_ref"],
            "route_id": str(row["route_id"]),
        }
    return context


@require_GET
def live_status_events(request):
    try:
        authorized_warehouses = _authorized_warehouses(request)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    if not authorized_warehouses:
        return error_response("forbidden", "El usuario no tiene depositos autorizados para recibir eventos.", status=403)

    limit = min(max(int(request.GET.get("limit") or 100), 1), 500)
    entity_types = {
        value.strip()
        for value in request.GET.get("entity_type", "").split(",")
        if value.strip()
    } or LIVE_ENTITY_TYPES
    entity_types &= LIVE_ENTITY_TYPES
    qs = StatusHistory.objects.filter(entity_type__in=entity_types).order_by("created_at", "id")
    if since := parse_datetime(request.GET.get("since", "")):
        qs = qs.filter(created_at__gt=since)
    events = list(qs[:limit])
    context = _event_context(events)
    results = []
    for event in events:
        extra = context.get((event.entity_type, event.entity_id), {})
        warehouse_ref = str(extra.get("warehouse_ref") or "").strip()
        if warehouse_ref not in authorized_warehouses:
            continue
        results.append(
            {
                "id": str(event.id),
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "from_status": event.from_status,
                "to_status": event.to_status,
                "actor": event.actor,
                "reason": event.reason,
                "payload": event.payload,
                "warehouse_ref": warehouse_ref,
                "route_id": extra.get("route_id", ""),
                "delivery_id": extra.get("delivery_id", ""),
                "fulfillment_id": extra.get("fulfillment_id", ""),
                "created_at": event.created_at.isoformat(),
            }
        )
    return json_response({"results": results, "cursor": events[-1].created_at.isoformat() if events else request.GET.get("since", "")})
