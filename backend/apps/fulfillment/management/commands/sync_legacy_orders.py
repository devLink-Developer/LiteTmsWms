from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.fulfillment.services import FulfillmentRuleError, ingest_legacy_order
from apps.integrations.legacy.models import LegacyOrder


class Command(BaseCommand):
    help = "Ingests invoiced Litecore orders into the isolated TMS/WMS schema."

    def add_arguments(self, parser):
        parser.add_argument("--sales-order-number", default="")
        parser.add_argument("--from-date", default="")
        parser.add_argument("--to-date", default="")
        parser.add_argument("--status", default="FACTURADO")
        parser.add_argument("--limit", type=int, default=100, help="Use 0 to process every matching order.")
        parser.add_argument("--actor", default="local.sync")
        parser.add_argument("--watch", action="store_true", help="Run forever and sync every --poll-interval seconds.")
        parser.add_argument("--poll-interval", type=int, default=60, help="Seconds between sync cycles in --watch mode.")
        parser.add_argument(
            "--oldest-first",
            action="store_true",
            help="Process older invoices first. Default is newest modified orders first for polling.",
        )

    def handle(self, *args, **options):
        poll_interval = options["poll_interval"]
        if poll_interval < 1:
            raise ValueError("--poll-interval must be greater than 0.")

        if not options["watch"]:
            self._sync_once(options)
            return

        self.stdout.write(self.style.SUCCESS(f"Sync periodico Litecore iniciado cada {poll_interval}s."))
        while True:
            started_at = timezone.now()
            try:
                self._sync_once(options)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Error en ciclo de sync Litecore: {exc}"))
            finally:
                close_old_connections()

            elapsed = (timezone.now() - started_at).total_seconds()
            time.sleep(max(0, poll_interval - elapsed))

    def _sync_once(self, options):
        sales_order_number = options["sales_order_number"].strip()
        from_date = parse_date(options["from_date"]) if options["from_date"] else None
        to_date = parse_date(options["to_date"]) if options["to_date"] else None
        status = options["status"].strip()
        limit = options["limit"]
        actor = options["actor"]
        oldest_first = options["oldest_first"]

        queryset = LegacyOrder.objects.using("litecore").filter(invoice_number__gt="", sales_order_number__gt="")
        if sales_order_number:
            queryset = queryset.filter(sales_order_number=sales_order_number)
        if from_date:
            queryset = queryset.filter(invoice_date__date__gte=from_date)
        if to_date:
            queryset = queryset.filter(invoice_date__date__lte=to_date)
        if status:
            queryset = queryset.filter(order_status=status)
        if oldest_first:
            queryset = queryset.order_by("invoice_date", "sales_order_number")
        else:
            queryset = queryset.order_by("-modified_datetime", "-invoice_date", "sales_order_number")
        if limit > 0:
            queryset = queryset[:limit]

        processed = 0
        skipped = 0
        self.stdout.write(f"[{timezone.now().isoformat()}] Buscando pedidos Litecore facturados...")
        for order in queryset:
            key = f"sync:litecore:{order.sales_order_number}:{order.modified_datetime.isoformat()}"
            try:
                result = ingest_legacy_order(
                    sales_order_number=order.sales_order_number,
                    idempotency_key=key,
                    actor=actor,
                )
            except (FulfillmentRuleError, LegacyOrder.DoesNotExist, LegacyOrder.MultipleObjectsReturned) as exc:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"{order.sales_order_number}: {exc}"))
                continue
            processed += 1
            self.stdout.write(f"{order.sales_order_number}: {result.status}")

        self.stdout.write(self.style.SUCCESS(f"Procesados={processed} omitidos={skipped}"))
