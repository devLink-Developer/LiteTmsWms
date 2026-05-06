from __future__ import annotations

from django.db import models

from apps.common.models import LegacyReferenceModel, TimestampedModel


class LogisticsIncident(TimestampedModel, LegacyReferenceModel):
    class IncidentSeverity(models.TextChoices):
        LOW = "low", "Baja"
        MEDIUM = "medium", "Media"
        HIGH = "high", "Alta"
        BLOCKER = "blocker", "Bloqueante"

    class IncidentStatus(models.TextChoices):
        OPEN = "open", "Abierta"
        IN_REVIEW = "in_review", "En revision"
        RESOLVED = "resolved", "Resuelta"
        CANCELLED = "cancelled", "Cancelada"

    incident_number = models.CharField(max_length=40, unique=True)
    domain = models.CharField(max_length=40)
    entity_type = models.CharField(max_length=80)
    entity_id = models.CharField(max_length=80)
    severity = models.CharField(max_length=20, choices=IncidentSeverity.choices, default=IncidentSeverity.MEDIUM)
    status = models.CharField(max_length=30, choices=IncidentStatus.choices, default=IncidentStatus.OPEN)
    title = models.CharField(max_length=160)
    description = models.TextField()
    resolution = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["domain", "status"]),
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["severity", "created_at"]),
        ]


class WarehouseMaster(TimestampedModel):
    warehouse_ref = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=160)
    warehouse_type = models.CharField(max_length=40, blank=True)
    branch_ref = models.CharField(max_length=80, blank=True)
    store_ref = models.CharField(max_length=80, blank=True)
    store_name = models.CharField(max_length=160, blank=True)
    is_pickup_allowed = models.BooleanField(default=False)
    is_shipping_allowed = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    default_available_location_ref = models.CharField(max_length=120, blank=True)
    default_reserved_location_ref = models.CharField(max_length=120, blank=True)
    default_preparation_location_ref = models.CharField(max_length=120, blank=True)
    default_transit_location_ref = models.CharField(max_length=120, blank=True)
    default_breakage_location_ref = models.CharField(max_length=120, blank=True)
    default_loss_location_ref = models.CharField(max_length=120, blank=True)
    source_system = models.CharField(max_length=40, default="tmswms")
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["active", "warehouse_ref"]),
            models.Index(fields=["store_ref", "active"]),
            models.Index(fields=["branch_ref", "active"]),
        ]

    def __str__(self) -> str:
        return self.warehouse_ref


class WarehouseLocation(TimestampedModel):
    warehouse_ref = models.CharField(max_length=80)
    location_ref = models.CharField(max_length=120)
    name = models.CharField(max_length=160)
    location_type = models.CharField(max_length=40)
    purpose = models.CharField(max_length=40)
    zone_ref = models.CharField(max_length=40, blank=True)
    aisle = models.CharField(max_length=20, blank=True)
    floor = models.CharField(max_length=20, blank=True)
    level = models.CharField(max_length=20, blank=True)
    position = models.CharField(max_length=20, blank=True)
    is_dispatchable = models.BooleanField(default=False)
    is_reservable = models.BooleanField(default=False)
    is_pickable = models.BooleanField(default=False)
    allows_scrap = models.BooleanField(default=False)
    system_location = models.BooleanField(default=False)
    generated = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["warehouse_ref", "location_ref"], name="uq_warehouse_location_ref"),
        ]
        indexes = [
            models.Index(fields=["warehouse_ref", "active"]),
            models.Index(fields=["warehouse_ref", "purpose"]),
            models.Index(fields=["location_ref"]),
        ]

    def __str__(self) -> str:
        return f"{self.warehouse_ref}:{self.location_ref}"


class MaterialMasterSnapshot(TimestampedModel):
    item_ref = models.CharField(max_length=60)
    store_ref = models.CharField(max_length=80, blank=True)
    sap_code = models.CharField(max_length=80, blank=True)
    sap_item_id = models.CharField(max_length=80, blank=True)
    name = models.CharField(max_length=240, blank=True)
    long_name = models.CharField(max_length=320, blank=True)
    category = models.CharField(max_length=160, blank=True)
    coverage_group = models.CharField(max_length=80, blank=True)
    uom = models.CharField(max_length=20, blank=True)
    uom_code = models.CharField(max_length=20, blank=True)
    raw_weight = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    weight_uom = models.CharField(max_length=20, blank=True)
    weight_kg = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    raw_volume = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    volume_uom = models.CharField(max_length=20, blank=True)
    volume_m3 = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    multiple = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    freight_product = models.BooleanField(default=False)
    service_product = models.BooleanField(default=False)
    source_file = models.CharField(max_length=260, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["store_ref", "item_ref"], name="uq_material_snapshot_store_item"),
        ]
        indexes = [
            models.Index(fields=["item_ref"]),
            models.Index(fields=["store_ref", "item_ref"]),
            models.Index(fields=["category"]),
        ]
