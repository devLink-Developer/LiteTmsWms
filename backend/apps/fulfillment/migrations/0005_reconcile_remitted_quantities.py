from collections import defaultdict
from decimal import Decimal

from django.db import migrations


def reconcile_remitted_quantities(apps, schema_editor):
    DeliveryDocumentLine = apps.get_model("fulfillment", "DeliveryDocumentLine")
    DeliveryOrder = apps.get_model("fulfillment", "DeliveryOrder")
    DeliveryOrderLine = apps.get_model("fulfillment", "DeliveryOrderLine")
    FulfillmentOrder = apps.get_model("fulfillment", "FulfillmentOrder")
    FulfillmentOrderLine = apps.get_model("fulfillment", "FulfillmentOrderLine")

    remitted_by_delivery_line = defaultdict(lambda: Decimal("0"))
    remitted_delivery_line_ids = set()
    remitted_delivery_ids = set()

    issued_lines = DeliveryDocumentLine.objects.filter(document__document_type="remito", document__status="issued")
    for document_line in issued_lines.select_related("delivery_line", "document").iterator():
        remitted_by_delivery_line[document_line.delivery_line_id] += document_line.quantity
        remitted_delivery_line_ids.add(document_line.delivery_line_id)
        remitted_delivery_ids.add(document_line.delivery_line.delivery_id)

    if remitted_delivery_line_ids:
        for delivery_line in DeliveryOrderLine.objects.filter(id__in=remitted_delivery_line_ids).iterator():
            remitted_qty = remitted_by_delivery_line[delivery_line.id]
            if delivery_line.delivered_qty < remitted_qty:
                delivery_line.delivered_qty = remitted_qty
                delivery_line.save(update_fields=["delivered_qty", "updated_at"])

    if remitted_delivery_ids:
        DeliveryOrder.objects.filter(id__in=remitted_delivery_ids).update(status="delivered_complete")

    reserved_statuses = {"confirmed", "planned", "assigned", "preparing"}
    prepared_statuses = {"prepared", "loaded"}

    for fulfillment_line in FulfillmentOrderLine.objects.all().iterator():
        reserved_qty = Decimal("0")
        prepared_qty = Decimal("0")
        remitted_qty = Decimal("0")
        delivery_lines = DeliveryOrderLine.objects.filter(fulfillment_line_id=fulfillment_line.id).select_related("delivery")
        for delivery_line in delivery_lines:
            if delivery_line.id in remitted_delivery_line_ids:
                remitted_qty += remitted_by_delivery_line[delivery_line.id]
                continue
            if delivery_line.delivery.status in reserved_statuses:
                reserved_qty += delivery_line.planned_qty
            if delivery_line.delivery.status in prepared_statuses:
                prepared_qty += delivery_line.planned_qty

        updates = []
        if fulfillment_line.reserved_qty != reserved_qty:
            fulfillment_line.reserved_qty = reserved_qty
            updates.append("reserved_qty")
        if fulfillment_line.prepared_qty != prepared_qty:
            fulfillment_line.prepared_qty = prepared_qty
            updates.append("prepared_qty")
        delivered_qty = max(fulfillment_line.delivered_qty, remitted_qty)
        if fulfillment_line.delivered_qty < delivered_qty:
            fulfillment_line.delivered_qty = min(fulfillment_line.ordered_qty, delivered_qty)
            updates.append("delivered_qty")
        if updates:
            updates.append("updated_at")
            fulfillment_line.save(update_fields=updates)

    for fulfillment in FulfillmentOrder.objects.prefetch_related("lines").all().iterator(chunk_size=200):
        lines = list(fulfillment.lines.all())
        if not lines:
            continue
        if all(line.delivered_qty >= line.ordered_qty for line in lines):
            next_status = "delivered"
        elif any(line.delivered_qty > 0 for line in lines):
            next_status = "partially_delivered"
        else:
            continue
        if fulfillment.status != next_status:
            fulfillment.status = next_status
            fulfillment.save(update_fields=["status", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("fulfillment", "0004_normalize_operational_quantities"),
    ]

    operations = [
        migrations.RunPython(reconcile_remitted_quantities, migrations.RunPython.noop),
    ]
