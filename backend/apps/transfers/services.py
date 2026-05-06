from __future__ import annotations

import json
import hashlib
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.core.models import AuditTrail, DomainEventOutbox, IdempotencyKey, StatusHistory
from apps.core.sequences import allocate_sequence_number
from apps.fulfillment.services import IdempotentResult
from apps.inventory.models import InventoryLedgerEntry, InventoryReservation, StockState
from apps.inventory.services import (
    InventoryRuleError,
    move_prepared_stock_to_state,
    move_reserved_inventory_to_preparation,
    move_transit_stock_to_state,
    pack_reserved_inventory,
    reserve_inventory,
)
from apps.transfers.models import TransferOrder, TransferOrderLine, TransferReceipt, TransferShipment


TRANSFER_SEQUENCE_NAME = "Transferencias"
TRANSFER_SHIPMENT_SEQUENCE_NAME = "Despachos TR"
TRANSFER_RECEIPT_SEQUENCE_NAME = "Recepciones TR"
ZERO = Decimal("0")


class TransferRuleError(ValueError):
    pass


def _decimal(value, default: str = "0") -> Decimal:
    if value in [None, ""]:
        value = default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _request_hash(payload: dict) -> str:
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
    request_hash = _request_hash(payload)
    existing = IdempotencyKey.objects.filter(key=key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise TransferRuleError("La Idempotency-Key ya fue usada con otro payload.")
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


def _serialize_transfer(transfer: TransferOrder) -> dict:
    transfer = TransferOrder.objects.prefetch_related("lines", "shipments", "receipts").get(id=transfer.id)
    return {
        "id": str(transfer.id),
        "transfer_number": transfer.transfer_number,
        "status": transfer.status,
        "origin_warehouse_ref": transfer.origin_warehouse_ref,
        "destination_warehouse_ref": transfer.destination_warehouse_ref,
        "requested_by": transfer.requested_by,
        "approved_by": transfer.approved_by,
        "reason": transfer.reason,
        "lines": [
            {
                "id": str(line.id),
                "line_number": line.line_number,
                "item_ref": line.item_ref,
                "requested_qty": str(line.requested_qty),
                "shipped_qty": str(line.shipped_qty),
                "received_qty": str(line.received_qty),
                "difference_qty": str(line.difference_qty),
                "uom": line.uom,
                "warehouse_ref": line.warehouse_ref,
            }
            for line in transfer.lines.all().order_by("line_number")
        ],
        "shipments": [
            {
                "id": str(shipment.id),
                "shipment_number": shipment.shipment_number,
                "status": shipment.status,
                "shipped_at": shipment.shipped_at.isoformat() if shipment.shipped_at else None,
            }
            for shipment in transfer.shipments.all().order_by("created_at")
        ],
        "receipts": [
            {
                "id": str(receipt.id),
                "receipt_number": receipt.receipt_number,
                "status": receipt.status,
                "received_at": receipt.received_at.isoformat() if receipt.received_at else None,
                "has_differences": receipt.has_differences,
            }
            for receipt in transfer.receipts.all().order_by("created_at")
        ],
    }


@transaction.atomic
def create_transfer(*, payload: dict, idempotency_key: str, actor: str) -> IdempotentResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="transfer.create",
        reference_type="transfer_order",
        reference_id="new",
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)
    origin = str(payload.get("origin_warehouse_ref") or payload.get("origin_warehouse") or "").strip()
    destination = str(payload.get("destination_warehouse_ref") or payload.get("destination_warehouse") or "").strip()
    if not origin or not destination or origin == destination:
        raise TransferRuleError("La transferencia requiere origen y destino distintos.")
    lines = payload.get("lines") or []
    if not lines:
        raise TransferRuleError("La transferencia requiere lineas.")
    transfer = TransferOrder.objects.create(
        transfer_number=allocate_sequence_number(TRANSFER_SEQUENCE_NAME, actor=actor),
        origin_warehouse_ref=origin,
        destination_warehouse_ref=destination,
        requested_by=str(payload.get("requested_by") or actor),
        reason=str(payload.get("reason") or "").strip(),
        created_by=actor,
    )
    for index, line in enumerate(lines, start=1):
        qty = _decimal(line.get("requested_qty") or line.get("quantity"))
        if qty <= ZERO:
            raise TransferRuleError("Todas las lineas deben tener cantidad positiva.")
        TransferOrderLine.objects.create(
            transfer=transfer,
            line_number=int(line.get("line_number") or index),
            requested_qty=qty,
            uom=str(line.get("uom") or "UN"),
            item_ref=str(line.get("item_ref") or "").strip(),
            warehouse_ref=origin,
            created_by=actor,
        )
    AuditTrail.objects.create(
        entity_type="transfer_order",
        entity_id=str(transfer.id),
        action="created",
        actor=actor,
        after={"transfer_number": transfer.transfer_number},
    )
    result = IdempotentResult({"result": _serialize_transfer(transfer)}, 201)
    return _finish_idempotent_command(idempotency, result)


def _transition_transfer(transfer: TransferOrder, *, to_status: str, actor: str, reason: str, payload=None) -> None:
    from_status = transfer.status
    transfer.status = to_status
    transfer.updated_by = actor
    transfer.save(update_fields=["status", "updated_by", "updated_at"])
    _status_history("transfer_order", str(transfer.id), from_status, to_status, actor, reason, payload)


@transaction.atomic
def approve_transfer(*, transfer_id: str, payload: dict, idempotency_key: str, actor: str) -> IdempotentResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="transfer.approve",
        reference_type="transfer_order",
        reference_id=transfer_id,
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)
    transfer = TransferOrder.objects.select_for_update().get(id=transfer_id)
    if transfer.status != TransferOrder.TransferStatus.REQUESTED:
        raise TransferRuleError("Solo se pueden aprobar transferencias solicitadas.")
    transfer.approved_by = str(payload.get("approved_by") or actor)
    transfer.save(update_fields=["approved_by", "updated_at"])
    _transition_transfer(transfer, to_status=TransferOrder.TransferStatus.APPROVED, actor=actor, reason="Aprobacion de transferencia")
    result = IdempotentResult({"result": _serialize_transfer(transfer)})
    return _finish_idempotent_command(idempotency, result)


@transaction.atomic
def prepare_transfer(*, transfer_id: str, payload: dict, idempotency_key: str, actor: str) -> IdempotentResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="transfer.prepare",
        reference_type="transfer_order",
        reference_id=transfer_id,
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)
    transfer = TransferOrder.objects.select_for_update().prefetch_related("lines").get(id=transfer_id)
    if transfer.status not in [TransferOrder.TransferStatus.REQUESTED, TransferOrder.TransferStatus.APPROVED, TransferOrder.TransferStatus.PICKING]:
        raise TransferRuleError("La transferencia no puede prepararse en su estado actual.")
    if not InventoryReservation.objects.filter(source_type="transfer_order", source_ref=str(transfer.id)).exists():
        try:
            reserve_inventory(
                warehouse_ref=transfer.origin_warehouse_ref,
                source_type="transfer_order",
                source_ref=str(transfer.id),
                actor=actor,
                lines=[
                    {
                        "item_ref": line.item_ref,
                        "warehouse_ref": transfer.origin_warehouse_ref,
                        "quantity": str(line.requested_qty),
                        "uom": line.uom,
                    }
                    for line in transfer.lines.all()
                ],
                idempotency_key=f"{idempotency_key}:inventory",
                source_stock_state=StockState.ON_HAND,
            )
        except InventoryRuleError as exc:
            raise TransferRuleError(str(exc)) from exc
    try:
        move_reserved_inventory_to_preparation(
            source_type="transfer_order",
            source_ref=str(transfer.id),
            actor=actor,
            idempotency_key=f"{idempotency_key}:prepare-location",
        )
    except (InventoryRuleError, InventoryReservation.DoesNotExist) as exc:
        raise TransferRuleError(str(exc)) from exc
    _transition_transfer(transfer, to_status=TransferOrder.TransferStatus.PICKING, actor=actor, reason="Preparacion de transferencia")
    result = IdempotentResult({"result": _serialize_transfer(transfer)})
    return _finish_idempotent_command(idempotency, result)


@transaction.atomic
def dispatch_transfer(*, transfer_id: str, payload: dict, idempotency_key: str, actor: str) -> IdempotentResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="transfer.dispatch",
        reference_type="transfer_order",
        reference_id=transfer_id,
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)
    transfer = TransferOrder.objects.select_for_update().prefetch_related("lines").get(id=transfer_id)
    if transfer.status not in [TransferOrder.TransferStatus.APPROVED, TransferOrder.TransferStatus.PICKING, TransferOrder.TransferStatus.DISPATCHED]:
        raise TransferRuleError("La transferencia debe estar aprobada o en picking para despacharse.")
    if transfer.status != TransferOrder.TransferStatus.DISPATCHED:
        try:
            pack_reserved_inventory(
                source_type="transfer_order",
                source_ref=str(transfer.id),
                actor=actor,
                idempotency_key=f"{idempotency_key}:pack",
            )
        except (InventoryRuleError, InventoryReservation.DoesNotExist) as exc:
            raise TransferRuleError(str(exc)) from exc
    for index, line in enumerate(transfer.lines.select_for_update().all(), start=1):
        ship_qty = _decimal((payload.get("lines_by_id") or {}).get(str(line.id)) or line.requested_qty)
        if ship_qty <= ZERO or ship_qty > line.requested_qty:
            raise TransferRuleError("La cantidad despachada debe ser positiva y no superar lo solicitado.")
        if line.shipped_qty >= ship_qty:
            continue
        delta = ship_qty - line.shipped_qty
        move_prepared_stock_to_state(
            warehouse_ref=transfer.origin_warehouse_ref,
            item_ref=line.item_ref,
            quantity=delta,
            uom=line.uom,
            to_state=StockState.IN_TRANSIT,
            target_location_purpose="transit",
            source_type="transfer_order",
            source_ref=str(transfer.id),
            document_type="transfer_order",
            document_ref=str(transfer.id),
            actor=actor,
            idempotency_key=f"{idempotency_key}:dispatch:{index}",
            reason="Despacho de transferencia",
            movement_type=InventoryLedgerEntry.MovementType.TRANSFER_OUT,
        )
        line.shipped_qty = ship_qty
        line.updated_by = actor
        line.save(update_fields=["shipped_qty", "updated_by", "updated_at"])
    if not transfer.shipments.exists():
        TransferShipment.objects.create(
            transfer=transfer,
            shipment_number=allocate_sequence_number(TRANSFER_SHIPMENT_SEQUENCE_NAME, actor=actor),
            status="dispatched",
            shipped_at=timezone.now(),
            actor=actor,
            created_by=actor,
        )
    _transition_transfer(transfer, to_status=TransferOrder.TransferStatus.IN_TRANSIT, actor=actor, reason="Despacho de transferencia")
    result = IdempotentResult({"result": _serialize_transfer(transfer)})
    return _finish_idempotent_command(idempotency, result)


@transaction.atomic
def receive_transfer(*, transfer_id: str, payload: dict, idempotency_key: str, actor: str) -> IdempotentResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="transfer.receive",
        reference_type="transfer_order",
        reference_id=transfer_id,
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)
    transfer = TransferOrder.objects.select_for_update().prefetch_related("lines").get(id=transfer_id)
    if transfer.status not in [TransferOrder.TransferStatus.IN_TRANSIT, TransferOrder.TransferStatus.PARTIAL_RECEIVED, TransferOrder.TransferStatus.DISCREPANT]:
        raise TransferRuleError("La transferencia debe estar en transito para recibirse.")
    received_lines = {str(row.get("line_id") or ""): _decimal(row.get("received_qty")) for row in payload.get("lines", [])}
    has_differences = False
    for index, line in enumerate(transfer.lines.select_for_update().all(), start=1):
        target_received = received_lines.get(str(line.id), line.shipped_qty)
        if target_received > line.shipped_qty and not payload.get("incident_ref"):
            raise TransferRuleError("Recibir mas que lo despachado requiere incidencia.")
        if target_received < line.received_qty:
            raise TransferRuleError("No se puede reducir una cantidad ya recibida.")
        delta = target_received - line.received_qty
        if delta > ZERO:
            move_transit_stock_to_state(
                source_warehouse_ref=transfer.origin_warehouse_ref,
                target_warehouse_ref=transfer.destination_warehouse_ref,
                item_ref=line.item_ref,
                quantity=delta,
                uom=line.uom,
                to_state=StockState.ON_HAND,
                target_location_purpose="available",
                document_type="transfer_order",
                document_ref=str(transfer.id),
                actor=actor,
                idempotency_key=f"{idempotency_key}:receive:{index}",
                reason="Recepcion de transferencia",
                movement_type=InventoryLedgerEntry.MovementType.TRANSFER_IN,
            )
        line.received_qty = target_received
        line.difference_qty = line.shipped_qty - line.received_qty
        has_differences = has_differences or line.difference_qty != ZERO
        line.updated_by = actor
        line.save(update_fields=["received_qty", "difference_qty", "updated_by", "updated_at"])
    TransferReceipt.objects.create(
        transfer=transfer,
        receipt_number=allocate_sequence_number(TRANSFER_RECEIPT_SEQUENCE_NAME, actor=actor),
        status="received",
        received_at=timezone.now(),
        actor=actor,
        has_differences=has_differences,
        created_by=actor,
    )
    if has_differences:
        next_status = TransferOrder.TransferStatus.DISCREPANT if payload.get("close_with_difference") else TransferOrder.TransferStatus.PARTIAL_RECEIVED
    elif transfer.lines.filter(received_qty__lt=F("shipped_qty")).exists():
        next_status = TransferOrder.TransferStatus.PARTIAL_RECEIVED
    else:
        next_status = TransferOrder.TransferStatus.RECEIVED
    _transition_transfer(transfer, to_status=next_status, actor=actor, reason="Recepcion de transferencia")
    result = IdempotentResult({"result": _serialize_transfer(transfer)})
    return _finish_idempotent_command(idempotency, result)

@transaction.atomic
def close_transfer(*, transfer_id: str, payload: dict, idempotency_key: str, actor: str) -> IdempotentResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="transfer.close",
        reference_type="transfer_order",
        reference_id=transfer_id,
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)
    transfer = TransferOrder.objects.select_for_update().prefetch_related("lines").get(id=transfer_id)
    if transfer.status not in [TransferOrder.TransferStatus.RECEIVED, TransferOrder.TransferStatus.DISCREPANT, TransferOrder.TransferStatus.PARTIAL_RECEIVED]:
        raise TransferRuleError("La transferencia debe estar recibida o discrepante para cerrarse.")
    has_differences = transfer.lines.exclude(difference_qty=ZERO).exists()
    if has_differences and not str(payload.get("reason") or transfer.reason or "").strip():
        raise TransferRuleError("El cierre con diferencias requiere motivo documentado.")
    if payload.get("reason"):
        transfer.reason = str(payload["reason"])
        transfer.save(update_fields=["reason", "updated_at"])
    _transition_transfer(transfer, to_status=TransferOrder.TransferStatus.CLOSED, actor=actor, reason="Cierre de transferencia", payload={"has_differences": has_differences})
    AuditTrail.objects.create(
        entity_type="transfer_order",
        entity_id=str(transfer.id),
        action="closed",
        actor=actor,
        reason=transfer.reason,
        after={"status": transfer.status, "has_differences": has_differences},
    )
    DomainEventOutbox.objects.create(
        event_type="transfer.closed",
        aggregate_type="transfer_order",
        aggregate_id=str(transfer.id),
        payload={"has_differences": has_differences},
    )
    result = IdempotentResult({"result": _serialize_transfer(transfer)})
    return _finish_idempotent_command(idempotency, result)
