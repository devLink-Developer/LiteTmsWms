from __future__ import annotations

from django.db import models

from apps.common.models import LegacyReferenceModel, TimestampedModel
from apps.vehicles.models import Vehicle


class RouteSheet(TimestampedModel):
    class RouteStatus(models.TextChoices):
        DRAFT = "draft", "Borrador"
        PLANNED = "planned", "Planificada"
        CAPACITY_CHECKED = "capacity_checked", "Capacidad validada"
        ASSIGNED = "assigned", "Asignada"
        LOADING = "loading", "En carga"
        IN_TRANSIT = "in_transit", "En transito"
        CLOSED = "closed", "Cerrada"
        CANCELLED = "cancelled", "Cancelada"

    route_number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=30, choices=RouteStatus.choices, default=RouteStatus.DRAFT)
    branch_ref = models.CharField(max_length=80)
    warehouse_ref = models.CharField(max_length=80)
    vehicle = models.ForeignKey(Vehicle, null=True, blank=True, related_name="routes", on_delete=models.PROTECT)
    planned_date = models.DateField()
    planned_weight_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    planned_volume_m3 = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    loaded_weight_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    loaded_volume_m3 = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    planning_version = models.PositiveIntegerField(default=1)
    generated_by = models.CharField(max_length=40, default="manual")
    capacity_override_reason = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "planned_date"]),
            models.Index(fields=["branch_ref", "warehouse_ref"]),
            models.Index(fields=["route_number"]),
        ]


class RouteStop(TimestampedModel, LegacyReferenceModel):
    class StopStatus(models.TextChoices):
        PENDING = "pending", "Pendiente"
        PLANNED = "planned", "Planificada"
        ALLOCATED = "allocated", "Asignada"
        LOADED = "loaded", "Cargada"
        EN_ROUTE = "en_route", "En ruta"
        ARRIVED = "arrived", "Arribada"
        DELIVERED = "delivered", "Entregada"
        FAILED = "failed", "Fallida"
        RESCHEDULED = "rescheduled", "Reprogramada"
        CANCELLED = "cancelled", "Cancelada"

    route = models.ForeignKey(RouteSheet, related_name="stops", on_delete=models.CASCADE)
    sequence = models.PositiveIntegerField()
    status = models.CharField(max_length=30, choices=StopStatus.choices, default=StopStatus.PENDING)
    customer_ref = models.CharField(max_length=80)
    address_snapshot = models.JSONField(default=dict, blank=True)
    latitude = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    planned_weight_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    planned_volume_m3 = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    incident_ref = models.CharField(max_length=80, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["route", "sequence"], name="uq_route_stop_sequence")]
        indexes = [
            models.Index(fields=["status", "sequence"]),
            models.Index(fields=["customer_ref"]),
            models.Index(fields=["legacy_sales_order_number"]),
        ]


class RouteStopLine(TimestampedModel, LegacyReferenceModel):
    stop = models.ForeignKey(RouteStop, related_name="lines", on_delete=models.CASCADE)
    delivery_ref = models.CharField(max_length=80)
    quantity = models.DecimalField(max_digits=18, decimal_places=6)
    uom = models.CharField(max_length=20)
    weight_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    volume_m3 = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    capacity_estimated = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["delivery_ref"]),
            models.Index(fields=["item_ref", "warehouse_ref"]),
        ]


class RouteAssignment(TimestampedModel):
    route = models.ForeignKey(RouteSheet, related_name="assignments", on_delete=models.CASCADE)
    vehicle = models.ForeignKey(Vehicle, related_name="assignments", on_delete=models.PROTECT)
    assigned_by = models.CharField(max_length=120)
    assigned_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField(blank=True)


class RouteOptimizationRun(TimestampedModel):
    route = models.ForeignKey(RouteSheet, related_name="optimization_runs", on_delete=models.CASCADE)
    algorithm = models.CharField(max_length=80, default="v1_capacity_zone_sequence")
    input_payload = models.JSONField(default=dict)
    output_payload = models.JSONField(default=dict)
    accepted = models.BooleanField(default=False)
