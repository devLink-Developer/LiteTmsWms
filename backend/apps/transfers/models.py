from __future__ import annotations

from django.db import models

from apps.common.models import LegacyReferenceModel, TimestampedModel


class TransferOrder(TimestampedModel, LegacyReferenceModel):
    class TransferStatus(models.TextChoices):
        REQUESTED = "requested", "Solicitada"
        APPROVED = "approved", "Aprobada"
        PICKING = "picking", "Picking origen"
        DISPATCHED = "dispatched", "Despachada"
        IN_TRANSIT = "in_transit", "En transito"
        PARTIAL_RECEIVED = "partial_received", "Recepcion parcial"
        RECEIVED = "received", "Recibida"
        DISCREPANT = "discrepant", "Con diferencia"
        CLOSED = "closed", "Cerrada"
        CANCELLED = "cancelled", "Cancelada"

    transfer_number = models.CharField(max_length=40, unique=True)
    origin_warehouse_ref = models.CharField(max_length=80)
    destination_warehouse_ref = models.CharField(max_length=80)
    status = models.CharField(max_length=30, choices=TransferStatus.choices, default=TransferStatus.REQUESTED)
    requested_by = models.CharField(max_length=120)
    approved_by = models.CharField(max_length=120, blank=True)
    reason = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["origin_warehouse_ref", "destination_warehouse_ref"]),
            models.Index(fields=["transfer_number"]),
        ]


class TransferOrderLine(TimestampedModel, LegacyReferenceModel):
    transfer = models.ForeignKey(TransferOrder, related_name="lines", on_delete=models.CASCADE)
    line_number = models.PositiveIntegerField()
    requested_qty = models.DecimalField(max_digits=18, decimal_places=6)
    shipped_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    received_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    difference_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    uom = models.CharField(max_length=20)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["transfer", "line_number"], name="uq_transfer_line_number")
        ]
        indexes = [
            models.Index(fields=["item_ref", "warehouse_ref"]),
            models.Index(fields=["legacy_line_id"]),
        ]


class TransferShipment(TimestampedModel):
    transfer = models.ForeignKey(TransferOrder, related_name="shipments", on_delete=models.CASCADE)
    shipment_number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=30, default="created")
    shipped_at = models.DateTimeField(null=True, blank=True)
    actor = models.CharField(max_length=120, blank=True)


class TransferReceipt(TimestampedModel):
    transfer = models.ForeignKey(TransferOrder, related_name="receipts", on_delete=models.CASCADE)
    receipt_number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=30, default="draft")
    received_at = models.DateTimeField(null=True, blank=True)
    actor = models.CharField(max_length=120, blank=True)
    has_differences = models.BooleanField(default=False)
