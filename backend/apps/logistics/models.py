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
