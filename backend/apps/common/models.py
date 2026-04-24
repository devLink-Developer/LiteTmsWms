from __future__ import annotations

import uuid

from django.db import models


class TimestampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.CharField(max_length=120, blank=True)
    updated_by = models.CharField(max_length=120, blank=True)

    class Meta:
        abstract = True


class LegacyReferenceModel(models.Model):
    source_system = models.CharField(max_length=40, default="litecore")
    source_table = models.CharField(max_length=120, blank=True)
    source_pk = models.CharField(max_length=120, blank=True)
    source_version = models.CharField(max_length=120, blank=True)
    source_hash = models.CharField(max_length=128, blank=True)
    legacy_transaction_number = models.CharField(max_length=60, blank=True)
    legacy_sales_order_number = models.CharField(max_length=60, blank=True)
    legacy_line_id = models.CharField(max_length=60, blank=True)
    legacy_line_rec_id = models.CharField(max_length=60, blank=True)
    legacy_rec_id = models.CharField(max_length=60, blank=True)
    item_ref = models.CharField(max_length=60, blank=True)
    warehouse_ref = models.CharField(max_length=80, blank=True)
    store_ref = models.CharField(max_length=80, blank=True)

    class Meta:
        abstract = True


class StatusTextChoices(models.TextChoices):
    DRAFT = "draft", "Borrador"
    OPEN = "open", "Abierto"
    CANCELLED = "cancelled", "Cancelado"
    CLOSED = "closed", "Cerrado"
