from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from apps.inventory.models import InventoryBalance, StockState
from apps.logistics.services import default_location_ref, generate_default_locations


STATE_PURPOSE = {
    StockState.ON_HAND: "available",
    StockState.PACKED: "available",
    StockState.RESERVED: "reserved",
    StockState.PICKING: "preparation",
    StockState.IN_TRANSIT: "transit",
    StockState.DELIVERED: "transit",
    StockState.SCRAPPED: "loss",
}


class Command(BaseCommand):
    help = "Normalizes inventory balances without location_ref into warehouse default locations."

    def add_arguments(self, parser):
        parser.add_argument("--warehouse", default="", help="Limita la normalizacion a un almacen.")
        parser.add_argument("--actor", default="normalize-stock-locations")
        parser.add_argument("--batch-size", type=int, default=1000)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        warehouse_filter = str(options["warehouse"] or "").strip()
        actor = str(options["actor"] or "").strip() or "normalize-stock-locations"
        dry_run = bool(options["dry_run"])
        batch_size = max(1, int(options["batch_size"] or 1000))

        moved_rows = 0
        deleted_zero_rows = 0
        generated_warehouses: set[str] = set()
        supported_states = list(STATE_PURPOSE)

        while True:
            with transaction.atomic():
                qs = InventoryBalance.objects.filter(location_ref="", stock_state__in=supported_states)
                if warehouse_filter:
                    qs = qs.filter(warehouse_ref=warehouse_filter)
                batch_ids = list(qs.order_by("warehouse_ref", "item_ref", "stock_state", "lot_ref", "uom", "id").values_list("id", flat=True)[:batch_size])
                if not batch_ids:
                    break
                grouped_rows = list(
                    InventoryBalance.objects.filter(id__in=batch_ids)
                    .values("warehouse_ref", "item_ref", "lot_ref", "stock_state", "uom")
                    .annotate(quantity=Sum("quantity"))
                )
                target_keys: list[tuple[str, str, str, str, str, str, object]] = []
                zero_group_ids = 0
                for row in grouped_rows:
                    warehouse_ref = str(row["warehouse_ref"] or "").strip()
                    if not warehouse_ref:
                        continue
                    purpose = STATE_PURPOSE[row["stock_state"]]
                    target_ref = default_location_ref(warehouse_ref, purpose)
                    quantity = row["quantity"] or 0
                    if quantity == 0:
                        zero_group_ids += 1
                        continue
                    target_keys.append(
                        (
                            warehouse_ref,
                            target_ref,
                            row["item_ref"],
                            row["lot_ref"],
                            row["stock_state"],
                            row["uom"],
                            quantity,
                        )
                    )
                moved_rows += len(target_keys)
                deleted_zero_rows += zero_group_ids
                if dry_run:
                    break
                warehouses = {key[0] for key in target_keys}
                for warehouse_ref in warehouses:
                    if warehouse_ref not in generated_warehouses:
                        generate_default_locations(warehouse_ref=warehouse_ref, actor=actor)
                        generated_warehouses.add(warehouse_ref)

                existing = {
                    (row.warehouse_ref, row.location_ref, row.item_ref, row.lot_ref, row.stock_state, row.uom): row
                    for row in InventoryBalance.objects.filter(
                        warehouse_ref__in={key[0] for key in target_keys},
                        location_ref__in={key[1] for key in target_keys},
                        item_ref__in={key[2] for key in target_keys},
                        lot_ref__in={key[3] for key in target_keys},
                        stock_state__in={key[4] for key in target_keys},
                        uom__in={key[5] for key in target_keys},
                    )
                }
                to_create = []
                to_update = []
                for warehouse_ref, target_ref, item_ref, lot_ref, stock_state, uom, quantity in target_keys:
                    key = (warehouse_ref, target_ref, item_ref, lot_ref, stock_state, uom)
                    target = existing.get(key)
                    if target is None:
                        to_create.append(
                            InventoryBalance(
                                warehouse_ref=warehouse_ref,
                                location_ref=target_ref,
                                item_ref=item_ref,
                                lot_ref=lot_ref,
                                stock_state=stock_state,
                                uom=uom,
                                quantity=quantity,
                                created_by=actor,
                                updated_by=actor,
                            )
                        )
                        continue
                    target.quantity += quantity
                    target.version += 1
                    target.updated_by = actor
                    to_update.append(target)
                if to_create:
                    InventoryBalance.objects.bulk_create(to_create, batch_size=batch_size)
                if to_update:
                    InventoryBalance.objects.bulk_update(to_update, ["quantity", "version", "updated_by", "updated_at"], batch_size=batch_size)
                InventoryBalance.objects.filter(id__in=batch_ids).delete()
            if dry_run:
                break

        status = "DRY-RUN" if dry_run else "OK"
        self.stdout.write(f"{status} normalizacion de ubicaciones: movidos={moved_rows} ceros_eliminados={deleted_zero_rows}")
