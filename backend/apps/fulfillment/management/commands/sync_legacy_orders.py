from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.fulfillment.models import LegacyOrderSyncCursor
from apps.fulfillment.services import FulfillmentRuleError, ingest_legacy_order, legacy_sales_order_type, process_legacy_order_impact
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
        parser.add_argument("--poll-interval", type=int, default=10, help="Seconds between sync cycles in --watch mode.")
        parser.add_argument(
            "--backfill",
            action="store_true",
            help="Process matching historical rows instead of only rows newer than the sync cursor.",
        )
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
        backfill = options["backfill"]

        queryset = (
            LegacyOrder.objects.using("litecore")
            .filter(invoice_number__gt="", sales_order_number__gt="")
            .filter(
                Q(sales_order_type__iexact="P")
                | Q(sales_order_type__iexact="A")
                | Q(sales_order_type__iexact="D")
            )
        )
        if sales_order_number:
            queryset = queryset.filter(sales_order_number=sales_order_number)
        if from_date:
            queryset = queryset.filter(invoice_date__date__gte=from_date)
        if to_date:
            queryset = queryset.filter(invoice_date__date__lte=to_date)
        if status:
            queryset = queryset.filter(order_status=status)

        use_cursor = not backfill and not sales_order_number and not from_date and not to_date
        cursor = None
        if use_cursor:
            cursor_name = f"litecore.orders:{status or 'all'}"
            cursor, _ = LegacyOrderSyncCursor.objects.get_or_create(
                name=cursor_name,
                defaults={"created_by": actor},
            )
            if cursor.last_modified_datetime:
                queryset = queryset.filter(
                    Q(modified_datetime__gt=cursor.last_modified_datetime)
                    | Q(modified_datetime=cursor.last_modified_datetime, transaction_id__gt=cursor.last_source_pk)
                )
            else:
                latest = queryset.order_by("-modified_datetime", "-transaction_id").first()
                if latest is not None:
                    cursor.last_modified_datetime = latest.modified_datetime
                    cursor.last_source_pk = latest.transaction_id
                    cursor.updated_by = actor
                    cursor.save(update_fields=["last_modified_datetime", "last_source_pk", "updated_by", "updated_at"])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Cursor {cursor.name} inicializado en {latest.modified_datetime.isoformat()} / {latest.transaction_id}.",
                        )
                    )
                    self.stdout.write(self.style.SUCCESS("Procesados=0 omitidos=0"))
                    return

        if use_cursor or oldest_first:
            queryset = queryset.order_by("modified_datetime", "transaction_id")
        else:
            queryset = queryset.order_by("-modified_datetime", "-invoice_date", "sales_order_number")
        if limit > 0:
            queryset = queryset[:limit]

        processed = 0
        skipped = 0
        self.stdout.write(f"[{timezone.now().isoformat()}] Buscando novedades Litecore...")
        for order in queryset:
            order_type = legacy_sales_order_type(order)
            key = f"sync:litecore:{order_type}:{order.sales_order_number}:{order.modified_datetime.isoformat()}"
            try:
                if order_type in {"A", "D"}:
                    result = process_legacy_order_impact(
                        sales_order_number=order.sales_order_number,
                        idempotency_key=key,
                        actor=actor,
                    )
                else:
                    result = ingest_legacy_order(
                        sales_order_number=order.sales_order_number,
                        idempotency_key=key,
                        actor=actor,
                    )
            except (FulfillmentRuleError, LegacyOrder.DoesNotExist, LegacyOrder.MultipleObjectsReturned) as exc:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"{order.sales_order_number}: {exc}"))
            else:
                processed += 1
                self.stdout.write(f"{order.sales_order_number}: {result.status}")
            if cursor is not None:
                cursor.last_modified_datetime = order.modified_datetime
                cursor.last_source_pk = order.transaction_id
                cursor.updated_by = actor
                cursor.save(update_fields=["last_modified_datetime", "last_source_pk", "updated_by", "updated_at"])

        self.stdout.write(self.style.SUCCESS(f"Procesados={processed} omitidos={skipped}"))
