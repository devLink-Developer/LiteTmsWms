from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.core.models import AuditTrail, DomainEventOutbox
from apps.inventory.models import (
    InventoryBalance,
    InventoryLedgerEntry,
    InventoryReservation,
    InventoryReservationLine,
    InventoryTransformation,
    InventoryTransformationLine,
    StockState,
)


class InventoryRuleError(ValueError):
    pass


@dataclass(frozen=True)
class LedgerCommand:
    idempotency_key: str
    movement_type: str
    direction: str
    warehouse_ref: str
    item_ref: str
    stock_state: str
    quantity: Decimal
    uom: str
    document_type: str
    document_ref: str
    actor: str
    reason: str = ""
    legacy_sales_order_number: str = ""
    legacy_line_id: str = ""


def _signed_quantity(direction: str, quantity: Decimal) -> Decimal:
    if quantity <= 0:
        raise InventoryRuleError("La cantidad debe ser mayor a cero.")
    if direction == InventoryLedgerEntry.Direction.INCREASE:
        return quantity
    if direction == InventoryLedgerEntry.Direction.DECREASE:
        return quantity * Decimal("-1")
    raise InventoryRuleError(f"Direccion de movimiento invalida: {direction}")


def _apply_balance_delta(
    *,
    warehouse_ref: str,
    item_ref: str,
    stock_state: str,
    uom: str,
    delta: Decimal,
) -> InventoryBalance:
    balance, _ = InventoryBalance.objects.select_for_update().get_or_create(
        warehouse_ref=warehouse_ref,
        item_ref=item_ref,
        lot_ref="",
        stock_state=stock_state,
        uom=uom,
        defaults={"quantity": Decimal("0")},
    )
    next_quantity = balance.quantity + delta
    if next_quantity < 0:
        raise InventoryRuleError("La operacion dejaria stock negativo.")
    balance.quantity = next_quantity
    balance.version += 1
    balance.save(update_fields=["quantity", "version", "updated_at"])
    return balance


@transaction.atomic
def post_ledger_entry(command: LedgerCommand) -> InventoryLedgerEntry:
    existing = InventoryLedgerEntry.objects.filter(idempotency_key=command.idempotency_key).first()
    if existing:
        return existing

    delta = _signed_quantity(command.direction, command.quantity)
    balance = _apply_balance_delta(
        warehouse_ref=command.warehouse_ref,
        item_ref=command.item_ref,
        stock_state=command.stock_state,
        uom=command.uom,
        delta=delta,
    )
    entry = InventoryLedgerEntry.objects.create(
        idempotency_key=command.idempotency_key,
        movement_type=command.movement_type,
        direction=command.direction,
        warehouse_ref=command.warehouse_ref,
        item_ref=command.item_ref,
        stock_state=command.stock_state,
        quantity=command.quantity,
        uom=command.uom,
        document_type=command.document_type,
        document_ref=command.document_ref,
        reason=command.reason,
        created_by=command.actor,
        legacy_sales_order_number=command.legacy_sales_order_number,
        legacy_line_id=command.legacy_line_id,
        payload={"balance_id": str(balance.id), "balance_version": balance.version},
    )
    AuditTrail.objects.create(
        entity_type="inventory_ledger_entry",
        entity_id=str(entry.id),
        action="posted",
        actor=command.actor,
        reason=command.reason,
        after={"movement_type": entry.movement_type, "quantity": str(entry.quantity)},
        source_references={
            "document_type": command.document_type,
            "document_ref": command.document_ref,
            "legacy_sales_order_number": command.legacy_sales_order_number,
            "legacy_line_id": command.legacy_line_id,
        },
    )
    DomainEventOutbox.objects.create(
        event_type="inventory.ledger.posted",
        aggregate_type="inventory_ledger_entry",
        aggregate_id=str(entry.id),
        payload={"warehouse_ref": entry.warehouse_ref, "item_ref": entry.item_ref},
    )
    return entry


@transaction.atomic
def reserve_inventory(
    *,
    warehouse_ref: str,
    source_type: str,
    source_ref: str,
    actor: str,
    lines: list[dict[str, str]],
    idempotency_key: str,
    source_stock_state: str = StockState.ON_HAND,
) -> InventoryReservation:
    existing = InventoryReservation.objects.filter(source_type=source_type, source_ref=source_ref).first()
    if existing:
        return existing

    reservation = InventoryReservation.objects.create(
        warehouse_ref=warehouse_ref,
        source_type=source_type,
        source_ref=source_ref,
        requested_by=actor,
        created_by=actor,
    )
    reservation_lines = []
    for index, line in enumerate(lines, start=1):
        qty = Decimal(line["quantity"])
        item_ref = line["item_ref"]
        line_warehouse_ref = line.get("warehouse_ref") or warehouse_ref
        uom = line.get("uom", "UN")
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:hold:{index}",
                movement_type=InventoryLedgerEntry.MovementType.RESERVATION_HOLD,
                direction=InventoryLedgerEntry.Direction.DECREASE,
                warehouse_ref=line_warehouse_ref,
                item_ref=item_ref,
                stock_state=source_stock_state,
                quantity=qty,
                uom=uom,
                document_type="inventory_reservation",
                document_ref=str(reservation.id),
                actor=actor,
                reason="Reserva operativa",
                legacy_sales_order_number=line.get("legacy_sales_order_number", ""),
                legacy_line_id=line.get("legacy_line_id", ""),
            )
        )
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:reserved:{index}",
                movement_type=InventoryLedgerEntry.MovementType.RESERVATION_HOLD,
                direction=InventoryLedgerEntry.Direction.INCREASE,
                warehouse_ref=line_warehouse_ref,
                item_ref=item_ref,
                stock_state=StockState.RESERVED,
                quantity=qty,
                uom=uom,
                document_type="inventory_reservation",
                document_ref=str(reservation.id),
                actor=actor,
                reason="Reserva operativa",
                legacy_sales_order_number=line.get("legacy_sales_order_number", ""),
                legacy_line_id=line.get("legacy_line_id", ""),
            )
        )
        reservation_lines.append(
            InventoryReservationLine(
                reservation=reservation,
                warehouse_ref=line_warehouse_ref,
                item_ref=item_ref,
                requested_qty=qty,
                reserved_qty=qty,
                uom=uom,
                legacy_sales_order_number=line.get("legacy_sales_order_number", ""),
                legacy_line_id=line.get("legacy_line_id", ""),
                created_by=actor,
            )
        )
    if reservation_lines:
        InventoryReservationLine.objects.bulk_create(reservation_lines)
    reservation.status = InventoryReservation.ReservationStatus.ALLOCATED
    reservation.save(update_fields=["status", "updated_at"])
    return reservation


@transaction.atomic
def pack_reserved_inventory(
    *,
    source_type: str,
    source_ref: str,
    actor: str,
    idempotency_key: str,
) -> InventoryReservation:
    reservation = InventoryReservation.objects.select_for_update().prefetch_related("lines").get(
        source_type=source_type,
        source_ref=source_ref,
    )
    if reservation.status == InventoryReservation.ReservationStatus.CONSUMED:
        return reservation
    if reservation.status != InventoryReservation.ReservationStatus.ALLOCATED:
        raise InventoryRuleError("La reserva debe estar asignada para preparar stock.")

    lines_to_update = []
    now = timezone.now()
    for index, line in enumerate(reservation.lines.all(), start=1):
        qty = line.reserved_qty - line.fulfilled_qty
        if qty <= 0:
            continue
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:reserved:{index}",
                movement_type=InventoryLedgerEntry.MovementType.PICK,
                direction=InventoryLedgerEntry.Direction.DECREASE,
                warehouse_ref=line.warehouse_ref or reservation.warehouse_ref,
                item_ref=line.item_ref,
                stock_state=StockState.RESERVED,
                quantity=qty,
                uom=line.uom,
                document_type=source_type,
                document_ref=source_ref,
                actor=actor,
                reason="Preparacion de entrega",
                legacy_sales_order_number=line.legacy_sales_order_number,
                legacy_line_id=line.legacy_line_id,
            )
        )
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:packed:{index}",
                movement_type=InventoryLedgerEntry.MovementType.PICK,
                direction=InventoryLedgerEntry.Direction.INCREASE,
                warehouse_ref=line.warehouse_ref or reservation.warehouse_ref,
                item_ref=line.item_ref,
                stock_state=StockState.PACKED,
                quantity=qty,
                uom=line.uom,
                document_type=source_type,
                document_ref=source_ref,
                actor=actor,
                reason="Preparacion de entrega",
                legacy_sales_order_number=line.legacy_sales_order_number,
                legacy_line_id=line.legacy_line_id,
            )
        )
        line.fulfilled_qty += qty
        line.updated_by = actor
        line.updated_at = now
        lines_to_update.append(line)

    if lines_to_update:
        InventoryReservationLine.objects.bulk_update(
            lines_to_update,
            ["fulfilled_qty", "updated_by", "updated_at"],
        )

    reservation.status = InventoryReservation.ReservationStatus.CONSUMED
    reservation.updated_by = actor
    reservation.save(update_fields=["status", "updated_by", "updated_at"])
    return reservation


@transaction.atomic
def post_transformation(transformation_id: UUID, *, actor: str, idempotency_key: str) -> InventoryTransformation:
    transformation = InventoryTransformation.objects.select_for_update().get(id=transformation_id)
    if transformation.status == InventoryTransformation.TransformationStatus.POSTED:
        return transformation
    if transformation.status not in [
        InventoryTransformation.TransformationStatus.DRAFT,
        InventoryTransformation.TransformationStatus.VALIDATED,
    ]:
        raise InventoryRuleError("La transformacion no puede postearse en su estado actual.")

    lines = list(transformation.lines.all())
    input_total = sum((line.quantity for line in lines if line.role == InventoryTransformationLine.LineRole.INPUT), Decimal("0"))
    output_total = sum(
        (line.quantity for line in lines if line.role in [InventoryTransformationLine.LineRole.OUTPUT, InventoryTransformationLine.LineRole.WASTE]),
        Decimal("0"),
    )
    if input_total <= 0 or output_total <= 0:
        raise InventoryRuleError("La transformacion requiere origen y destino.")

    for index, line in enumerate(lines, start=1):
        is_input = line.role == InventoryTransformationLine.LineRole.INPUT
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:line:{index}",
                movement_type=(
                    InventoryLedgerEntry.MovementType.TRANSFORMATION_OUT
                    if is_input
                    else InventoryLedgerEntry.MovementType.TRANSFORMATION_IN
                ),
                direction=(
                    InventoryLedgerEntry.Direction.DECREASE
                    if is_input
                    else InventoryLedgerEntry.Direction.INCREASE
                ),
                warehouse_ref=line.warehouse_ref or transformation.warehouse_ref,
                item_ref=line.item_ref,
                stock_state=StockState.ON_HAND,
                quantity=line.quantity,
                uom=line.uom,
                document_type="inventory_transformation",
                document_ref=str(transformation.id),
                actor=actor,
                reason=transformation.reason,
            )
        )
    transformation.status = InventoryTransformation.TransformationStatus.POSTED
    transformation.posted_at = timezone.now()
    transformation.updated_by = actor
    transformation.save(update_fields=["status", "posted_at", "updated_by", "updated_at"])
    return transformation
