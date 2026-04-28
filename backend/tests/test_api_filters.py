from __future__ import annotations

import json
from datetime import date
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.fulfillment.models import DeliveryOrder, DeliveryPreparationTask, FulfillmentOrder
from apps.inventory.models import (
    InventoryBalance,
    InventoryLedgerEntry,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptLine,
    StockState,
)
from apps.logistics.models import MaterialMasterSnapshot
from apps.routes.models import RouteSheet
from apps.shipping.models import Shipment, ShipmentEvent
from apps.transfers.models import TransferOrder


class ApiFilterTests(TestCase):
    def _results(self, path: str, params: dict[str, str] | None = None) -> list[dict]:
        response = self.client.get(path, params or {})
        self.assertEqual(response.status_code, 200, response.content)
        return json.loads(response.content)["results"]

    def _create_ledger_entry(
        self,
        *,
        idempotency_key: str,
        movement_type: str,
        direction: str,
        warehouse_ref: str,
        item_ref: str,
        stock_state: str,
        document_type: str,
        document_ref: str,
        posted_at,
    ) -> InventoryLedgerEntry:
        entry = InventoryLedgerEntry.objects.create(
            idempotency_key=idempotency_key,
            movement_type=movement_type,
            direction=direction,
            warehouse_ref=warehouse_ref,
            item_ref=item_ref,
            stock_state=stock_state,
            quantity=Decimal("1"),
            uom="UN",
            document_type=document_type,
            document_ref=document_ref,
        )
        InventoryLedgerEntry.objects.filter(id=entry.id).update(posted_at=posted_at)
        return entry

    def test_inventory_balances_filter_by_warehouse_item_and_state(self):
        InventoryBalance.objects.create(
            warehouse_ref="WH-A",
            item_ref="ITEM-1",
            lot_ref="",
            stock_state=StockState.ON_HAND,
            uom="UN",
            quantity=Decimal("10"),
        )
        InventoryBalance.objects.create(
            warehouse_ref="WH-A",
            item_ref="ITEM-2",
            lot_ref="",
            stock_state=StockState.ON_HAND,
            uom="UN",
            quantity=Decimal("5"),
        )
        InventoryBalance.objects.create(
            warehouse_ref="WH-B",
            item_ref="ITEM-1",
            lot_ref="",
            stock_state=StockState.RESERVED,
            uom="UN",
            quantity=Decimal("3"),
        )

        results = self._results(
            "/api/v1/inventory/balances/",
            {"warehouse": "WH-A", "item": "ITEM-1", "state": StockState.ON_HAND},
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["warehouse_ref"], "WH-A")
        self.assertEqual(results[0]["item_ref"], "ITEM-1")
        self.assertEqual(results[0]["stock_state"], StockState.ON_HAND)

    @patch("apps.inventory.api.fulfillment_warehouse_codes_for_stores")
    @patch("apps.inventory.api.employee_delivery_permissions")
    def test_inventory_balances_are_scoped_to_stock_fulfillment_group(self, employee_delivery_permissions, fulfillment_warehouse_codes_for_stores):
        get_user_model().objects.create_user(username="operator@example.com")
        self.client.force_login(get_user_model().objects.get(username="operator@example.com"))
        employee_delivery_permissions.return_value = {
            "employee": {"store_codes": ["S001"], "branch_ref": "S001"},
            "authorized_warehouses": ["W-SHIPPING"],
            "permissions": ["stock:view"],
        }
        fulfillment_warehouse_codes_for_stores.return_value = {"WH-A", "WH-C"}
        InventoryBalance.objects.create(
            warehouse_ref="WH-A",
            item_ref="ITEM-1",
            lot_ref="",
            stock_state=StockState.ON_HAND,
            uom="UN",
            quantity=Decimal("10"),
        )
        InventoryBalance.objects.create(
            warehouse_ref="WH-B",
            item_ref="ITEM-2",
            lot_ref="",
            stock_state=StockState.ON_HAND,
            uom="UN",
            quantity=Decimal("5"),
        )
        InventoryBalance.objects.create(
            warehouse_ref="WH-C",
            item_ref="ITEM-3",
            lot_ref="",
            stock_state=StockState.RESERVED,
            uom="UN",
            quantity=Decimal("2"),
        )

        response = self.client.get("/api/v1/inventory/balances/")

        self.assertEqual(response.status_code, 200, response.content)
        payload = json.loads(response.content)
        self.assertEqual(payload["allowed_warehouses"], ["WH-A", "WH-C"])
        self.assertEqual({row["warehouse_ref"] for row in payload["results"]}, {"WH-A", "WH-C"})
        fulfillment_warehouse_codes_for_stores.assert_called_once_with({"S001"})

    @patch("apps.inventory.api.fulfillment_warehouse_codes_for_stores")
    @patch("apps.inventory.api.employee_delivery_permissions")
    def test_inventory_balances_reject_warehouses_outside_stock_scope(self, employee_delivery_permissions, fulfillment_warehouse_codes_for_stores):
        get_user_model().objects.create_user(username="operator@example.com")
        self.client.force_login(get_user_model().objects.get(username="operator@example.com"))
        employee_delivery_permissions.return_value = {
            "employee": {"store_codes": ["S001"], "branch_ref": "S001"},
            "authorized_warehouses": ["W-SHIPPING"],
            "permissions": ["stock:view"],
        }
        fulfillment_warehouse_codes_for_stores.return_value = {"WH-A"}

        response = self.client.get("/api/v1/inventory/balances/", {"warehouse": "WH-B"})

        self.assertEqual(response.status_code, 403, response.content)

    def test_inventory_advanced_stock_aggregates_states_by_item_warehouse_and_location(self):
        for stock_state, quantity in [
            (StockState.ON_HAND, "10"),
            (StockState.RESERVED, "2"),
            (StockState.PICKING, "1"),
            (StockState.PACKED, "3"),
            (StockState.IN_TRANSIT, "4"),
            (StockState.SCRAPPED, "0.5"),
        ]:
            InventoryBalance.objects.create(
                warehouse_ref="WH-A",
                item_ref="ITEM-1",
                lot_ref="LOC-01",
                stock_state=stock_state,
                uom="UN",
                quantity=Decimal(quantity),
            )
        InventoryBalance.objects.create(
            warehouse_ref="WH-A",
            item_ref="ITEM-1",
            lot_ref="LOC-01",
            stock_state=StockState.DELIVERED,
            uom="UN",
            quantity=Decimal("99"),
        )
        InventoryBalance.objects.create(
            warehouse_ref="WH-A",
            item_ref="ITEM-1",
            lot_ref="LOC-02",
            stock_state=StockState.ON_HAND,
            uom="UN",
            quantity=Decimal("7"),
        )

        results = self._results(
            "/api/v1/inventory/advanced-stock/",
            {"warehouse": "WH-A", "item": "ITEM-1", "location_ref": "LOC-01"},
        )

        self.assertEqual(len(results), 1)
        row = results[0]
        self.assertEqual(row["warehouse_ref"], "WH-A")
        self.assertEqual(row["item_ref"], "ITEM-1")
        self.assertEqual(row["lot_ref"], "LOC-01")
        self.assertEqual(row["location_ref"], "LOC-01")
        self.assertEqual(row["location_name"], "")
        self.assertEqual(row["quantities"]["available"], "10")
        self.assertEqual(row["quantities"]["reserved"], "2")
        self.assertEqual(row["quantities"]["in_preparation"], "1")
        self.assertEqual(row["quantities"]["prepared"], "3")
        self.assertEqual(row["quantities"]["in_transit"], "4")
        self.assertEqual(row["quantities"]["damaged_waste"], "0.5")
        self.assertEqual(row["quantities"]["total"], "20.5")
        self.assertEqual([state["label"] for state in row["state_quantities"]], [
            "Disponible",
            "Reservado",
            "En Preparacion",
            "Preparado",
            "En Transito",
            "Roto/Merma",
        ])

    def test_inventory_advanced_stock_enriches_items_and_filters_by_name(self):
        InventoryBalance.objects.create(
            warehouse_ref="WH-A",
            item_ref="ITEM-1",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("5"),
        )
        InventoryBalance.objects.create(
            warehouse_ref="WH-A",
            item_ref="ITEM-2",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("7"),
        )
        MaterialMasterSnapshot.objects.create(item_ref="ITEM-1", name="Porcelanato gris", category="CER")
        MaterialMasterSnapshot.objects.create(item_ref="ITEM-2", name="Bacha blanca", category="SAN")

        results = self._results("/api/v1/inventory/advanced-stock/", {"item": "porcelanato"})

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["item_ref"], "ITEM-1")
        self.assertEqual(results[0]["item_name"], "Porcelanato gris")
        self.assertEqual(results[0]["category_ref"], "CER")

    def test_inventory_advanced_stock_filters_by_category(self):
        InventoryBalance.objects.create(
            warehouse_ref="WH-A",
            item_ref="ITEM-1",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("5"),
        )
        InventoryBalance.objects.create(
            warehouse_ref="WH-A",
            item_ref="ITEM-2",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("7"),
        )
        MaterialMasterSnapshot.objects.create(item_ref="ITEM-1", name="Porcelanato gris", category="CER")
        MaterialMasterSnapshot.objects.create(item_ref="ITEM-2", name="Bacha blanca", category="SAN")

        results = self._results("/api/v1/inventory/advanced-stock/", {"category": "san"})

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["item_ref"], "ITEM-2")

    @patch("apps.inventory.api.fulfillment_warehouse_codes_for_stores")
    @patch("apps.inventory.api.employee_delivery_permissions")
    def test_inventory_advanced_stock_uses_fulfillment_group_scope(self, employee_delivery_permissions, fulfillment_warehouse_codes_for_stores):
        get_user_model().objects.create_user(username="operator@example.com")
        self.client.force_login(get_user_model().objects.get(username="operator@example.com"))
        employee_delivery_permissions.return_value = {
            "employee": {"store_codes": ["S001"], "branch_ref": "S001"},
            "authorized_warehouses": ["W-SHIPPING"],
            "permissions": ["stock:view"],
        }
        fulfillment_warehouse_codes_for_stores.return_value = {"WH-A", "WH-C"}
        for warehouse_ref in ["WH-A", "WH-B", "WH-C"]:
            InventoryBalance.objects.create(
                warehouse_ref=warehouse_ref,
                item_ref=f"ITEM-{warehouse_ref}",
                lot_ref="",
                stock_state=StockState.ON_HAND,
                uom="UN",
                quantity=Decimal("1"),
            )

        response = self.client.get("/api/v1/inventory/advanced-stock/")

        self.assertEqual(response.status_code, 200, response.content)
        payload = json.loads(response.content)
        self.assertEqual(payload["allowed_warehouses"], ["WH-A", "WH-C"])
        self.assertEqual({row["warehouse_ref"] for row in payload["results"]}, {"WH-A", "WH-C"})
        self.assertEqual({row["location_ref"] for row in payload["results"]}, {""})
        fulfillment_warehouse_codes_for_stores.assert_called_once_with({"S001"})

    @patch("apps.inventory.api.fulfillment_warehouse_codes_for_stores")
    @patch("apps.inventory.api.employee_delivery_permissions")
    def test_inventory_advanced_stock_rejects_warehouses_outside_stock_scope(self, employee_delivery_permissions, fulfillment_warehouse_codes_for_stores):
        get_user_model().objects.create_user(username="operator@example.com")
        self.client.force_login(get_user_model().objects.get(username="operator@example.com"))
        employee_delivery_permissions.return_value = {
            "employee": {"store_codes": ["S001"], "branch_ref": "S001"},
            "authorized_warehouses": ["W-SHIPPING"],
            "permissions": ["stock:view"],
        }
        fulfillment_warehouse_codes_for_stores.return_value = {"WH-A"}

        response = self.client.get("/api/v1/inventory/advanced-stock/", {"warehouse": "WH-B"})

        self.assertEqual(response.status_code, 403, response.content)

    def test_pos_freight_product_refs_reads_automatic_freight_params(self):
        from apps.logistics import parquet_master_data

        parquet_master_data.pos_freight_product_refs.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            master_dir = Path(tmp_dir)
            params_path = master_dir / "parametros_pos.parquet"
            params_path.write_text("", encoding="utf-8")
            rows = [
                {
                    "Estado": True,
                    "ParamName": "automatic_freight",
                    "Params": json.dumps(
                        {
                            "enabled": True,
                            "article_id": "13505c79-595e-4b89-8217-f8b97f4d2350",
                            "article_name": "FLETE",
                            "article_number": "350320",
                        }
                    ),
                }
            ]
            with (
                patch.object(parquet_master_data, "master_data_dir", return_value=master_dir),
                patch.object(parquet_master_data, "_read_rows", return_value=(params_path, rows)),
            ):
                refs = parquet_master_data.pos_freight_product_refs("PRO3DP")

        parquet_master_data.pos_freight_product_refs.cache_clear()
        self.assertIn("350320", refs)
        self.assertNotIn("FLETE", refs)
        self.assertNotIn("13505c79-595e-4b89-8217-f8b97f4d2350", refs)

    def test_inventory_ledger_filters_by_supported_fields(self):
        now = timezone.now()
        today = timezone.localdate(now).isoformat()
        self._create_ledger_entry(
            idempotency_key="ledger-match",
            movement_type=InventoryLedgerEntry.MovementType.TRANSFER_IN,
            direction=InventoryLedgerEntry.Direction.INCREASE,
            warehouse_ref="WH-B",
            item_ref="ITEM-2",
            stock_state=StockState.IN_TRANSIT,
            document_type="transfer",
            document_ref="TR-100",
            posted_at=now,
        )
        self._create_ledger_entry(
            idempotency_key="ledger-old",
            movement_type=InventoryLedgerEntry.MovementType.TRANSFER_IN,
            direction=InventoryLedgerEntry.Direction.INCREASE,
            warehouse_ref="WH-B",
            item_ref="ITEM-2",
            stock_state=StockState.IN_TRANSIT,
            document_type="transfer",
            document_ref="TR-OLD",
            posted_at=now - timedelta(days=5),
        )
        self._create_ledger_entry(
            idempotency_key="ledger-other",
            movement_type=InventoryLedgerEntry.MovementType.DISPATCH,
            direction=InventoryLedgerEntry.Direction.DECREASE,
            warehouse_ref="WH-C",
            item_ref="ITEM-3",
            stock_state=StockState.ON_HAND,
            document_type="delivery",
            document_ref="DEL-1",
            posted_at=now,
        )

        results = self._results(
            "/api/v1/inventory/ledger/",
            {
                "movement_type": InventoryLedgerEntry.MovementType.TRANSFER_IN,
                "direction": InventoryLedgerEntry.Direction.INCREASE,
                "warehouse": "WH-B",
                "item": "ITEM-2",
                "stock_state": StockState.IN_TRANSIT,
                "document_type": "transfer",
                "document_ref": "TR-100",
                "date_from": today,
                "date_to": today,
            },
        )

        self.assertEqual([row["document_ref"] for row in results], ["TR-100"])

    def test_inventory_ledger_supports_reference_and_state_aliases(self):
        now = timezone.now()
        self._create_ledger_entry(
            idempotency_key="ledger-alias",
            movement_type=InventoryLedgerEntry.MovementType.INBOUND_RECEIPT,
            direction=InventoryLedgerEntry.Direction.INCREASE,
            warehouse_ref="WH-A",
            item_ref="ITEM-1",
            stock_state=StockState.ON_HAND,
            document_type="purchase_receipt",
            document_ref="RCPT-1",
            posted_at=now,
        )
        self._create_ledger_entry(
            idempotency_key="ledger-alias-other",
            movement_type=InventoryLedgerEntry.MovementType.INBOUND_RECEIPT,
            direction=InventoryLedgerEntry.Direction.INCREASE,
            warehouse_ref="WH-A",
            item_ref="ITEM-1",
            stock_state=StockState.RESERVED,
            document_type="purchase_receipt",
            document_ref="RCPT-2",
            posted_at=now,
        )

        results = self._results(
            "/api/v1/inventory/ledger/",
            {
                "state": StockState.ON_HAND,
                "reference_type": "purchase_receipt",
                "reference_id": "RCPT-1",
            },
        )

        self.assertEqual([row["document_ref"] for row in results], ["RCPT-1"])

    def test_inventory_receipts_filter_by_purchase_order_warehouse_status_and_item(self):
        receipt = PurchaseOrderReceipt.objects.create(
            purchase_order_ref="PO-100",
            supplier_ref="SUP-1",
            status=PurchaseOrderReceipt.ReceiptStatus.RECEIVED,
            warehouse_ref="WH-A",
        )
        PurchaseOrderReceiptLine.objects.create(
            receipt=receipt,
            expected_qty=Decimal("2"),
            received_qty=Decimal("2"),
            uom="UN",
            item_ref="ITEM-1",
            warehouse_ref="WH-A",
        )
        other_receipt = PurchaseOrderReceipt.objects.create(
            purchase_order_ref="PO-200",
            supplier_ref="SUP-2",
            status=PurchaseOrderReceipt.ReceiptStatus.EXPECTED,
            warehouse_ref="WH-B",
        )
        PurchaseOrderReceiptLine.objects.create(
            receipt=other_receipt,
            expected_qty=Decimal("4"),
            uom="UN",
            item_ref="ITEM-2",
            warehouse_ref="WH-B",
        )

        results = self._results(
            "/api/v1/inventory/receipts/",
            {
                "purchase_order_ref": "PO-100",
                "warehouse": "WH-A",
                "status": PurchaseOrderReceipt.ReceiptStatus.RECEIVED,
                "item": "ITEM-1",
            },
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["purchase_order_ref"], "PO-100")
        self.assertEqual(results[0]["status"], PurchaseOrderReceipt.ReceiptStatus.RECEIVED)
        self.assertEqual(results[0]["warehouse_ref"], "WH-A")

    def test_transfers_filter_by_origin_destination_status_and_number(self):
        TransferOrder.objects.create(
            transfer_number="TR-100",
            origin_warehouse_ref="WH-A",
            destination_warehouse_ref="WH-B",
            status=TransferOrder.TransferStatus.IN_TRANSIT,
            requested_by="tester",
        )
        TransferOrder.objects.create(
            transfer_number="TR-200",
            origin_warehouse_ref="WH-A",
            destination_warehouse_ref="WH-C",
            status=TransferOrder.TransferStatus.REQUESTED,
            requested_by="tester",
        )

        results = self._results(
            "/api/v1/transfers/",
            {
                "origin_warehouse": "WH-A",
                "destination_warehouse": "WH-B",
                "status": TransferOrder.TransferStatus.IN_TRANSIT,
                "transfer_number": "TR-100",
            },
        )

        self.assertEqual([row["transfer_number"] for row in results], ["TR-100"])

    def test_shipping_filter_returned_shipments_by_status_and_event_type(self):
        returned = Shipment.objects.create(
            shipment_number="SHIP-100",
            status=Shipment.ShipmentStatus.RETURNED,
            delivery_ref="DEL-100",
        )
        ShipmentEvent.objects.create(
            shipment=returned,
            event_type="shipping.returned",
            status=Shipment.ShipmentStatus.RETURNED,
        )
        attempted = Shipment.objects.create(
            shipment_number="SHIP-200",
            status=Shipment.ShipmentStatus.RETURNED,
            delivery_ref="DEL-200",
        )
        ShipmentEvent.objects.create(
            shipment=attempted,
            event_type="shipping.attempted",
            status=Shipment.ShipmentStatus.ATTEMPTED,
        )
        delivered = Shipment.objects.create(
            shipment_number="SHIP-300",
            status=Shipment.ShipmentStatus.DELIVERED,
            delivery_ref="DEL-300",
        )
        ShipmentEvent.objects.create(
            shipment=delivered,
            event_type="shipping.returned",
            status=Shipment.ShipmentStatus.RETURNED,
        )

        results = self._results(
            "/api/v1/shipping/",
            {
                "status": Shipment.ShipmentStatus.RETURNED,
                "event_type": "shipping.returned",
            },
        )

        self.assertEqual([row["shipment_number"] for row in results], ["SHIP-100"])

    def test_delivery_orders_filter_by_reparto_delivery_mode(self):
        fulfillment = FulfillmentOrder.objects.create(
            fulfillment_number="FUL-100",
            customer_ref="CUST-1",
            delivery_mode="Repart Prg",
            warehouse_ref="WH-A",
        )
        DeliveryOrder.objects.create(
            delivery_number="DEL-100",
            fulfillment=fulfillment,
            status=DeliveryOrder.DeliveryStatus.PREPARED,
            delivery_mode="Repart Prg",
            warehouse_ref="WH-A",
            planned_date=date(2026, 4, 24),
        )
        DeliveryOrder.objects.create(
            delivery_number="DEL-200",
            fulfillment=fulfillment,
            status=DeliveryOrder.DeliveryStatus.PREPARED,
            delivery_mode="Retiro en tienda",
            warehouse_ref="WH-A",
            planned_date=date(2026, 4, 24),
        )
        DeliveryOrder.objects.create(
            delivery_number="DEL-300",
            fulfillment=fulfillment,
            status=DeliveryOrder.DeliveryStatus.PREPARED,
            delivery_mode="Repart Prg",
            warehouse_ref="WH-A",
            planned_date=date(2026, 4, 25),
        )

        results = self._results(
            "/api/v1/fulfillment/deliveries/",
            {"delivery_mode": "Reparto", "planned_date": "2026-04-24"},
        )

        self.assertEqual([row["delivery_number"] for row in results], ["DEL-100"])
        self.assertEqual(results[0]["sales_order_number"], "")
        self.assertEqual(results[0]["customer_ref"], "CUST-1")

    @patch("apps.fulfillment.api.employee_delivery_permissions")
    def test_reparto_confirmation_queue_includes_uncreated_fulfillment_orders(self, employee_delivery_permissions):
        employee_delivery_permissions.return_value = {"authorized_warehouses": ["WH-A"]}
        planned_date = timezone.localdate()
        fulfillment = FulfillmentOrder.objects.create(
            fulfillment_number="FUL-101",
            customer_ref="CUST-1",
            delivery_mode="Repart Prg",
            warehouse_ref="WH-A",
            requested_date=planned_date,
            legacy_sales_order_number="VENT8-101",
            address_snapshot={
                "address_id": "ADDR-1",
                "street": "Uruguay",
                "street_number": "3947",
                "city": "Posadas",
            },
        )
        fulfillment.lines.create(
            ordered_qty=Decimal("2"),
            uom="UN",
            item_ref="ITEM-1",
            warehouse_ref="WH-A",
            legacy_sales_order_number="VENT8-101",
            legacy_line_id="10",
        )

        results = self._results(
            "/api/v1/fulfillment/reparto-confirmation/",
            {"planned_date": planned_date.isoformat()},
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source_type"], "fulfillment")
        self.assertEqual(results[0]["sales_order_number"], "VENT8-101")
        self.assertEqual(results[0]["delivery_number"], "sin entrega")
        self.assertEqual(results[0]["address_snapshot"]["address_id"], "ADDR-1")
        self.assertEqual(results[0]["address_snapshot"]["street"], "Uruguay")
        self.assertEqual(results[0]["lines"][0]["split_qty"], "2.000000")

    @patch("apps.fulfillment.api.employee_delivery_permissions")
    def test_reparto_confirmation_queue_filters_authorized_warehouse(self, employee_delivery_permissions):
        employee_delivery_permissions.return_value = {"authorized_warehouses": ["WH-A"]}
        planned_date = timezone.localdate()
        for warehouse_ref in ["WH-A", "WH-B"]:
            fulfillment = FulfillmentOrder.objects.create(
                fulfillment_number=f"FUL-{warehouse_ref}",
                customer_ref="CUST-1",
                delivery_mode="Repart Prg",
                warehouse_ref=warehouse_ref,
                requested_date=planned_date,
                legacy_sales_order_number=f"VENT8-{warehouse_ref}",
            )
            fulfillment.lines.create(
                ordered_qty=Decimal("1"),
                uom="UN",
                item_ref=f"ITEM-{warehouse_ref}",
                warehouse_ref=warehouse_ref,
                legacy_sales_order_number=f"VENT8-{warehouse_ref}",
                legacy_line_id="10",
            )

        results = self._results(
            "/api/v1/fulfillment/reparto-confirmation/",
            {"planned_date": planned_date.isoformat()},
        )

        self.assertEqual([row["warehouse_ref"] for row in results], ["WH-A"])

    @patch("apps.fulfillment.api.employee_delivery_permissions")
    def test_reparto_confirmation_queue_rejects_unauthorized_warehouse_filter(self, employee_delivery_permissions):
        employee_delivery_permissions.return_value = {"authorized_warehouses": ["WH-A"]}
        planned_date = timezone.localdate()
        fulfillment = FulfillmentOrder.objects.create(
            fulfillment_number="FUL-WH-B",
            customer_ref="CUST-1",
            delivery_mode="Repart Prg",
            warehouse_ref="WH-B",
            requested_date=planned_date,
            legacy_sales_order_number="VENT8-WH-B",
        )
        fulfillment.lines.create(
            ordered_qty=Decimal("1"),
            uom="UN",
            item_ref="ITEM-WH-B",
            warehouse_ref="WH-B",
            legacy_sales_order_number="VENT8-WH-B",
            legacy_line_id="10",
        )

        results = self._results(
            "/api/v1/fulfillment/reparto-confirmation/",
            {"planned_date": planned_date.isoformat(), "warehouse_ref": "WH-B"},
        )

        self.assertEqual(results, [])

    @patch("apps.fulfillment.api.employee_delivery_permissions")
    def test_reparto_confirmation_queue_does_not_return_past_deliveries(self, employee_delivery_permissions):
        employee_delivery_permissions.return_value = {"authorized_warehouses": ["WH-A"]}
        past_date = timezone.localdate() - timedelta(days=1)
        fulfillment = FulfillmentOrder.objects.create(
            fulfillment_number="FUL-PAST",
            customer_ref="CUST-1",
            delivery_mode="Repart Prg",
            warehouse_ref="WH-A",
            requested_date=past_date,
            legacy_sales_order_number="VENT8-PAST",
        )
        fulfillment.lines.create(
            ordered_qty=Decimal("1"),
            uom="UN",
            item_ref="ITEM-PAST",
            warehouse_ref="WH-A",
            legacy_sales_order_number="VENT8-PAST",
            legacy_line_id="10",
        )

        results = self._results(
            "/api/v1/fulfillment/reparto-confirmation/",
            {"planned_date": past_date.isoformat()},
        )

        self.assertEqual(results, [])

    @patch("apps.fulfillment.api.employee_delivery_permissions")
    def test_reparto_stock_check_rejects_past_delivery_date(self, employee_delivery_permissions):
        employee_delivery_permissions.return_value = {"authorized_warehouses": ["WH-A"]}
        fulfillment = FulfillmentOrder.objects.create(
            fulfillment_number="FUL-PAST-CMD",
            customer_ref="CUST-1",
            delivery_mode="Repart Prg",
            warehouse_ref="WH-A",
            legacy_sales_order_number="VENT8-PAST-CMD",
        )
        delivery = DeliveryOrder.objects.create(
            delivery_number="DEL-PAST-CMD",
            fulfillment=fulfillment,
            status=DeliveryOrder.DeliveryStatus.CREATED,
            delivery_mode="Repart Prg",
            warehouse_ref="WH-A",
            planned_date=timezone.localdate() - timedelta(days=1),
        )

        response = self.client.post(f"/api/v1/fulfillment/deliveries/{delivery.id}/stock-check")

        self.assertEqual(response.status_code, 422)

    @patch("apps.fulfillment.api.employee_delivery_permissions")
    def test_expedition_queue_is_not_filtered_by_authorized_warehouse(self, employee_delivery_permissions):
        employee_delivery_permissions.return_value = {"authorized_warehouses": ["WH-A"]}
        fulfillment = FulfillmentOrder.objects.create(
            fulfillment_number="FUL-ENTREGA",
            customer_ref="CUST-1",
            delivery_mode="Repart Prg",
            warehouse_ref="WH-B",
            requested_date=date(2026, 4, 24),
            legacy_sales_order_number="VENT8-ENTREGA",
        )
        fulfillment.lines.create(
            ordered_qty=Decimal("1"),
            uom="UN",
            item_ref="ITEM-WH-B",
            warehouse_ref="WH-B",
            legacy_sales_order_number="VENT8-ENTREGA",
            legacy_line_id="10",
        )

        with patch(
            "apps.fulfillment.services._resolve_customer_snapshots",
            return_value={"CUST-1": {"name": "Cliente 1", "document_number": "", "address": {}}},
        ):
            results = self._results(
                "/api/v1/fulfillment/expedition-queue/",
                {"sales_order_number": "VENT8-ENTREGA"},
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["warehouse_ref"], "WH-B")

    @patch("apps.fulfillment.api.employee_delivery_permissions")
    def test_preparation_tasks_filter_authorized_warehouse_not_date(self, employee_delivery_permissions):
        employee_delivery_permissions.return_value = {"authorized_warehouses": ["WH-A"]}
        now = timezone.now()
        fulfillment_a = FulfillmentOrder.objects.create(
            fulfillment_number="FUL-TASK-A",
            customer_ref="CUST-1",
            delivery_mode="Repart Prg",
            warehouse_ref="WH-A",
            legacy_sales_order_number="VENT8-TASK-A",
        )
        delivery_today = DeliveryOrder.objects.create(
            delivery_number="DEL-TASK-TODAY",
            fulfillment=fulfillment_a,
            status=DeliveryOrder.DeliveryStatus.PREPARING,
            delivery_mode="Repart Prg",
            warehouse_ref="WH-A",
            planned_date=timezone.localdate(),
        )
        delivery_later = DeliveryOrder.objects.create(
            delivery_number="DEL-TASK-LATER",
            fulfillment=fulfillment_a,
            status=DeliveryOrder.DeliveryStatus.PREPARING,
            delivery_mode="Repart Prg",
            warehouse_ref="WH-A",
            planned_date=timezone.localdate() + timedelta(days=1),
        )
        fulfillment_b = FulfillmentOrder.objects.create(
            fulfillment_number="FUL-TASK-B",
            customer_ref="CUST-1",
            delivery_mode="Repart Prg",
            warehouse_ref="WH-B",
            legacy_sales_order_number="VENT8-TASK-B",
        )
        delivery_other_warehouse = DeliveryOrder.objects.create(
            delivery_number="DEL-TASK-WH-B",
            fulfillment=fulfillment_b,
            status=DeliveryOrder.DeliveryStatus.PREPARING,
            delivery_mode="Repart Prg",
            warehouse_ref="WH-B",
            planned_date=timezone.localdate(),
        )
        DeliveryPreparationTask.objects.create(
            delivery=delivery_today,
            status=DeliveryPreparationTask.TaskStatus.ASSIGNED,
            assigned_to="prep",
            assigned_at=now,
            warehouse_ref="WH-A",
        )
        DeliveryPreparationTask.objects.create(
            delivery=delivery_later,
            status=DeliveryPreparationTask.TaskStatus.ASSIGNED,
            assigned_to="prep",
            assigned_at=now - timedelta(minutes=1),
            warehouse_ref="WH-A",
        )
        DeliveryPreparationTask.objects.create(
            delivery=delivery_other_warehouse,
            status=DeliveryPreparationTask.TaskStatus.ASSIGNED,
            assigned_to="prep",
            assigned_at=now - timedelta(minutes=2),
            warehouse_ref="WH-B",
        )

        results = self._results(
            "/api/v1/fulfillment/preparation-tasks/",
            {"status": "all", "planned_date": timezone.localdate().isoformat()},
        )

        self.assertEqual({row["delivery"]["delivery_number"] for row in results}, {"DEL-TASK-TODAY", "DEL-TASK-LATER"})
        self.assertEqual({row["warehouse_ref"] for row in results}, {"WH-A"})

    @patch("apps.routes.api.employee_delivery_permissions")
    def test_route_sheets_filter_authorized_warehouse(self, employee_delivery_permissions):
        employee_delivery_permissions.return_value = {"authorized_warehouses": ["WH-A"]}
        RouteSheet.objects.create(route_number="R-WH-A", branch_ref="BR-1", warehouse_ref="WH-A", planned_date=date(2026, 4, 24))
        RouteSheet.objects.create(route_number="R-WH-B", branch_ref="BR-1", warehouse_ref="WH-B", planned_date=date(2026, 4, 24))

        results = self._results("/api/v1/routesheets/")

        self.assertEqual([row["route_number"] for row in results], ["R-WH-A"])

    @patch("apps.routes.api.employee_delivery_permissions")
    def test_route_sheet_detail_rejects_unauthorized_warehouse(self, employee_delivery_permissions):
        employee_delivery_permissions.return_value = {"authorized_warehouses": ["WH-A"]}
        route = RouteSheet.objects.create(
            route_number="R-WH-B",
            branch_ref="BR-1",
            warehouse_ref="WH-B",
            planned_date=date(2026, 4, 24),
        )

        response = self.client.get(f"/api/v1/routesheets/{route.id}/")

        self.assertEqual(response.status_code, 403)
