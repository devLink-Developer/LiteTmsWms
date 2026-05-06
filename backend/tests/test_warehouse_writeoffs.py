from __future__ import annotations

import json
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase

from apps.inventory.models import InventoryBalance, InventoryLedgerEntry, InventoryReservation, InventoryWriteOff, StockState
from apps.inventory.services import reserve_inventory
from apps.logistics.models import WarehouseLocation, WarehouseMaster


class WarehouseWriteOffTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_X_ACTOR="stock-operator")
        session = self.client.session
        session["authorized_warehouses"] = ["W001"]
        session["active_warehouse_ref"] = "W001"
        session.save()

    def _post(self, path: str, payload: dict, key: str):
        return self.client.post(path, json.dumps(payload), content_type="application/json", HTTP_IDEMPOTENCY_KEY=key)

    def test_warehouse_create_generates_default_and_layout_locations(self):
        response = self._post(
            "/api/v1/logistics/warehouses/",
            {
                "warehouse_ref": "W001",
                "name": "Deposito Central",
                "store_ref": "S001",
                "layout": {"zones": 1, "aisles": 1, "floors": 1, "levels": 1, "positions": 2},
            },
            "warehouse-w001",
        )

        self.assertEqual(response.status_code, 201, response.content)
        warehouse = WarehouseMaster.objects.get(warehouse_ref="W001")
        self.assertEqual(warehouse.default_breakage_location_ref, "W001-BAJ-ROT")
        self.assertEqual(warehouse.default_transit_location_ref, "W001-TRN-GEN")
        self.assertTrue(WarehouseLocation.objects.filter(warehouse_ref="W001", location_ref="W001-DSP-GEN", is_dispatchable=True).exists())
        self.assertTrue(WarehouseLocation.objects.filter(warehouse_ref="W001", location_ref="W001-TRN-GEN", purpose="transit").exists())
        self.assertTrue(WarehouseLocation.objects.filter(warehouse_ref="W001", location_ref="W001-BAJ-PER", allows_scrap=True).exists())
        self.assertTrue(WarehouseLocation.objects.filter(warehouse_ref="W001", location_ref="W001-DSP-Z01-A01-F01-N01-P002").exists())

        replay = self._post(
            "/api/v1/logistics/warehouses/",
            {
                "warehouse_ref": "W001",
                "name": "Deposito Central",
                "store_ref": "S001",
                "layout": {"zones": 1, "aisles": 1, "floors": 1, "levels": 1, "positions": 2},
            },
            "warehouse-w001",
        )
        self.assertEqual(replay.status_code, 201, replay.content)
        self.assertEqual(WarehouseLocation.objects.filter(warehouse_ref="W001").count(), 8)

    def test_write_off_breakage_moves_packed_to_scrapped_and_is_idempotent(self):
        self._post(
            "/api/v1/logistics/warehouses/",
            {"warehouse_ref": "W001", "name": "Deposito Central"},
            "warehouse-w001",
        )
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="ITEM-1",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("10"),
        )
        payload = {
            "warehouse_ref": "W001",
            "reason_code": "breakage",
            "reason": "Rotura detectada en preparacion",
            "source_location_ref": "W001-DSP-GEN",
            "lines": [{"item_ref": "ITEM-1", "quantity": "2", "uom": "UN"}],
        }

        response = self._post("/api/v1/inventory/write-offs/", payload, "writeoff-1")

        self.assertEqual(response.status_code, 201, response.content)
        result = response.json()["result"]
        self.assertEqual(result["status"], InventoryWriteOff.WriteOffStatus.POSTED)
        self.assertEqual(result["target_location_ref"], "W001-BAJ-ROT")
        packed = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
        )
        scrapped = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-BAJ-ROT",
            item_ref="ITEM-1",
            stock_state=StockState.SCRAPPED,
        )
        self.assertEqual(packed.quantity, Decimal("8.000000"))
        self.assertEqual(scrapped.quantity, Decimal("2.000000"))
        self.assertEqual(InventoryLedgerEntry.objects.filter(document_type="inventory_write_off").count(), 2)

        replay = self._post("/api/v1/inventory/write-offs/", payload, "writeoff-1")
        self.assertEqual(replay.status_code, 201, replay.content)
        self.assertEqual(InventoryLedgerEntry.objects.filter(document_type="inventory_write_off").count(), 2)
        packed.refresh_from_db()
        self.assertEqual(packed.quantity, Decimal("8.000000"))

    def test_reserve_inventory_splits_available_positions_by_location_order(self):
        self._post(
            "/api/v1/logistics/warehouses/",
            {"warehouse_ref": "W001", "name": "Deposito Central"},
            "warehouse-w001",
        )
        WarehouseLocation.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-Z01-A01-F01-N01-P001",
            name="Posicion 1",
            location_type="rack",
            purpose="available",
            zone_ref="Z01",
            aisle="A01",
            floor="F01",
            level="N01",
            position="P001",
            is_dispatchable=True,
            is_pickable=True,
            sort_order=20,
        )
        WarehouseLocation.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-Z01-A01-F01-N01-P002",
            name="Posicion 2",
            location_type="rack",
            purpose="available",
            zone_ref="Z01",
            aisle="A01",
            floor="F01",
            level="N01",
            position="P002",
            is_dispatchable=True,
            is_pickable=True,
            sort_order=30,
        )
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-Z01-A01-F01-N01-P001",
            item_ref="ITEM-1",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("1"),
        )
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-Z01-A01-F01-N01-P002",
            item_ref="ITEM-1",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("2"),
        )

        reservation = reserve_inventory(
            warehouse_ref="W001",
            source_type="delivery_order",
            source_ref="DEL-1",
            actor="tester",
            lines=[{"item_ref": "ITEM-1", "quantity": "3", "uom": "UN"}],
            idempotency_key="reserve-split",
            source_stock_state=StockState.PACKED,
        )

        self.assertEqual(reservation.status, InventoryReservation.ReservationStatus.ALLOCATED)
        self.assertEqual(
            list(reservation.lines.order_by("source_location_ref").values_list("source_location_ref", "reserved_qty")),
            [
                ("W001-DSP-Z01-A01-F01-N01-P001", Decimal("1.000000")),
                ("W001-DSP-Z01-A01-F01-N01-P002", Decimal("2.000000")),
            ],
        )
        reserved = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-RSV-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.RESERVED,
        )
        self.assertEqual(reserved.quantity, Decimal("3.000000"))

    def test_write_off_rejects_non_active_warehouse(self):
        response = self._post(
            "/api/v1/inventory/write-offs/",
            {
                "warehouse_ref": "W002",
                "reason_code": "loss",
                "reason": "No encontrada",
                "lines": [{"item_ref": "ITEM-1", "quantity": "1", "uom": "UN"}],
            },
            "writeoff-forbidden",
        )

        self.assertEqual(response.status_code, 403, response.content)

    def test_advanced_stock_separates_real_location_from_legacy_fallback(self):
        self._post(
            "/api/v1/logistics/warehouses/",
            {"warehouse_ref": "W001", "name": "Deposito Central"},
            "warehouse-w001",
        )
        WarehouseLocation.objects.filter(warehouse_ref="W001", location_ref="W001-DSP-GEN").update(name="Disponible general")
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="ITEM-LOC",
            lot_ref="LOT-1",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("4"),
        )
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="",
            item_ref="ITEM-LEGACY",
            lot_ref="LOT-LEGACY",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("1"),
        )

        response = self.client.get("/api/v1/inventory/advanced-stock/?warehouse=W001&state=packed")

        self.assertEqual(response.status_code, 200, response.content)
        rows = {row["item_ref"]: row for row in response.json()["results"]}
        self.assertEqual(rows["ITEM-LOC"]["location_ref"], "W001-DSP-GEN")
        self.assertEqual(rows["ITEM-LOC"]["warehouse_location_ref"], "W001-DSP-GEN")
        self.assertEqual(rows["ITEM-LOC"]["location_name"], "Disponible general")
        self.assertEqual(rows["ITEM-LEGACY"]["location_ref"], "")
        self.assertEqual(rows["ITEM-LEGACY"]["warehouse_location_ref"], "LOT-LEGACY")
        self.assertTrue(rows["ITEM-LEGACY"]["location_ref_is_fallback"])

        available_response = self.client.get("/api/v1/inventory/advanced-stock/?warehouse=W001&state=packed&location_scope=available")
        self.assertEqual(available_response.status_code, 200, available_response.content)
        self.assertEqual([row["item_ref"] for row in available_response.json()["results"]], ["ITEM-LOC"])
        self.assertTrue(available_response.json()["results"][0]["is_dispatchable"])

    def test_reverse_write_off_restores_stock(self):
        self._post(
            "/api/v1/logistics/warehouses/",
            {"warehouse_ref": "W001", "name": "Deposito Central"},
            "warehouse-w001",
        )
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="ITEM-1",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("10"),
        )
        create_response = self._post(
            "/api/v1/inventory/write-offs/",
            {
                "warehouse_ref": "W001",
                "reason_code": "loss",
                "reason": "Perdida en conteo",
                "source_location_ref": "W001-DSP-GEN",
                "lines": [{"item_ref": "ITEM-1", "quantity": "3", "uom": "UN"}],
            },
            "writeoff-reverse",
        )
        write_off_id = create_response.json()["result"]["id"]

        reverse_response = self._post(
            f"/api/v1/inventory/write-offs/{write_off_id}/reverse/",
            {"reason": "Conteo corregido"},
            "writeoff-reverse-command",
        )

        self.assertEqual(reverse_response.status_code, 200, reverse_response.content)
        packed = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
        )
        scrapped = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-BAJ-PER",
            item_ref="ITEM-1",
            stock_state=StockState.SCRAPPED,
        )
        self.assertEqual(packed.quantity, Decimal("10.000000"))
        self.assertEqual(scrapped.quantity, Decimal("0.000000"))
        self.assertEqual(InventoryWriteOff.objects.get(id=write_off_id).status, InventoryWriteOff.WriteOffStatus.REVERSED)

    def test_normalize_stock_locations_command_moves_blank_balances_to_defaults(self):
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="",
            item_ref="ITEM-1",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("4"),
        )
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="",
            item_ref="ITEM-2",
            lot_ref="",
            stock_state=StockState.IN_TRANSIT,
            uom="UN",
            quantity=Decimal("1"),
        )
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="",
            item_ref="ITEM-3",
            lot_ref="",
            stock_state=StockState.DELIVERED,
            uom="UN",
            quantity=Decimal("2"),
        )

        call_command("normalize_stock_locations", stdout=StringIO())

        self.assertFalse(InventoryBalance.objects.filter(location_ref="").exists())
        self.assertEqual(
            InventoryBalance.objects.get(
                warehouse_ref="W001",
                location_ref="W001-DSP-GEN",
                item_ref="ITEM-1",
                stock_state=StockState.PACKED,
            ).quantity,
            Decimal("4.000000"),
        )
        self.assertEqual(
            InventoryBalance.objects.get(
                warehouse_ref="W001",
                location_ref="W001-TRN-GEN",
                item_ref="ITEM-2",
                stock_state=StockState.IN_TRANSIT,
            ).quantity,
            Decimal("1.000000"),
        )
        self.assertEqual(
            InventoryBalance.objects.get(
                warehouse_ref="W001",
                location_ref="W001-TRN-GEN",
                item_ref="ITEM-3",
                stock_state=StockState.DELIVERED,
            ).quantity,
            Decimal("2.000000"),
        )
