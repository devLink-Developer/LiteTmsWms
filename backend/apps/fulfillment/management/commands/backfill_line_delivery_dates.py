from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connections

from apps.fulfillment.models import DeliveryOrder, FulfillmentOrder


FULFILLMENT_STATUSES_TO_UPDATE = {
    FulfillmentOrder.FulfillmentStatus.PENDING,
    FulfillmentOrder.FulfillmentStatus.ALLOCATED,
    FulfillmentOrder.FulfillmentStatus.PREPARING,
    FulfillmentOrder.FulfillmentStatus.READY_FOR_DISPATCH,
}

DELIVERY_STATUSES_TO_UPDATE = {
    DeliveryOrder.DeliveryStatus.CREATED,
    DeliveryOrder.DeliveryStatus.PLANNED,
    DeliveryOrder.DeliveryStatus.CONFIRMED,
    DeliveryOrder.DeliveryStatus.PREPARING,
    DeliveryOrder.DeliveryStatus.PREPARED,
}


class Command(BaseCommand):
    help = "Backfill requested/planned delivery dates from legacy transactions_orders_retailLineItem.LineDeliveryDate."

    def add_arguments(self, parser):
        parser.add_argument("--sales-order", dest="sales_order", default="", help="Limit backfill to one SalesOrderNumber.")
        parser.add_argument("--limit", type=int, default=0, help="Maximum number of fulfillment orders to inspect.")
        parser.add_argument("--dry-run", action="store_true", help="Report changes without writing TMS/WMS.")

    def _legacy_line_delivery_date(self, sales_order_number: str):
        with connections["litecore"].cursor() as cursor:
            cursor.execute(
                """
                select "LineDeliveryDate"
                from public."transactions_orders_retailLineItem"
                where "SalesOrderNumber" = %s
                  and "LineDeliveryDate" is not null
                order by "LineNumber", "retailLineItemId"
                limit 1
                """,
                [sales_order_number],
            )
            row = cursor.fetchone()
        return row[0].date() if row and row[0] else None

    def handle(self, *args, **options):
        sales_order = str(options.get("sales_order") or "").strip()
        limit = int(options.get("limit") or 0)
        dry_run = bool(options.get("dry_run"))
        qs = FulfillmentOrder.objects.exclude(legacy_sales_order_number="").prefetch_related("deliveries").order_by("legacy_sales_order_number")
        if sales_order:
            qs = qs.filter(legacy_sales_order_number=sales_order)
        if limit > 0:
            qs = qs[:limit]

        checked = 0
        fulfillment_updates = 0
        delivery_updates = 0
        skipped = 0
        iterable = qs.iterator(chunk_size=200) if limit <= 0 else qs
        for fulfillment in iterable:
            checked += 1
            delivery_date = self._legacy_line_delivery_date(fulfillment.legacy_sales_order_number)
            if not delivery_date:
                skipped += 1
                continue

            if fulfillment.status in FULFILLMENT_STATUSES_TO_UPDATE and fulfillment.requested_date != delivery_date:
                fulfillment_updates += 1
                self.stdout.write(
                    f"{fulfillment.legacy_sales_order_number}: fulfillment {fulfillment.requested_date} -> {delivery_date}"
                )
                if not dry_run:
                    fulfillment.requested_date = delivery_date
                    fulfillment.updated_by = "backfill-line-delivery-date"
                    fulfillment.save(update_fields=["requested_date", "updated_by", "updated_at"])

            for delivery in fulfillment.deliveries.all():
                if delivery.status not in DELIVERY_STATUSES_TO_UPDATE or delivery.planned_date == delivery_date:
                    continue
                delivery_updates += 1
                self.stdout.write(
                    f"{fulfillment.legacy_sales_order_number}: delivery {delivery.delivery_number} {delivery.planned_date} -> {delivery_date}"
                )
                if not dry_run:
                    delivery.planned_date = delivery_date
                    delivery.updated_by = "backfill-line-delivery-date"
                    delivery.save(update_fields=["planned_date", "updated_by", "updated_at"])

        suffix = " dry-run" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"LineDeliveryDate backfill{suffix}: checked={checked}, "
                f"fulfillment_updates={fulfillment_updates}, delivery_updates={delivery_updates}, skipped={skipped}"
            )
        )
