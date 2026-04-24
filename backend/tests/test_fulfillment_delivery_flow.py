from decimal import Decimal

from django.test import TestCase

from apps.fulfillment.models import (
    DeliveryDocument,
    DeliveryOrder,
    DeliveryOrderLine,
    DeliveryPreparationTask,
    FulfillmentOrder,
    FulfillmentOrderLine,
)
from apps.fulfillment.services import (
    FulfillmentRuleError,
    issue_remito,
    mark_preparation_task_prepared,
    send_delivery_to_prepare,
    validate_delivery_stock,
)
from apps.inventory.models import InventoryBalance, InventoryReservation, StockState


class DeliveryPreparationFlowTests(TestCase):
    def setUp(self):
        self.fulfillment = FulfillmentOrder.objects.create(
            fulfillment_number="FUL-1",
            status=FulfillmentOrder.FulfillmentStatus.PENDING,
            customer_ref="CUST-1",
            delivery_mode="home",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-1",
        )
        self.fulfillment_line = FulfillmentOrderLine.objects.create(
            fulfillment=self.fulfillment,
            ordered_qty=Decimal("5"),
            uom="UN",
            item_ref="ITEM-1",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-1",
            legacy_line_id="10",
        )
        self.delivery = DeliveryOrder.objects.create(
            fulfillment=self.fulfillment,
            delivery_number="ENT-SO-1-1",
            status=DeliveryOrder.DeliveryStatus.CREATED,
            delivery_mode="home",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-1",
        )
        self.delivery_line = DeliveryOrderLine.objects.create(
            delivery=self.delivery,
            fulfillment_line=self.fulfillment_line,
            planned_qty=Decimal("3"),
            uom="UN",
            item_ref="ITEM-1",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-1",
            legacy_line_id="10",
        )
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            item_ref="ITEM-1",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("5"),
        )

    def test_confirm_delivery_reserves_inventory_by_line(self):
        validate_delivery_stock(
            delivery_id=str(self.delivery.id),
            idempotency_key="confirm-1",
            actor="tester",
            authorized_warehouses=["W001"],
        )

        self.delivery.refresh_from_db()
        self.fulfillment_line.refresh_from_db()
        reservation = InventoryReservation.objects.get(source_type="delivery_order", source_ref=str(self.delivery.id))
        packed = InventoryBalance.objects.get(warehouse_ref="W001", item_ref="ITEM-1", stock_state=StockState.PACKED)
        reserved = InventoryBalance.objects.get(warehouse_ref="W001", item_ref="ITEM-1", stock_state=StockState.RESERVED)

        self.assertEqual(self.delivery.status, DeliveryOrder.DeliveryStatus.CONFIRMED)
        self.assertEqual(self.fulfillment_line.reserved_qty, Decimal("3"))
        self.assertEqual(reservation.lines.get().reserved_qty, Decimal("3"))
        self.assertEqual(packed.quantity, Decimal("2"))
        self.assertEqual(reserved.quantity, Decimal("3"))

    def test_preparation_task_flow_marks_delivery_prepared_and_allows_remito(self):
        validate_delivery_stock(
            delivery_id=str(self.delivery.id),
            idempotency_key="confirm-2",
            actor="tester",
            authorized_warehouses=["W001"],
        )
        with self.assertRaises(FulfillmentRuleError):
            issue_remito(
                delivery_id=str(self.delivery.id),
                idempotency_key="remito-before-prepared",
                actor="tester",
                authorized_warehouses=["W001"],
            )

        send_delivery_to_prepare(
            delivery_id=str(self.delivery.id),
            idempotency_key="prepare-1",
            actor="tester",
            assigned_employee_ref="EMP-1",
            authorized_warehouses=["W001"],
        )
        task = DeliveryPreparationTask.objects.get(delivery=self.delivery)
        self.delivery.refresh_from_db()
        self.assertEqual(task.assigned_to, "EMP-1")
        self.assertEqual(self.delivery.status, DeliveryOrder.DeliveryStatus.PREPARING)

        mark_preparation_task_prepared(
            task_id=str(task.id),
            idempotency_key="prepared-1",
            actor="EMP-1",
            authorized_warehouses=["W001"],
        )
        self.delivery.refresh_from_db()
        self.fulfillment_line.refresh_from_db()
        task.refresh_from_db()
        reserved = InventoryBalance.objects.get(warehouse_ref="W001", item_ref="ITEM-1", stock_state=StockState.RESERVED)
        packed = InventoryBalance.objects.get(warehouse_ref="W001", item_ref="ITEM-1", stock_state=StockState.PACKED)

        self.assertEqual(task.status, DeliveryPreparationTask.TaskStatus.PREPARED)
        self.assertEqual(self.delivery.status, DeliveryOrder.DeliveryStatus.PREPARED)
        self.assertEqual(self.fulfillment_line.prepared_qty, Decimal("3"))
        self.assertEqual(reserved.quantity, Decimal("0"))
        self.assertEqual(packed.quantity, Decimal("5"))

        result = issue_remito(
            delivery_id=str(self.delivery.id),
            idempotency_key="remito-after-prepared",
            actor="tester",
            authorized_warehouses=["W001"],
        )
        document = DeliveryDocument.objects.get(id=result.payload["result"]["id"])
        self.assertEqual(document.lines.get().quantity, Decimal("3"))

    def test_only_assigned_employee_can_mark_prepared(self):
        validate_delivery_stock(
            delivery_id=str(self.delivery.id),
            idempotency_key="confirm-3",
            actor="tester",
            authorized_warehouses=["W001"],
        )
        send_delivery_to_prepare(
            delivery_id=str(self.delivery.id),
            idempotency_key="prepare-2",
            actor="tester",
            assigned_employee_ref="EMP-1",
            authorized_warehouses=["W001"],
        )
        task = DeliveryPreparationTask.objects.get(delivery=self.delivery)

        with self.assertRaises(PermissionError):
            mark_preparation_task_prepared(
                task_id=str(task.id),
                idempotency_key="prepared-forbidden",
                actor="EMP-2",
                authorized_warehouses=["W001"],
            )
