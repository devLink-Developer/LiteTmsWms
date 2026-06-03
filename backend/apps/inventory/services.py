from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import AuditTrail, DomainEventOutbox, IdempotencyKey, StatusHistory
from apps.inventory.models import (
    InventoryBalance,
    InventoryLedgerEntry,
    InventoryReservation,
    InventoryReservationLine,
    InventoryTransformation,
    InventoryTransformationLine,
    InventoryWriteOff,
    InventoryWriteOffLine,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptLine,
    StockState,
)
from apps.logistics.models import WarehouseLocation, WarehouseMaster
from apps.logistics.parquet_master_data import calculate_sheet_cutting_plan
from apps.logistics.services import default_location_ref, generate_default_locations


class InventoryRuleError(ValueError):
    pass


@dataclass(frozen=True)
class InventoryCommandResult:
    payload: dict
    status: int = 200


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
    location_ref: str = ""
    reason: str = ""
    lot_ref: str = ""
    legacy_sales_order_number: str = ""
    legacy_line_id: str = ""
    is_reversal: bool = False
    reversal_of: UUID | None = None


ZERO = Decimal("0")
QTY_SCALE = Decimal("0.000001")


@dataclass(frozen=True)
class StockAllocation:
    warehouse_ref: str
    location_ref: str
    item_ref: str
    stock_state: str
    quantity: Decimal
    uom: str
    lot_ref: str = ""


STATE_DEFAULT_PURPOSE = {
    StockState.ON_HAND: "available",
    StockState.PACKED: "available",
    StockState.RESERVED: "reserved",
    StockState.PICKING: "preparation",
    StockState.IN_TRANSIT: "transit",
    StockState.DELIVERED: "transit",
    StockState.SCRAPPED: "loss",
}


def _clean(value) -> str:
    return str(value or "").strip()


def _stock_uom(value) -> str:
    unit = _clean(value).upper()
    if unit in {"", "ST", "UN", "UND", "UNIDAD", "UNIDADES", "EA", "PZA", "PZ"}:
        return "UN"
    return unit


def _decimal(value, default: str = "0") -> Decimal:
    if value in [None, ""]:
        value = default
    try:
        return Decimal(str(value)).quantize(QTY_SCALE)
    except (InvalidOperation, ValueError):
        return Decimal(default).quantize(QTY_SCALE)


def _warehouse_ref(value) -> str:
    return _clean(value).upper()


def stock_state_default_purpose(stock_state: str) -> str:
    purpose = STATE_DEFAULT_PURPOSE.get(stock_state)
    if not purpose:
        raise InventoryRuleError(f"Estado sin ubicacion default configurada: {stock_state}")
    return purpose


def location_ref_for_purpose(warehouse_ref: str, purpose: str, *, actor: str = "system") -> str:
    wh = _warehouse_ref(warehouse_ref)
    if not wh:
        raise InventoryRuleError("warehouse_ref es obligatorio para resolver ubicacion.")
    field_by_purpose = {
        "available": "default_available_location_ref",
        "reserved": "default_reserved_location_ref",
        "preparation": "default_preparation_location_ref",
        "transit": "default_transit_location_ref",
        "breakage": "default_breakage_location_ref",
        "loss": "default_loss_location_ref",
    }
    field = field_by_purpose.get(purpose)
    if not field:
        raise InventoryRuleError(f"Purpose de ubicacion invalido: {purpose}")
    warehouse = WarehouseMaster.objects.filter(warehouse_ref=wh).first()
    configured = _clean(getattr(warehouse, field, "") if warehouse else "")
    if configured:
        return configured
    generate_default_locations(warehouse_ref=wh, actor=actor)
    fallback = default_location_ref(wh, purpose)
    if warehouse and hasattr(warehouse, field) and not getattr(warehouse, field):
        setattr(warehouse, field, fallback)
        warehouse.updated_by = actor
        warehouse.save(update_fields=[field, "updated_by", "updated_at"])
    return fallback


def _dispatchable_location_refs(warehouse_ref: str, *, actor: str = "system") -> list[str]:
    wh = _warehouse_ref(warehouse_ref)
    refs = list(
        WarehouseLocation.objects.filter(warehouse_ref=wh, active=True, is_dispatchable=True)
        .order_by("sort_order", "system_location", "location_ref")
        .values_list("location_ref", flat=True)
    )
    if refs:
        return refs
    generate_default_locations(warehouse_ref=wh, actor=actor)
    refs = list(
        WarehouseLocation.objects.filter(warehouse_ref=wh, active=True, is_dispatchable=True)
        .order_by("sort_order", "system_location", "location_ref")
        .values_list("location_ref", flat=True)
    )
    return refs or [location_ref_for_purpose(wh, "available", actor=actor)]


def _normalize_blank_balances_for_key(
    *,
    warehouse_ref: str,
    item_ref: str,
    stock_state: str,
    uom: str,
    actor: str,
    lot_ref: str = "",
) -> None:
    purpose = stock_state_default_purpose(stock_state)
    target_location_ref = location_ref_for_purpose(warehouse_ref, purpose, actor=actor)
    blank_balances = list(
        InventoryBalance.objects.select_for_update().filter(
            warehouse_ref=warehouse_ref,
            location_ref="",
            item_ref=item_ref,
            lot_ref=lot_ref,
            stock_state=stock_state,
            uom=uom,
        )
    )
    if not blank_balances:
        return
    for blank in blank_balances:
        target, _created = InventoryBalance.objects.select_for_update().get_or_create(
            warehouse_ref=warehouse_ref,
            location_ref=target_location_ref,
            item_ref=item_ref,
            lot_ref=blank.lot_ref,
            stock_state=stock_state,
            uom=uom,
            defaults={"quantity": Decimal("0"), "created_by": actor, "updated_by": actor},
        )
        target.quantity += blank.quantity
        target.version += 1
        target.updated_by = actor
        target.save(update_fields=["quantity", "version", "updated_by", "updated_at"])
        blank.delete()


def _location_order(warehouse_ref: str, location_refs: list[str]) -> dict[str, tuple[int, int, str]]:
    if not location_refs:
        return {}
    locations = WarehouseLocation.objects.filter(warehouse_ref=warehouse_ref, location_ref__in=location_refs)
    return {
        location.location_ref: (location.sort_order, 1 if location.system_location else 0, location.location_ref)
        for location in locations
    }


def _allocate_balances(
    *,
    warehouse_ref: str,
    item_ref: str,
    stock_state: str,
    quantity: Decimal,
    uom: str,
    actor: str,
    location_refs: list[str],
    lot_ref: str = "",
    normalize_blank: bool = True,
) -> list[StockAllocation]:
    wh = _warehouse_ref(warehouse_ref)
    item = _clean(item_ref)
    unit = _stock_uom(uom)
    qty = _decimal(quantity)
    lot = _clean(lot_ref)
    if qty <= ZERO:
        raise InventoryRuleError("La cantidad debe ser mayor a cero.")
    if normalize_blank:
        _normalize_blank_balances_for_key(
            warehouse_ref=wh,
            item_ref=item,
            stock_state=stock_state,
            uom=unit,
            lot_ref=lot,
            actor=actor,
        )
    refs = [_clean(ref) for ref in location_refs if _clean(ref)]
    if not refs:
        raise InventoryRuleError("No hay ubicaciones disponibles para asignar stock.")
    balances = list(
        InventoryBalance.objects.select_for_update().filter(
            warehouse_ref=wh,
            location_ref__in=refs,
            item_ref=item,
            lot_ref=lot,
            stock_state=stock_state,
            uom=unit,
            quantity__gt=ZERO,
        )
    )
    order = _location_order(wh, refs)
    balances.sort(key=lambda balance: (order.get(balance.location_ref, (999999, 1, balance.location_ref)), str(balance.id)))
    remaining = qty
    allocations: list[StockAllocation] = []
    for balance in balances:
        if remaining <= ZERO:
            break
        taken = min(remaining, balance.quantity).quantize(QTY_SCALE)
        if taken <= ZERO:
            continue
        allocations.append(
            StockAllocation(
                warehouse_ref=wh,
                location_ref=balance.location_ref,
                item_ref=item,
                stock_state=stock_state,
                quantity=taken,
                uom=unit,
                lot_ref=balance.lot_ref,
            )
        )
        remaining -= taken
    if remaining > ZERO:
        raise InventoryRuleError("Stock insuficiente en ubicaciones disponibles.")
    return allocations


def available_stock_quantities_for_keys(
    keys: set[tuple[str, str, str]],
    *,
    stock_state: str = StockState.PACKED,
    include_legacy_blank: bool = True,
    actor: str = "system",
) -> dict[tuple[str, str, str], Decimal]:
    normalized_keys = {
        (_warehouse_ref(warehouse_ref), _clean(item_ref), _clean(uom) or "UN"): _stock_uom(uom)
        for warehouse_ref, item_ref, uom in keys
        if _warehouse_ref(warehouse_ref) and _clean(item_ref) and (_clean(uom) or "UN")
    }
    if not normalized_keys:
        return {}
    totals = {key: ZERO for key in normalized_keys.keys()}
    requested_by_canonical_key: dict[tuple[str, str, str], list[tuple[str, str, str]]] = defaultdict(list)
    for requested_key, canonical_uom in normalized_keys.items():
        requested_by_canonical_key[(requested_key[0], requested_key[1], canonical_uom)].append(requested_key)
    warehouses = {key[0] for key in normalized_keys}
    items = {key[1] for key in normalized_keys}
    uoms = {
        variant
        for requested_uom, canonical_uom in {(key[2], canonical) for key, canonical in normalized_keys.items()}
        for variant in {requested_uom, requested_uom.upper(), requested_uom.lower(), canonical_uom, canonical_uom.upper(), canonical_uom.lower()}
        if variant
    }
    dispatchable_by_warehouse = {
        warehouse_ref: set(_dispatchable_location_refs(warehouse_ref, actor=actor))
        for warehouse_ref in warehouses
    }
    all_dispatchable_refs = {ref for refs in dispatchable_by_warehouse.values() for ref in refs}
    if all_dispatchable_refs:
        for row in (
            InventoryBalance.objects.filter(
                warehouse_ref__in=warehouses,
                location_ref__in=all_dispatchable_refs,
                item_ref__in=items,
                lot_ref="",
                stock_state=stock_state,
                uom__in=uoms,
            )
            .values("warehouse_ref", "item_ref", "uom")
            .annotate(total=Sum("quantity"))
        ):
            canonical_key = (row["warehouse_ref"], row["item_ref"], _stock_uom(row["uom"]))
            for requested_key in requested_by_canonical_key.get(canonical_key, []):
                totals[requested_key] += row["total"] or ZERO
    if include_legacy_blank:
        for row in (
            InventoryBalance.objects.filter(
                warehouse_ref__in=warehouses,
                location_ref="",
                item_ref__in=items,
                lot_ref="",
                stock_state=stock_state,
                uom__in=uoms,
            )
            .values("warehouse_ref", "item_ref", "uom")
            .annotate(total=Sum("quantity"))
        ):
            canonical_key = (row["warehouse_ref"], row["item_ref"], _stock_uom(row["uom"]))
            for requested_key in requested_by_canonical_key.get(canonical_key, []):
                totals[requested_key] += row["total"] or ZERO
    return totals


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
            raise InventoryRuleError("La Idempotency-Key ya fue usada con otro payload.")
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


def _finish_idempotent_command(record: IdempotencyKey, result: InventoryCommandResult) -> InventoryCommandResult:
    record.response_payload = result.payload
    record.response_status = result.status
    record.status = IdempotencyKey.ProcessingStatus.SUCCEEDED
    record.save(update_fields=["response_payload", "response_status", "status", "updated_at"])
    return result


def _status_history(entity_type: str, entity_id: str, from_status: str, to_status: str, actor: str, reason: str, payload=None) -> None:
    if from_status == to_status:
        return
    StatusHistory.objects.create(
        entity_type=entity_type,
        entity_id=entity_id,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        reason=reason,
        payload=payload or {},
    )


def _audit_event(entity_type: str, entity_id: str, action: str, actor: str, *, reason: str = "", before=None, after=None) -> None:
    AuditTrail.objects.create(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
        reason=reason,
        before=before or {},
        after=after or {},
    )
    DomainEventOutbox.objects.create(
        event_type=f"{entity_type}.{action}",
        aggregate_type=entity_type,
        aggregate_id=entity_id,
        payload={"before": before or {}, "after": after or {}, "actor": actor},
    )


def _write_off_number(payload: dict, idempotency_key: str) -> str:
    provided = _clean(payload.get("write_off_number"))
    if provided:
        return provided
    digest = hashlib.sha1(idempotency_key.encode("utf-8")).hexdigest()[:12].upper()
    return f"WO-{digest}"


def _signed_quantity(direction: str, quantity: Decimal) -> Decimal:
    if quantity <= 0:
        raise InventoryRuleError("La cantidad debe ser mayor a cero.")
    if direction == InventoryLedgerEntry.Direction.INCREASE:
        return quantity
    if direction == InventoryLedgerEntry.Direction.DECREASE:
        return quantity * Decimal("-1")
    raise InventoryRuleError(f"Direccion de movimiento invalida: {direction}")


def _display_decimal(value: Decimal) -> str:
    quantized = _decimal(value)
    if quantized == quantized.to_integral_value():
        return format(quantized.quantize(Decimal("1")), "f")
    return format(quantized.normalize(), "f")


def _apply_balance_delta(
    *,
    warehouse_ref: str,
    location_ref: str = "",
    item_ref: str,
    stock_state: str,
    uom: str,
    delta: Decimal,
    lot_ref: str = "",
) -> InventoryBalance:
    unit = _stock_uom(uom)
    balance, _ = InventoryBalance.objects.select_for_update().get_or_create(
        warehouse_ref=warehouse_ref,
        location_ref=location_ref,
        item_ref=item_ref,
        lot_ref=lot_ref,
        stock_state=stock_state,
        uom=unit,
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

    unit = _stock_uom(command.uom)
    delta = _signed_quantity(command.direction, command.quantity)
    balance = _apply_balance_delta(
        warehouse_ref=command.warehouse_ref,
        location_ref=command.location_ref,
        item_ref=command.item_ref,
        stock_state=command.stock_state,
        uom=unit,
        delta=delta,
        lot_ref=command.lot_ref,
    )
    entry = InventoryLedgerEntry.objects.create(
        idempotency_key=command.idempotency_key,
        movement_type=command.movement_type,
        direction=command.direction,
        warehouse_ref=command.warehouse_ref,
        location_ref=command.location_ref,
        item_ref=command.item_ref,
        stock_state=command.stock_state,
        lot_ref=command.lot_ref,
        quantity=command.quantity,
        uom=unit,
        document_type=command.document_type,
        document_ref=command.document_ref,
        reason=command.reason,
        is_reversal=command.is_reversal,
        reversal_of=command.reversal_of,
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
        after={
            "movement_type": entry.movement_type,
            "direction": entry.direction,
            "warehouse_ref": entry.warehouse_ref,
            "location_ref": entry.location_ref,
            "lot_ref": entry.lot_ref,
            "item_ref": entry.item_ref,
            "stock_state": entry.stock_state,
            "quantity": str(entry.quantity),
            "uom": entry.uom,
            "document_type": entry.document_type,
            "document_ref": entry.document_ref,
        },
        source_references={
            "document_type": command.document_type,
            "document_ref": command.document_ref,
            "location_ref": command.location_ref,
            "lot_ref": command.lot_ref,
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
    inactive_statuses = [
        InventoryReservation.ReservationStatus.RELEASED,
        InventoryReservation.ReservationStatus.CANCELLED,
        InventoryReservation.ReservationStatus.EXPIRED,
    ]
    existing = (
        InventoryReservation.objects.filter(source_type=source_type, source_ref=source_ref)
        .exclude(status__in=inactive_statuses)
        .first()
    )
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
        qty = _decimal(line["quantity"])
        item_ref = _clean(line["item_ref"])
        line_warehouse_ref = _warehouse_ref(line.get("warehouse_ref") or warehouse_ref)
        uom = _stock_uom(line.get("uom"))
        if source_stock_state in {StockState.ON_HAND, StockState.PACKED}:
            source_locations = _dispatchable_location_refs(line_warehouse_ref, actor=actor)
        else:
            source_locations = [location_ref_for_purpose(line_warehouse_ref, stock_state_default_purpose(source_stock_state), actor=actor)]
        reserved_location_ref = location_ref_for_purpose(line_warehouse_ref, "reserved", actor=actor)
        allocations = _allocate_balances(
            warehouse_ref=line_warehouse_ref,
            item_ref=item_ref,
            stock_state=source_stock_state,
            quantity=qty,
            uom=uom,
            lot_ref=line.get("lot_ref", ""),
            actor=actor,
            location_refs=source_locations,
        )
        for allocation_index, allocation in enumerate(allocations, start=1):
            allocation_key = f"{index}:{allocation_index}"
            post_ledger_entry(
                LedgerCommand(
                    idempotency_key=f"{idempotency_key}:hold:{allocation_key}",
                    movement_type=InventoryLedgerEntry.MovementType.RESERVATION_HOLD,
                    direction=InventoryLedgerEntry.Direction.DECREASE,
                    warehouse_ref=line_warehouse_ref,
                    location_ref=allocation.location_ref,
                    item_ref=item_ref,
                    stock_state=source_stock_state,
                    quantity=allocation.quantity,
                    uom=uom,
                    document_type="inventory_reservation",
                    document_ref=str(reservation.id),
                    actor=actor,
                    reason="Reserva operativa",
                    lot_ref=allocation.lot_ref,
                    legacy_sales_order_number=line.get("legacy_sales_order_number", ""),
                    legacy_line_id=line.get("legacy_line_id", ""),
                )
            )
            post_ledger_entry(
                LedgerCommand(
                    idempotency_key=f"{idempotency_key}:reserved:{allocation_key}",
                    movement_type=InventoryLedgerEntry.MovementType.RESERVATION_HOLD,
                    direction=InventoryLedgerEntry.Direction.INCREASE,
                    warehouse_ref=line_warehouse_ref,
                    location_ref=reserved_location_ref,
                    item_ref=item_ref,
                    stock_state=StockState.RESERVED,
                    quantity=allocation.quantity,
                    uom=uom,
                    document_type="inventory_reservation",
                    document_ref=str(reservation.id),
                    actor=actor,
                    reason="Reserva operativa",
                    lot_ref=allocation.lot_ref,
                    legacy_sales_order_number=line.get("legacy_sales_order_number", ""),
                    legacy_line_id=line.get("legacy_line_id", ""),
                )
            )
            reservation_lines.append(
                InventoryReservationLine(
                    reservation=reservation,
                    warehouse_ref=line_warehouse_ref,
                    item_ref=item_ref,
                    requested_qty=allocation.quantity,
                    reserved_qty=allocation.quantity,
                    source_location_ref=allocation.location_ref,
                    location_ref=reserved_location_ref,
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
def release_inventory_reservation(
    *,
    source_type: str,
    source_ref: str,
    actor: str,
    idempotency_key: str,
    target_stock_state: str = StockState.PACKED,
) -> InventoryReservation:
    reservation = InventoryReservation.objects.select_for_update().prefetch_related("lines").get(
        source_type=source_type,
        source_ref=source_ref,
        status=InventoryReservation.ReservationStatus.ALLOCATED,
    )
    release_location_purpose = stock_state_default_purpose(target_stock_state)
    for index, line in enumerate(reservation.lines.all(), start=1):
        qty = _decimal(line.reserved_qty)
        if qty <= ZERO:
            continue
        warehouse_ref = _warehouse_ref(line.warehouse_ref or reservation.warehouse_ref)
        item_ref = _clean(line.item_ref)
        uom = _clean(line.uom) or "UN"
        source_location_ref = _clean(line.location_ref) or location_ref_for_purpose(warehouse_ref, "reserved", actor=actor)
        target_location_ref = _clean(line.source_location_ref) or location_ref_for_purpose(
            warehouse_ref,
            release_location_purpose,
            actor=actor,
        )
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:release-reserved:{index}",
                movement_type=InventoryLedgerEntry.MovementType.RESERVATION_RELEASE,
                direction=InventoryLedgerEntry.Direction.DECREASE,
                warehouse_ref=warehouse_ref,
                location_ref=source_location_ref,
                item_ref=item_ref,
                stock_state=StockState.RESERVED,
                quantity=qty,
                uom=uom,
                document_type="inventory_reservation",
                document_ref=str(reservation.id),
                actor=actor,
                reason="Liberacion de reserva operativa",
                legacy_sales_order_number=line.legacy_sales_order_number,
                legacy_line_id=line.legacy_line_id,
            )
        )
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:release-stock:{index}",
                movement_type=InventoryLedgerEntry.MovementType.RESERVATION_RELEASE,
                direction=InventoryLedgerEntry.Direction.INCREASE,
                warehouse_ref=warehouse_ref,
                location_ref=target_location_ref,
                item_ref=item_ref,
                stock_state=target_stock_state,
                quantity=qty,
                uom=uom,
                document_type="inventory_reservation",
                document_ref=str(reservation.id),
                actor=actor,
                reason="Liberacion de reserva operativa",
                legacy_sales_order_number=line.legacy_sales_order_number,
                legacy_line_id=line.legacy_line_id,
            )
        )
    reservation.status = InventoryReservation.ReservationStatus.RELEASED
    reservation.updated_by = actor
    reservation.save(update_fields=["status", "updated_by", "updated_at"])
    return reservation


@transaction.atomic
def move_reserved_inventory_to_preparation(
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
    if reservation.status in [InventoryReservation.ReservationStatus.PREPARING, InventoryReservation.ReservationStatus.CONSUMED]:
        return reservation
    if reservation.status != InventoryReservation.ReservationStatus.ALLOCATED:
        raise InventoryRuleError("La reserva debe estar asignada para enviarse a preparacion.")

    lines_to_update = []
    now = timezone.now()
    for index, line in enumerate(reservation.lines.all(), start=1):
        qty = line.reserved_qty
        if qty <= ZERO:
            continue
        warehouse_ref = _warehouse_ref(line.warehouse_ref or reservation.warehouse_ref)
        source_location_ref = line.location_ref or location_ref_for_purpose(warehouse_ref, "reserved", actor=actor)
        target_location_ref = location_ref_for_purpose(warehouse_ref, "preparation", actor=actor)
        _normalize_blank_balances_for_key(
            warehouse_ref=warehouse_ref,
            item_ref=line.item_ref,
            stock_state=StockState.RESERVED,
            uom=line.uom,
            actor=actor,
        )
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:reserved:{index}",
                movement_type=InventoryLedgerEntry.MovementType.PICK,
                direction=InventoryLedgerEntry.Direction.DECREASE,
                warehouse_ref=warehouse_ref,
                location_ref=source_location_ref,
                item_ref=line.item_ref,
                stock_state=StockState.RESERVED,
                quantity=qty,
                uom=line.uom,
                document_type=source_type,
                document_ref=source_ref,
                actor=actor,
                reason="Envio a preparacion",
                legacy_sales_order_number=line.legacy_sales_order_number,
                legacy_line_id=line.legacy_line_id,
            )
        )
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:picking:{index}",
                movement_type=InventoryLedgerEntry.MovementType.PICK,
                direction=InventoryLedgerEntry.Direction.INCREASE,
                warehouse_ref=warehouse_ref,
                location_ref=target_location_ref,
                item_ref=line.item_ref,
                stock_state=StockState.PICKING,
                quantity=qty,
                uom=line.uom,
                document_type=source_type,
                document_ref=source_ref,
                actor=actor,
                reason="Envio a preparacion",
                legacy_sales_order_number=line.legacy_sales_order_number,
                legacy_line_id=line.legacy_line_id,
            )
        )
        line.location_ref = target_location_ref
        line.updated_by = actor
        line.updated_at = now
        lines_to_update.append(line)

    if lines_to_update:
        InventoryReservationLine.objects.bulk_update(lines_to_update, ["location_ref", "updated_by", "updated_at"])

    reservation.status = InventoryReservation.ReservationStatus.PREPARING
    reservation.updated_by = actor
    reservation.save(update_fields=["status", "updated_by", "updated_at"])
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
    if reservation.status == InventoryReservation.ReservationStatus.ALLOCATED:
        move_reserved_inventory_to_preparation(
            source_type=source_type,
            source_ref=source_ref,
            actor=actor,
            idempotency_key=f"{idempotency_key}:prepare",
        )
        reservation = InventoryReservation.objects.select_for_update().prefetch_related("lines").get(
            source_type=source_type,
            source_ref=source_ref,
        )
    if reservation.status != InventoryReservation.ReservationStatus.PREPARING:
        raise InventoryRuleError("La reserva debe estar asignada para preparar stock.")

    lines_to_update = []
    now = timezone.now()
    for index, line in enumerate(reservation.lines.all(), start=1):
        qty = line.reserved_qty - line.fulfilled_qty
        if qty <= 0:
            continue
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:picking:{index}",
                movement_type=InventoryLedgerEntry.MovementType.PICK,
                direction=InventoryLedgerEntry.Direction.DECREASE,
                warehouse_ref=line.warehouse_ref or reservation.warehouse_ref,
                location_ref=line.location_ref or location_ref_for_purpose(line.warehouse_ref or reservation.warehouse_ref, "preparation", actor=actor),
                item_ref=line.item_ref,
                stock_state=StockState.PICKING,
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
                location_ref=line.location_ref or location_ref_for_purpose(line.warehouse_ref or reservation.warehouse_ref, "preparation", actor=actor),
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


def _reservation_source_locations(
    *,
    source_type: str,
    source_ref: str,
    warehouse_ref: str,
    item_ref: str,
    uom: str,
    legacy_line_id: str = "",
) -> list[str]:
    if not source_type or not source_ref:
        return []
    qs = InventoryReservationLine.objects.filter(
        reservation__source_type=source_type,
        reservation__source_ref=source_ref,
        warehouse_ref=warehouse_ref,
        item_ref=item_ref,
        uom=uom,
    )
    if legacy_line_id:
        qs = qs.filter(legacy_line_id=legacy_line_id)
    refs = [
        row.location_ref
        for row in qs.order_by("location_ref", "created_at").only("location_ref")
        if row.location_ref
    ]
    return list(dict.fromkeys(refs))


@transaction.atomic
def move_prepared_stock_to_state(
    *,
    warehouse_ref: str,
    item_ref: str,
    quantity: Decimal,
    uom: str,
    to_state: str,
    document_type: str,
    document_ref: str,
    actor: str,
    idempotency_key: str,
    reason: str,
    source_type: str = "",
    source_ref: str = "",
    target_location_purpose: str = "transit",
    target_location_ref: str = "",
    legacy_sales_order_number: str = "",
    legacy_line_id: str = "",
    movement_type: str = InventoryLedgerEntry.MovementType.DISPATCH,
) -> list[StockAllocation]:
    wh = _warehouse_ref(warehouse_ref)
    item = _clean(item_ref)
    unit = _clean(uom) or "UN"
    source_locations = _reservation_source_locations(
        source_type=source_type,
        source_ref=source_ref,
        warehouse_ref=wh,
        item_ref=item,
        uom=unit,
        legacy_line_id=legacy_line_id,
    )
    used_reservation_locations = bool(source_locations)
    if not source_locations:
        source_locations = [location_ref_for_purpose(wh, "preparation", actor=actor)]
    target_ref = _clean(target_location_ref) or location_ref_for_purpose(wh, target_location_purpose, actor=actor)
    try:
        allocations = _allocate_balances(
            warehouse_ref=wh,
            item_ref=item,
            stock_state=StockState.PACKED,
            quantity=quantity,
            uom=unit,
            actor=actor,
            location_refs=source_locations,
        )
    except InventoryRuleError:
        if used_reservation_locations:
            raise
        allocations = _allocate_balances(
            warehouse_ref=wh,
            item_ref=item,
            stock_state=StockState.PACKED,
            quantity=quantity,
            uom=unit,
            actor=actor,
            location_refs=_dispatchable_location_refs(wh, actor=actor),
        )
    for index, allocation in enumerate(allocations, start=1):
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:packed:{index}",
                movement_type=movement_type,
                direction=InventoryLedgerEntry.Direction.DECREASE,
                warehouse_ref=wh,
                location_ref=allocation.location_ref,
                item_ref=item,
                stock_state=StockState.PACKED,
                quantity=allocation.quantity,
                uom=unit,
                document_type=document_type,
                document_ref=document_ref,
                actor=actor,
                reason=reason,
                lot_ref=allocation.lot_ref,
                legacy_sales_order_number=legacy_sales_order_number,
                legacy_line_id=legacy_line_id,
            )
        )
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:{to_state}:{index}",
                movement_type=movement_type,
                direction=InventoryLedgerEntry.Direction.INCREASE,
                warehouse_ref=wh,
                location_ref=target_ref,
                item_ref=item,
                stock_state=to_state,
                quantity=allocation.quantity,
                uom=unit,
                document_type=document_type,
                document_ref=document_ref,
                actor=actor,
                reason=reason,
                lot_ref=allocation.lot_ref,
                legacy_sales_order_number=legacy_sales_order_number,
                legacy_line_id=legacy_line_id,
            )
        )
    return allocations


@transaction.atomic
def move_transit_stock_to_state(
    *,
    source_warehouse_ref: str,
    item_ref: str,
    quantity: Decimal,
    uom: str,
    to_state: str,
    document_type: str,
    document_ref: str,
    actor: str,
    idempotency_key: str,
    reason: str,
    target_warehouse_ref: str = "",
    target_location_purpose: str = "transit",
    target_location_ref: str = "",
    legacy_sales_order_number: str = "",
    legacy_line_id: str = "",
    movement_type: str = InventoryLedgerEntry.MovementType.DISPATCH,
) -> list[StockAllocation]:
    source_wh = _warehouse_ref(source_warehouse_ref)
    target_wh = _warehouse_ref(target_warehouse_ref or source_wh)
    item = _clean(item_ref)
    unit = _clean(uom) or "UN"
    source_location_ref = location_ref_for_purpose(source_wh, "transit", actor=actor)
    target_ref = _clean(target_location_ref) or location_ref_for_purpose(target_wh, target_location_purpose, actor=actor)
    allocations = _allocate_balances(
        warehouse_ref=source_wh,
        item_ref=item,
        stock_state=StockState.IN_TRANSIT,
        quantity=quantity,
        uom=unit,
        actor=actor,
        location_refs=[source_location_ref],
    )
    for index, allocation in enumerate(allocations, start=1):
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:transit:{index}",
                movement_type=movement_type,
                direction=InventoryLedgerEntry.Direction.DECREASE,
                warehouse_ref=source_wh,
                location_ref=allocation.location_ref,
                item_ref=item,
                stock_state=StockState.IN_TRANSIT,
                quantity=allocation.quantity,
                uom=unit,
                document_type=document_type,
                document_ref=document_ref,
                actor=actor,
                reason=reason,
                lot_ref=allocation.lot_ref,
                legacy_sales_order_number=legacy_sales_order_number,
                legacy_line_id=legacy_line_id,
            )
        )
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:{to_state}:{index}",
                movement_type=movement_type,
                direction=InventoryLedgerEntry.Direction.INCREASE,
                warehouse_ref=target_wh,
                location_ref=target_ref,
                item_ref=item,
                stock_state=to_state,
                quantity=allocation.quantity,
                uom=unit,
                document_type=document_type,
                document_ref=document_ref,
                actor=actor,
                reason=reason,
                lot_ref=allocation.lot_ref,
                legacy_sales_order_number=legacy_sales_order_number,
                legacy_line_id=legacy_line_id,
            )
        )
    return allocations


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


def _sheet_cutting_plan_from_payload(payload: dict, *, require_outputs: bool = True) -> dict:
    plan = calculate_sheet_cutting_plan(
        store=_clean(payload.get("store")),
        category=_clean(payload.get("category")),
        source_item_ref=_clean(payload.get("source_item_ref")),
        source_length_cm=payload.get("source_length_cm"),
        source_quantity=payload.get("source_quantity") or 1,
        cuts=payload.get("cuts") or [],
    )
    source_item_ref = _clean((plan.get("source") or {}).get("item_ref"))
    if not source_item_ref:
        raise InventoryRuleError("El corte requiere un articulo origen concreto.")
    outputs = plan.get("outputs") or []
    if require_outputs and not outputs:
        raise InventoryRuleError("El corte requiere articulos destino.")
    missing_outputs = [str(index) for index, output in enumerate(outputs, start=1) if not _clean(output.get("item_ref"))]
    if missing_outputs:
        raise InventoryRuleError("Todos los cortes destino deben resolver un articulo de catalogo.")
    if require_outputs and not plan.get("valid"):
        raise InventoryRuleError(plan.get("message") or "El corte no es valido.")
    return plan


def _sheet_cutting_stock_validation(*, warehouse_ref: str, payload: dict, actor: str, require_outputs: bool = False) -> dict:
    warehouse = _warehouse_ref(warehouse_ref)
    if not warehouse:
        raise InventoryRuleError("warehouse_ref es obligatorio para validar el corte.")
    plan = _sheet_cutting_plan_from_payload(payload, require_outputs=require_outputs)
    source = plan["source"]
    source_item_ref = _clean(source.get("item_ref"))
    source_uom = _stock_uom(source.get("uom") or source.get("uom_code"))
    required_qty = _decimal(source.get("quantity") or 1)
    available_by_key = available_stock_quantities_for_keys(
        {(warehouse, source_item_ref, source_uom)},
        stock_state=StockState.PACKED,
        actor="fulfillment",
    )
    available_qty = available_by_key.get((warehouse, source_item_ref, source_uom), ZERO)
    has_stock = available_qty >= required_qty
    has_outputs = bool(plan.get("outputs"))
    exact_fit = _decimal(plan.get("waste_cm")) == ZERO
    plan_valid = bool(plan.get("valid")) and (not has_outputs or exact_fit)
    if not has_stock:
        message = "Stock insuficiente para el largo origen."
    elif has_outputs and bool(plan.get("valid")) and not exact_fit:
        message = "El sobrante debe ser 0 cm para ejecutar el corte."
    elif has_outputs and plan_valid:
        message = "Corte validado con stock disponible."
    elif has_outputs:
        message = plan.get("message") or "El corte no es valido."
    else:
        message = "Origen validado con stock disponible."
    return {
        "plan": plan,
        "stock": {
            "warehouse_ref": warehouse,
            "source_item_ref": source_item_ref,
            "source_uom": source_uom,
            "stock_state": StockState.PACKED,
            "required_qty": _display_decimal(required_qty),
            "available_qty": _display_decimal(available_qty),
            "has_stock": has_stock,
        },
        "valid": plan_valid and has_stock,
        "message": message,
    }


def validate_sheet_cutting_stock(*, payload: dict, actor: str) -> InventoryCommandResult:
    warehouse_ref = _clean(payload.get("warehouse_ref"))
    validation = _sheet_cutting_stock_validation(warehouse_ref=warehouse_ref, payload=payload, actor=actor, require_outputs=False)
    return InventoryCommandResult({"result": validation})


@transaction.atomic
def execute_sheet_cutting(*, payload: dict, idempotency_key: str, actor: str) -> InventoryCommandResult:
    warehouse_ref = _warehouse_ref(payload.get("warehouse_ref"))
    if not warehouse_ref:
        raise InventoryRuleError("warehouse_ref es obligatorio para ejecutar el corte.")
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="inventory.sheet_cutting.execute",
        reference_type="inventory_transformation",
        reference_id=_clean(payload.get("source_item_ref")) or "new",
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return InventoryCommandResult(idempotency.response_payload, idempotency.response_status)

    validation = _sheet_cutting_stock_validation(warehouse_ref=warehouse_ref, payload=payload, actor=actor, require_outputs=True)
    if not validation["valid"]:
        raise InventoryRuleError(validation["message"])

    plan = validation["plan"]
    source = plan["source"]
    source_item_ref = _clean(source.get("item_ref"))
    source_uom = _stock_uom(source.get("uom") or source.get("uom_code"))
    source_qty = _decimal(source.get("quantity") or 1)
    reason = _clean(payload.get("reason")) or "Corte de chapas"
    source_locations = _dispatchable_location_refs(warehouse_ref, actor=actor)
    target_location_ref = location_ref_for_purpose(warehouse_ref, "available", actor=actor)
    allocations = _allocate_balances(
        warehouse_ref=warehouse_ref,
        item_ref=source_item_ref,
        stock_state=StockState.PACKED,
        quantity=source_qty,
        uom=source_uom,
        actor=actor,
        location_refs=source_locations,
    )

    transformation = InventoryTransformation.objects.create(
        transformation_type=InventoryTransformation.TransformationType.SPLIT,
        status=InventoryTransformation.TransformationStatus.DRAFT,
        reason=reason,
        conversion_group_id="sheet_cutting",
        warehouse_ref=warehouse_ref,
        item_ref=source_item_ref,
        created_by=actor,
        updated_by=actor,
    )
    input_line = InventoryTransformationLine.objects.create(
        transformation=transformation,
        role=InventoryTransformationLine.LineRole.INPUT,
        warehouse_ref=warehouse_ref,
        item_ref=source_item_ref,
        quantity=source_qty,
        uom=source_uom,
        conversion_factor=Decimal("1"),
        created_by=actor,
        updated_by=actor,
    )

    for index, allocation in enumerate(allocations, start=1):
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:source:{index}",
                movement_type=InventoryLedgerEntry.MovementType.TRANSFORMATION_OUT,
                direction=InventoryLedgerEntry.Direction.DECREASE,
                warehouse_ref=warehouse_ref,
                location_ref=allocation.location_ref,
                item_ref=source_item_ref,
                stock_state=StockState.PACKED,
                quantity=allocation.quantity,
                uom=source_uom,
                document_type="inventory_sheet_cutting",
                document_ref=str(transformation.id),
                actor=actor,
                reason=reason,
                lot_ref=allocation.lot_ref,
            )
        )

    output_lines = []
    for index, output in enumerate(plan.get("outputs") or [], start=1):
        output_item_ref = _clean(output.get("item_ref"))
        output_uom = _stock_uom(output.get("uom") or output.get("uom_code") or source_uom)
        output_qty = _decimal(output.get("quantity"))
        output_line = InventoryTransformationLine.objects.create(
            transformation=transformation,
            role=InventoryTransformationLine.LineRole.OUTPUT,
            warehouse_ref=warehouse_ref,
            item_ref=output_item_ref,
            quantity=output_qty,
            uom=output_uom,
            parent_line_ref=str(input_line.id),
            conversion_factor=_decimal(output.get("length_cm"), "1"),
            created_by=actor,
            updated_by=actor,
        )
        output_lines.append(output_line)
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:output:{index}",
                movement_type=InventoryLedgerEntry.MovementType.TRANSFORMATION_IN,
                direction=InventoryLedgerEntry.Direction.INCREASE,
                warehouse_ref=warehouse_ref,
                location_ref=target_location_ref,
                item_ref=output_item_ref,
                stock_state=StockState.PACKED,
                quantity=output_qty,
                uom=output_uom,
                document_type="inventory_sheet_cutting",
                document_ref=str(transformation.id),
                actor=actor,
                reason=reason,
            )
        )

    from_status = transformation.status
    transformation.status = InventoryTransformation.TransformationStatus.POSTED
    transformation.posted_at = timezone.now()
    transformation.updated_by = actor
    transformation.save(update_fields=["status", "posted_at", "updated_by", "updated_at"])
    after = {
        "id": str(transformation.id),
        "status": transformation.status,
        "warehouse_ref": warehouse_ref,
        "transformation_type": transformation.transformation_type,
        "reason": transformation.reason,
        "posted_at": transformation.posted_at.isoformat() if transformation.posted_at else None,
        "source": {
            **source,
            "uom": source_uom,
            "quantity": _display_decimal(source_qty),
        },
        "outputs": [
            {
                **output,
                "uom": _stock_uom(output.get("uom") or output.get("uom_code") or source_uom),
                "quantity": _display_decimal(_decimal(output.get("quantity"))),
            }
            for output in plan.get("outputs") or []
        ],
        "used_cm": plan.get("used_cm"),
        "used_m": plan.get("used_m"),
        "waste_cm": plan.get("waste_cm"),
        "waste_m": plan.get("waste_m"),
        "stock": validation["stock"],
    }
    _status_history("inventory_transformation", str(transformation.id), from_status, transformation.status, actor, "sheet_cutting", after)
    _audit_event("inventory_transformation", str(transformation.id), "sheet_cutting_posted", actor, reason=reason, after=after)
    result = InventoryCommandResult({"result": after}, 201)
    return _finish_idempotent_command(idempotency, result)


def _command_ref(prefix: str, idempotency_key: str) -> str:
    digest = hashlib.sha1(idempotency_key.encode("utf-8")).hexdigest()[:12].upper()
    return f"{prefix}-{digest}"


def _ensure_location_active(warehouse_ref: str, location_ref: str) -> None:
    if not location_ref:
        raise InventoryRuleError("location_ref es obligatorio.")
    exists = WarehouseLocation.objects.filter(warehouse_ref=warehouse_ref, location_ref=location_ref, active=True).exists()
    if not exists:
        raise InventoryRuleError("La ubicacion informada no existe o esta inactiva.")


def _ensure_location_purpose(warehouse_ref: str, location_ref: str, *, allowed_purposes: set[str], message: str) -> None:
    if not location_ref:
        raise InventoryRuleError("location_ref es obligatorio.")
    location = WarehouseLocation.objects.filter(warehouse_ref=warehouse_ref, location_ref=location_ref, active=True).first()
    if not location:
        raise InventoryRuleError("La ubicacion informada no existe o esta inactiva.")
    if location.purpose not in allowed_purposes:
        raise InventoryRuleError(message)


def serialize_receipt(receipt: PurchaseOrderReceipt) -> dict:
    receipt = PurchaseOrderReceipt.objects.prefetch_related("lines").get(id=receipt.id)
    return {
        "id": str(receipt.id),
        "purchase_order_ref": receipt.purchase_order_ref,
        "supplier_ref": receipt.supplier_ref,
        "status": receipt.status,
        "warehouse_ref": receipt.warehouse_ref,
        "reason": receipt.reason,
        "received_at": receipt.received_at.isoformat() if receipt.received_at else None,
        "closed_at": receipt.closed_at.isoformat() if receipt.closed_at else None,
        "lines_count": receipt.lines.count(),
        "lines": [
            {
                "id": str(line.id),
                "item_ref": line.item_ref,
                "warehouse_ref": line.warehouse_ref,
                "location_ref": line.location_ref,
                "lot_ref": line.lot_ref,
                "expected_qty": _display_decimal(line.expected_qty),
                "received_qty": _display_decimal(line.received_qty),
                "difference_qty": _display_decimal(line.difference_qty),
                "uom": line.uom,
                "incident_ref": line.incident_ref,
                "legacy_line_id": line.legacy_line_id,
            }
            for line in receipt.lines.order_by("created_at")
        ],
    }


@transaction.atomic
def receive_purchase_order(*, payload: dict, idempotency_key: str, actor: str) -> InventoryCommandResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="inventory.receipt.receive",
        reference_type="purchase_order_receipt",
        reference_id=_clean(payload.get("purchase_order_ref")) or "new",
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return InventoryCommandResult(idempotency.response_payload, idempotency.response_status)

    warehouse_ref = _warehouse_ref(payload.get("warehouse_ref"))
    if not warehouse_ref:
        raise InventoryRuleError("La recepcion requiere warehouse_ref.")
    purchase_order_ref = _clean(payload.get("purchase_order_ref"))
    if not purchase_order_ref:
        raise InventoryRuleError("La recepcion requiere purchase_order_ref.")
    raw_lines = payload.get("lines") or []
    if not raw_lines:
        raise InventoryRuleError("La recepcion requiere lineas.")
    header_location_ref = _clean(payload.get("location_ref") or payload.get("target_location_ref")) or location_ref_for_purpose(
        warehouse_ref,
        "available",
        actor=actor,
    )
    _ensure_location_active(warehouse_ref, header_location_ref)

    receipt = PurchaseOrderReceipt.objects.create(
        purchase_order_ref=purchase_order_ref,
        supplier_ref=_clean(payload.get("supplier_ref")),
        status=PurchaseOrderReceipt.ReceiptStatus.RECEIVING,
        warehouse_ref=warehouse_ref,
        reason=_clean(payload.get("reason")),
        received_at=timezone.now(),
        created_by=actor,
        updated_by=actor,
    )
    has_difference = False
    has_over_receipt = False
    for index, raw_line in enumerate(raw_lines, start=1):
        item_ref = _clean(raw_line.get("item_ref"))
        if not item_ref:
            raise InventoryRuleError("Todas las lineas de recepcion requieren item_ref.")
        received_qty = _decimal(raw_line.get("received_qty") or raw_line.get("quantity"))
        if received_qty <= ZERO:
            raise InventoryRuleError("Todas las lineas de recepcion deben tener cantidad positiva.")
        expected_qty = _decimal(raw_line.get("expected_qty") or raw_line.get("ordered_qty") or received_qty)
        uom = _clean(raw_line.get("uom")) or "UN"
        line_warehouse_ref = _warehouse_ref(raw_line.get("warehouse_ref") or warehouse_ref)
        if line_warehouse_ref != warehouse_ref:
            raise InventoryRuleError("Todas las lineas de recepcion deben pertenecer al mismo almacen.")
        location_ref = _clean(raw_line.get("location_ref") or raw_line.get("target_location_ref")) or header_location_ref
        _ensure_location_active(warehouse_ref, location_ref)
        lot_ref = _clean(raw_line.get("lot_ref"))
        difference_qty = expected_qty - received_qty
        has_difference = has_difference or difference_qty != ZERO
        has_over_receipt = has_over_receipt or difference_qty < ZERO
        line = PurchaseOrderReceiptLine.objects.create(
            receipt=receipt,
            warehouse_ref=warehouse_ref,
            location_ref=location_ref,
            lot_ref=lot_ref,
            item_ref=item_ref,
            expected_qty=expected_qty,
            received_qty=received_qty,
            difference_qty=difference_qty,
            uom=uom,
            incident_ref=_clean(raw_line.get("incident_ref")),
            legacy_line_id=_clean(raw_line.get("legacy_line_id")),
            legacy_line_rec_id=_clean(raw_line.get("legacy_line_rec_id")),
            created_by=actor,
            updated_by=actor,
        )
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:line:{index}:packed",
                movement_type=InventoryLedgerEntry.MovementType.INBOUND_RECEIPT,
                direction=InventoryLedgerEntry.Direction.INCREASE,
                warehouse_ref=warehouse_ref,
                location_ref=location_ref,
                item_ref=item_ref,
                stock_state=StockState.PACKED,
                quantity=received_qty,
                uom=uom,
                document_type="purchase_order_receipt",
                document_ref=str(receipt.id),
                actor=actor,
                reason=receipt.reason or "Recepcion de orden de compra",
                lot_ref=lot_ref,
                legacy_line_id=line.legacy_line_id,
            )
        )

    from_status = receipt.status
    receipt.status = (
        PurchaseOrderReceipt.ReceiptStatus.WITH_INCIDENT
        if has_over_receipt
        else PurchaseOrderReceipt.ReceiptStatus.PARTIAL_RECEIVED
        if has_difference
        else PurchaseOrderReceipt.ReceiptStatus.RECEIVED
    )
    receipt.updated_by = actor
    receipt.save(update_fields=["status", "updated_by", "updated_at"])
    after = serialize_receipt(receipt)
    _status_history("purchase_order_receipt", str(receipt.id), from_status, receipt.status, actor, "received", after)
    _audit_event("purchase_order_receipt", str(receipt.id), "received", actor, reason=receipt.reason, after=after)
    result = InventoryCommandResult({"result": after}, 201)
    return _finish_idempotent_command(idempotency, result)


def serialize_transformation(transformation: InventoryTransformation) -> dict:
    transformation = InventoryTransformation.objects.prefetch_related("lines").get(id=transformation.id)
    return {
        "id": str(transformation.id),
        "transformation_type": transformation.transformation_type,
        "status": transformation.status,
        "warehouse_ref": transformation.warehouse_ref,
        "reason": transformation.reason,
        "conversion_group_id": transformation.conversion_group_id,
        "posted_at": transformation.posted_at.isoformat() if transformation.posted_at else None,
        "lines": [
            {
                "id": str(line.id),
                "role": line.role,
                "item_ref": line.item_ref,
                "warehouse_ref": line.warehouse_ref,
                "location_ref": line.location_ref,
                "lot_ref": line.lot_ref,
                "quantity": _display_decimal(line.quantity),
                "uom": line.uom,
                "parent_line_ref": line.parent_line_ref,
                "conversion_factor": str(line.conversion_factor),
            }
            for line in transformation.lines.order_by("created_at")
        ],
    }


@transaction.atomic
def execute_inventory_exchange(*, payload: dict, idempotency_key: str, actor: str) -> InventoryCommandResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="inventory.exchange.execute",
        reference_type="inventory_transformation",
        reference_id=_clean(payload.get("exchange_ref")) or "new",
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return InventoryCommandResult(idempotency.response_payload, idempotency.response_status)

    source = payload.get("input") or payload.get("source") or payload
    warehouse_ref = _warehouse_ref(payload.get("warehouse_ref") or source.get("warehouse_ref"))
    if not warehouse_ref:
        raise InventoryRuleError("El canje requiere warehouse_ref.")
    source_item_ref = _clean(source.get("item_ref"))
    if not source_item_ref:
        raise InventoryRuleError("El canje requiere item_ref origen.")
    source_qty = _decimal(source.get("quantity") or source.get("input_qty"))
    if source_qty <= ZERO:
        raise InventoryRuleError("La cantidad origen debe ser mayor a cero.")
    source_uom = _clean(source.get("uom")) or "UN"
    source_location_ref = _clean(source.get("location_ref") or source.get("source_location_ref")) or location_ref_for_purpose(
        warehouse_ref,
        "available",
        actor=actor,
    )
    _ensure_location_active(warehouse_ref, source_location_ref)
    source_lot_ref = _clean(source.get("lot_ref"))
    raw_outputs = payload.get("outputs") or []
    if not raw_outputs:
        raise InventoryRuleError("El canje requiere salidas.")

    normalized_outputs = []
    consumed_total = ZERO
    for index, output in enumerate(raw_outputs, start=1):
        output_item_ref = _clean(output.get("item_ref"))
        if not output_item_ref:
            raise InventoryRuleError("Todas las salidas de canje requieren item_ref.")
        output_qty = _decimal(output.get("quantity"))
        if output_qty <= ZERO:
            raise InventoryRuleError("Todas las salidas de canje deben tener cantidad positiva.")
        factor = _decimal(output.get("input_conversion_factor") or output.get("conversion_factor"), "0")
        if factor <= ZERO:
            raise InventoryRuleError("Cada salida de canje requiere input_conversion_factor positivo.")
        target_location_ref = _clean(output.get("location_ref") or output.get("target_location_ref") or payload.get("target_location_ref")) or location_ref_for_purpose(
            warehouse_ref,
            "available",
            actor=actor,
        )
        _ensure_location_active(warehouse_ref, target_location_ref)
        consumed_total += output_qty * factor
        normalized_outputs.append(
            {
                "line_number": index,
                "item_ref": output_item_ref,
                "quantity": output_qty,
                "uom": _clean(output.get("uom")) or source_uom,
                "input_conversion_factor": factor,
                "location_ref": target_location_ref,
                "lot_ref": _clean(output.get("lot_ref")),
            }
        )
    if abs(_decimal(consumed_total) - source_qty) > QTY_SCALE:
        raise InventoryRuleError("El canje no conserva cantidad segun los factores declarados.")

    reason = _clean(payload.get("reason")) or "Canje lote a saldo"
    allocations = _allocate_balances(
        warehouse_ref=warehouse_ref,
        item_ref=source_item_ref,
        stock_state=StockState.PACKED,
        quantity=source_qty,
        uom=source_uom,
        actor=actor,
        location_refs=[source_location_ref],
        lot_ref=source_lot_ref,
        normalize_blank=False,
    )
    transformation = InventoryTransformation.objects.create(
        transformation_type=InventoryTransformation.TransformationType.EXCHANGE,
        status=InventoryTransformation.TransformationStatus.DRAFT,
        reason=reason,
        conversion_group_id=_clean(payload.get("exchange_ref")) or _command_ref("EXC", idempotency_key),
        warehouse_ref=warehouse_ref,
        item_ref=source_item_ref,
        created_by=actor,
        updated_by=actor,
    )
    input_line = InventoryTransformationLine.objects.create(
        transformation=transformation,
        role=InventoryTransformationLine.LineRole.INPUT,
        warehouse_ref=warehouse_ref,
        location_ref=source_location_ref,
        lot_ref=source_lot_ref,
        item_ref=source_item_ref,
        quantity=source_qty,
        uom=source_uom,
        conversion_factor=Decimal("1"),
        created_by=actor,
        updated_by=actor,
    )
    for index, allocation in enumerate(allocations, start=1):
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:source:{index}",
                movement_type=InventoryLedgerEntry.MovementType.TRANSFORMATION_OUT,
                direction=InventoryLedgerEntry.Direction.DECREASE,
                warehouse_ref=warehouse_ref,
                location_ref=allocation.location_ref,
                item_ref=source_item_ref,
                stock_state=StockState.PACKED,
                quantity=allocation.quantity,
                uom=source_uom,
                document_type="inventory_exchange",
                document_ref=str(transformation.id),
                actor=actor,
                reason=reason,
                lot_ref=allocation.lot_ref,
            )
        )
    for output in normalized_outputs:
        InventoryTransformationLine.objects.create(
            transformation=transformation,
            role=InventoryTransformationLine.LineRole.OUTPUT,
            warehouse_ref=warehouse_ref,
            location_ref=output["location_ref"],
            lot_ref=output["lot_ref"],
            item_ref=output["item_ref"],
            quantity=output["quantity"],
            uom=output["uom"],
            parent_line_ref=str(input_line.id),
            conversion_factor=output["input_conversion_factor"],
            created_by=actor,
            updated_by=actor,
        )
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:output:{output['line_number']}",
                movement_type=InventoryLedgerEntry.MovementType.TRANSFORMATION_IN,
                direction=InventoryLedgerEntry.Direction.INCREASE,
                warehouse_ref=warehouse_ref,
                location_ref=output["location_ref"],
                item_ref=output["item_ref"],
                stock_state=StockState.PACKED,
                quantity=output["quantity"],
                uom=output["uom"],
                document_type="inventory_exchange",
                document_ref=str(transformation.id),
                actor=actor,
                reason=reason,
                lot_ref=output["lot_ref"],
            )
        )

    from_status = transformation.status
    transformation.status = InventoryTransformation.TransformationStatus.POSTED
    transformation.posted_at = timezone.now()
    transformation.updated_by = actor
    transformation.save(update_fields=["status", "posted_at", "updated_by", "updated_at"])
    after = serialize_transformation(transformation)
    _status_history("inventory_transformation", str(transformation.id), from_status, transformation.status, actor, "exchange", after)
    _audit_event("inventory_transformation", str(transformation.id), "exchange_posted", actor, reason=reason, after=after)
    result = InventoryCommandResult({"result": after}, 201)
    return _finish_idempotent_command(idempotency, result)


@transaction.atomic
def move_inventory_between_locations(*, payload: dict, idempotency_key: str, actor: str) -> InventoryCommandResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="inventory.location_move",
        reference_type="inventory_location_move",
        reference_id=_clean(payload.get("move_ref")) or "new",
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return InventoryCommandResult(idempotency.response_payload, idempotency.response_status)

    warehouse_ref = _warehouse_ref(payload.get("warehouse_ref"))
    item_ref = _clean(payload.get("item_ref"))
    source_location_ref = _clean(payload.get("source_location_ref"))
    target_location_ref = _clean(payload.get("target_location_ref"))
    quantity = _decimal(payload.get("quantity"))
    uom = _clean(payload.get("uom")) or "UN"
    lot_ref = _clean(payload.get("lot_ref"))
    reason = _clean(payload.get("reason")) or "Movimiento entre posiciones"
    if not warehouse_ref or not item_ref:
        raise InventoryRuleError("El movimiento requiere warehouse_ref e item_ref.")
    if quantity <= ZERO:
        raise InventoryRuleError("La cantidad del movimiento debe ser mayor a cero.")
    if source_location_ref == target_location_ref:
        raise InventoryRuleError("La ubicacion origen y destino deben ser distintas.")
    _ensure_location_active(warehouse_ref, source_location_ref)
    _ensure_location_active(warehouse_ref, target_location_ref)

    document_ref = _clean(payload.get("move_ref")) or _command_ref("MOV", idempotency_key)
    allocations = _allocate_balances(
        warehouse_ref=warehouse_ref,
        item_ref=item_ref,
        stock_state=StockState.PACKED,
        quantity=quantity,
        uom=uom,
        actor=actor,
        location_refs=[source_location_ref],
        lot_ref=lot_ref,
        normalize_blank=False,
    )
    entries = []
    for index, allocation in enumerate(allocations, start=1):
        source_entry = post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:source:{index}",
                movement_type=InventoryLedgerEntry.MovementType.LOCATION_TRANSFER,
                direction=InventoryLedgerEntry.Direction.DECREASE,
                warehouse_ref=warehouse_ref,
                location_ref=allocation.location_ref,
                item_ref=item_ref,
                stock_state=StockState.PACKED,
                quantity=allocation.quantity,
                uom=uom,
                document_type="inventory_location_move",
                document_ref=document_ref,
                actor=actor,
                reason=reason,
                lot_ref=allocation.lot_ref,
            )
        )
        target_entry = post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:target:{index}",
                movement_type=InventoryLedgerEntry.MovementType.LOCATION_TRANSFER,
                direction=InventoryLedgerEntry.Direction.INCREASE,
                warehouse_ref=warehouse_ref,
                location_ref=target_location_ref,
                item_ref=item_ref,
                stock_state=StockState.PACKED,
                quantity=allocation.quantity,
                uom=uom,
                document_type="inventory_location_move",
                document_ref=document_ref,
                actor=actor,
                reason=reason,
                lot_ref=allocation.lot_ref,
            )
        )
        entries.extend([source_entry, target_entry])

    result_payload = {
        "result": {
            "document_ref": document_ref,
            "warehouse_ref": warehouse_ref,
            "source_location_ref": source_location_ref,
            "target_location_ref": target_location_ref,
            "item_ref": item_ref,
            "lot_ref": lot_ref,
            "stock_state": StockState.PACKED,
            "quantity": _display_decimal(quantity),
            "uom": uom,
            "reason": reason,
            "ledger_entry_ids": [str(entry.id) for entry in entries],
        }
    }
    _audit_event("inventory_location_move", document_ref, "posted", actor, reason=reason, after=result_payload["result"])
    return _finish_idempotent_command(idempotency, InventoryCommandResult(result_payload, 201))


def serialize_ledger_entry(entry: InventoryLedgerEntry) -> dict:
    return {
        "id": str(entry.id),
        "movement_type": entry.movement_type,
        "direction": entry.direction,
        "warehouse_ref": entry.warehouse_ref,
        "location_ref": entry.location_ref,
        "lot_ref": entry.lot_ref,
        "item_ref": entry.item_ref,
        "stock_state": entry.stock_state,
        "quantity": _display_decimal(entry.quantity),
        "uom": entry.uom,
        "document_type": entry.document_type,
        "document_ref": entry.document_ref,
        "reason": entry.reason,
        "created_by": entry.created_by,
        "is_reversal": entry.is_reversal,
        "reversal_of": str(entry.reversal_of) if entry.reversal_of else "",
        "legacy_transaction_number": entry.legacy_transaction_number,
        "legacy_sales_order_number": entry.legacy_sales_order_number,
        "legacy_line_id": entry.legacy_line_id,
        "posted_at": entry.posted_at.isoformat(),
    }


@transaction.atomic
def adjust_inventory_manually(*, payload: dict, idempotency_key: str, actor: str) -> InventoryCommandResult:
    document_ref = _clean(payload.get("document_ref") or payload.get("adjustment_ref")) or _command_ref("AJU", idempotency_key)
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="inventory.manual_adjustment",
        reference_type="inventory_manual_adjustment",
        reference_id=document_ref,
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return InventoryCommandResult(idempotency.response_payload, idempotency.response_status)

    warehouse_ref = _warehouse_ref(payload.get("warehouse_ref"))
    item_ref = _clean(payload.get("item_ref"))
    quantity = _decimal(payload.get("quantity"))
    uom = _stock_uom(payload.get("uom"))
    direction = _clean(payload.get("direction")).lower()
    lot_ref = _clean(payload.get("lot_ref"))
    reason = _clean(payload.get("reason"))
    if not warehouse_ref or not item_ref:
        raise InventoryRuleError("El ajuste manual requiere warehouse_ref e item_ref.")
    if quantity <= ZERO:
        raise InventoryRuleError("La cantidad del ajuste debe ser mayor a cero.")
    if direction not in {InventoryLedgerEntry.Direction.INCREASE, InventoryLedgerEntry.Direction.DECREASE}:
        raise InventoryRuleError("La direccion debe ser increase o decrease.")
    if not reason:
        raise InventoryRuleError("El ajuste manual requiere motivo.")

    location_ref = _clean(
        payload.get("location_ref")
        or payload.get("source_location_ref")
        or payload.get("target_location_ref")
    ) or location_ref_for_purpose(warehouse_ref, "available", actor=actor)

    entries: list[InventoryLedgerEntry] = []
    if direction == InventoryLedgerEntry.Direction.INCREASE:
        _ensure_location_purpose(
            warehouse_ref,
            location_ref,
            allowed_purposes={"available"},
            message="La alta manual solo permite ubicaciones disponibles.",
        )
        entries.append(
            post_ledger_entry(
                LedgerCommand(
                    idempotency_key=f"{idempotency_key}:increase",
                    movement_type=InventoryLedgerEntry.MovementType.ADJUSTMENT,
                    direction=InventoryLedgerEntry.Direction.INCREASE,
                    warehouse_ref=warehouse_ref,
                    location_ref=location_ref,
                    item_ref=item_ref,
                    stock_state=StockState.PACKED,
                    quantity=quantity,
                    uom=uom,
                    document_type="inventory_manual_adjustment",
                    document_ref=document_ref,
                    actor=actor,
                    reason=reason,
                    lot_ref=lot_ref,
                )
            )
        )
    else:
        _ensure_location_active(warehouse_ref, location_ref)
        allocations = _allocate_balances(
            warehouse_ref=warehouse_ref,
            item_ref=item_ref,
            stock_state=StockState.PACKED,
            quantity=quantity,
            uom=uom,
            actor=actor,
            location_refs=[location_ref],
            lot_ref=lot_ref,
            normalize_blank=False,
        )
        for index, allocation in enumerate(allocations, start=1):
            entries.append(
                post_ledger_entry(
                    LedgerCommand(
                        idempotency_key=f"{idempotency_key}:decrease:{index}",
                        movement_type=InventoryLedgerEntry.MovementType.ADJUSTMENT,
                        direction=InventoryLedgerEntry.Direction.DECREASE,
                        warehouse_ref=warehouse_ref,
                        location_ref=allocation.location_ref,
                        item_ref=item_ref,
                        stock_state=StockState.PACKED,
                        quantity=allocation.quantity,
                        uom=uom,
                        document_type="inventory_manual_adjustment",
                        document_ref=document_ref,
                        actor=actor,
                        reason=reason,
                        lot_ref=allocation.lot_ref,
                    )
                )
            )

    result_payload = {
        "result": {
            "document_ref": document_ref,
            "warehouse_ref": warehouse_ref,
            "location_ref": location_ref,
            "lot_ref": lot_ref,
            "item_ref": item_ref,
            "stock_state": StockState.PACKED,
            "direction": direction,
            "quantity": _display_decimal(quantity),
            "uom": uom,
            "reason": reason,
            "ledger_entries": [serialize_ledger_entry(entry) for entry in entries],
        }
    }
    _audit_event("inventory_manual_adjustment", document_ref, "posted", actor, reason=reason, after=result_payload["result"])
    return _finish_idempotent_command(idempotency, InventoryCommandResult(result_payload, 201))


def serialize_write_off(write_off: InventoryWriteOff) -> dict:
    write_off = InventoryWriteOff.objects.prefetch_related("lines").get(id=write_off.id)
    return {
        "id": str(write_off.id),
        "write_off_number": write_off.write_off_number,
        "status": write_off.status,
        "warehouse_ref": write_off.warehouse_ref,
        "location_ref": write_off.location_ref,
        "source_location_ref": write_off.location_ref,
        "target_location_ref": write_off.target_location_ref,
        "source_stock_state": write_off.source_stock_state,
        "reason_code": write_off.reason_code,
        "reason": write_off.reason,
        "requested_by": write_off.requested_by,
        "approved_by": write_off.approved_by,
        "posted_at": write_off.posted_at.isoformat() if write_off.posted_at else None,
        "reversed_at": write_off.reversed_at.isoformat() if write_off.reversed_at else None,
        "reversed_by": write_off.reversed_by,
        "reversal_reason": write_off.reversal_reason,
        "created_at": write_off.created_at.isoformat() if write_off.created_at else None,
        "updated_at": write_off.updated_at.isoformat() if write_off.updated_at else None,
        "lines": [
            {
                "id": str(line.id),
                "line_number": line.line_number,
                "warehouse_ref": line.warehouse_ref,
                "location_ref": line.location_ref,
                "source_location_ref": line.location_ref,
                "target_location_ref": line.target_location_ref,
                "lot_ref": line.lot_ref,
                "item_ref": line.item_ref,
                "stock_state": line.stock_state,
                "quantity": str(line.quantity),
                "posted_qty": str(line.posted_qty),
                "uom": line.uom,
                "reason_code": line.reason_code,
                "reason": line.reason,
                "legacy_sales_order_number": line.legacy_sales_order_number,
                "legacy_line_id": line.legacy_line_id,
            }
            for line in write_off.lines.all().order_by("line_number")
        ],
    }


def _write_off_line_payload(payload: dict, *, header_warehouse_ref: str, header_location_ref: str, header_stock_state: str, index: int) -> dict:
    item_ref = _clean(payload.get("item_ref"))
    if not item_ref:
        raise InventoryRuleError("Todas las lineas de baja requieren item_ref.")
    quantity = _decimal(payload.get("quantity") or payload.get("qty"))
    if quantity <= ZERO:
        raise InventoryRuleError("Todas las lineas de baja deben tener cantidad positiva.")
    stock_state = _clean(payload.get("stock_state") or payload.get("source_stock_state") or header_stock_state)
    if stock_state != StockState.PACKED:
        raise InventoryRuleError("Las roturas y perdidas solo pueden salir de stock disponible para entrega.")
    return {
        "line_number": int(payload.get("line_number") or index),
        "warehouse_ref": _clean(payload.get("warehouse_ref")) or header_warehouse_ref,
        "location_ref": _clean(payload.get("source_location_ref") or payload.get("location_ref")) or header_location_ref,
        "target_location_ref": _clean(payload.get("target_location_ref")),
        "lot_ref": _clean(payload.get("lot_ref")),
        "item_ref": item_ref,
        "stock_state": stock_state,
        "quantity": quantity,
        "uom": _clean(payload.get("uom")) or "UN",
        "reason_code": _clean(payload.get("reason_code")),
        "reason": _clean(payload.get("reason")),
        "legacy_sales_order_number": _clean(payload.get("legacy_sales_order_number")),
        "legacy_line_id": _clean(payload.get("legacy_line_id")),
    }


def _target_location_for_reason(warehouse_ref: str, reason_code: str, actor: str) -> str:
    reason = _clean(reason_code)
    if reason not in {InventoryWriteOff.ReasonCode.BREAKAGE, InventoryWriteOff.ReasonCode.LOSS}:
        raise InventoryRuleError("reason_code debe ser breakage o loss.")
    purpose = "breakage" if reason == InventoryWriteOff.ReasonCode.BREAKAGE else "loss"
    warehouse = WarehouseMaster.objects.filter(warehouse_ref=warehouse_ref).first()
    if warehouse:
        configured = (
            warehouse.default_breakage_location_ref
            if reason == InventoryWriteOff.ReasonCode.BREAKAGE
            else warehouse.default_loss_location_ref
        )
        if configured:
            return configured
    generate_default_locations(warehouse_ref=warehouse_ref, actor=actor)
    return default_location_ref(warehouse_ref, purpose)


def _validate_source_location(warehouse_ref: str, location_ref: str) -> None:
    if not location_ref:
        return
    location = WarehouseLocation.objects.filter(warehouse_ref=warehouse_ref, location_ref=location_ref, active=True).first()
    if location is None:
        raise InventoryRuleError("La ubicacion origen no existe o esta inactiva.")
    if not location.is_dispatchable:
        raise InventoryRuleError("La ubicacion origen no esta disponible para entrega.")


@transaction.atomic
def create_inventory_write_off(*, payload: dict, idempotency_key: str, actor: str) -> InventoryCommandResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="inventory.write_off.create",
        reference_type="inventory_write_off",
        reference_id=_clean(payload.get("write_off_number")) or "new",
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return InventoryCommandResult(idempotency.response_payload, idempotency.response_status)

    warehouse_ref = _clean(payload.get("warehouse_ref"))
    if not warehouse_ref:
        raise InventoryRuleError("La baja requiere warehouse_ref.")
    source_stock_state = _clean(payload.get("source_stock_state") or StockState.PACKED)
    if source_stock_state != StockState.PACKED:
        raise InventoryRuleError("Las roturas y perdidas solo pueden salir de stock disponible para entrega.")
    reason_code = _clean(payload.get("reason_code"))
    target_location_ref = _target_location_for_reason(warehouse_ref, reason_code, actor)
    reason = _clean(payload.get("reason"))
    if not reason:
        raise InventoryRuleError("La baja requiere motivo.")
    raw_lines = payload.get("lines") or []
    if not raw_lines:
        raise InventoryRuleError("La baja requiere lineas.")

    write_off_number = _write_off_number(payload, idempotency_key)
    existing = InventoryWriteOff.objects.filter(write_off_number=write_off_number).first()
    if existing and replay:
        result = InventoryCommandResult({"result": serialize_write_off(existing)}, 200)
        return _finish_idempotent_command(idempotency, result)
    if existing:
        raise InventoryRuleError("Ya existe una baja con ese numero.")

    write_off = InventoryWriteOff.objects.create(
        write_off_number=write_off_number,
        status=InventoryWriteOff.WriteOffStatus.DRAFT,
        warehouse_ref=warehouse_ref,
        location_ref=_clean(payload.get("source_location_ref") or payload.get("location_ref")),
        target_location_ref=target_location_ref,
        source_stock_state=source_stock_state,
        reason_code=reason_code,
        reason=reason,
        requested_by=_clean(payload.get("requested_by")) or actor,
        payload=payload.get("payload") or {},
        created_by=actor,
        updated_by=actor,
    )
    for index, raw_line in enumerate(raw_lines, start=1):
        data = _write_off_line_payload(
            raw_line,
            header_warehouse_ref=warehouse_ref,
            header_location_ref=write_off.location_ref,
            header_stock_state=source_stock_state,
            index=index,
        )
        source_location_ref = data["location_ref"]
        _validate_source_location(data["warehouse_ref"], source_location_ref)
        data["target_location_ref"] = data["target_location_ref"] or target_location_ref
        InventoryWriteOffLine.objects.create(
            write_off=write_off,
            created_by=actor,
            updated_by=actor,
            **data,
        )

    after = serialize_write_off(write_off)
    _status_history(
        "inventory_write_off",
        str(write_off.id),
        "",
        write_off.status,
        actor,
        "created",
        after,
    )
    _audit_event("inventory_write_off", str(write_off.id), "created", actor, reason=write_off.reason, after=after)
    posted = post_inventory_write_off(
        write_off_id=str(write_off.id),
        payload={"auto_post": True},
        idempotency_key=f"{idempotency_key}:post",
        actor=actor,
    )
    result = InventoryCommandResult(posted.payload, 201)
    return _finish_idempotent_command(idempotency, result)


@transaction.atomic
def post_inventory_write_off(*, write_off_id: str, payload: dict, idempotency_key: str, actor: str) -> InventoryCommandResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="inventory.write_off.post",
        reference_type="inventory_write_off",
        reference_id=write_off_id,
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return InventoryCommandResult(idempotency.response_payload, idempotency.response_status)

    write_off = InventoryWriteOff.objects.select_for_update().prefetch_related("lines").get(id=write_off_id)
    before = serialize_write_off(write_off)
    if write_off.status == InventoryWriteOff.WriteOffStatus.CANCELLED:
        raise InventoryRuleError("La baja cancelada no puede postearse.")
    if write_off.status == InventoryWriteOff.WriteOffStatus.POSTED:
        result = InventoryCommandResult({"result": before})
        return _finish_idempotent_command(idempotency, result)

    approved_by = _clean(payload.get("approved_by")) or actor
    if payload.get("reason"):
        write_off.reason = _clean(payload.get("reason"))
    write_off.approved_by = approved_by

    lines = list(write_off.lines.select_for_update().order_by("line_number"))
    if not lines:
        raise InventoryRuleError("La baja requiere lineas.")
    for index, line in enumerate(lines, start=1):
        remaining_qty = line.quantity - line.posted_qty
        if remaining_qty <= ZERO:
            continue
        warehouse_ref = line.warehouse_ref or write_off.warehouse_ref
        location_ref = line.location_ref or write_off.location_ref
        target_location_ref = line.target_location_ref or write_off.target_location_ref
        reason = line.reason or write_off.reason
        if (line.stock_state or write_off.source_stock_state) != StockState.PACKED:
            raise InventoryRuleError("Las roturas y perdidas solo pueden salir de stock disponible para entrega.")
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:line:{index}:source",
                movement_type=InventoryLedgerEntry.MovementType.WRITE_OFF,
                direction=InventoryLedgerEntry.Direction.DECREASE,
                warehouse_ref=warehouse_ref,
                location_ref=location_ref,
                item_ref=line.item_ref,
                stock_state=line.stock_state or write_off.source_stock_state,
                quantity=remaining_qty,
                uom=line.uom,
                document_type="inventory_write_off",
                document_ref=str(write_off.id),
                actor=actor,
                reason=reason,
                lot_ref=line.lot_ref,
                legacy_sales_order_number=line.legacy_sales_order_number,
                legacy_line_id=line.legacy_line_id,
            )
        )
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:line:{index}:scrap",
                movement_type=InventoryLedgerEntry.MovementType.WRITE_OFF,
                direction=InventoryLedgerEntry.Direction.INCREASE,
                warehouse_ref=warehouse_ref,
                location_ref=target_location_ref,
                item_ref=line.item_ref,
                stock_state=StockState.SCRAPPED,
                quantity=remaining_qty,
                uom=line.uom,
                document_type="inventory_write_off",
                document_ref=str(write_off.id),
                actor=actor,
                reason=reason,
                lot_ref=line.lot_ref,
                legacy_sales_order_number=line.legacy_sales_order_number,
                legacy_line_id=line.legacy_line_id,
            )
        )
        line.posted_qty = line.quantity
        line.updated_by = actor
        line.save(update_fields=["posted_qty", "updated_by", "updated_at"])

    from_status = write_off.status
    write_off.status = InventoryWriteOff.WriteOffStatus.POSTED
    write_off.posted_at = timezone.now()
    write_off.updated_by = actor
    write_off.save(update_fields=["status", "posted_at", "approved_by", "reason", "updated_by", "updated_at"])
    after = serialize_write_off(write_off)
    _status_history(
        "inventory_write_off",
        str(write_off.id),
        from_status,
        write_off.status,
        actor,
        "posted",
        after,
    )
    _audit_event("inventory_write_off", str(write_off.id), "posted", actor, reason=write_off.reason, before=before, after=after)
    result = InventoryCommandResult({"result": after})
    return _finish_idempotent_command(idempotency, result)


@transaction.atomic
def reverse_inventory_write_off(*, write_off_id: str, payload: dict, idempotency_key: str, actor: str) -> InventoryCommandResult:
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="inventory.write_off.reverse",
        reference_type="inventory_write_off",
        reference_id=write_off_id,
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return InventoryCommandResult(idempotency.response_payload, idempotency.response_status)

    write_off = InventoryWriteOff.objects.select_for_update().prefetch_related("lines").get(id=write_off_id)
    before = serialize_write_off(write_off)
    if write_off.status == InventoryWriteOff.WriteOffStatus.REVERSED:
        raise InventoryRuleError("La baja ya fue reversada.")
    if write_off.status != InventoryWriteOff.WriteOffStatus.POSTED:
        raise InventoryRuleError("Solo se pueden reversar bajas posteadas.")
    reversal_reason = _clean(payload.get("reason") or payload.get("reversal_reason"))
    if not reversal_reason:
        raise InventoryRuleError("La reversa requiere motivo.")

    lines = list(write_off.lines.select_for_update().order_by("line_number"))
    for index, line in enumerate(lines, start=1):
        qty = line.posted_qty
        if qty <= ZERO:
            continue
        warehouse_ref = line.warehouse_ref or write_off.warehouse_ref
        source_location_ref = line.location_ref or write_off.location_ref
        target_location_ref = line.target_location_ref or write_off.target_location_ref
        scrap_entry = post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:line:{index}:scrap",
                movement_type=InventoryLedgerEntry.MovementType.REVERSAL,
                direction=InventoryLedgerEntry.Direction.DECREASE,
                warehouse_ref=warehouse_ref,
                location_ref=target_location_ref,
                item_ref=line.item_ref,
                stock_state=StockState.SCRAPPED,
                quantity=qty,
                uom=line.uom,
                document_type="inventory_write_off_reversal",
                document_ref=str(write_off.id),
                actor=actor,
                reason=reversal_reason,
                lot_ref=line.lot_ref,
                legacy_sales_order_number=line.legacy_sales_order_number,
                legacy_line_id=line.legacy_line_id,
                is_reversal=True,
            )
        )
        post_ledger_entry(
            LedgerCommand(
                idempotency_key=f"{idempotency_key}:line:{index}:source",
                movement_type=InventoryLedgerEntry.MovementType.REVERSAL,
                direction=InventoryLedgerEntry.Direction.INCREASE,
                warehouse_ref=warehouse_ref,
                location_ref=source_location_ref,
                item_ref=line.item_ref,
                stock_state=line.stock_state or write_off.source_stock_state,
                quantity=qty,
                uom=line.uom,
                document_type="inventory_write_off_reversal",
                document_ref=str(write_off.id),
                actor=actor,
                reason=reversal_reason,
                lot_ref=line.lot_ref,
                legacy_sales_order_number=line.legacy_sales_order_number,
                legacy_line_id=line.legacy_line_id,
                is_reversal=True,
                reversal_of=scrap_entry.id,
            )
        )

    from_status = write_off.status
    write_off.status = InventoryWriteOff.WriteOffStatus.REVERSED
    write_off.reversed_at = timezone.now()
    write_off.reversed_by = actor
    write_off.reversal_reason = reversal_reason
    write_off.updated_by = actor
    write_off.save(update_fields=["status", "reversed_at", "reversed_by", "reversal_reason", "updated_by", "updated_at"])
    after = serialize_write_off(write_off)
    _status_history("inventory_write_off", str(write_off.id), from_status, write_off.status, actor, "reversed", after)
    _audit_event("inventory_write_off", str(write_off.id), "reversed", actor, reason=reversal_reason, before=before, after=after)
    result = InventoryCommandResult({"result": after})
    return _finish_idempotent_command(idempotency, result)
