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
