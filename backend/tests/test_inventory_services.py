from decimal import Decimal

from django.test import TestCase

from apps.inventory.models import InventoryBalance, InventoryLedgerEntry, PurchaseOrderReceipt, StockState
from apps.inventory.services import (
    InventoryRuleError,
    LedgerCommand,
    adjust_inventory_manually,
    available_stock_quantities_for_keys,
    execute_inventory_exchange,
    move_inventory_between_locations,
    post_ledger_entry,
    receive_purchase_order,
)
from apps.logistics.models import WarehouseLocation
from apps.logistics.services import generate_default_locations


class InventoryLedgerServiceTests(TestCase):
    def test_available_stock_quantities_matches_case_insensitive_uom(self):
        generate_default_locations(warehouse_ref="W001", actor="tester")
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("5"),
        )

        quantities = available_stock_quantities_for_keys({("W001", "ITEM-1", "un")}, stock_state=StockState.PACKED)

        self.assertEqual(quantities[("W001", "ITEM-1", "un")], Decimal("5"))

    def test_post_ledger_entry_updates_balance(self):
        entry = post_ledger_entry(
            LedgerCommand(
                idempotency_key="test-inbound-1",
                movement_type=InventoryLedgerEntry.MovementType.INBOUND_RECEIPT,
                direction=InventoryLedgerEntry.Direction.INCREASE,
                warehouse_ref="W001",
                item_ref="ITEM-1",
                stock_state=StockState.ON_HAND,
                quantity=Decimal("10"),
                uom="UN",
                document_type="purchase_receipt",
                document_ref="R-1",
                actor="tester",
            )
        )

        balance = InventoryBalance.objects.get(warehouse_ref="W001", item_ref="ITEM-1")
        self.assertEqual(entry.quantity, Decimal("10"))
        self.assertEqual(balance.quantity, Decimal("10"))

    def test_negative_balance_is_rejected(self):
        with self.assertRaises(InventoryRuleError):
            post_ledger_entry(
                LedgerCommand(
                    idempotency_key="test-dispatch-1",
                    movement_type=InventoryLedgerEntry.MovementType.DISPATCH,
                    direction=InventoryLedgerEntry.Direction.DECREASE,
                    warehouse_ref="W001",
                    item_ref="ITEM-1",
                    stock_state=StockState.ON_HAND,
                    quantity=Decimal("1"),
                    uom="UN",
                    document_type="delivery",
                    document_ref="D-1",
                    actor="tester",
                )
            )

    def test_idempotent_ledger_command_does_not_duplicate_effect(self):
        command = LedgerCommand(
            idempotency_key="test-idempotent-1",
            movement_type=InventoryLedgerEntry.MovementType.INBOUND_RECEIPT,
            direction=InventoryLedgerEntry.Direction.INCREASE,
            warehouse_ref="W001",
            item_ref="ITEM-1",
            stock_state=StockState.ON_HAND,
            quantity=Decimal("5"),
            uom="UN",
            document_type="purchase_receipt",
            document_ref="R-2",
            actor="tester",
        )
        first = post_ledger_entry(command)
        second = post_ledger_entry(command)

        balance = InventoryBalance.objects.get(warehouse_ref="W001", item_ref="ITEM-1")
        self.assertEqual(first.id, second.id)
        self.assertEqual(balance.quantity, Decimal("5"))


class InventoryTransactionCommandTests(TestCase):
    def test_manual_adjustment_increase_posts_packed_stock(self):
        generate_default_locations(warehouse_ref="W001", actor="tester")

        result = adjust_inventory_manually(
            payload={
                "warehouse_ref": "W001",
                "direction": "increase",
                "item_ref": "ITEM-MAN",
                "location_ref": "W001-DSP-GEN",
                "quantity": "7",
                "uom": "un",
                "reason": "Alta manual inicial",
            },
            idempotency_key="manual-increase-1",
            actor="operator",
        )

        balance = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="ITEM-MAN",
            stock_state=StockState.PACKED,
            uom="UN",
        )
        ledger = InventoryLedgerEntry.objects.get(document_ref=result.payload["result"]["document_ref"])
        self.assertEqual(balance.quantity, Decimal("7.000000"))
        self.assertEqual(ledger.movement_type, InventoryLedgerEntry.MovementType.ADJUSTMENT)
        self.assertEqual(ledger.direction, InventoryLedgerEntry.Direction.INCREASE)
        self.assertEqual(ledger.document_type, "inventory_manual_adjustment")

    def test_manual_adjustment_increase_rejects_transactional_location(self):
        generate_default_locations(warehouse_ref="W001", actor="tester")

        with self.assertRaisesRegex(InventoryRuleError, "ubicaciones disponibles"):
            adjust_inventory_manually(
                payload={
                    "warehouse_ref": "W001",
                    "direction": "increase",
                    "item_ref": "ITEM-MAN",
                    "location_ref": "W001-PRE-GEN",
                    "quantity": "7",
                    "uom": "UN",
                    "reason": "Alta manual en preparacion",
                },
                idempotency_key="manual-increase-transactional",
                actor="operator",
            )

    def test_manual_adjustment_decrease_uses_origin_location_stock(self):
        generate_default_locations(warehouse_ref="W001", actor="tester")
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="ITEM-MAN",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("7"),
        )

        adjust_inventory_manually(
            payload={
                "warehouse_ref": "W001",
                "direction": "decrease",
                "item_ref": "ITEM-MAN",
                "location_ref": "W001-DSP-GEN",
                "quantity": "3",
                "uom": "UN",
                "reason": "Baja manual por correccion",
            },
            idempotency_key="manual-decrease-1",
            actor="operator",
        )

        balance = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="ITEM-MAN",
            stock_state=StockState.PACKED,
            uom="UN",
        )
        ledger = InventoryLedgerEntry.objects.get(document_type="inventory_manual_adjustment")
        self.assertEqual(balance.quantity, Decimal("4.000000"))
        self.assertEqual(ledger.direction, InventoryLedgerEntry.Direction.DECREASE)

    def test_manual_adjustment_decrease_rejects_missing_origin_stock(self):
        generate_default_locations(warehouse_ref="W001", actor="tester")

        with self.assertRaises(InventoryRuleError):
            adjust_inventory_manually(
                payload={
                    "warehouse_ref": "W001",
                    "direction": "decrease",
                    "item_ref": "ITEM-MAN",
                    "location_ref": "W001-DSP-GEN",
                    "quantity": "1",
                    "uom": "UN",
                    "reason": "Baja manual sin stock",
                },
                idempotency_key="manual-decrease-missing",
                actor="operator",
            )

    def test_purchase_order_receipt_posts_packed_stock_and_is_idempotent(self):
        payload = {
            "warehouse_ref": "W001",
            "purchase_order_ref": "OC-100",
            "supplier_ref": "SUP-1",
            "lines": [{"item_ref": "ITEM-OC", "received_qty": "6", "expected_qty": "6", "uom": "UN"}],
        }

        first = receive_purchase_order(payload=payload, idempotency_key="receipt-oc-1", actor="receiver")
        second = receive_purchase_order(payload=payload, idempotency_key="receipt-oc-1", actor="receiver")

        receipt = PurchaseOrderReceipt.objects.get(id=first.payload["result"]["id"])
        balance = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="ITEM-OC",
            stock_state=StockState.PACKED,
        )
        ledger = InventoryLedgerEntry.objects.get(document_type="purchase_order_receipt", document_ref=str(receipt.id))
        self.assertEqual(first.payload, second.payload)
        self.assertEqual(receipt.status, PurchaseOrderReceipt.ReceiptStatus.RECEIVED)
        self.assertEqual(balance.quantity, Decimal("6.000000"))
        self.assertEqual(ledger.movement_type, InventoryLedgerEntry.MovementType.INBOUND_RECEIPT)
        self.assertEqual(ledger.location_ref, "W001-DSP-GEN")
        self.assertEqual(InventoryLedgerEntry.objects.filter(document_type="purchase_order_receipt").count(), 1)

    def test_purchase_order_receipt_rejects_invalid_quantity(self):
        with self.assertRaises(InventoryRuleError):
            receive_purchase_order(
                payload={
                    "warehouse_ref": "W001",
                    "purchase_order_ref": "OC-101",
                    "lines": [{"item_ref": "ITEM-OC", "received_qty": "0", "uom": "UN"}],
                },
                idempotency_key="receipt-invalid",
                actor="receiver",
            )

    def test_exchange_converts_one_25kg_bag_into_twenty_five_1kg_items(self):
        generate_default_locations(warehouse_ref="W001", actor="tester")
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="CEM-25KG",
            lot_ref="LOTE-1",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("1"),
        )

        result = execute_inventory_exchange(
            payload={
                "warehouse_ref": "W001",
                "reason": "Canje bolsa 25kg a saldo",
                "input": {
                    "item_ref": "CEM-25KG",
                    "quantity": "1",
                    "uom": "UN",
                    "location_ref": "W001-DSP-GEN",
                    "lot_ref": "LOTE-1",
                },
                "outputs": [
                    {
                        "item_ref": "CEM-1KG",
                        "quantity": "25",
                        "uom": "UN",
                        "input_conversion_factor": "0.04",
                        "location_ref": "W001-DSP-GEN",
                    }
                ],
            },
            idempotency_key="exchange-cement-1",
            actor="operator",
        )

        source = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            lot_ref="LOTE-1",
            item_ref="CEM-25KG",
            stock_state=StockState.PACKED,
        )
        output = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="CEM-1KG",
            stock_state=StockState.PACKED,
        )
        ledger = InventoryLedgerEntry.objects.filter(document_type="inventory_exchange", document_ref=result.payload["result"]["id"])
        self.assertEqual(source.quantity, Decimal("0.000000"))
        self.assertEqual(output.quantity, Decimal("25.000000"))
        self.assertEqual(ledger.count(), 2)
        self.assertEqual({row.direction for row in ledger}, {InventoryLedgerEntry.Direction.INCREASE, InventoryLedgerEntry.Direction.DECREASE})

    def test_exchange_rejects_non_conserved_factor(self):
        generate_default_locations(warehouse_ref="W001", actor="tester")
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="CEM-25KG",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("1"),
        )

        with self.assertRaises(InventoryRuleError):
            execute_inventory_exchange(
                payload={
                    "warehouse_ref": "W001",
                    "input": {"item_ref": "CEM-25KG", "quantity": "1", "uom": "UN", "location_ref": "W001-DSP-GEN"},
                    "outputs": [{"item_ref": "CEM-1KG", "quantity": "24", "uom": "UN", "input_conversion_factor": "0.04"}],
                },
                idempotency_key="exchange-invalid",
                actor="operator",
            )
        self.assertFalse(InventoryLedgerEntry.objects.filter(document_type="inventory_exchange").exists())

    def test_location_move_conserves_total_between_positions_and_is_idempotent(self):
        for ref in ["W001-DSP-A", "W001-DSP-B"]:
            WarehouseLocation.objects.create(
                warehouse_ref="W001",
                location_ref=ref,
                name=ref,
                location_type="rack",
                purpose="available",
                is_dispatchable=True,
                is_pickable=True,
                active=True,
            )
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-A",
            item_ref="ITEM-MOVE",
            lot_ref="L1",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("10"),
        )
        payload = {
            "warehouse_ref": "W001",
            "source_location_ref": "W001-DSP-A",
            "target_location_ref": "W001-DSP-B",
            "item_ref": "ITEM-MOVE",
            "lot_ref": "L1",
            "quantity": "4",
            "uom": "UN",
            "reason": "Reubicacion interna",
        }

        first = move_inventory_between_locations(payload=payload, idempotency_key="move-1", actor="operator")
        second = move_inventory_between_locations(payload=payload, idempotency_key="move-1", actor="operator")

        source = InventoryBalance.objects.get(warehouse_ref="W001", location_ref="W001-DSP-A", item_ref="ITEM-MOVE", lot_ref="L1")
        target = InventoryBalance.objects.get(warehouse_ref="W001", location_ref="W001-DSP-B", item_ref="ITEM-MOVE", lot_ref="L1")
        self.assertEqual(first.payload, second.payload)
        self.assertEqual(source.quantity, Decimal("6.000000"))
        self.assertEqual(target.quantity, Decimal("4.000000"))
        self.assertEqual(InventoryLedgerEntry.objects.filter(document_type="inventory_location_move").count(), 2)
