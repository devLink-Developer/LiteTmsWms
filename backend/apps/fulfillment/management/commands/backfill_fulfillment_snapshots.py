from __future__ import annotations

from itertools import islice

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.fulfillment.models import FulfillmentOrder, FulfillmentOrderLine
from apps.fulfillment.services import (
    _customer_document_from_snapshot,
    _resolve_customer_snapshots,
    _resolve_line_item_snapshots,
)


def _digits(value) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())


def _address_text(address) -> str:
    if not isinstance(address, dict):
        return ""
    formatted = str(address.get("formatted") or "").strip()
    if formatted:
        return formatted
    return " ".join(
        str(address.get(key) or "").strip()
        for key in ["street", "street_number", "city", "state", "zip_code"]
        if str(address.get(key) or "").strip()
    )


def _customer_snapshot(order: FulfillmentOrder) -> dict:
    snapshot = dict(order.customer_snapshot or {})
    customer_ref = str(order.customer_ref or "").strip()
    if not snapshot or snapshot.get("source") == "local_backfill":
        address = order.address_snapshot or {}
        snapshot = {
            "customer_ref": customer_ref,
            "name": customer_ref,
            "document_type": "",
            "document_number": order.customer_document,
            "phone": "",
            "email": "",
            "address": address,
            "address_text": _address_text(address),
            "source": "local_backfill",
        }
    snapshot["customer_ref"] = str(snapshot.get("customer_ref") or customer_ref).strip()
    return snapshot


def _item_snapshot(line: FulfillmentOrderLine) -> dict:
    return {
        "item_ref": line.item_ref,
        "name": line.item_ref,
        "long_name": line.item_ref,
        "category": "",
        "coverage_group": "",
        "uom": line.uom,
        "sap_uom": line.uom,
        "sales_uom": line.uom,
        "delivery_uom": line.uom,
        "conversion_factor": "1.000000",
        "unit_weight_kg": "0.000000",
        "unit_volume_m3": "0.000000",
        "freight_product": False,
        "service_product": False,
        "virtual_product": False,
        "source": "local_backfill",
    }


class Command(BaseCommand):
    help = "Backfills customer/item snapshots in the TMS/WMS schema."

    def add_arguments(self, parser):
        parser.add_argument("--sales-order-number", default="")
        parser.add_argument("--limit", type=int, default=0, help="Use 0 to process every matching row.")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--actor", default="local.snapshot-backfill")
        parser.add_argument("--all", action="store_true", help="Refresh existing local_backfill snapshots too.")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--source",
            choices=["local", "legacy"],
            default="local",
            help="local writes minimal snapshots from TMS/WMS only; legacy enriches from Litecore/Parquet.",
        )

    def handle(self, *args, **options):
        sales_order_number = str(options["sales_order_number"] or "").strip()
        limit = int(options["limit"] or 0)
        batch_size = max(int(options["batch_size"] or 500), 1)
        actor = str(options["actor"] or "local.snapshot-backfill").strip()
        dry_run = bool(options["dry_run"])
        refresh_all = bool(options["all"])
        source = str(options["source"] or "local").strip()

        order_qs = FulfillmentOrder.objects.using("default").order_by("created_at")
        line_qs = FulfillmentOrderLine.objects.using("default").order_by("created_at")
        if sales_order_number:
            order_qs = order_qs.filter(legacy_sales_order_number=sales_order_number)
            line_qs = line_qs.filter(legacy_sales_order_number=sales_order_number)
        if source == "local" and not refresh_all:
            order_qs = order_qs.filter(Q(customer_snapshot={}) | Q(customer_document=""))
            line_qs = line_qs.filter(Q(item_snapshot={}) | Q(item_snapshot__isnull=True))
        if limit > 0:
            order_qs = order_qs[:limit]
            line_qs = line_qs[:limit]

        updated_orders = self._backfill_orders(
            order_qs,
            batch_size=batch_size,
            actor=actor,
            dry_run=dry_run,
            source=source,
            refresh_all=refresh_all,
        )
        updated_lines = self._backfill_lines(
            line_qs,
            batch_size=batch_size,
            actor=actor,
            dry_run=dry_run,
            source=source,
            refresh_all=refresh_all,
        )
        suffix = " dry-run" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"Snapshots backfill{suffix}: source={source} fulfillment_orders={updated_orders} fulfillment_lines={updated_lines}"
            )
        )

    def _backfill_orders(
        self,
        queryset,
        *,
        batch_size: int,
        actor: str,
        dry_run: bool,
        source: str,
        refresh_all: bool,
    ) -> int:
        updated = 0
        iterator = queryset.iterator(chunk_size=batch_size)
        while True:
            batch = list(islice(iterator, batch_size))
            if not batch:
                break
            legacy_snapshots = {}
            if source == "legacy":
                refs = {order.customer_ref for order in batch if str(order.customer_ref or "").strip()}
                legacy_snapshots = _resolve_customer_snapshots(refs)
            now = timezone.now()
            to_update = []
            for order in batch:
                current = dict(order.customer_snapshot or {})
                if source == "legacy":
                    should_update = (
                        refresh_all
                        or not current
                        or not order.customer_document
                        or current.get("source") in {"local_backfill", "fallback"}
                    )
                    if not should_update:
                        continue
                    customer_ref = str(order.customer_ref or "").strip()
                    snapshot = dict(legacy_snapshots.get(customer_ref) or _customer_snapshot(order))
                    if not snapshot.get("address") and order.address_snapshot:
                        snapshot["address"] = order.address_snapshot
                    if not snapshot.get("address_text") and snapshot.get("address"):
                        snapshot["address_text"] = _address_text(snapshot["address"])
                else:
                    snapshot = _customer_snapshot(order)
                document = _customer_document_from_snapshot(snapshot) or _digits(order.customer_document)
                if snapshot == (order.customer_snapshot or {}) and document == order.customer_document:
                    continue
                updated += 1
                if dry_run:
                    continue
                order.customer_snapshot = snapshot
                order.customer_document = document
                order.updated_by = actor
                order.updated_at = now
                to_update.append(order)
            if to_update:
                FulfillmentOrder.objects.using("default").bulk_update(
                    to_update,
                    ["customer_snapshot", "customer_document", "updated_by", "updated_at"],
                )
        return updated

    def _backfill_lines(
        self,
        queryset,
        *,
        batch_size: int,
        actor: str,
        dry_run: bool,
        source: str,
        refresh_all: bool,
    ) -> int:
        updated = 0
        iterator = queryset.iterator(chunk_size=batch_size)
        while True:
            batch = list(islice(iterator, batch_size))
            if not batch:
                break
            legacy_snapshots = {}
            if source == "legacy":
                candidate_lines = []
                for line in batch:
                    current = dict(line.item_snapshot or {})
                    should_update = (
                        refresh_all
                        or not current
                        or current.get("source") in {"local_backfill", "fallback"}
                        or not current.get("name")
                        or current.get("name") == line.item_ref
                    )
                    if should_update:
                        line.item_snapshot = {}
                        candidate_lines.append(line)
                legacy_snapshots = _resolve_line_item_snapshots(candidate_lines)
            now = timezone.now()
            to_update = []
            for line in batch:
                if source == "legacy":
                    snapshot = legacy_snapshots.get(line.id)
                    if snapshot is None:
                        continue
                else:
                    snapshot = _item_snapshot(line)
                if snapshot == (line.item_snapshot or {}):
                    continue
                updated += 1
                if dry_run:
                    continue
                line.item_snapshot = snapshot
                line.updated_by = actor
                line.updated_at = now
                to_update.append(line)
            if to_update:
                FulfillmentOrderLine.objects.using("default").bulk_update(
                    to_update,
                    ["item_snapshot", "updated_by", "updated_at"],
                )
        return updated
