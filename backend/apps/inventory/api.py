from __future__ import annotations

from decimal import Decimal

from django.http import HttpRequest
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.common.api import error_response, json_response, parse_json_body, require_idempotency_key
from apps.inventory.models import InventoryBalance, InventoryLedgerEntry, PurchaseOrderReceipt
from apps.inventory.services import InventoryRuleError, reserve_inventory


def _decimal(value: Decimal) -> str:
    return format(value, "f")


def _query_alias(request: HttpRequest, *names: str) -> str:
    for name in names:
        value = request.GET.get(name)
        if value:
            return value
    return ""


def _iso_datetime(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


@require_GET
def balances(request: HttpRequest):
    qs = InventoryBalance.objects.all().order_by("warehouse_ref", "item_ref", "stock_state")
    if warehouse := request.GET.get("warehouse"):
        qs = qs.filter(warehouse_ref=warehouse)
    if item := request.GET.get("item"):
        qs = qs.filter(item_ref=item)
    if state := _query_alias(request, "state", "stock_state"):
        qs = qs.filter(stock_state=state)
    data = [
        {
            "id": str(row.id),
            "warehouse_ref": row.warehouse_ref,
            "item_ref": row.item_ref,
            "stock_state": row.stock_state,
            "quantity": _decimal(row.quantity),
            "uom": row.uom,
            "version": row.version,
        }
        for row in qs[:200]
    ]
    return json_response({"results": data})


@require_GET
def ledger(request: HttpRequest):
    qs = InventoryLedgerEntry.objects.all().order_by("-posted_at")
    if movement_type := request.GET.get("movement_type"):
        qs = qs.filter(movement_type=movement_type)
    if direction := request.GET.get("direction"):
        qs = qs.filter(direction=direction)
    if warehouse := request.GET.get("warehouse"):
        qs = qs.filter(warehouse_ref=warehouse)
    if item := request.GET.get("item"):
        qs = qs.filter(item_ref=item)
    if stock_state := _query_alias(request, "stock_state", "state"):
        qs = qs.filter(stock_state=stock_state)
    if document_type := _query_alias(request, "document_type", "reference_type"):
        qs = qs.filter(document_type=document_type)
    if document_ref := _query_alias(request, "document_ref", "reference_id"):
        qs = qs.filter(document_ref=document_ref)
    if date_from := request.GET.get("date_from"):
        parsed = parse_date(date_from)
        if parsed is None:
            return error_response("validation_error", "date_from debe tener formato YYYY-MM-DD.", status=400)
        qs = qs.filter(posted_at__date__gte=parsed)
    if date_to := request.GET.get("date_to"):
        parsed = parse_date(date_to)
        if parsed is None:
            return error_response("validation_error", "date_to debe tener formato YYYY-MM-DD.", status=400)
        qs = qs.filter(posted_at__date__lte=parsed)
    data = [
        {
            "id": str(row.id),
            "movement_type": row.movement_type,
            "direction": row.direction,
            "warehouse_ref": row.warehouse_ref,
            "item_ref": row.item_ref,
            "stock_state": row.stock_state,
            "quantity": _decimal(row.quantity),
            "uom": row.uom,
            "document_type": row.document_type,
            "document_ref": row.document_ref,
            "posted_at": row.posted_at.isoformat(),
        }
        for row in qs[:200]
    ]
    return json_response({"results": data})


@require_GET
def receipts(request: HttpRequest):
    qs = PurchaseOrderReceipt.objects.all().order_by("-created_at")
    if purchase_order_ref := request.GET.get("purchase_order_ref"):
        qs = qs.filter(purchase_order_ref=purchase_order_ref)
    if warehouse := request.GET.get("warehouse"):
        qs = qs.filter(warehouse_ref=warehouse)
    if status := request.GET.get("status"):
        qs = qs.filter(status=status)
    if item := request.GET.get("item"):
        qs = qs.filter(lines__item_ref=item).distinct()
    data = [
        {
            "id": str(row.id),
            "purchase_order_ref": row.purchase_order_ref,
            "supplier_ref": row.supplier_ref,
            "status": row.status,
            "warehouse_ref": row.warehouse_ref,
            "lines_count": row.lines.count(),
            "received_at": _iso_datetime(row.received_at),
            "closed_at": _iso_datetime(row.closed_at),
        }
        for row in qs[:100]
    ]
    return json_response({"results": data})


@csrf_exempt
@require_POST
def reservations(request: HttpRequest):
    try:
        idempotency_key = require_idempotency_key(request)
        payload = parse_json_body(request)
        reservation = reserve_inventory(
            warehouse_ref=payload["warehouse_ref"],
            source_type=payload["source_type"],
            source_ref=payload["source_ref"],
            actor=payload.get("actor", "system"),
            lines=payload["lines"],
            idempotency_key=idempotency_key,
        )
    except KeyError as exc:
        return error_response("validation_error", f"Falta campo requerido: {exc}", status=400)
    except ValueError as exc:
        return error_response("validation_error", str(exc), status=400)
    except InventoryRuleError as exc:
        return error_response("business_rule_violation", str(exc), status=422)
    return json_response(
        {
            "id": str(reservation.id),
            "status": reservation.status,
            "source_type": reservation.source_type,
            "source_ref": reservation.source_ref,
        },
        status=201,
    )
