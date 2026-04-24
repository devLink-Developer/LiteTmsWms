from decimal import Decimal

from django.db import migrations
from django.db.models import Sum


def normalize_operational_quantities(apps, schema_editor):
    FulfillmentOrderLine = apps.get_model("fulfillment", "FulfillmentOrderLine")
    DeliveryOrderLine = apps.get_model("fulfillment", "DeliveryOrderLine")

    reserved_statuses = [
        "confirmed",
        "planned",
        "assigned",
        "preparing",
        "prepared",
        "loaded",
        "in_route",
        "attempted",
        "delivered_partial",
        "delivered_complete",
    ]
    prepared_statuses = [
        "prepared",
        "loaded",
        "in_route",
        "attempted",
        "delivered_partial",
        "delivered_complete",
    ]

    for line in FulfillmentOrderLine.objects.all().iterator():
        reserved_qty = (
            DeliveryOrderLine.objects.filter(fulfillment_line_id=line.id, delivery__status__in=reserved_statuses).aggregate(
                total=Sum("planned_qty")
            )["total"]
            or Decimal("0")
        )
        prepared_qty = (
            DeliveryOrderLine.objects.filter(fulfillment_line_id=line.id, delivery__status__in=prepared_statuses).aggregate(
                total=Sum("planned_qty")
            )["total"]
            or Decimal("0")
        )
        updates = []
        if line.reserved_qty != reserved_qty:
            line.reserved_qty = reserved_qty
            updates.append("reserved_qty")
        if line.prepared_qty != prepared_qty:
            line.prepared_qty = prepared_qty
            updates.append("prepared_qty")
        if updates:
            updates.append("updated_at")
            line.save(update_fields=updates)


class Migration(migrations.Migration):

    dependencies = [
        ("fulfillment", "0003_alter_deliveryorder_status_deliverypreparationtask"),
    ]

    operations = [
        migrations.RunPython(normalize_operational_quantities, migrations.RunPython.noop),
    ]
