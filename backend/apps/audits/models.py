from __future__ import annotations

from django.db import models

from apps.common.models import LegacyReferenceModel, TimestampedModel


class WarehouseAudit(TimestampedModel):
    class AuditStatus(models.TextChoices):
        DRAFT = "draft", "Borrador"
        COUNTING = "counting", "En conteo"
        COUNTED = "counted", "Contada"
        DISCREPANCY_REVIEW = "discrepancy_review", "Revision de diferencias"
        ADJUSTMENT_PENDING_APPROVAL = "adjustment_pending_approval", "Ajuste pendiente"
        APPROVED = "approved", "Aprobada"
        POSTED = "posted", "Posteada"
        CLOSED = "closed", "Cerrada"
        CANCELLED = "cancelled", "Cancelada"

    audit_number = models.CharField(max_length=40, unique=True)
    warehouse_ref = models.CharField(max_length=80)
    status = models.CharField(max_length=40, choices=AuditStatus.choices, default=AuditStatus.DRAFT)
    blind_count = models.BooleanField(default=False)
    planned_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.CharField(max_length=120, blank=True)
    reason = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["warehouse_ref", "status"]),
            models.Index(fields=["audit_number"]),
        ]


class WarehouseAuditLine(TimestampedModel, LegacyReferenceModel):
    audit = models.ForeignKey(WarehouseAudit, related_name="lines", on_delete=models.CASCADE)
    expected_qty = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    counted_qty = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    difference_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    uom = models.CharField(max_length=20)
    requires_approval = models.BooleanField(default=False)
    adjustment_ref = models.CharField(max_length=80, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["item_ref", "warehouse_ref"]),
            models.Index(fields=["requires_approval"]),
        ]
