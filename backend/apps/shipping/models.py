from __future__ import annotations

from django.db import models

from apps.common.models import LegacyReferenceModel, TimestampedModel


class Shipment(TimestampedModel, LegacyReferenceModel):
    class ShipmentStatus(models.TextChoices):
        PENDING = "pending", "Pendiente"
        PREPARED = "prepared", "Preparado"
        DISPATCHED = "dispatched", "Despachado"
        IN_TRANSIT = "in_transit", "En transito"
        ATTEMPTED = "attempted", "Intento"
        RESCHEDULED = "rescheduled", "Reprogramado"
        DELIVERED = "delivered", "Entregado"
        RETURNED = "returned", "Devuelto"
        CLOSED = "closed", "Cerrado"
        CANCELLED = "cancelled", "Cancelado"

    shipment_number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=30, choices=ShipmentStatus.choices, default=ShipmentStatus.PENDING)
    delivery_ref = models.CharField(max_length=80)
    route_ref = models.CharField(max_length=80, blank=True)
    carrier_ref = models.CharField(max_length=80, blank=True)
    tracking_ref = models.CharField(max_length=120, blank=True)
    planned_date = models.DateField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "planned_date"]),
            models.Index(fields=["delivery_ref"]),
            models.Index(fields=["route_ref"]),
            models.Index(fields=["legacy_sales_order_number"]),
        ]


class ShipmentEvent(TimestampedModel):
    shipment = models.ForeignKey(Shipment, related_name="events", on_delete=models.CASCADE)
    event_type = models.CharField(max_length=80)
    status = models.CharField(max_length=40)
    actor = models.CharField(max_length=120, blank=True)
    reason = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["shipment", "created_at"]),
            models.Index(fields=["event_type", "created_at"]),
        ]
