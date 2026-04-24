from __future__ import annotations

from django.db import models

from apps.common.models import TimestampedModel


class AuditTrail(TimestampedModel):
    entity_type = models.CharField(max_length=80)
    entity_id = models.CharField(max_length=80)
    action = models.CharField(max_length=80)
    actor = models.CharField(max_length=120)
    reason = models.TextField(blank=True)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    source_references = models.JSONField(default=dict, blank=True)
    correlation_id = models.CharField(max_length=80, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["correlation_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.entity_type}:{self.entity_id}:{self.action}"


class StatusHistory(TimestampedModel):
    entity_type = models.CharField(max_length=80)
    entity_id = models.CharField(max_length=80)
    from_status = models.CharField(max_length=40, blank=True)
    to_status = models.CharField(max_length=40)
    actor = models.CharField(max_length=120)
    reason = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    correlation_id = models.CharField(max_length=80, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["entity_type", "entity_id", "created_at"]),
            models.Index(fields=["to_status", "created_at"]),
        ]


class IdempotencyKey(TimestampedModel):
    class ProcessingStatus(models.TextChoices):
        STARTED = "started", "Started"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    key = models.CharField(max_length=120, unique=True)
    operation_type = models.CharField(max_length=80)
    reference_type = models.CharField(max_length=80, blank=True)
    reference_id = models.CharField(max_length=80, blank=True)
    request_hash = models.CharField(max_length=128)
    response_payload = models.JSONField(default=dict, blank=True)
    response_status = models.PositiveSmallIntegerField(default=200)
    status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.STARTED,
    )
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["operation_type", "reference_type", "reference_id"]),
            models.Index(fields=["status", "created_at"]),
        ]


class DomainEventOutbox(TimestampedModel):
    class EventStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PUBLISHED = "published", "Published"
        FAILED = "failed", "Failed"

    event_type = models.CharField(max_length=120)
    aggregate_type = models.CharField(max_length=80)
    aggregate_id = models.CharField(max_length=80)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=EventStatus.choices, default=EventStatus.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["aggregate_type", "aggregate_id"]),
            models.Index(fields=["event_type", "created_at"]),
        ]
