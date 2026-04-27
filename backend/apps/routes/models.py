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
        SETTLEMENT_PENDING = "settlement_pending", "Rendicion pendiente"
        CLOSED = "closed", "Cerrada"
        CLOSED_WITH_INCIDENT = "closed_with_incident", "Cerrada con incidencia"
        CANCELLED = "cancelled", "Cancelada"

    route_number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=30, choices=RouteStatus.choices, default=RouteStatus.DRAFT)
    branch_ref = models.CharField(max_length=80)
    warehouse_ref = models.CharField(max_length=80)
    vehicle = models.ForeignKey(Vehicle, null=True, blank=True, related_name="routes", on_delete=models.PROTECT)
    driver_ref = models.CharField(max_length=120, blank=True)
    planned_date = models.DateField()
    planned_weight_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    planned_volume_m3 = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    loaded_weight_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    loaded_volume_m3 = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    total_distance_km = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    total_time_minutes = models.PositiveIntegerField(default=0)
    routing_provider = models.CharField(max_length=40, default="manual")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.CharField(max_length=120, blank=True)
    route_geometry = models.JSONField(default=dict, blank=True)
    preview_payload = models.JSONField(default=dict, blank=True)
    planning_version = models.PositiveIntegerField(default=1)
    generated_by = models.CharField(max_length=40, default="manual")
    capacity_override_reason = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "planned_date"]),
            models.Index(fields=["warehouse_ref", "planned_date", "status"], name="routesheet_wh_dt_st_idx"),
            models.Index(fields=["driver_ref", "planned_date", "status"], name="routesheet_driver_dt_st_idx"),
            models.Index(fields=["branch_ref", "warehouse_ref"]),
            models.Index(fields=["route_number"]),
        ]


class RouteStop(TimestampedModel, LegacyReferenceModel):
    class StopType(models.TextChoices):
        DELIVERY = "delivery", "Entrega cliente"
        TRANSFER = "transfer", "Transferencia interna"
        DEPOT = "depot", "Deposito"

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
    stop_type = models.CharField(max_length=30, choices=StopType.choices, default=StopType.DELIVERY)
    source_type = models.CharField(max_length=80, default="delivery_order")
    source_ref = models.CharField(max_length=80, blank=True, default="")
    customer_ref = models.CharField(max_length=80, blank=True)
    address_snapshot = models.JSONField(default=dict, blank=True)
    latitude = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    service_time_minutes = models.PositiveIntegerField(default=10)
    planned_arrival_at = models.DateTimeField(null=True, blank=True)
    time_window_start = models.DateTimeField(null=True, blank=True)
    time_window_end = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    outcome_status = models.CharField(max_length=40, blank=True)
    outcome_reason = models.CharField(max_length=80, blank=True)
    outcome_payload = models.JSONField(default=dict, blank=True)
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
    delivery_ref = models.CharField(max_length=80, blank=True)
    source_line_ref = models.CharField(max_length=80, blank=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=6)
    delivered_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    returned_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    difference_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    uom = models.CharField(max_length=20)
    weight_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    volume_m3 = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    capacity_estimated = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["delivery_ref"]),
            models.Index(fields=["item_ref", "warehouse_ref"]),
        ]


class RouteRendition(TimestampedModel):
    class RenditionStatus(models.TextChoices):
        DRAFT = "draft", "Borrador"
        POSTED = "posted", "Posteada"
        VOIDED = "voided", "Anulada"

    route = models.ForeignKey(RouteSheet, related_name="renditions", on_delete=models.PROTECT)
    status = models.CharField(max_length=30, choices=RenditionStatus.choices, default=RenditionStatus.DRAFT)
    closed_by = models.CharField(max_length=120, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    has_incidents = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["route", "status"]),
            models.Index(fields=["closed_at"]),
        ]


class RouteRenditionLine(TimestampedModel):
    rendition = models.ForeignKey(RouteRendition, related_name="lines", on_delete=models.CASCADE)
    stop = models.ForeignKey(RouteStop, related_name="rendition_lines", on_delete=models.PROTECT)
    status = models.CharField(max_length=40)
    reason = models.CharField(max_length=80, blank=True)
    delivered_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    returned_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    difference_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    observations = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["rendition", "status"]),
            models.Index(fields=["stop"]),
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
