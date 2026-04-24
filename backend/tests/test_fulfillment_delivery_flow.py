from decimal import Decimal
from uuid import uuid4

from django.db import connection
from django.test import TestCase
from django.utils import timezone

from apps.core.sequences import SequenceConfigError, allocate_sequence_number
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
    split_fulfillment_delivery,
    validate_delivery_stock,
)
from apps.inventory.models import InventoryBalance, InventoryReservation, StockState


def _sequence_table_ref() -> str:
    if connection.vendor == "postgresql":
        return "public.maestros_pagos_sequenceconfig"
    return "maestros_pagos_sequenceconfig"


def _ensure_sequence_table() -> None:
    table_ref = _sequence_table_ref()
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_ref} (
                    "RecId" uuid PRIMARY KEY,
                    "Estado" boolean NOT NULL,
                    "CreadoEn" timestamp with time zone NOT NULL,
                    "CreadoPor" varchar NOT NULL,
                    "ModificadoEn" timestamp with time zone NOT NULL,
                    "ModificadoPor" varchar NOT NULL,
                    "Module" varchar NOT NULL,
                    "Prefix" varchar NOT NULL,
                    "Suffix" varchar NOT NULL,
                    "PaddingLength" integer NOT NULL,
                    "CurrentNumber" integer NOT NULL,
                    "Increment" integer NOT NULL,
                    "Active" boolean NOT NULL,
                    "Name" varchar NOT NULL
                )
                """
            )
        else:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_ref} (
                    "RecId" text PRIMARY KEY,
                    "Estado" integer NOT NULL,
                    "CreadoEn" text NOT NULL,
                    "CreadoPor" text NOT NULL,
                    "ModificadoEn" text NOT NULL,
                    "ModificadoPor" text NOT NULL,
                    "Module" text NOT NULL,
                    "Prefix" text NOT NULL,
                    "Suffix" text NOT NULL,
                    "PaddingLength" integer NOT NULL,
                    "CurrentNumber" integer NOT NULL,
                    "Increment" integer NOT NULL,
                    "Active" integer NOT NULL,
                    "Name" text NOT NULL
                )
                """
            )


def _reset_sequence(name: str, *, prefix: str, current_number: int = 0) -> None:
    _ensure_sequence_table()
    now = timezone.now()
    with connection.cursor() as cursor:
        cursor.execute(f'DELETE FROM {_sequence_table_ref()} WHERE "Name" = %s', [name])
        cursor.execute(
            f"""
            INSERT INTO {_sequence_table_ref()} (
                "RecId",
                "Estado",
                "CreadoEn",
                "CreadoPor",
                "ModificadoEn",
                "ModificadoPor",
                "Module",
                "Prefix",
                "Suffix",
                "PaddingLength",
                "CurrentNumber",
                "Increment",
                "Active",
                "Name"
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                str(uuid4()),
                True,
                now,
                "test",
                now,
                "test",
                "OTHER",
                prefix,
                "",
                9,
                current_number,
                1,
                True,
                name,
            ],
        )


def _current_sequence_number(name: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT "CurrentNumber" FROM {_sequence_table_ref()} WHERE "Name" = %s', [name])
        return int(cursor.fetchone()[0])


class SequenceConfigTests(TestCase):
    def test_sequence_number_is_allocated_from_sequence_config(self):
        _reset_sequence("Entregas", prefix="E-")

        first = allocate_sequence_number("Entregas", actor="tester")
        second = allocate_sequence_number("Entregas", actor="tester")

        self.assertEqual(first, "E-000000001")
        self.assertEqual(second, "E-000000002")
        self.assertEqual(_current_sequence_number("Entregas"), 2)

    def test_missing_sequence_raises_clear_error(self):
        _ensure_sequence_table()
        with connection.cursor() as cursor:
            cursor.execute(f'DELETE FROM {_sequence_table_ref()} WHERE "Name" = %s', ["Entregas"])

        with self.assertRaisesRegex(SequenceConfigError, "Name='Entregas'"):
            allocate_sequence_number("Entregas", actor="tester")


class DeliveryPreparationFlowTests(TestCase):
    def setUp(self):
        _reset_sequence("Entregas", prefix="E-")
        _reset_sequence("Remitos", prefix="R-")
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
        self.delivery.refresh_from_db()
        self.fulfillment.refresh_from_db()
        self.fulfillment_line.refresh_from_db()
        packed.refresh_from_db()
        delivered = InventoryBalance.objects.get(warehouse_ref="W001", item_ref="ITEM-1", stock_state=StockState.DELIVERED)

        self.assertEqual(document.document_number, "R-000000001")
        self.assertEqual(document.lines.get().quantity, Decimal("3"))
        self.assertEqual(self.delivery.status, DeliveryOrder.DeliveryStatus.DELIVERED_COMPLETE)
        self.assertEqual(self.fulfillment.status, FulfillmentOrder.FulfillmentStatus.PARTIALLY_DELIVERED)
        self.assertEqual(self.fulfillment_line.delivered_qty, Decimal("3"))
        self.assertEqual(self.fulfillment_line.prepared_qty, Decimal("0"))
        self.assertEqual(packed.quantity, Decimal("2"))
        self.assertEqual(delivered.quantity, Decimal("3"))

        next_delivery = split_fulfillment_delivery(
            fulfillment_id=str(self.fulfillment.id),
            lines=[{"fulfillment_line_id": str(self.fulfillment_line.id), "split_qty": "2"}],
            delivery_mode="home",
            planned_date=None,
            reason="Entrega pendiente",
            idempotency_key="split-pending-after-remito",
            actor="tester",
            authorized_warehouses=["W001"],
        )
        replayed_delivery = split_fulfillment_delivery(
            fulfillment_id=str(self.fulfillment.id),
            lines=[{"fulfillment_line_id": str(self.fulfillment_line.id), "split_qty": "2"}],
            delivery_mode="home",
            planned_date=None,
            reason="Entrega pendiente",
            idempotency_key="split-pending-after-remito",
            actor="tester",
            authorized_warehouses=["W001"],
        )
        self.assertEqual(next_delivery.payload, replayed_delivery.payload)
        self.assertEqual(next_delivery.payload["result"]["delivery_number"], "E-000000001")
        self.assertEqual(Decimal(next_delivery.payload["result"]["lines"][0]["planned_qty"]), Decimal("2"))
        self.assertEqual(_current_sequence_number("Entregas"), 1)
        self.assertEqual(_current_sequence_number("Remitos"), 1)

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
