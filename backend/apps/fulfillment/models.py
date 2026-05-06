from __future__ import annotations

from django.db import models

from apps.common.models import LegacyReferenceModel, TimestampedModel


class FulfillmentOrder(TimestampedModel, LegacyReferenceModel):
    class FulfillmentStatus(models.TextChoices):
        PENDING = "pending", "Pendiente"
        ALLOCATED = "allocated", "Reservada"
        PREPARING = "preparing", "En preparacion"
        READY_FOR_DISPATCH = "ready_for_dispatch", "Lista despacho"
        PARTIALLY_DELIVERED = "partially_delivered", "Entregada parcial"
        DELIVERED = "delivered", "Entregada"
        RESCHEDULED = "rescheduled", "Reprogramada"
        CLOSED = "closed", "Cerrada"
        CANCELLED = "cancelled", "Cancelada"

    fulfillment_number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=30, choices=FulfillmentStatus.choices, default=FulfillmentStatus.PENDING)
    customer_ref = models.CharField(max_length=80)
    delivery_mode = models.CharField(max_length=60)
    requested_date = models.DateField(null=True, blank=True)
    address_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "requested_date"]),
            models.Index(fields=["warehouse_ref", "status", "requested_date"], name="ful_order_wh_st_req_idx"),
            models.Index(fields=["delivery_mode", "status", "requested_date"], name="ful_order_mode_st_req_idx"),
            models.Index(fields=["legacy_sales_order_number"]),
            models.Index(fields=["customer_ref"]),
        ]


class FulfillmentOrderLine(TimestampedModel, LegacyReferenceModel):
    fulfillment = models.ForeignKey(FulfillmentOrder, related_name="lines", on_delete=models.CASCADE)
    ordered_qty = models.DecimalField(max_digits=18, decimal_places=6)
    reserved_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    prepared_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    delivered_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    cancelled_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    uom = models.CharField(max_length=20)

    @property
    def pending_qty(self):
        return self.ordered_qty - self.delivered_qty - self.cancelled_qty

    class Meta:
        indexes = [
            models.Index(fields=["legacy_line_id"]),
            models.Index(fields=["item_ref", "warehouse_ref"]),
        ]


class FulfillmentOrderImpact(TimestampedModel, LegacyReferenceModel):
    class ImpactType(models.TextChoices):
        ANNULMENT = "annulment", "Anulacion"
        RETURN = "return", "Devolucion"

    class ImpactStatus(models.TextChoices):
        PENDING = "pending", "Pendiente"
        APPLIED = "applied", "Aplicado"

    fulfillment = models.ForeignKey(
        FulfillmentOrder,
        related_name="impacts",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    impact_type = models.CharField(max_length=20, choices=ImpactType.choices)
    status = models.CharField(max_length=20, choices=ImpactStatus.choices, default=ImpactStatus.PENDING)
    impact_sales_order_number = models.CharField(max_length=60, blank=True)
    impact_transaction_number = models.CharField(max_length=60, blank=True)
    impact_date = models.DateTimeField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["impact_type", "status"], name="fulfillmen_impact_f2a1c7_idx"),
            models.Index(fields=["legacy_sales_order_number", "impact_type"], name="fulfillmen_legacy__fb508f_idx"),
            models.Index(fields=["impact_sales_order_number"], name="fulfillmen_impact_7e826d_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["source_table", "source_pk"], name="ful_order_impact_source_uniq"),
        ]


class FulfillmentOrderImpactLine(TimestampedModel, LegacyReferenceModel):
    impact = models.ForeignKey(FulfillmentOrderImpact, related_name="lines", on_delete=models.CASCADE)
    fulfillment_line = models.ForeignKey(
        FulfillmentOrderLine,
        related_name="impact_lines",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    quantity = models.DecimalField(max_digits=18, decimal_places=6)
    applied_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    uom = models.CharField(max_length=20)

    class Meta:
        indexes = [
            models.Index(fields=["legacy_line_id"], name="fulfillmen_legacy__e44782_idx"),
            models.Index(fields=["item_ref", "warehouse_ref"], name="fulfillmen_item_re_b21e0d_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["impact", "source_pk"], name="ful_order_impact_line_source_uniq"),
        ]


class LegacyOrderSyncCursor(TimestampedModel):
    name = models.CharField(max_length=120, unique=True)
    last_modified_datetime = models.DateTimeField(null=True, blank=True)
    last_source_pk = models.CharField(max_length=120, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["name"], name="fulfillmen_name_6aa941_idx"),
            models.Index(fields=["last_modified_datetime", "last_source_pk"], name="fulfillmen_last_mo_82c92d_idx"),
        ]


class DeliveryOrder(TimestampedModel, LegacyReferenceModel):
    class DeliveryStatus(models.TextChoices):
        CREATED = "created", "Creada"
        CONFIRMED = "confirmed", "Confirmada"
        PLANNED = "planned", "Planificada"
        ASSIGNED = "assigned", "Asignada"
        PREPARING = "preparing", "En preparacion"
        PREPARED = "prepared", "Preparada"
        LOADED = "loaded", "Cargada"
        IN_ROUTE = "in_route", "En ruta"
        ATTEMPTED = "attempted", "Intentada"
        DELIVERED_PARTIAL = "delivered_partial", "Entregada parcial"
        DELIVERED_COMPLETE = "delivered_complete", "Entregada total"
        RETURNED = "returned", "Devuelta"
        CANCELLED = "cancelled", "Cancelada"

    delivery_number = models.CharField(max_length=40, unique=True)
    fulfillment = models.ForeignKey(FulfillmentOrder, related_name="deliveries", on_delete=models.CASCADE)
    status = models.CharField(max_length=30, choices=DeliveryStatus.choices, default=DeliveryStatus.CREATED)
    delivery_mode = models.CharField(max_length=60)
    planned_date = models.DateField(null=True, blank=True)
    address_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "planned_date"]),
            models.Index(fields=["warehouse_ref", "status", "planned_date"], name="ful_deliv_wh_st_dt_idx"),
            models.Index(fields=["delivery_mode", "status", "planned_date"], name="ful_deliv_mode_st_dt_idx"),
            models.Index(fields=["delivery_mode"]),
        ]


class DeliveryOrderLine(TimestampedModel, LegacyReferenceModel):
    delivery = models.ForeignKey(DeliveryOrder, related_name="lines", on_delete=models.CASCADE)
    fulfillment_line = models.ForeignKey(FulfillmentOrderLine, related_name="delivery_lines", on_delete=models.PROTECT)
    planned_qty = models.DecimalField(max_digits=18, decimal_places=6)
    delivery_unit_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    delivery_uom = models.CharField(max_length=20, blank=True)
    conversion_factor = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    dispatched_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    delivered_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    uom = models.CharField(max_length=20)
    item_snapshot = models.JSONField(default=dict, blank=True)
    planned_weight_kg = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    planned_volume_m3 = models.DecimalField(max_digits=18, decimal_places=6, default=0)


class DeliverySplit(TimestampedModel, LegacyReferenceModel):
    fulfillment_line = models.ForeignKey(FulfillmentOrderLine, related_name="splits", on_delete=models.CASCADE)
    delivery_line = models.ForeignKey(DeliveryOrderLine, related_name="splits", on_delete=models.CASCADE)
    split_qty = models.DecimalField(max_digits=18, decimal_places=6)
    remaining_after_split = models.DecimalField(max_digits=18, decimal_places=6)
    reason = models.TextField(blank=True)


class DeliveryPreparationTask(TimestampedModel, LegacyReferenceModel):
    class TaskStatus(models.TextChoices):
        ASSIGNED = "assigned", "Asignada"
        PREPARING = "preparing", "En preparacion"
        PREPARED = "prepared", "Preparada"
        CANCELLED = "cancelled", "Cancelada"

    delivery = models.OneToOneField(DeliveryOrder, related_name="preparation_task", on_delete=models.CASCADE)
    status = models.CharField(max_length=30, choices=TaskStatus.choices, default=TaskStatus.ASSIGNED)
    assigned_to = models.CharField(max_length=120)
    assigned_at = models.DateTimeField()
    prepared_by = models.CharField(max_length=120, blank=True)
    prepared_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "assigned_to"]),
            models.Index(fields=["warehouse_ref", "status"]),
        ]


class DeliveryDocument(TimestampedModel, LegacyReferenceModel):
    class DocumentType(models.TextChoices):
        REMITO = "remito", "Remito"

    class DocumentStatus(models.TextChoices):
        OPEN = "open", "Abierto"
        CLOSED = "closed", "Cerrado"
        VOIDED = "voided", "Anulado"

    delivery = models.ForeignKey(DeliveryOrder, related_name="documents", on_delete=models.PROTECT)
    document_number = models.CharField(max_length=60, unique=True)
    document_type = models.CharField(max_length=30, choices=DocumentType.choices, default=DocumentType.REMITO)
    status = models.CharField(max_length=30, choices=DocumentStatus.choices, default=DocumentStatus.OPEN)
    issued_at = models.DateTimeField()
    customer_ref = models.CharField(max_length=80)
    address_snapshot = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["delivery", "document_type"], name="fulfillment_deliver_07303f_idx"),
            models.Index(fields=["legacy_sales_order_number"], name="fulfillment_legacy__d57a4d_idx"),
            models.Index(fields=["issued_at"], name="fulfillment_issued__5e535f_idx"),
        ]


class DeliveryExecution(TimestampedModel, LegacyReferenceModel):
    class ExecutionStatus(models.TextChoices):
        DELIVERED_COMPLETE = "delivered_complete", "Entregada completa"
        DELIVERED_PARTIAL = "delivered_partial", "Entregada parcial"
        NOT_DELIVERED = "not_delivered", "No entregada"

    class FailureReason(models.TextChoices):
        NONE = "", "Sin motivo"
        CUSTOMER_ABSENT = "customer_absent", "Cliente ausente"
        REJECTED = "rejected", "Rechazo"
        LOGISTICS_ISSUE = "logistics_issue", "Problema logistico"
        OTHER = "other", "Otro"

    delivery = models.ForeignKey(DeliveryOrder, related_name="executions", on_delete=models.PROTECT)
    route_stop_ref = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=40, choices=ExecutionStatus.choices)
    reason = models.CharField(max_length=40, choices=FailureReason.choices, blank=True)
    delivered_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    returned_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    executed_at = models.DateTimeField()
    observations = models.TextField(blank=True)
    evidence_payload = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["delivery", "executed_at"]),
            models.Index(fields=["route_stop_ref"]),
            models.Index(fields=["status", "executed_at"]),
        ]


class DeliveryDocumentLine(TimestampedModel, LegacyReferenceModel):
    document = models.ForeignKey(DeliveryDocument, related_name="lines", on_delete=models.CASCADE)
    delivery_line = models.ForeignKey(DeliveryOrderLine, related_name="document_lines", on_delete=models.PROTECT)
    item_ref = models.CharField(max_length=60, blank=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=6)
    delivery_unit_qty = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    delivery_uom = models.CharField(max_length=20, blank=True)
    conversion_factor = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    uom = models.CharField(max_length=20)
    item_snapshot = models.JSONField(default=dict, blank=True)
    planned_weight_kg = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    planned_volume_m3 = models.DecimalField(max_digits=18, decimal_places=6, default=0)
