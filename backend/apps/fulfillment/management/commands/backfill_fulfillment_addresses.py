from __future__ import annotations

from itertools import islice

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.fulfillment.models import FulfillmentOrder
from apps.fulfillment.services import _address_snapshot, _select_customer_address
from apps.integrations.legacy.models import LegacyCustomerAddress, LegacyOrderLine


class Command(BaseCommand):
    help = "Backfills fulfillment address snapshots from read-only Litecore order lines into TMS/WMS."

    def add_arguments(self, parser):
        parser.add_argument("--sales-order-number", default="")
        parser.add_argument("--limit", type=int, default=0, help="Use 0 to process every matching fulfillment.")
        parser.add_argument("--actor", default="local.backfill")
        parser.add_argument("--batch-size", type=int, default=200)
        parser.add_argument("--all", action="store_true", help="Refresh existing snapshots too. Default updates only empty snapshots.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        sales_order_number = options["sales_order_number"].strip()
        limit = options["limit"]
        actor = options["actor"]
        batch_size = max(options["batch_size"], 1)
        dry_run = options["dry_run"]
        verbosity = int(options.get("verbosity") or 1)

        queryset = FulfillmentOrder.objects.order_by("created_at")
        if sales_order_number:
            queryset = queryset.filter(legacy_sales_order_number=sales_order_number)
        if not options["all"]:
            queryset = queryset.filter(Q(address_snapshot={}) | Q(address_snapshot__isnull=True))
        if limit > 0:
            queryset = queryset[:limit]

        updated = unchanged = skipped = 0
        iterator = queryset.iterator(chunk_size=batch_size)
        while True:
            batch = list(islice(iterator, batch_size))
            if not batch:
                break

            sales_orders = [row.legacy_sales_order_number.strip() for row in batch if row.legacy_sales_order_number.strip()]
            customer_refs = [row.customer_ref.strip() for row in batch if row.customer_ref.strip()]
            first_line_by_order = {}
            if sales_orders:
                legacy_lines = (
                    LegacyOrderLine.objects.using("litecore")
                    .filter(sales_order_number__in=sales_orders)
                    .order_by("sales_order_number", "line_number", "retail_line_item_id")
                )
                for line in legacy_lines:
                    first_line_by_order.setdefault(line.sales_order_number, line)
            location_ids = [
                line.delivery_address_location_id
                for line in first_line_by_order.values()
                if line.delivery_address_location_id
            ]
            addresses_by_customer_location = {}
            addresses_by_location = {}
            addresses_by_customer = {}
            if location_ids or customer_refs:
                address_filters = Q()
                if location_ids:
                    address_filters |= Q(address_location_id__in=location_ids)
                if customer_refs:
                    address_filters |= Q(customer_account_number__in=customer_refs)
                customer_addresses = LegacyCustomerAddress.objects.using("litecore").filter(address_filters, estado=True)
                for address in customer_addresses:
                    customer_ref = address.customer_account_number.strip()
                    location_id = address.address_location_id.strip()
                    if customer_ref and location_id:
                        addresses_by_customer_location.setdefault((customer_ref, location_id), address)
                    if location_id:
                        addresses_by_location.setdefault(location_id, address)
                    if customer_ref:
                        addresses_by_customer.setdefault(customer_ref, []).append(address)

            to_update = []
            now = timezone.now()
            for fulfillment in batch:
                sales_order = fulfillment.legacy_sales_order_number.strip()
                if not sales_order:
                    skipped += 1
                    continue

                line = first_line_by_order.get(sales_order)
                if line is None:
                    skipped += 1
                    if verbosity > 1:
                        self.stdout.write(self.style.WARNING(f"{sales_order}: sin linea legacy"))
                    continue

                location_id = line.delivery_address_location_id.strip()
                customer_address = (
                    addresses_by_customer_location.get((fulfillment.customer_ref.strip(), location_id))
                    or addresses_by_location.get(location_id)
                    or _select_customer_address(addresses_by_customer.get(fulfillment.customer_ref.strip(), []))
                )
                snapshot = _address_snapshot(line, fulfillment=fulfillment, customer_address=customer_address)
                if not snapshot:
                    skipped += 1
                    if verbosity > 1:
                        self.stdout.write(self.style.WARNING(f"{sales_order}: sin direccion legacy"))
                    continue
                if snapshot == (fulfillment.address_snapshot or {}):
                    unchanged += 1
                    continue

                updated += 1
                if dry_run:
                    if verbosity > 1:
                        self.stdout.write(f"{sales_order}: actualizaria direccion {snapshot.get('address_id') or snapshot.get('location_id') or ''}")
                    continue

                fulfillment.address_snapshot = snapshot
                fulfillment.updated_by = actor
                fulfillment.updated_at = now
                to_update.append(fulfillment)

            if to_update:
                FulfillmentOrder.objects.bulk_update(to_update, ["address_snapshot", "updated_by", "updated_at"])

        self.stdout.write(self.style.SUCCESS(f"Actualizados={updated} sin_cambios={unchanged} omitidos={skipped}"))
