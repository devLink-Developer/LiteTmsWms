from decimal import Decimal

from django.test import TestCase

from apps.inventory.models import InventoryBalance, InventoryLedgerEntry, StockState
from apps.inventory.services import InventoryRuleError, LedgerCommand, post_ledger_entry


class InventoryLedgerServiceTests(TestCase):
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
