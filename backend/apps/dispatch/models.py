from __future__ import annotations

from django.db import models

from apps.common.models import LegacyReferenceModel, TimestampedModel


class StoreDispatch(TimestampedModel, LegacyReferenceModel):
    class DispatchStatus(models.TextChoices):
        REQUESTED = "requested", "Solicitado"
        AUTHORIZED = "authorized", "Autorizado"
        PREPARED = "prepared", "Preparado"
        COUNTER_READY = "counter_ready", "En mostrador"
        PARTIAL_PICKUP = "partial_pickup", "Retiro parcial"
        PICKED_UP = "picked_up", "Retirado"
        WITH_INCIDENT = "with_incident", "Con incidencia"
        CLOSED = "closed", "Cerrado"
        CANCELLED = "cancelled", "Cancelado"

    dispatch_number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=30, choices=DispatchStatus.choices, default=DispatchStatus.REQUESTED)
    customer_ref = models.CharField(max_length=80)
    pickup_by_third_party = models.BooleanField(default=False)
    third_party_snapshot = models.JSONField(default=dict, blank=True)
    validation_payload = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "warehouse_ref"]),
            models.Index(fields=["customer_ref"]),
            models.Index(fields=["legacy_sales_order_number"]),
        ]


class StoreDispatchLine(TimestampedModel, LegacyReferenceModel):
    dispatch = models.ForeignKey(StoreDispatch, related_name="lines", on_delete=models.CASCADE)
    planned_qty = models.DecimalField(max_digits=18, decimal_places=6)
    picked_up_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    uom = models.CharField(max_length=20)

    class Meta:
        indexes = [
            models.Index(fields=["item_ref", "warehouse_ref"]),
            models.Index(fields=["legacy_line_id"]),
        ]
