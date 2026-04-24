from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.models import AuditTrail, DomainEventOutbox, IdempotencyKey, StatusHistory
from apps.fulfillment.models import (
    DeliveryDocument,
    DeliveryDocumentLine,
    DeliveryOrder,
    DeliveryOrderLine,
    DeliveryPreparationTask,
    DeliverySplit,
    FulfillmentOrder,
    FulfillmentOrderLine,
)
from apps.integrations.legacy.models import LegacyOrder, LegacyOrderInvoice, LegacyOrderLine
from apps.inventory.models import InventoryBalance, InventoryReservation, StockState
from apps.inventory.services import InventoryRuleError, pack_reserved_inventory, reserve_inventory
from apps.logistics.parquet_master_data import customer_refs_for_dni


class FulfillmentRuleError(ValueError):
    pass


class FulfillmentAuthorizationError(PermissionError):
    pass


@dataclass(frozen=True)
class IdempotentResult:
    payload: dict
    status: int = 200


def _hash_payload(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _warehouse_set(authorized_warehouses) -> set[str] | None:
    if authorized_warehouses is None:
        return None
    return {str(warehouse).strip() for warehouse in authorized_warehouses if str(warehouse).strip()}


def _ensure_warehouse_authorized(warehouse_ref: str, authorized_warehouses) -> None:
    allowed = _warehouse_set(authorized_warehouses)
    if allowed is None:
        return
    if not allowed or str(warehouse_ref or "").strip() not in allowed:
        raise FulfillmentAuthorizationError("El usuario no tiene permiso para operar entregas en este deposito.")


def _start_idempotent_command(
    *,
    key: str,
    operation_type: str,
    reference_type: str,
    reference_id: str,
    payload: dict,
) -> tuple[IdempotencyKey, bool]:
    request_hash = _hash_payload(payload)
    existing = IdempotencyKey.objects.filter(key=key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise FulfillmentRuleError("La Idempotency-Key ya fue usada con otro payload.")
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


def _order_is_effectively_invoiced(order: LegacyOrder) -> bool:
    if not order.invoice_number.strip() or order.invoice_date is None:
        return False

    invoice = (
        LegacyOrderInvoice.objects.using("litecore")
        .filter(sales_order_number=order.sales_order_number, invoice_number=order.invoice_number)
        .first()
    )
    if not invoice:
        return True

    rejected_states = {"rejected", "rechazada", "error", "failed", "cancelled", "canceled", "anulada"}
    return invoice.estado.strip().lower() not in rejected_states


def _line_remaining_qty(line: LegacyOrderLine) -> Decimal:
    if line.remain_sales_physical is not None:
        return max(Decimal("0"), line.remain_sales_physical)
    delivered = line.sales_quantity_delivered or Decimal("0")
    return max(Decimal("0"), line.ordered_sales_quantity - delivered)


def _address_snapshot(line: LegacyOrderLine | None) -> dict:
    if line is None:
        return {}

    return {
        "state": line.delivery_address_state_id,
        "city": line.delivery_address_city,
        "street": line.delivery_address_street,
        "street_number": line.delivery_address_street_number,
        "zip_code": line.delivery_address_zip_code,
        "description": line.delivery_address_description or "",
        "latitude": str(line.delivery_address_latitude or ""),
        "longitude": str(line.delivery_address_longitude or ""),
    }


def _prefetched_list(instance, related_name: str):
    if related_name in getattr(instance, "_prefetched_objects_cache", {}):
        return list(getattr(instance, related_name).all())
    return None


def _max_dispatchable_from_values(
    fulfillment_line: FulfillmentOrderLine,
    *,
    already_planned: Decimal,
    packed_qty: Decimal,
) -> Decimal:
    remaining_qty = max(Decimal("0"), fulfillment_line.pending_qty - already_planned)
    packed_remaining = max(Decimal("0"), packed_qty - already_planned)
    return min(remaining_qty, packed_remaining)


def _line_metrics(lines: list[FulfillmentOrderLine]) -> dict:
    if not lines:
        return {}

    line_ids = [line.id for line in lines]
    planned_by_line = {
        row["fulfillment_line_id"]: row["total"] or Decimal("0")
        for row in DeliveryOrderLine.objects.filter(fulfillment_line_id__in=line_ids)
        .values("fulfillment_line_id")
        .annotate(total=Sum("planned_qty"))
    }

    warehouses = {line.warehouse_ref for line in lines}
    items = {line.item_ref for line in lines}
    uoms = {line.uom for line in lines}
    packed_by_key = {
        (row["warehouse_ref"], row["item_ref"], row["uom"]): row["total"] or Decimal("0")
        for row in InventoryBalance.objects.filter(
            warehouse_ref__in=warehouses,
            item_ref__in=items,
            lot_ref="",
            stock_state=StockState.PACKED,
            uom__in=uoms,
        )
        .values("warehouse_ref", "item_ref", "uom")
        .annotate(total=Sum("quantity"))
    }

    return {
        line.id: {
            "planned_qty": planned_by_line.get(line.id, Decimal("0")),
            "packed_qty": packed_by_key.get((line.warehouse_ref, line.item_ref, line.uom), Decimal("0")),
        }
        for line in lines
    }


def _serialize_fulfillment_line(line: FulfillmentOrderLine, metrics: dict) -> dict:
    metric = metrics.get(line.id)
    if metric is None:
        planned_qty = _planned_elsewhere(line)
        packed_qty = _packed_balance_quantity(line)
    else:
        planned_qty = metric["planned_qty"]
        packed_qty = metric["packed_qty"]

    return {
        "id": str(line.id),
        "legacy_line_id": line.legacy_line_id,
        "legacy_line_rec_id": line.legacy_line_rec_id,
        "item_ref": line.item_ref,
        "warehouse_ref": line.warehouse_ref,
        "ordered_qty": str(line.ordered_qty),
        "reserved_qty": str(line.reserved_qty),
        "prepared_qty": str(line.prepared_qty),
        "delivered_qty": str(line.delivered_qty),
        "cancelled_qty": str(line.cancelled_qty),
        "pending_qty": str(line.pending_qty),
        "planned_qty": str(planned_qty),
        "stock_available": str(packed_qty),
        "max_dispatchable_qty": str(
            _max_dispatchable_from_values(
                line,
                already_planned=planned_qty,
                packed_qty=packed_qty,
            )
        ),
        "uom": line.uom,
    }


def _serialize_fulfillment(fulfillment: FulfillmentOrder, *, line_metrics: dict | None = None) -> dict:
    prefetched_lines = _prefetched_list(fulfillment, "lines")
    lines = sorted(prefetched_lines, key=lambda line: line.legacy_line_id) if prefetched_lines is not None else list(fulfillment.lines.order_by("legacy_line_id"))
    prefetched_deliveries = _prefetched_list(fulfillment, "deliveries")
    deliveries = (
        sorted(prefetched_deliveries, key=lambda delivery: delivery.created_at)
        if prefetched_deliveries is not None
        else list(fulfillment.deliveries.prefetch_related("lines", "documents").order_by("created_at"))
    )
    metrics = line_metrics or {}
    return {
        "id": str(fulfillment.id),
        "created_at": fulfillment.created_at.isoformat(),
        "updated_at": fulfillment.updated_at.isoformat(),
        "fulfillment_number": fulfillment.fulfillment_number,
        "status": fulfillment.status,
        "sales_order_number": fulfillment.legacy_sales_order_number,
        "transaction_number": fulfillment.legacy_transaction_number,
        "customer_ref": fulfillment.customer_ref,
        "delivery_mode": fulfillment.delivery_mode,
        "requested_date": fulfillment.requested_date.isoformat() if fulfillment.requested_date else None,
        "warehouse_ref": fulfillment.warehouse_ref,
        "source_hash": fulfillment.source_hash,
        "lines": [_serialize_fulfillment_line(line, metrics) for line in lines],
        "deliveries": [
            {
                "id": str(delivery.id),
                "created_at": delivery.created_at.isoformat(),
                "updated_at": delivery.updated_at.isoformat(),
                "delivery_number": delivery.delivery_number,
                "status": delivery.status,
                "delivery_mode": delivery.delivery_mode,
                "planned_date": delivery.planned_date.isoformat() if delivery.planned_date else None,
                "address_snapshot": delivery.address_snapshot,
                "documents": [
                    {
                        "id": str(document.id),
                        "document_number": document.document_number,
                        "document_type": document.document_type,
                        "status": document.status,
                        "issued_at": document.issued_at.isoformat(),
                    }
                    for document in delivery.documents.all()
                ],
                "preparation_task": _serialize_task(delivery.preparation_task) if hasattr(delivery, "preparation_task") else None,
                "lines": [
                    {
                        "id": str(delivery_line.id),
                        "fulfillment_line_id": str(delivery_line.fulfillment_line_id),
                        "legacy_line_id": delivery_line.legacy_line_id,
                        "item_ref": delivery_line.item_ref,
                        "planned_qty": str(delivery_line.planned_qty),
                        "dispatched_qty": str(delivery_line.dispatched_qty),
                        "delivered_qty": str(delivery_line.delivered_qty),
                        "uom": delivery_line.uom,
                    }
                    for delivery_line in delivery.lines.all()
                ],
            }
            for delivery in deliveries
        ],
    }


def _bootstrap_packed_balance(line: FulfillmentOrderLine, quantity: Decimal) -> None:
    balance, created = InventoryBalance.objects.get_or_create(
        warehouse_ref=line.warehouse_ref,
        item_ref=line.item_ref,
        lot_ref="",
        stock_state=StockState.PACKED,
        uom=line.uom,
        defaults={"quantity": quantity},
    )
    if created:
        return
    if balance.quantity < quantity:
        balance.quantity = quantity
        balance.version += 1
        balance.save(update_fields=["quantity", "version", "updated_at"])


@transaction.atomic
def ingest_legacy_order(*, sales_order_number: str, idempotency_key: str, actor: str) -> IdempotentResult:
    command_payload = {"sales_order_number": sales_order_number}
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="fulfillment.from_legacy_order",
        reference_type="sales_order",
        reference_id=sales_order_number,
        payload=command_payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)

    order = LegacyOrder.objects.using("litecore").get(sales_order_number=sales_order_number)
    legacy_lines = list(
        LegacyOrderLine.objects.using("litecore")
        .filter(sales_order_number=sales_order_number)
        .order_by("line_number", "retail_line_item_id")
    )
    if not legacy_lines:
        raise FulfillmentRuleError("El pedido legacy no tiene lineas operables.")
    if not _order_is_effectively_invoiced(order):
        raise FulfillmentRuleError("El pedido legacy no tiene evidencia funcional de facturacion.")

    source_payload = {
        "order": {
            "transaction_id": order.transaction_id,
            "sales_order_number": order.sales_order_number,
            "transaction_number": order.transaction_number,
            "invoice_number": order.invoice_number,
            "invoice_date": order.invoice_date,
            "order_status": order.order_status,
            "warehouse": order.warehouse,
        },
        "lines": [
            {
                "retail_line_item_id": line.retail_line_item_id,
                "sales_order_line_rec_id": line.sales_order_line_rec_id,
                "item_number": line.item_number,
                "ordered_qty": line.ordered_sales_quantity,
                "remaining_qty": _line_remaining_qty(line),
                "warehouse": line.shipping_warehouse_id or line.fulfillment_store_id or line.warehouse,
                "delivery_mode": line.delivery_mode_code,
                "requested_shipping_date": line.requested_shipping_date,
            }
            for line in legacy_lines
        ],
    }
    source_hash = _hash_payload(source_payload)
    first_line = legacy_lines[0]

    fulfillment, created = FulfillmentOrder.objects.get_or_create(
        fulfillment_number=f"FUL-{order.sales_order_number}",
        defaults={
            "legacy_sales_order_number": order.sales_order_number,
            "legacy_transaction_number": order.transaction_number,
            "source_table": "transactions_orders_transaction",
            "source_pk": order.transaction_id,
            "source_hash": source_hash,
            "legacy_rec_id": str(order.rec_id),
            "warehouse_ref": order.warehouse,
            "store_ref": order.store_id or "",
            "customer_ref": order.customer_account,
            "delivery_mode": first_line.delivery_mode_code,
            "requested_date": first_line.requested_shipping_date.date(),
            "created_by": actor,
        },
    )
    if not created and fulfillment.status == FulfillmentOrder.FulfillmentStatus.PENDING:
        fulfillment.source_hash = source_hash
        fulfillment.legacy_transaction_number = order.transaction_number
        fulfillment.customer_ref = order.customer_account
        fulfillment.delivery_mode = first_line.delivery_mode_code
        fulfillment.requested_date = first_line.requested_shipping_date.date()
        fulfillment.warehouse_ref = order.warehouse
        fulfillment.updated_by = actor
        fulfillment.save(
            update_fields=[
                "source_hash",
                "legacy_transaction_number",
                "customer_ref",
                "delivery_mode",
                "requested_date",
                "warehouse_ref",
                "updated_by",
                "updated_at",
            ]
        )

    for legacy_line in legacy_lines:
        remaining_qty = _line_remaining_qty(legacy_line)
        fulfillment_line, created_line = FulfillmentOrderLine.objects.get_or_create(
            fulfillment=fulfillment,
            source_table="transactions_orders_retailLineItem",
            source_pk=str(legacy_line.retail_line_item_id),
            defaults={
                "legacy_sales_order_number": order.sales_order_number,
                "legacy_transaction_number": order.transaction_number,
                "legacy_line_id": str(legacy_line.retail_line_item_id),
                "legacy_line_rec_id": str(legacy_line.sales_order_line_rec_id),
                "legacy_rec_id": str(legacy_line.rec_id),
                "item_ref": legacy_line.item_number,
                "warehouse_ref": legacy_line.shipping_warehouse_id or legacy_line.fulfillment_store_id or legacy_line.warehouse,
                "store_ref": legacy_line.fulfillment_store_id,
                "ordered_qty": legacy_line.ordered_sales_quantity,
                "reserved_qty": Decimal("0"),
                "prepared_qty": Decimal("0"),
                "delivered_qty": legacy_line.sales_quantity_delivered or Decimal("0"),
                "cancelled_qty": Decimal("0"),
                "uom": legacy_line.sales_unit_symbol,
                "source_hash": source_hash,
                "created_by": actor,
            },
        )
        if not created_line:
            fulfillment_line.legacy_sales_order_number = order.sales_order_number
            fulfillment_line.legacy_transaction_number = order.transaction_number
            fulfillment_line.legacy_line_id = str(legacy_line.retail_line_item_id)
            fulfillment_line.legacy_line_rec_id = str(legacy_line.sales_order_line_rec_id)
            fulfillment_line.legacy_rec_id = str(legacy_line.rec_id)
            fulfillment_line.item_ref = legacy_line.item_number
            fulfillment_line.warehouse_ref = legacy_line.shipping_warehouse_id or legacy_line.fulfillment_store_id or legacy_line.warehouse
            fulfillment_line.store_ref = legacy_line.fulfillment_store_id
            fulfillment_line.ordered_qty = legacy_line.ordered_sales_quantity
            fulfillment_line.delivered_qty = legacy_line.sales_quantity_delivered or Decimal("0")
            fulfillment_line.cancelled_qty = Decimal("0")
            fulfillment_line.uom = legacy_line.sales_unit_symbol
            fulfillment_line.source_hash = source_hash
            fulfillment_line.updated_by = actor
            fulfillment_line.save(
                update_fields=[
                    "legacy_sales_order_number",
                    "legacy_transaction_number",
                    "legacy_line_id",
                    "legacy_line_rec_id",
                    "legacy_rec_id",
                    "item_ref",
                    "warehouse_ref",
                    "store_ref",
                    "ordered_qty",
                    "delivered_qty",
                    "cancelled_qty",
                    "uom",
                    "source_hash",
                    "updated_by",
                    "updated_at",
                ]
            )
        _bootstrap_packed_balance(fulfillment_line, remaining_qty)

    if created:
        StatusHistory.objects.create(
            entity_type="fulfillment_order",
            entity_id=str(fulfillment.id),
            to_status=fulfillment.status,
            actor=actor,
            reason="Ingesta desde Litecore local",
        )
        DomainEventOutbox.objects.create(
            event_type="fulfillment.ingested",
            aggregate_type="fulfillment_order",
            aggregate_id=str(fulfillment.id),
            payload={"sales_order_number": order.sales_order_number},
        )

    result = IdempotentResult({"result": _serialize_fulfillment(fulfillment)}, 201 if created else 200)
    return _finish_idempotent_command(idempotency, result)


def _planned_elsewhere(fulfillment_line: FulfillmentOrderLine, exclude_delivery_id: str | None = None) -> Decimal:
    queryset = DeliveryOrderLine.objects.filter(fulfillment_line=fulfillment_line)
    if exclude_delivery_id:
        queryset = queryset.exclude(delivery_id=exclude_delivery_id)
    return queryset.aggregate(total=Sum("planned_qty"))["total"] or Decimal("0")


def _packed_balance_quantity(fulfillment_line: FulfillmentOrderLine) -> Decimal:
    balance = InventoryBalance.objects.filter(
        warehouse_ref=fulfillment_line.warehouse_ref,
        item_ref=fulfillment_line.item_ref,
        lot_ref="",
        stock_state=StockState.PACKED,
        uom=fulfillment_line.uom,
    ).first()
    return balance.quantity if balance else Decimal("0")


def _max_dispatchable(fulfillment_line: FulfillmentOrderLine, exclude_delivery_id: str | None = None) -> Decimal:
    already_planned = _planned_elsewhere(fulfillment_line, exclude_delivery_id)
    return _max_dispatchable_from_values(
        fulfillment_line,
        already_planned=already_planned,
        packed_qty=_packed_balance_quantity(fulfillment_line),
    )


@transaction.atomic
def split_fulfillment_delivery(
    *,
    fulfillment_id: str,
    lines: list[dict],
    delivery_mode: str,
    planned_date,
    reason: str,
    idempotency_key: str,
    actor: str,
    authorized_warehouses=None,
) -> IdempotentResult:
    command_payload = {
        "fulfillment_id": fulfillment_id,
        "lines": lines,
        "delivery_mode": delivery_mode,
        "planned_date": str(planned_date or ""),
        "reason": reason,
    }
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="fulfillment.split",
        reference_type="fulfillment_order",
        reference_id=fulfillment_id,
        payload=command_payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)

    fulfillment = FulfillmentOrder.objects.select_for_update().get(id=fulfillment_id)
    _ensure_warehouse_authorized(fulfillment.warehouse_ref, authorized_warehouses)
    next_number = fulfillment.deliveries.count() + 1
    delivery = DeliveryOrder.objects.create(
        fulfillment=fulfillment,
        delivery_number=f"ENT-{fulfillment.legacy_sales_order_number}-{next_number}",
        delivery_mode=delivery_mode or fulfillment.delivery_mode,
        planned_date=planned_date or fulfillment.requested_date,
        status=DeliveryOrder.DeliveryStatus.CREATED,
        legacy_sales_order_number=fulfillment.legacy_sales_order_number,
        legacy_transaction_number=fulfillment.legacy_transaction_number,
        warehouse_ref=fulfillment.warehouse_ref,
        store_ref=fulfillment.store_ref,
        address_snapshot={},
        created_by=actor,
    )

    for payload_line in lines:
        line_id = str(payload_line.get("fulfillment_line_id") or "")
        split_qty = Decimal(str(payload_line.get("split_qty") or "0"))
        if split_qty <= 0:
            continue
        fulfillment_line = fulfillment.lines.select_for_update().get(id=line_id)
        _ensure_warehouse_authorized(fulfillment_line.warehouse_ref or fulfillment.warehouse_ref, authorized_warehouses)
        max_qty = _max_dispatchable(fulfillment_line)
        if split_qty > max_qty:
            raise FulfillmentRuleError(
                f"La linea {fulfillment_line.item_ref} solicita {split_qty} y solo permite {max_qty}."
            )
        delivery_line = DeliveryOrderLine.objects.create(
            delivery=delivery,
            fulfillment_line=fulfillment_line,
            planned_qty=split_qty,
            uom=fulfillment_line.uom,
            legacy_sales_order_number=fulfillment_line.legacy_sales_order_number,
            legacy_transaction_number=fulfillment_line.legacy_transaction_number,
            legacy_line_id=fulfillment_line.legacy_line_id,
            legacy_line_rec_id=fulfillment_line.legacy_line_rec_id,
            item_ref=fulfillment_line.item_ref,
            warehouse_ref=fulfillment_line.warehouse_ref,
            store_ref=fulfillment_line.store_ref,
            created_by=actor,
        )
        DeliverySplit.objects.create(
            fulfillment_line=fulfillment_line,
            delivery_line=delivery_line,
            split_qty=split_qty,
            remaining_after_split=max(Decimal("0"), fulfillment_line.pending_qty - _planned_elsewhere(fulfillment_line)),
            reason=reason,
            legacy_sales_order_number=fulfillment_line.legacy_sales_order_number,
            legacy_transaction_number=fulfillment_line.legacy_transaction_number,
            legacy_line_id=fulfillment_line.legacy_line_id,
            legacy_line_rec_id=fulfillment_line.legacy_line_rec_id,
            item_ref=fulfillment_line.item_ref,
            warehouse_ref=fulfillment_line.warehouse_ref,
            created_by=actor,
        )

    if not delivery.lines.exists():
        raise FulfillmentRuleError("La entrega no tiene cantidades positivas.")

    result = IdempotentResult({"result": _serialize_delivery(delivery)}, 201)
    return _finish_idempotent_command(idempotency, result)


def _serialize_task(task: DeliveryPreparationTask) -> dict:
    return {
        "id": str(task.id),
        "delivery_id": str(task.delivery_id),
        "status": task.status,
        "assigned_employee_ref": task.assigned_to,
        "assigned_at": task.assigned_at.isoformat() if task.assigned_at else None,
        "prepared_by": task.prepared_by,
        "prepared_at": task.prepared_at.isoformat() if task.prepared_at else None,
        "notes": task.notes,
    }


def _serialize_delivery(delivery: DeliveryOrder) -> dict:
    delivery = (
        DeliveryOrder.objects.prefetch_related("lines", "documents")
        .select_related("fulfillment")
        .get(id=delivery.id)
    )
    return {
        "id": str(delivery.id),
        "delivery_number": delivery.delivery_number,
        "status": delivery.status,
        "delivery_mode": delivery.delivery_mode,
        "planned_date": delivery.planned_date.isoformat() if delivery.planned_date else None,
        "fulfillment_id": str(delivery.fulfillment_id),
        "sales_order_number": delivery.legacy_sales_order_number,
        "lines": [
            {
                "id": str(line.id),
                "fulfillment_line_id": str(line.fulfillment_line_id),
                "legacy_line_id": line.legacy_line_id,
                "item_ref": line.item_ref,
                "planned_qty": str(line.planned_qty),
                "dispatched_qty": str(line.dispatched_qty),
                "delivered_qty": str(line.delivered_qty),
                "uom": line.uom,
            }
            for line in delivery.lines.all()
        ],
        "documents": [
            {
                "id": str(document.id),
                "document_number": document.document_number,
                "document_type": document.document_type,
                "status": document.status,
                "issued_at": document.issued_at.isoformat(),
            }
            for document in delivery.documents.all()
        ],
        "preparation_task": _serialize_task(delivery.preparation_task) if hasattr(delivery, "preparation_task") else None,
    }


@transaction.atomic
def validate_delivery_stock(*, delivery_id: str, idempotency_key: str, actor: str, authorized_warehouses=None) -> IdempotentResult:
    command_payload = {"delivery_id": delivery_id}
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="delivery.confirm",
        reference_type="delivery_order",
        reference_id=delivery_id,
        payload=command_payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)

    delivery = (
        DeliveryOrder.objects.select_for_update()
        .select_related("fulfillment")
        .prefetch_related("lines__fulfillment_line")
        .get(id=delivery_id)
    )
    _ensure_warehouse_authorized(delivery.warehouse_ref, authorized_warehouses)
    if delivery.status not in [
        DeliveryOrder.DeliveryStatus.CREATED,
        DeliveryOrder.DeliveryStatus.PLANNED,
        DeliveryOrder.DeliveryStatus.CONFIRMED,
    ]:
        raise FulfillmentRuleError("La entrega solo se puede confirmar desde creada o planificada.")

    existing_reservation = InventoryReservation.objects.filter(source_type="delivery_order", source_ref=str(delivery.id)).first()
    issues = []
    for line in delivery.lines.all():
        _ensure_warehouse_authorized(line.warehouse_ref or delivery.warehouse_ref, authorized_warehouses)
        balance = InventoryBalance.objects.filter(
            warehouse_ref=line.warehouse_ref or delivery.warehouse_ref,
            item_ref=line.item_ref,
            lot_ref="",
            stock_state=StockState.PACKED,
            uom=line.uom,
        ).first()
        available_qty = balance.quantity if balance else Decimal("0")
        if existing_reservation is None and line.planned_qty > available_qty:
            issues.append(
                {
                    "line_id": str(line.id),
                    "item_ref": line.item_ref,
                    "planned_qty": str(line.planned_qty),
                    "available_qty": str(available_qty),
                }
            )
    if issues:
        raise FulfillmentRuleError(f"Stock insuficiente para confirmar la entrega: {issues}")

    if existing_reservation is None:
        try:
            reserve_inventory(
                warehouse_ref=delivery.warehouse_ref,
                source_type="delivery_order",
                source_ref=str(delivery.id),
                actor=actor,
                lines=[
                    {
                        "item_ref": line.item_ref,
                        "warehouse_ref": line.warehouse_ref or delivery.warehouse_ref,
                        "quantity": str(line.planned_qty),
                        "uom": line.uom,
                        "legacy_sales_order_number": line.legacy_sales_order_number,
                        "legacy_line_id": line.legacy_line_id,
                    }
                    for line in delivery.lines.all()
                ],
                idempotency_key=f"{idempotency_key}:inventory",
                source_stock_state=StockState.PACKED,
            )
        except InventoryRuleError as exc:
            raise FulfillmentRuleError(str(exc)) from exc
        for line in delivery.lines.all():
            fulfillment_line = line.fulfillment_line
            fulfillment_line.reserved_qty += line.planned_qty
            fulfillment_line.updated_by = actor
            fulfillment_line.save(update_fields=["reserved_qty", "updated_by", "updated_at"])

    from_status = delivery.status
    delivery.status = DeliveryOrder.DeliveryStatus.CONFIRMED
    delivery.updated_by = actor
    delivery.save(update_fields=["status", "updated_by", "updated_at"])
    fulfillment = delivery.fulfillment
    if fulfillment.status == FulfillmentOrder.FulfillmentStatus.PENDING:
        fulfillment.status = FulfillmentOrder.FulfillmentStatus.ALLOCATED
        fulfillment.updated_by = actor
        fulfillment.save(update_fields=["status", "updated_by", "updated_at"])
    StatusHistory.objects.create(
        entity_type="delivery_order",
        entity_id=str(delivery.id),
        from_status=from_status,
        to_status=delivery.status,
        actor=actor,
        reason="Confirmacion de entrega",
    )
    result = IdempotentResult({"result": _serialize_delivery(delivery)})
    return _finish_idempotent_command(idempotency, result)


@transaction.atomic
def send_delivery_to_prepare(
    *,
    delivery_id: str,
    idempotency_key: str,
    actor: str,
    assigned_employee_ref: str = "",
    notes: str = "",
    authorized_warehouses=None,
) -> IdempotentResult:
    command_payload = {
        "delivery_id": delivery_id,
        "assigned_employee_ref": assigned_employee_ref,
        "notes": notes,
    }
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="delivery.send_to_prepare",
        reference_type="delivery_order",
        reference_id=delivery_id,
        payload=command_payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)

    delivery = DeliveryOrder.objects.select_for_update().select_related("fulfillment").prefetch_related("lines").get(id=delivery_id)
    _ensure_warehouse_authorized(delivery.warehouse_ref, authorized_warehouses)
    for line in delivery.lines.all():
        _ensure_warehouse_authorized(line.warehouse_ref or delivery.warehouse_ref, authorized_warehouses)
    if delivery.status not in [DeliveryOrder.DeliveryStatus.CONFIRMED, DeliveryOrder.DeliveryStatus.PREPARING]:
        raise FulfillmentRuleError("La entrega debe estar confirmada para enviarse a preparar.")
    if not InventoryReservation.objects.filter(source_type="delivery_order", source_ref=str(delivery.id)).exists():
        raise FulfillmentRuleError("La entrega debe tener reserva de inventario antes de prepararse.")

    assigned_employee_ref = (assigned_employee_ref or actor).strip()
    task = DeliveryPreparationTask.objects.select_for_update().filter(delivery=delivery).first()
    created = False
    if task is None:
        if not assigned_employee_ref:
            raise FulfillmentRuleError("assigned_employee_ref es obligatorio para crear la tarea de preparacion.")
        task = DeliveryPreparationTask.objects.create(
            delivery=delivery,
            status=DeliveryPreparationTask.TaskStatus.ASSIGNED,
            assigned_to=assigned_employee_ref,
            assigned_at=timezone.now(),
            notes=notes,
            legacy_sales_order_number=delivery.legacy_sales_order_number,
            legacy_transaction_number=delivery.legacy_transaction_number,
            warehouse_ref=delivery.warehouse_ref,
            store_ref=delivery.store_ref,
            created_by=actor,
        )
        created = True
    elif assigned_employee_ref or notes:
        if task.status in [DeliveryPreparationTask.TaskStatus.PREPARED, DeliveryPreparationTask.TaskStatus.CANCELLED]:
            raise FulfillmentRuleError("La tarea de preparacion no puede reasignarse en su estado actual.")
        if assigned_employee_ref:
            task.assigned_to = assigned_employee_ref
            task.assigned_at = task.assigned_at or timezone.now()
            task.status = DeliveryPreparationTask.TaskStatus.ASSIGNED
        if notes:
            task.notes = notes
        task.updated_by = actor
        task.save(update_fields=["assigned_to", "assigned_at", "status", "notes", "updated_by", "updated_at"])

    from_status = delivery.status
    delivery.status = DeliveryOrder.DeliveryStatus.PREPARING
    delivery.updated_by = actor
    delivery.save(update_fields=["status", "updated_by", "updated_at"])
    fulfillment = delivery.fulfillment
    if fulfillment.status in [FulfillmentOrder.FulfillmentStatus.PENDING, FulfillmentOrder.FulfillmentStatus.ALLOCATED]:
        fulfillment.status = FulfillmentOrder.FulfillmentStatus.PREPARING
        fulfillment.updated_by = actor
        fulfillment.save(update_fields=["status", "updated_by", "updated_at"])
    StatusHistory.objects.create(
        entity_type="delivery_order",
        entity_id=str(delivery.id),
        from_status=from_status,
        to_status=delivery.status,
        actor=actor,
        reason="Envio a preparacion",
        payload={"preparation_task_id": str(task.id)},
    )
    result = IdempotentResult({"result": _serialize_delivery(delivery), "preparation_task": _serialize_task(task)}, 201 if created else 200)
    return _finish_idempotent_command(idempotency, result)


@transaction.atomic
def mark_preparation_task_prepared(
    *,
    task_id: str,
    idempotency_key: str,
    actor: str,
    notes: str = "",
    authorized_warehouses=None,
) -> IdempotentResult:
    command_payload = {"task_id": task_id, "notes": notes}
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="preparation_task.mark_prepared",
        reference_type="preparation_task",
        reference_id=task_id,
        payload=command_payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)

    task = DeliveryPreparationTask.objects.select_for_update().select_related("delivery", "delivery__fulfillment").get(id=task_id)
    delivery = DeliveryOrder.objects.select_for_update().prefetch_related("lines__fulfillment_line").get(id=task.delivery_id)
    _ensure_warehouse_authorized(delivery.warehouse_ref, authorized_warehouses)
    for line in delivery.lines.all():
        _ensure_warehouse_authorized(line.warehouse_ref or delivery.warehouse_ref, authorized_warehouses)
    if task.status == DeliveryPreparationTask.TaskStatus.PREPARED:
        result = IdempotentResult({"result": _serialize_delivery(delivery), "preparation_task": _serialize_task(task)})
        return _finish_idempotent_command(idempotency, result)
    if task.status == DeliveryPreparationTask.TaskStatus.CANCELLED:
        raise FulfillmentRuleError("La tarea de preparacion esta cancelada.")
    if delivery.status != DeliveryOrder.DeliveryStatus.PREPARING:
        raise FulfillmentRuleError("La entrega debe estar en preparacion para marcarla preparada.")
    if task.assigned_to.strip().casefold() != actor.strip().casefold():
        raise FulfillmentAuthorizationError("Solo el encargado asignado puede marcar la tarea como preparada.")

    try:
        pack_reserved_inventory(
            source_type="delivery_order",
            source_ref=str(delivery.id),
            actor=actor,
            idempotency_key=f"{idempotency_key}:inventory",
        )
    except (InventoryRuleError, InventoryReservation.DoesNotExist) as exc:
        raise FulfillmentRuleError(str(exc)) from exc

    for line in delivery.lines.all():
        fulfillment_line = line.fulfillment_line
        fulfillment_line.prepared_qty += line.planned_qty
        fulfillment_line.updated_by = actor
        fulfillment_line.save(update_fields=["prepared_qty", "updated_by", "updated_at"])

    task.status = DeliveryPreparationTask.TaskStatus.PREPARED
    task.prepared_by = actor
    task.prepared_at = timezone.now()
    if notes:
        task.notes = notes
    task.updated_by = actor
    task.save(update_fields=["status", "prepared_by", "prepared_at", "notes", "updated_by", "updated_at"])

    from_status = delivery.status
    delivery.status = DeliveryOrder.DeliveryStatus.PREPARED
    delivery.updated_by = actor
    delivery.save(update_fields=["status", "updated_by", "updated_at"])
    fulfillment = delivery.fulfillment
    fulfillment.status = FulfillmentOrder.FulfillmentStatus.READY_FOR_DISPATCH
    fulfillment.updated_by = actor
    fulfillment.save(update_fields=["status", "updated_by", "updated_at"])
    StatusHistory.objects.create(
        entity_type="delivery_order",
        entity_id=str(delivery.id),
        from_status=from_status,
        to_status=delivery.status,
        actor=actor,
        reason="Entrega preparada",
        payload={"preparation_task_id": str(task.id)},
    )
    result = IdempotentResult({"result": _serialize_delivery(delivery), "preparation_task": _serialize_task(task)})
    return _finish_idempotent_command(idempotency, result)


@transaction.atomic
def issue_remito(*, delivery_id: str, idempotency_key: str, actor: str, authorized_warehouses=None) -> IdempotentResult:
    command_payload = {"delivery_id": delivery_id}
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="delivery.issue_remito",
        reference_type="delivery_order",
        reference_id=delivery_id,
        payload=command_payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)

    delivery = DeliveryOrder.objects.select_for_update().select_related("fulfillment").prefetch_related("lines").get(id=delivery_id)
    _ensure_warehouse_authorized(delivery.warehouse_ref, authorized_warehouses)
    for line in delivery.lines.all():
        _ensure_warehouse_authorized(line.warehouse_ref or delivery.warehouse_ref, authorized_warehouses)
    if delivery.status != DeliveryOrder.DeliveryStatus.PREPARED:
        raise FulfillmentRuleError("El remito solo se puede emitir para una entrega preparada.")

    existing = delivery.documents.filter(document_type=DeliveryDocument.DocumentType.REMITO).first()
    if existing:
        result = IdempotentResult({"result": _serialize_document(existing)})
        return _finish_idempotent_command(idempotency, result)

    document = DeliveryDocument.objects.create(
        delivery=delivery,
        document_number=f"R-{delivery.delivery_number}",
        document_type=DeliveryDocument.DocumentType.REMITO,
        status=DeliveryDocument.DocumentStatus.ISSUED,
        issued_at=timezone.now(),
        customer_ref=delivery.fulfillment.customer_ref,
        address_snapshot=delivery.address_snapshot,
        payload=_serialize_delivery(delivery),
        legacy_sales_order_number=delivery.legacy_sales_order_number,
        legacy_transaction_number=delivery.legacy_transaction_number,
        warehouse_ref=delivery.warehouse_ref,
        created_by=actor,
    )
    for line in delivery.lines.filter(planned_qty__gt=0):
        DeliveryDocumentLine.objects.create(
            document=document,
            delivery_line=line,
            item_ref=line.item_ref,
            quantity=line.planned_qty,
            uom=line.uom,
            legacy_sales_order_number=line.legacy_sales_order_number,
            legacy_transaction_number=line.legacy_transaction_number,
            legacy_line_id=line.legacy_line_id,
            legacy_line_rec_id=line.legacy_line_rec_id,
            warehouse_ref=line.warehouse_ref,
            created_by=actor,
        )
    AuditTrail.objects.create(
        entity_type="delivery_document",
        entity_id=str(document.id),
        action="issued",
        actor=actor,
        after={"document_number": document.document_number, "delivery_id": str(delivery.id)},
    )
    result = IdempotentResult({"result": _serialize_document(document)}, 201)
    return _finish_idempotent_command(idempotency, result)


def _serialize_document(document: DeliveryDocument) -> dict:
    document = DeliveryDocument.objects.prefetch_related("lines").select_related("delivery").get(id=document.id)
    return {
        "id": str(document.id),
        "document_number": document.document_number,
        "document_type": document.document_type,
        "status": document.status,
        "issued_at": document.issued_at.isoformat(),
        "delivery_id": str(document.delivery_id),
        "sales_order_number": document.legacy_sales_order_number,
        "lines": [
            {
                "id": str(line.id),
                "item_ref": line.item_ref,
                "quantity": str(line.quantity),
                "uom": line.uom,
                "legacy_line_id": line.legacy_line_id,
            }
            for line in document.lines.all()
        ],
    }


FULFILLMENT_PENDING_DELIVERY_STATUSES = {
    FulfillmentOrder.FulfillmentStatus.PENDING,
    FulfillmentOrder.FulfillmentStatus.ALLOCATED,
    FulfillmentOrder.FulfillmentStatus.PREPARING,
    FulfillmentOrder.FulfillmentStatus.READY_FOR_DISPATCH,
    FulfillmentOrder.FulfillmentStatus.PARTIALLY_DELIVERED,
    FulfillmentOrder.FulfillmentStatus.RESCHEDULED,
}


def expedition_queue(
    *,
    sales_order_number: str = "",
    customer_ref: str = "",
    customer_dni: str = "",
    authorized_warehouses: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[dict]:
    sales_order_number = sales_order_number.strip()
    customer_ref = customer_ref.strip()
    customer_dni = customer_dni.strip()
    authorized_warehouse_set = {str(warehouse).strip() for warehouse in (authorized_warehouses or []) if str(warehouse).strip()}

    if not (sales_order_number or customer_ref or customer_dni):
        return []
    if not authorized_warehouse_set:
        return []

    customer_refs = {customer_ref} if customer_ref else set()
    if customer_dni:
        customer_refs.update(customer_refs_for_dni(customer_dni))
        if not customer_refs:
            return []

    filters = Q(status__in=FULFILLMENT_PENDING_DELIVERY_STATUSES)
    if sales_order_number:
        filters &= Q(legacy_sales_order_number=sales_order_number)
    if customer_refs:
        filters &= Q(customer_ref__in=customer_refs)

    fulfillments = list(
        FulfillmentOrder.objects.prefetch_related(
            "lines",
            "deliveries__lines",
            "deliveries__documents",
        )
        .filter(filters)
        .filter(warehouse_ref__in=authorized_warehouse_set)
        .distinct()
        .order_by("-created_at")[:100]
    )
    lines = [
        line
        for fulfillment in fulfillments
        for line in list(fulfillment.lines.all())
    ]
    metrics = _line_metrics(lines)
    return [
        _serialize_fulfillment(fulfillment, line_metrics=metrics)
        for fulfillment in fulfillments
        if any(line.pending_qty > 0 for line in fulfillment.lines.all())
    ]


def build_remito_pdf(document: DeliveryDocument) -> bytes:
    document = DeliveryDocument.objects.select_related("delivery", "delivery__fulfillment").prefetch_related("lines").get(id=document.id)
    lines = [
        f"Remito de entrega {document.document_number}",
        f"Pedido: {document.legacy_sales_order_number} / Transaccion: {document.legacy_transaction_number}",
        f"Cliente: {document.customer_ref}",
        f"Warehouse: {document.warehouse_ref} / Entrega: {document.delivery.delivery_number}",
        f"Emitido: {document.issued_at:%Y-%m-%d %H:%M}",
        "Lineas despachadas:",
    ]
    lines.extend(
        f"{line.item_ref} - {line.quantity.normalize()} {line.uom} - Legacy line {line.legacy_line_id}"
        for line in document.lines.all()
        if line.quantity > 0
    )

    content = "\n".join(
        f"BT {'/F2 16 Tf' if index == 0 else '/F1 9 Tf'} 50 {800 - index * 18} Td ({_pdf_escape(line)}) Tj ET"
        for index, line in enumerate(lines[:38])
    )
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
    ]
    pdf = "%PDF-1.4\n"
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n{obj}\nendobj\n"
    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n"
    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
    return pdf.encode("latin-1", errors="ignore")


def _pdf_escape(value: str) -> str:
    normalized = value.encode("ascii", "ignore").decode("ascii")
    return normalized.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
