from __future__ import annotations

from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq
from django.core.management import call_command
from django.test import TestCase

from apps.inventory.models import InventoryBalance, StockState
from apps.inventory.stock_cache_import import import_stock_cache, parse_stock_cache_mappings


def write_stock_cache(path: Path, rows: list[dict]):
    table = pa.Table.from_pylist(
        rows,
        schema=pa.schema(
            [
                ("codigo", pa.string()),
                ("almacen_365", pa.string()),
                ("stock_fisico", pa.float64()),
                ("disponible_venta", pa.float64()),
                ("disponible_entrega", pa.float64()),
                ("comprometido", pa.float64()),
            ]
        ),
    )
    pq.write_table(table, path)


class StockCacheImportTests(TestCase):
    def test_default_import_loads_delivery_available_as_packed(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "stock_cache.parquet"
            write_stock_cache(
                path,
                [
                    {
                        "codigo": "ITEM-1",
                        "almacen_365": "WH-1",
                        "stock_fisico": 8.0,
                        "disponible_venta": 6.0,
                        "disponible_entrega": 5.25,
                        "comprometido": 2.0,
                    },
                    {
                        "codigo": "ITEM-2",
                        "almacen_365": "WH-1",
                        "stock_fisico": -1.0,
                        "disponible_venta": -1.0,
                        "disponible_entrega": -1.0,
                        "comprometido": 0.0,
                    },
                    {
                        "codigo": "",
                        "almacen_365": "WH-1",
                        "stock_fisico": 9.0,
                        "disponible_venta": 9.0,
                        "disponible_entrega": 9.0,
                        "comprometido": 0.0,
                    },
                ],
            )

            result = import_stock_cache(path=path, actor="tester")

        balance = InventoryBalance.objects.get(
            warehouse_ref="WH-1",
            location_ref="WH-1-DSP-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
        )
        self.assertEqual(balance.quantity, Decimal("5.250000"))
        self.assertEqual(balance.uom, "UN")
        self.assertEqual(balance.created_by, "tester")
        self.assertEqual(result.source_rows, 3)
        self.assertEqual(result.written_balances, 1)
        self.assertEqual(result.skipped_missing_keys, 1)
        self.assertEqual(result.clamped_negative_quantities, 1)
        self.assertEqual(result.skipped_zero_quantity, 1)

    def test_custom_mappings_load_available_and_committed_buckets(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "stock_cache.parquet"
            write_stock_cache(
                path,
                [
                    {
                        "codigo": "ITEM-1",
                        "almacen_365": "WH-1",
                        "stock_fisico": 8.0,
                        "disponible_venta": 6.0,
                        "disponible_entrega": 5.0,
                        "comprometido": 2.0,
                    },
                ],
            )

            import_stock_cache(
                path=path,
                mappings=parse_stock_cache_mappings(["on_hand=disponible_venta", "reserved=comprometido"]),
                actor="tester",
            )

        on_hand = InventoryBalance.objects.get(
            warehouse_ref="WH-1",
            location_ref="WH-1-DSP-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.ON_HAND,
        )
        reserved = InventoryBalance.objects.get(
            warehouse_ref="WH-1",
            location_ref="WH-1-RSV-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.RESERVED,
        )
        self.assertEqual(on_hand.quantity, Decimal("6.000000"))
        self.assertEqual(reserved.quantity, Decimal("2.000000"))

    def test_import_upserts_existing_balance(self):
        InventoryBalance.objects.create(
            warehouse_ref="WH-1",
            location_ref="WH-1-DSP-GEN",
            item_ref="ITEM-1",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("1"),
            created_by="seed",
        )
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "stock_cache.parquet"
            write_stock_cache(
                path,
                [
                    {
                        "codigo": "ITEM-1",
                        "almacen_365": "WH-1",
                        "stock_fisico": 10.0,
                        "disponible_venta": 10.0,
                        "disponible_entrega": 7.0,
                        "comprometido": 0.0,
                    },
                ],
            )

            import_stock_cache(path=path, actor="tester")

        balance = InventoryBalance.objects.get(
            warehouse_ref="WH-1",
            location_ref="WH-1-DSP-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
        )
        self.assertEqual(balance.quantity, Decimal("7.000000"))
        self.assertEqual(balance.created_by, "seed")
        self.assertEqual(balance.updated_by, "tester")

    def test_management_command_dry_run_does_not_write(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "stock_cache.parquet"
            write_stock_cache(
                path,
                [
                    {
                        "codigo": "ITEM-1",
                        "almacen_365": "WH-1",
                        "stock_fisico": 4.0,
                        "disponible_venta": 4.0,
                        "disponible_entrega": 4.0,
                        "comprometido": 0.0,
                    },
                ],
            )

            call_command("import_stock_cache", "--path", str(path), "--dry-run", stdout=StringIO())

        self.assertEqual(InventoryBalance.objects.count(), 0)
