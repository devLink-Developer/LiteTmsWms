from __future__ import annotations

from decimal import Decimal

from django.http import HttpRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.common.api import error_response, json_response, parse_json_body, require_idempotency_key
from apps.inventory.models import InventoryBalance, InventoryLedgerEntry
from apps.inventory.services import InventoryRuleError, reserve_inventory


def _decimal(value: Decimal) -> str:
    return format(value, "f")


@require_GET
def balances(request: HttpRequest):
    qs = InventoryBalance.objects.all().order_by("warehouse_ref", "item_ref", "stock_state")
    if warehouse := request.GET.get("warehouse"):
        qs = qs.filter(warehouse_ref=warehouse)
    if item := request.GET.get("item"):
        qs = qs.filter(item_ref=item)
    if state := request.GET.get("state"):
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
    if reference_type := request.GET.get("reference_type"):
        qs = qs.filter(document_type=reference_type)
    if reference_id := request.GET.get("reference_id"):
        qs = qs.filter(document_ref=reference_id)
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
