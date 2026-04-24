from django.conf import settings
from django.http import HttpResponse
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.common.api import error_response, json_response, parse_json_body, require_idempotency_key
from apps.fulfillment.models import DeliveryDocument, DeliveryOrder, DeliveryPreparationTask, FulfillmentOrder
from apps.fulfillment.services import (
    FulfillmentAuthorizationError,
    FulfillmentRuleError,
    build_remito_pdf,
    expedition_queue,
    ingest_legacy_order,
    issue_remito,
    mark_preparation_task_prepared,
    send_delivery_to_prepare,
    split_fulfillment_delivery,
    validate_delivery_stock,
)
from apps.integrations.legacy.models import LegacyOrder
from apps.logistics.parquet_master_data import MasterDataSourceError, employee_delivery_permissions


def _request_actor(request) -> str:
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user.get_username()
    return (
        request.headers.get("X-Actor", "")
        or request.headers.get("X-User", "")
        or request.headers.get("X-User-Email", "")
        or settings.TMSWMS_DEFAULT_ACTOR
        or ""
    ).strip()


def _delivery_permissions(request) -> dict:
    return employee_delivery_permissions(_request_actor(request))


def _authorized_warehouses(request) -> list[str]:
    return _delivery_permissions(request).get("authorized_warehouses", [])


def _forbidden_without_warehouse(authorized_warehouses: list[str]):
    if authorized_warehouses:
        return None
    return error_response(
        "forbidden",
        "El usuario no tiene depositos autorizados para operar entregas.",
        status=403,
    )


def _queue_filters(request) -> dict[str, str]:
    query = request.GET.get("q", "").strip()
    sales_order_number = (
        request.GET.get("sales_order_number", "").strip()
        or request.GET.get("order_id", "").strip()
        or request.GET.get("pedido", "").strip()
    )
    customer_ref = (
        request.GET.get("customer_ref", "").strip()
        or request.GET.get("customer_id", "").strip()
        or request.GET.get("cliente", "").strip()
    )
    customer_dni = (
        request.GET.get("customer_dni", "").strip()
        or request.GET.get("dni", "").strip()
        or request.GET.get("document_number", "").strip()
    )
    if query and not (sales_order_number or customer_ref or customer_dni):
        if query.upper().startswith("VENT8"):
            sales_order_number = query
        elif query.isdigit():
            customer_ref = query
            customer_dni = query
    return {
        "sales_order_number": sales_order_number,
        "customer_ref": customer_ref,
        "customer_dni": customer_dni,
    }


@require_GET
def fulfillment_orders(request):
    rows = FulfillmentOrder.objects.prefetch_related("lines", "deliveries").order_by("-created_at")[:100]
    return json_response(
        {
            "results": [
                {
                    "id": str(row.id),
                    "created_at": row.created_at.isoformat(),
                    "updated_at": row.updated_at.isoformat(),
                    "fulfillment_number": row.fulfillment_number,
                    "status": row.status,
                    "sales_order_number": row.legacy_sales_order_number,
                    "transaction_number": row.legacy_transaction_number,
                    "customer_ref": row.customer_ref,
                    "warehouse_ref": row.warehouse_ref,
                    "delivery_mode": row.delivery_mode,
                    "requested_date": row.requested_date.isoformat() if row.requested_date else None,
                    "lines_count": row.lines.count(),
                    "deliveries_count": row.deliveries.count(),
                }
                for row in rows
            ]
        }
    )


@require_GET
def delivery_orders(request):
    qs = DeliveryOrder.objects.order_by("-created_at")
    if status := request.GET.get("status"):
        qs = qs.filter(status=status)
    if delivery_mode := request.GET.get("delivery_mode"):
        qs = qs.filter(delivery_mode__icontains=delivery_mode)
    rows = qs[:100]
    return json_response(
        {
            "results": [
                {
                    "id": str(row.id),
                    "delivery_number": row.delivery_number,
                    "status": row.status,
                    "delivery_mode": row.delivery_mode,
                    "warehouse_ref": row.warehouse_ref,
                    "planned_date": row.planned_date.isoformat() if row.planned_date else None,
                }
                for row in rows
            ]
        }
    )


@require_GET
def preparation_tasks(request):
    try:
        permissions = _delivery_permissions(request)
        authorized_warehouses = permissions.get("authorized_warehouses", [])
        forbidden = _forbidden_without_warehouse(authorized_warehouses)
        if forbidden:
            return forbidden

        status_filter = request.GET.get("status", "open").strip().lower()
        assigned_to = request.GET.get("assigned_to", "").strip()
        mine = request.GET.get("mine", "").strip().lower() in {"1", "true", "yes"}
        if mine and not assigned_to:
            assigned_to = _request_actor(request)

        rows = (
            DeliveryPreparationTask.objects.select_related("delivery", "delivery__fulfillment")
            .prefetch_related("delivery__lines")
            .filter(warehouse_ref__in=authorized_warehouses)
            .order_by("-assigned_at", "-created_at")
        )
        if status_filter == "open":
            rows = rows.filter(
                status__in=[
                    DeliveryPreparationTask.TaskStatus.ASSIGNED,
                    DeliveryPreparationTask.TaskStatus.PREPARING,
                ]
            )
        elif status_filter and status_filter != "all":
            rows = rows.filter(status=status_filter)
        if assigned_to:
            rows = rows.filter(assigned_to__iexact=assigned_to)

        results = []
        for task in rows[:200]:
            delivery = task.delivery
            fulfillment = delivery.fulfillment
            lines = list(delivery.lines.all())
            results.append(
                {
                    "id": str(task.id),
                    "status": task.status,
                    "assigned_employee_ref": task.assigned_to,
                    "assigned_at": task.assigned_at.isoformat() if task.assigned_at else None,
                    "prepared_by": task.prepared_by,
                    "prepared_at": task.prepared_at.isoformat() if task.prepared_at else None,
                    "notes": task.notes,
                    "warehouse_ref": task.warehouse_ref,
                    "store_ref": task.store_ref,
                    "delivery": {
                        "id": str(delivery.id),
                        "delivery_number": delivery.delivery_number,
                        "status": delivery.status,
                        "delivery_mode": delivery.delivery_mode,
                        "planned_date": delivery.planned_date.isoformat() if delivery.planned_date else None,
                    },
                    "order": {
                        "id": str(fulfillment.id),
                        "fulfillment_number": fulfillment.fulfillment_number,
                        "sales_order_number": fulfillment.legacy_sales_order_number,
                        "transaction_number": fulfillment.legacy_transaction_number,
                        "customer_ref": fulfillment.customer_ref,
                    },
                    "lines": [
                        {
                            "id": str(line.id),
                            "item_ref": line.item_ref,
                            "warehouse_ref": line.warehouse_ref or delivery.warehouse_ref,
                            "planned_qty": str(line.planned_qty),
                            "uom": line.uom,
                            "legacy_line_id": line.legacy_line_id,
                        }
                        for line in lines
                    ],
                    "total_qty": str(sum((line.planned_qty for line in lines), start=0)),
                }
            )
        return json_response(
            {
                "results": results,
                "permissions": {"authorized_warehouses": authorized_warehouses},
            }
        )
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)


@require_GET
def expedition_queue_view(request):
    filters = _queue_filters(request)
    if not any(filters.values()):
        return json_response({"results": []})
    try:
        permissions = _delivery_permissions(request)
        forbidden = _forbidden_without_warehouse(permissions.get("authorized_warehouses", []))
        if forbidden:
            return forbidden
        return json_response(
            {
                "results": expedition_queue(
                    **filters,
                    authorized_warehouses=permissions.get("authorized_warehouses", []),
                ),
                "permissions": {
                    "authorized_warehouses": permissions.get("authorized_warehouses", []),
                },
            }
        )
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)


@csrf_exempt
@require_POST
def from_legacy_order(request):
    try:
        payload = parse_json_body(request)
        sales_order_number = str(payload.get("sales_order_number") or "").strip()
        if not sales_order_number:
            return error_response("validation_error", "sales_order_number es obligatorio.", status=422)
        result = ingest_legacy_order(
            sales_order_number=sales_order_number,
            idempotency_key=require_idempotency_key(request),
            actor=request.headers.get("X-Actor", "local.tmswms"),
        )
        return json_response(result.payload, status=result.status)
    except LegacyOrder.DoesNotExist:
        return error_response("not_found", "Pedido legacy no encontrado.", status=404)
    except ValueError as exc:
        return error_response("business_rule_violation", str(exc), status=422)


@csrf_exempt
@require_POST
def split_fulfillment(request, fulfillment_id):
    try:
        payload = parse_json_body(request)
        authorized_warehouses = _authorized_warehouses(request)
        forbidden = _forbidden_without_warehouse(authorized_warehouses)
        if forbidden:
            return forbidden
        result = split_fulfillment_delivery(
            fulfillment_id=fulfillment_id,
            lines=payload.get("lines") or [],
            delivery_mode=str(payload.get("delivery_mode") or ""),
            planned_date=parse_date(str(payload.get("planned_date") or "")),
            reason=str(payload.get("reason") or "Split local de prueba"),
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request) or "local.tmswms",
            authorized_warehouses=authorized_warehouses,
        )
        return json_response(result.payload, status=result.status)
    except FulfillmentOrder.DoesNotExist:
        return error_response("not_found", "Fulfillment no encontrado.", status=404)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    except FulfillmentAuthorizationError as exc:
        return error_response("forbidden", str(exc), status=403)
    except ValueError as exc:
        return error_response("business_rule_violation", str(exc), status=422)


@csrf_exempt
@require_POST
def validate_stock(request, delivery_id):
    try:
        authorized_warehouses = _authorized_warehouses(request)
        forbidden = _forbidden_without_warehouse(authorized_warehouses)
        if forbidden:
            return forbidden
        result = validate_delivery_stock(
            delivery_id=delivery_id,
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request) or "local.tmswms",
            authorized_warehouses=authorized_warehouses,
        )
        return json_response(result.payload, status=result.status)
    except DeliveryOrder.DoesNotExist:
        return error_response("not_found", "Entrega no encontrada.", status=404)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    except FulfillmentAuthorizationError as exc:
        return error_response("forbidden", str(exc), status=403)
    except ValueError as exc:
        return error_response("business_rule_violation", str(exc), status=422)


@csrf_exempt
@require_POST
def send_to_prepare(request, delivery_id):
    try:
        payload = parse_json_body(request)
        authorized_warehouses = _authorized_warehouses(request)
        forbidden = _forbidden_without_warehouse(authorized_warehouses)
        if forbidden:
            return forbidden
        result = send_delivery_to_prepare(
            delivery_id=delivery_id,
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request) or "local.tmswms",
            assigned_employee_ref=str(payload.get("assigned_employee_ref") or payload.get("employee_ref") or "").strip(),
            notes=str(payload.get("notes") or "").strip(),
            authorized_warehouses=authorized_warehouses,
        )
        return json_response(result.payload, status=result.status)
    except DeliveryOrder.DoesNotExist:
        return error_response("not_found", "Entrega no encontrada.", status=404)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    except FulfillmentAuthorizationError as exc:
        return error_response("forbidden", str(exc), status=403)
    except ValueError as exc:
        return error_response("business_rule_violation", str(exc), status=422)


@csrf_exempt
@require_POST
def mark_prepared(request, task_id):
    try:
        payload = parse_json_body(request)
        authorized_warehouses = _authorized_warehouses(request)
        forbidden = _forbidden_without_warehouse(authorized_warehouses)
        if forbidden:
            return forbidden
        result = mark_preparation_task_prepared(
            task_id=task_id,
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request) or "local.tmswms",
            notes=str(payload.get("notes") or "").strip(),
            authorized_warehouses=authorized_warehouses,
        )
        return json_response(result.payload, status=result.status)
    except DeliveryPreparationTask.DoesNotExist:
        return error_response("not_found", "Tarea de preparacion no encontrada.", status=404)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    except FulfillmentAuthorizationError as exc:
        return error_response("forbidden", str(exc), status=403)
    except ValueError as exc:
        return error_response("business_rule_violation", str(exc), status=422)


@csrf_exempt
@require_POST
def mark_delivery_prepared(request, delivery_id):
    try:
        payload = parse_json_body(request)
        task = DeliveryPreparationTask.objects.get(delivery_id=delivery_id)
        authorized_warehouses = _authorized_warehouses(request)
        forbidden = _forbidden_without_warehouse(authorized_warehouses)
        if forbidden:
            return forbidden
        result = mark_preparation_task_prepared(
            task_id=str(task.id),
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request) or "local.tmswms",
            notes=str(payload.get("notes") or "").strip(),
            authorized_warehouses=authorized_warehouses,
        )
        return json_response(result.payload, status=result.status)
    except DeliveryPreparationTask.DoesNotExist:
        return error_response("not_found", "Tarea de preparacion no encontrada para la entrega.", status=404)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    except FulfillmentAuthorizationError as exc:
        return error_response("forbidden", str(exc), status=403)
    except ValueError as exc:
        return error_response("business_rule_violation", str(exc), status=422)


@csrf_exempt
@require_POST
def remito(request, delivery_id):
    try:
        authorized_warehouses = _authorized_warehouses(request)
        forbidden = _forbidden_without_warehouse(authorized_warehouses)
        if forbidden:
            return forbidden
        result = issue_remito(
            delivery_id=delivery_id,
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request) or "local.tmswms",
            authorized_warehouses=authorized_warehouses,
        )
        return json_response(result.payload, status=result.status)
    except DeliveryOrder.DoesNotExist:
        return error_response("not_found", "Entrega no encontrada.", status=404)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    except FulfillmentAuthorizationError as exc:
        return error_response("forbidden", str(exc), status=403)
    except ValueError as exc:
        return error_response("business_rule_violation", str(exc), status=422)


@require_GET
def remito_pdf(request, delivery_id):
    try:
        authorized_warehouses = _authorized_warehouses(request)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    forbidden = _forbidden_without_warehouse(authorized_warehouses)
    if forbidden:
        return forbidden
    document = (
        DeliveryDocument.objects.filter(delivery_id=delivery_id, document_type=DeliveryDocument.DocumentType.REMITO)
        .order_by("-issued_at")
        .first()
    )
    if not document:
        return error_response("not_found", "La entrega no tiene remito emitido.", status=404)
    if document.warehouse_ref not in authorized_warehouses:
        return error_response("forbidden", "El usuario no tiene permiso para descargar este remito.", status=403)
    response = HttpResponse(build_remito_pdf(document), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{document.document_number}.pdf"'
    return response
