from __future__ import annotations

from django.core.validators import MinValueValidator
from django.db import models

from apps.common.models import LegacyReferenceModel, TimestampedModel


class StockState(models.TextChoices):
    ON_HAND = "on_hand", "Disponible fisico"
    RESERVED = "reserved", "Reservado"
    PICKING = "picking", "En preparacion"
    PACKED = "packed", "Preparado"
    IN_TRANSIT = "in_transit", "En transito"
    DELIVERED = "delivered", "Entregado"
    ADJUSTED = "adjusted", "Ajustado"
    SCRAPPED = "scrapped", "Merma"
    CONVERTED = "converted", "Convertido"


class InventoryBalance(TimestampedModel):
    warehouse_ref = models.CharField(max_length=80)
    item_ref = models.CharField(max_length=60)
    lot_ref = models.CharField(max_length=80, blank=True)
    stock_state = models.CharField(max_length=30, choices=StockState.choices)
    uom = models.CharField(max_length=20)
    quantity = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse_ref", "item_ref", "lot_ref", "stock_state", "uom"],
                name="uq_inventory_balance_bucket",
            )
        ]
        indexes = [
            models.Index(fields=["warehouse_ref", "item_ref"]),
            models.Index(fields=["stock_state", "warehouse_ref"]),
        ]

    def __str__(self) -> str:
        return f"{self.warehouse_ref}:{self.item_ref}:{self.stock_state}={self.quantity}"


class InventoryLedgerEntry(TimestampedModel, LegacyReferenceModel):
    class MovementType(models.TextChoices):
        INBOUND_RECEIPT = "inbound_receipt", "Ingreso por recepcion"
        RESERVATION_HOLD = "reservation_hold", "Reserva"
        RESERVATION_RELEASE = "reservation_release", "Liberacion de reserva"
        PICK = "pick", "Preparacion"
        DISPATCH = "dispatch", "Despacho"
        TRANSFER_OUT = "transfer_out", "Salida transferencia"
        TRANSFER_IN = "transfer_in", "Entrada transferencia"
        ADJUSTMENT = "adjustment", "Ajuste"
        TRANSFORMATION_IN = "transformation_in", "Transformacion entrada"
        TRANSFORMATION_OUT = "transformation_out", "Transformacion salida"
        REVERSAL = "reversal", "Reversa"

    class Direction(models.TextChoices):
        INCREASE = "increase", "Incrementa"
        DECREASE = "decrease", "Decrementa"

    movement_type = models.CharField(max_length=40, choices=MovementType.choices)
    direction = models.CharField(max_length=20, choices=Direction.choices)
    stock_state = models.CharField(max_length=30, choices=StockState.choices)
    quantity = models.DecimalField(max_digits=18, decimal_places=6, validators=[MinValueValidator(0)])
    uom = models.CharField(max_length=20)
    document_type = models.CharField(max_length=80)
    document_ref = models.CharField(max_length=80)
    reason = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=120, unique=True)
    posted_at = models.DateTimeField(auto_now_add=True)
    is_reversal = models.BooleanField(default=False)
    reversal_of = models.UUIDField(blank=True, null=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["warehouse_ref", "item_ref", "stock_state"]),
            models.Index(fields=["document_type", "document_ref"]),
            models.Index(fields=["legacy_sales_order_number"]),
            models.Index(fields=["legacy_line_id"]),
            models.Index(fields=["posted_at"]),
        ]


class InventoryReservation(TimestampedModel, LegacyReferenceModel):
    class ReservationStatus(models.TextChoices):
        OPEN = "open", "Abierta"
        PARTIALLY_ALLOCATED = "partially_allocated", "Parcialmente asignada"
        ALLOCATED = "allocated", "Asignada"
        RELEASED = "released", "Liberada"
        CONSUMED = "consumed", "Consumida"
        EXPIRED = "expired", "Vencida"
        CANCELLED = "cancelled", "Cancelada"

    status = models.CharField(max_length=30, choices=ReservationStatus.choices, default=ReservationStatus.OPEN)
    source_type = models.CharField(max_length=80)
    source_ref = models.CharField(max_length=80)
    requested_by = models.CharField(max_length=120)
    expires_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "warehouse_ref"]),
            models.Index(fields=["source_type", "source_ref"]),
            models.Index(fields=["legacy_sales_order_number"]),
        ]


class InventoryReservationLine(TimestampedModel, LegacyReferenceModel):
    reservation = models.ForeignKey(
        InventoryReservation,
        related_name="lines",
        on_delete=models.CASCADE,
    )
    requested_qty = models.DecimalField(max_digits=18, decimal_places=6)
    reserved_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    fulfilled_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    uom = models.CharField(max_length=20)

    class Meta:
        indexes = [
            models.Index(fields=["item_ref", "warehouse_ref"]),
            models.Index(fields=["legacy_line_id"]),
        ]


class InventoryTransformation(TimestampedModel, LegacyReferenceModel):
    class TransformationType(models.TextChoices):
        SPLIT = "split", "Fraccionamiento"
        EXCHANGE = "exchange", "Canje"
        CONVERSION = "conversion", "Conversion interna"

    class TransformationStatus(models.TextChoices):
        DRAFT = "draft", "Borrador"
        VALIDATED = "validated", "Validada"
        POSTED = "posted", "Posteada"
        REVERSED = "reversed", "Revertida"

    transformation_type = models.CharField(max_length=30, choices=TransformationType.choices)
    status = models.CharField(
        max_length=30,
        choices=TransformationStatus.choices,
        default=TransformationStatus.DRAFT,
    )
    reason = models.TextField()
    conversion_group_id = models.CharField(max_length=80, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["transformation_type", "status"]),
            models.Index(fields=["warehouse_ref", "item_ref"]),
            models.Index(fields=["conversion_group_id"]),
        ]


class InventoryTransformationLine(TimestampedModel, LegacyReferenceModel):
    class LineRole(models.TextChoices):
        INPUT = "input", "Origen"
        OUTPUT = "output", "Destino"
        WASTE = "waste", "Merma"

    transformation = models.ForeignKey(
        InventoryTransformation,
        related_name="lines",
        on_delete=models.CASCADE,
    )
    role = models.CharField(max_length=20, choices=LineRole.choices)
    quantity = models.DecimalField(max_digits=18, decimal_places=6)
    uom = models.CharField(max_length=20)
    parent_line_ref = models.CharField(max_length=80, blank=True)
    conversion_factor = models.DecimalField(max_digits=18, decimal_places=8, default=1)

    class Meta:
        indexes = [
            models.Index(fields=["role", "item_ref"]),
            models.Index(fields=["parent_line_ref"]),
        ]


class PurchaseOrderReceipt(TimestampedModel, LegacyReferenceModel):
    class ReceiptStatus(models.TextChoices):
        DRAFT = "draft", "Borrador"
        EXPECTED = "expected", "Esperada"
        RECEIVING = "receiving", "En recepcion"
        PARTIAL_RECEIVED = "partial_received", "Recibida parcial"
        RECEIVED = "received", "Recibida total"
        WITH_INCIDENT = "with_incident", "Con incidencia"
        CLOSED = "closed", "Cerrada"
        CANCELLED = "cancelled", "Cancelada"

    purchase_order_ref = models.CharField(max_length=80)
    supplier_ref = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=30, choices=ReceiptStatus.choices, default=ReceiptStatus.DRAFT)
    received_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["purchase_order_ref"]),
            models.Index(fields=["warehouse_ref", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]


class PurchaseOrderReceiptLine(TimestampedModel, LegacyReferenceModel):
    receipt = models.ForeignKey(PurchaseOrderReceipt, related_name="lines", on_delete=models.CASCADE)
    expected_qty = models.DecimalField(max_digits=18, decimal_places=6)
    received_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    difference_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    uom = models.CharField(max_length=20)
    incident_ref = models.CharField(max_length=80, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["item_ref", "warehouse_ref"]),
            models.Index(fields=["incident_ref"]),
        ]
