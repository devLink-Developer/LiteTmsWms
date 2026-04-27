from __future__ import annotations

from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.common.api import error_response, json_response, parse_json_body, require_idempotency_key
from apps.transfers.models import TransferOrder
from apps.transfers.services import (
    TransferRuleError,
    approve_transfer,
    close_transfer,
    create_transfer,
    dispatch_transfer,
    prepare_transfer,
    receive_transfer,
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


def _transfer_error_response(exc: Exception):
    if isinstance(exc, TransferOrder.DoesNotExist):
        return error_response("not_found", "Transferencia no encontrada.", status=404)
    if isinstance(exc, TransferRuleError):
        return error_response("business_rule_violation", str(exc), status=422)
    if isinstance(exc, ValueError):
        return error_response("validation_error", str(exc), status=400)
    return error_response("server_error", str(exc), status=500)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def transfer_orders(request):
    if request.method == "POST":
        try:
            result = create_transfer(
                payload=parse_json_body(request),
                idempotency_key=require_idempotency_key(request),
                actor=_request_actor(request),
            )
            return json_response(result.payload, status=result.status)
        except Exception as exc:
            return _transfer_error_response(exc)

    qs = TransferOrder.objects.prefetch_related("lines").order_by("-created_at")
    if origin_warehouse := request.GET.get("origin_warehouse"):
        qs = qs.filter(origin_warehouse_ref=origin_warehouse)
    if destination_warehouse := request.GET.get("destination_warehouse"):
        qs = qs.filter(destination_warehouse_ref=destination_warehouse)
    if status := request.GET.get("status"):
        qs = qs.filter(status=status)
    if transfer_number := request.GET.get("transfer_number"):
        qs = qs.filter(transfer_number=transfer_number)
    rows = qs[:100]
    return json_response(
        {
            "results": [
                {
                    "id": str(row.id),
                    "transfer_number": row.transfer_number,
                    "status": row.status,
                    "origin_warehouse_ref": row.origin_warehouse_ref,
                    "destination_warehouse_ref": row.destination_warehouse_ref,
                    "requested_by": row.requested_by,
                    "approved_by": row.approved_by,
                    "reason": row.reason,
                    "lines_count": row.lines.count(),
                }
                for row in rows
            ]
        }
    )


def _run_command(request, transfer_id, command):
    try:
        result = command(
            transfer_id=str(transfer_id),
            payload=parse_json_body(request),
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request),
        )
        return json_response(result.payload, status=result.status)
    except Exception as exc:
        return _transfer_error_response(exc)


@csrf_exempt
@require_http_methods(["POST"])
def approve(request, transfer_id):
    return _run_command(request, transfer_id, approve_transfer)


@csrf_exempt
@require_http_methods(["POST"])
def prepare(request, transfer_id):
    return _run_command(request, transfer_id, prepare_transfer)


@csrf_exempt
@require_http_methods(["POST"])
def dispatch(request, transfer_id):
    return _run_command(request, transfer_id, dispatch_transfer)


@csrf_exempt
@require_http_methods(["POST"])
def receive(request, transfer_id):
    return _run_command(request, transfer_id, receive_transfer)


@csrf_exempt
@require_http_methods(["POST"])
def close(request, transfer_id):
    return _run_command(request, transfer_id, close_transfer)

