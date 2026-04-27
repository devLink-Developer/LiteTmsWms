from __future__ import annotations

import json
from datetime import date
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.fulfillment.models import DeliveryOrder, FulfillmentOrder
from apps.inventory.models import (
    InventoryBalance,
    InventoryLedgerEntry,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptLine,
    StockState,
)
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

    def test_reparto_confirmation_queue_includes_uncreated_fulfillment_orders(self):
        fulfillment = FulfillmentOrder.objects.create(
            fulfillment_number="FUL-101",
            customer_ref="CUST-1",
            delivery_mode="Repart Prg",
            warehouse_ref="WH-A",
            requested_date=date(2026, 4, 24),
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
            {"planned_date": "2026-04-24"},
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source_type"], "fulfillment")
        self.assertEqual(results[0]["sales_order_number"], "VENT8-101")
        self.assertEqual(results[0]["delivery_number"], "sin entrega")
        self.assertEqual(results[0]["address_snapshot"]["address_id"], "ADDR-1")
        self.assertEqual(results[0]["address_snapshot"]["street"], "Uruguay")
        self.assertEqual(results[0]["lines"][0]["split_qty"], "2.000000")
