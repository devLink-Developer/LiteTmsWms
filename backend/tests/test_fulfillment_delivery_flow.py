from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.db import connection
from django.test import TestCase
from django.utils import timezone

from apps.core.models import StatusHistory
from apps.core.sequences import SequenceConfigError, allocate_sequence_number
from apps.fulfillment.models import (
    DeliveryDocument,
    DeliveryDocumentLine,
    DeliveryExecution,
    DeliveryOrder,
    DeliveryOrderLine,
    DeliveryPreparationTask,
    DeliverySplit,
    FulfillmentOrder,
    FulfillmentOrderImpact,
    FulfillmentOrderImpactLine,
    FulfillmentOrderLine,
)
from apps.fulfillment.services import (
    FulfillmentRuleError,
    _apply_order_impact,
    check_delivery_stock,
    check_fulfillment_stock_for_split,
    confirm_available_delivery_stock,
    expedition_queue,
    ingest_legacy_order,
    issue_remito,
    mark_preparation_task_prepared,
    reassign_confirmed_delivery_warehouse,
    _line_delivery_date,
    send_delivery_to_prepare,
    split_fulfillment_delivery,
    validate_delivery_stock,
)
from apps.integrations.legacy.models import LegacyOrder
from apps.inventory.models import InventoryBalance, InventoryLedgerEntry, InventoryReservation, StockState
from apps.routes.models import RouteSheet, RouteStop


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


class LegacyOrderMappingTests(TestCase):
    def test_sales_order_type_and_origin_fields_are_mapped(self):
        self.assertEqual(LegacyOrder._meta.get_field("sales_order_type").db_column, "SalesOrderType")
        self.assertEqual(LegacyOrder._meta.get_field("sales_order_number_orig").db_column, "SalesOrderNumberOrig")

    def test_non_p_legacy_order_is_not_ingested_as_fulfillment(self):
        class FakeLegacyOrderManager:
            def get(self, **_kwargs):
                return SimpleNamespace(sales_order_type="A")

        with patch("apps.fulfillment.services.LegacyOrder.objects.using", return_value=FakeLegacyOrderManager()):
            with self.assertRaisesRegex(FulfillmentRuleError, "no es un pedido entregable"):
                ingest_legacy_order(
                    sales_order_number="ANU-1",
                    idempotency_key="legacy-non-p",
                    actor="tester",
                )
        self.assertFalse(FulfillmentOrder.objects.exists())


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
        packed = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
        )
        reserved = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-RSV-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.RESERVED,
        )

        self.assertEqual(self.delivery.status, DeliveryOrder.DeliveryStatus.CONFIRMED)
        self.assertEqual(self.fulfillment_line.reserved_qty, Decimal("3"))
        reservation_line = reservation.lines.get()
        self.assertEqual(reservation_line.reserved_qty, Decimal("3"))
        self.assertEqual(reservation_line.source_location_ref, "W001-DSP-GEN")
        self.assertEqual(reservation_line.location_ref, "W001-RSV-GEN")
        self.assertEqual(packed.quantity, Decimal("2"))
        self.assertEqual(reserved.quantity, Decimal("3"))

    def test_confirm_delivery_matches_packed_stock_when_line_uom_case_differs(self):
        self.fulfillment_line.uom = "un"
        self.fulfillment_line.save(update_fields=["uom", "updated_at"])
        self.delivery_line.uom = "un"
        self.delivery_line.save(update_fields=["uom", "updated_at"])

        validate_delivery_stock(
            delivery_id=str(self.delivery.id),
            idempotency_key="confirm-uom-case",
            actor="tester",
            authorized_warehouses=["W001"],
        )

        packed = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
            uom="UN",
        )
        reserved = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-RSV-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.RESERVED,
            uom="UN",
        )
        reservation_line = InventoryReservation.objects.get(source_type="delivery_order", source_ref=str(self.delivery.id)).lines.get()

        self.assertEqual(packed.quantity, Decimal("2"))
        self.assertEqual(reserved.quantity, Decimal("3"))
        self.assertEqual(reservation_line.uom, "UN")

    def test_confirm_available_delivery_reduces_lines_and_reserves_only_available_quantities(self):
        second_fulfillment_line = FulfillmentOrderLine.objects.create(
            fulfillment=self.fulfillment,
            ordered_qty=Decimal("2"),
            uom="UN",
            item_ref="ITEM-2",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-1",
            legacy_line_id="20",
        )
        second_delivery_line = DeliveryOrderLine.objects.create(
            delivery=self.delivery,
            fulfillment_line=second_fulfillment_line,
            planned_qty=Decimal("2"),
            uom="UN",
            item_ref="ITEM-2",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-1",
            legacy_line_id="20",
        )
        DeliverySplit.objects.create(
            fulfillment_line=self.fulfillment_line,
            delivery_line=self.delivery_line,
            split_qty=Decimal("3"),
            remaining_after_split=Decimal("2"),
            reason="test",
        )
        DeliverySplit.objects.create(
            fulfillment_line=second_fulfillment_line,
            delivery_line=second_delivery_line,
            split_qty=Decimal("2"),
            remaining_after_split=Decimal("0"),
            reason="test",
        )

        result = confirm_available_delivery_stock(
            delivery_id=str(self.delivery.id),
            lines=[{"delivery_line_id": str(self.delivery_line.id), "planned_qty": "2"}],
            idempotency_key="confirm-available-1",
            actor="tester",
            authorized_warehouses=["W001"],
        )

        self.delivery.refresh_from_db()
        self.delivery_line.refresh_from_db()
        self.fulfillment_line.refresh_from_db()
        self.assertEqual(result.payload["result"]["status"], DeliveryOrder.DeliveryStatus.CONFIRMED)
        self.assertEqual(self.delivery.status, DeliveryOrder.DeliveryStatus.CONFIRMED)
        self.assertEqual(self.delivery.lines.count(), 1)
        self.assertFalse(DeliveryOrderLine.objects.filter(id=second_delivery_line.id).exists())
        self.assertEqual(self.delivery_line.planned_qty, Decimal("2.000000"))
        self.assertEqual(self.fulfillment_line.reserved_qty, Decimal("2"))
        self.assertEqual(DeliverySplit.objects.get(delivery_line=self.delivery_line).split_qty, Decimal("2.000000"))
        reservation_line = InventoryReservation.objects.get(source_type="delivery_order", source_ref=str(self.delivery.id)).lines.get()
        self.assertEqual(reservation_line.reserved_qty, Decimal("2.000000"))
        self.assertTrue(
            StatusHistory.objects.filter(
                entity_type="delivery_order",
                entity_id=str(self.delivery.id),
                reason="Confirmacion parcial por stock disponible",
            ).exists()
        )

    def test_confirm_available_delivery_rejects_preparation_started(self):
        DeliveryPreparationTask.objects.create(
            delivery=self.delivery,
            status=DeliveryPreparationTask.TaskStatus.ASSIGNED,
            assigned_to="picker-1",
            assigned_at=timezone.now(),
        )

        with self.assertRaisesRegex(FulfillmentRuleError, "inicio preparacion"):
            confirm_available_delivery_stock(
                delivery_id=str(self.delivery.id),
                lines=[{"delivery_line_id": str(self.delivery_line.id), "planned_qty": "2"}],
                idempotency_key="confirm-available-prep",
                actor="tester",
                authorized_warehouses=["W001"],
            )

    def test_annulment_impact_cancels_non_remitted_qty_and_releases_reservation(self):
        validate_delivery_stock(
            delivery_id=str(self.delivery.id),
            idempotency_key="confirm-before-annulment",
            actor="tester",
            authorized_warehouses=["W001"],
        )
        impact = FulfillmentOrderImpact.objects.create(
            fulfillment=self.fulfillment,
            impact_type=FulfillmentOrderImpact.ImpactType.ANNULMENT,
            status=FulfillmentOrderImpact.ImpactStatus.PENDING,
            impact_sales_order_number="ANU-SO-1",
            impact_transaction_number="TX-ANU-1",
            legacy_sales_order_number="SO-1",
            warehouse_ref="W001",
            source_table="transactions_orders_transaction",
            source_pk="ANU-SO-1",
            created_by="tester",
        )
        FulfillmentOrderImpactLine.objects.create(
            impact=impact,
            fulfillment_line=self.fulfillment_line,
            item_ref="ITEM-1",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-1",
            legacy_line_id="10",
            source_table="transactions_orders_retailLineItem",
            source_pk="ANU-SO-1-L1",
            quantity=Decimal("2"),
            uom="UN",
        )

        _apply_order_impact(impact, actor="tester")

        self.fulfillment_line.refresh_from_db()
        self.delivery_line.refresh_from_db()
        reservation = InventoryReservation.objects.get(source_type="delivery_order", source_ref=str(self.delivery.id))
        reservation_line = reservation.lines.get()
        packed = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
        )
        reserved = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-RSV-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.RESERVED,
        )

        self.assertEqual(self.fulfillment_line.cancelled_qty, Decimal("2"))
        self.assertEqual(self.fulfillment_line.reserved_qty, Decimal("1"))
        self.assertEqual(self.delivery_line.planned_qty, Decimal("1"))
        self.assertEqual(reservation_line.reserved_qty, Decimal("1"))
        self.assertEqual(packed.quantity, Decimal("4"))
        self.assertEqual(reserved.quantity, Decimal("1"))

    def test_annulment_impact_cancels_pending_line_when_packed_stock_is_already_zero(self):
        InventoryBalance.objects.filter(
            warehouse_ref="W001",
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
        ).update(quantity=Decimal("0"))
        impact = FulfillmentOrderImpact.objects.create(
            fulfillment=self.fulfillment,
            impact_type=FulfillmentOrderImpact.ImpactType.ANNULMENT,
            status=FulfillmentOrderImpact.ImpactStatus.PENDING,
            impact_sales_order_number="ANU-SO-1",
            impact_transaction_number="TX-ANU-1",
            legacy_sales_order_number="SO-1",
            warehouse_ref="W001",
            source_table="transactions_orders_transaction",
            source_pk="ANU-SO-1",
            created_by="tester",
        )
        impact_line = FulfillmentOrderImpactLine.objects.create(
            impact=impact,
            fulfillment_line=self.fulfillment_line,
            item_ref="ITEM-1",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-1",
            legacy_line_id="10",
            source_table="transactions_orders_retailLineItem",
            source_pk="ANU-SO-1-L1",
            quantity=Decimal("1"),
            uom="UN",
        )

        _apply_order_impact(impact, actor="tester")

        self.fulfillment_line.refresh_from_db()
        impact.refresh_from_db()
        impact_line.refresh_from_db()
        self.assertEqual(self.fulfillment_line.cancelled_qty, Decimal("1"))
        self.assertEqual(impact_line.applied_qty, Decimal("1"))
        self.assertEqual(impact.status, FulfillmentOrderImpact.ImpactStatus.APPLIED)
        self.assertFalse(InventoryLedgerEntry.objects.filter(document_ref="ANU-SO-1").exists())

    def test_return_impact_posts_packed_stock_in_received_warehouse(self):
        impact = FulfillmentOrderImpact.objects.create(
            fulfillment=self.fulfillment,
            impact_type=FulfillmentOrderImpact.ImpactType.RETURN,
            status=FulfillmentOrderImpact.ImpactStatus.PENDING,
            impact_sales_order_number="DEV-SO-1",
            impact_transaction_number="TX-DEV-1",
            legacy_sales_order_number="SO-1",
            warehouse_ref="W001",
            source_table="transactions_orders_transaction",
            source_pk="DEV-SO-1",
            created_by="tester",
        )
        line = FulfillmentOrderImpactLine.objects.create(
            impact=impact,
            fulfillment_line=self.fulfillment_line,
            item_ref="ITEM-1",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-1",
            legacy_line_id="10",
            source_table="transactions_orders_retailLineItem",
            source_pk="DEV-SO-1-L1",
            quantity=Decimal("2"),
            uom="UN",
        )

        _apply_order_impact(impact, actor="tester")

        impact.refresh_from_db()
        line.refresh_from_db()
        balance = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
        )
        ledger = InventoryLedgerEntry.objects.get(document_type="legacy_return", document_ref="DEV-SO-1")
        self.assertEqual(impact.status, FulfillmentOrderImpact.ImpactStatus.APPLIED)
        self.assertEqual(line.applied_qty, Decimal("2"))
        self.assertEqual(balance.quantity, Decimal("2"))
        self.assertEqual(ledger.movement_type, InventoryLedgerEntry.MovementType.INBOUND_RECEIPT)

    def test_expedition_queue_serializes_impacts_and_traceability(self):
        impact = FulfillmentOrderImpact.objects.create(
            fulfillment=self.fulfillment,
            impact_type=FulfillmentOrderImpact.ImpactType.RETURN,
            status=FulfillmentOrderImpact.ImpactStatus.PENDING,
            impact_sales_order_number="DEV-SO-1",
            impact_transaction_number="TX-DEV-1",
            legacy_sales_order_number="SO-1",
            warehouse_ref="W001",
            source_table="transactions_orders_transaction",
            source_pk="DEV-SO-1-TRACE",
            created_by="tester",
        )
        FulfillmentOrderImpactLine.objects.create(
            impact=impact,
            fulfillment_line=self.fulfillment_line,
            item_ref="ITEM-1",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-1",
            legacy_line_id="10",
            source_table="transactions_orders_retailLineItem",
            source_pk="DEV-SO-1-TRACE-L1",
            quantity=Decimal("1"),
            uom="UN",
        )
        _apply_order_impact(impact, actor="tester")

        with patch("apps.fulfillment.services._resolve_customer_snapshots", return_value={}):
            result = expedition_queue(sales_order_number="SO-1", authorized_warehouses=["W001"])

        self.assertEqual(result[0]["sales_order_type"], "P")
        self.assertEqual(result[0]["impacts"][0]["type"], "devolucion")
        self.assertEqual(result[0]["lines"][0]["returned_qty"], "1")
        labels = {movement["label"] for movement in result[0]["movements"]}
        self.assertIn("Devolucion recibida", labels)
        self.assertIn("Stock ingresado", labels)

    def test_expedition_queue_matches_normalized_indexed_filters(self):
        customer = {"customer_ref": "CUST-1", "name": "Cliente Test", "document_number": "", "address": {}}
        with patch("apps.fulfillment.services._resolve_customer_snapshots", return_value={"CUST-1": customer}):
            by_order = expedition_queue(sales_order_number="so-1", authorized_warehouses=["W001"])
            by_customer = expedition_queue(customer_ref="cust-1", authorized_warehouses=["W001"])

        self.assertEqual([row["sales_order_number"] for row in by_order], ["SO-1"])
        self.assertEqual([row["customer_ref"] for row in by_customer], ["CUST-1"])

    def test_line_item_snapshots_reuse_pos_freight_refs_per_store(self):
        second_line = FulfillmentOrderLine.objects.create(
            fulfillment=self.fulfillment,
            ordered_qty=Decimal("2"),
            uom="UN",
            item_ref="ITEM-2",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-1",
            legacy_line_id="20",
        )

        with (
            patch("apps.fulfillment.services.material_snapshots_for_items", return_value={"results": {}}),
            patch("apps.fulfillment.services._legacy_item_snapshots", return_value={}),
            patch("apps.fulfillment.services.pos_freight_product_refs", return_value=set()) as pos_refs,
        ):
            from apps.fulfillment.services import _resolve_line_item_snapshots

            _resolve_line_item_snapshots([self.fulfillment_line, second_line])

        self.assertEqual([call.args[0] for call in pos_refs.call_args_list], ["W001", ""])

    def test_expedition_queue_refreshes_legacy_impacts_for_customer_search(self):
        customer = {"customer_ref": "CUST-1", "name": "Cliente Test", "document_number": "", "address": {}}
        with (
            patch("apps.fulfillment.services.process_legacy_impacts_for_order") as process_impacts,
            patch("apps.fulfillment.services._resolve_customer_snapshots", return_value={"CUST-1": customer}),
        ):
            expedition_queue(customer_ref="cust-1", authorized_warehouses=["W001"])

        process_impacts.assert_called_once_with(
            sales_order_number="SO-1",
            actor="expedition.search",
        )

    def test_expedition_queue_refreshes_legacy_impacts_in_bulk_for_customer_search(self):
        second = FulfillmentOrder.objects.create(
            fulfillment_number="FUL-2",
            status=FulfillmentOrder.FulfillmentStatus.PENDING,
            customer_ref="CUST-1",
            delivery_mode="home",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-2",
        )
        FulfillmentOrderLine.objects.create(
            fulfillment=second,
            ordered_qty=Decimal("2"),
            uom="UN",
            item_ref="ITEM-2",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-2",
            legacy_line_id="20",
        )
        customer = {"customer_ref": "CUST-1", "name": "Cliente Test", "document_number": "", "address": {}}

        with (
            patch("apps.fulfillment.services.process_legacy_impacts_for_order") as process_impacts,
            patch("apps.fulfillment.services._legacy_impact_orders_for_order_numbers", return_value=[]) as bulk_impacts,
            patch("apps.fulfillment.services._resolve_customer_snapshots", return_value={"CUST-1": customer}),
        ):
            result = expedition_queue(customer_ref="cust-1", authorized_warehouses=["W001"])

        self.assertEqual({row["sales_order_number"] for row in result}, {"SO-1", "SO-2"})
        process_impacts.assert_not_called()
        bulk_impacts.assert_called_once()
        self.assertEqual(bulk_impacts.call_args.args[0], {"SO-1", "SO-2"})

    def test_refresh_legacy_impacts_skips_applied_same_source_version(self):
        second = FulfillmentOrder.objects.create(
            fulfillment_number="FUL-2",
            status=FulfillmentOrder.FulfillmentStatus.PENDING,
            customer_ref="CUST-1",
            delivery_mode="home",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-2",
        )
        FulfillmentOrderImpact.objects.create(
            fulfillment=self.fulfillment,
            impact_type=FulfillmentOrderImpact.ImpactType.RETURN,
            status=FulfillmentOrderImpact.ImpactStatus.APPLIED,
            impact_sales_order_number="DEV-SO-1",
            impact_transaction_number="TX-DEV-1",
            legacy_sales_order_number="SO-1",
            warehouse_ref="W001",
            source_table="transactions_orders_transaction",
            source_pk="TX-SKIP",
            source_version="version-1",
            created_by="tester",
        )
        impact_order = SimpleNamespace(
            transaction_id="TX-SKIP",
            modified_datetime="version-1",
            invoice_date=None,
            sales_order_number="DEV-SO-1",
            sales_order_number_orig="SO-1",
        )

        with (
            patch("apps.fulfillment.services._legacy_impact_orders_for_order_numbers", return_value=[impact_order]),
            patch("apps.fulfillment.services._process_legacy_impact_order") as process_impact,
        ):
            from apps.fulfillment.services import refresh_legacy_impacts_for_fulfillments

            refresh_legacy_impacts_for_fulfillments([self.fulfillment, second], actor="expedition.search")

        process_impact.assert_not_called()

    def test_reassign_confirmed_delivery_moves_reservation_to_target_warehouse(self):
        validate_delivery_stock(
            delivery_id=str(self.delivery.id),
            idempotency_key="confirm-before-reassign",
            actor="tester",
            authorized_warehouses=["W001"],
        )
        DeliverySplit.objects.create(
            fulfillment_line=self.fulfillment_line,
            delivery_line=self.delivery_line,
            split_qty=Decimal("3"),
            remaining_after_split=Decimal("2"),
            reason="test",
            warehouse_ref="W001",
        )
        InventoryBalance.objects.create(
            warehouse_ref="W002",
            item_ref="ITEM-1",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("5"),
        )

        result = reassign_confirmed_delivery_warehouse(
            delivery_id=str(self.delivery.id),
            target_warehouse_ref="W002",
            idempotency_key="reassign-delivery",
            actor="tester",
            authorized_warehouses=["W002"],
        )

        self.delivery.refresh_from_db()
        self.delivery_line.refresh_from_db()
        self.fulfillment_line.refresh_from_db()
        active_reservation = InventoryReservation.objects.get(
            source_type="delivery_order",
            source_ref=str(self.delivery.id),
            status=InventoryReservation.ReservationStatus.ALLOCATED,
        )
        released_reservation = InventoryReservation.objects.get(
            source_type="delivery_order",
            source_ref=str(self.delivery.id),
            status=InventoryReservation.ReservationStatus.RELEASED,
        )
        old_packed = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
        )
        old_reserved = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-RSV-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.RESERVED,
        )
        new_packed = InventoryBalance.objects.get(
            warehouse_ref="W002",
            location_ref="W002-DSP-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
        )
        new_reserved = InventoryBalance.objects.get(
            warehouse_ref="W002",
            location_ref="W002-RSV-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.RESERVED,
        )

        self.assertEqual(result.payload["result"]["warehouse_ref"], "W002")
        self.assertEqual(self.delivery.warehouse_ref, "W002")
        self.assertEqual(self.delivery_line.warehouse_ref, "W002")
        self.assertEqual(DeliverySplit.objects.get(delivery_line=self.delivery_line).warehouse_ref, "W002")
        self.assertEqual(released_reservation.lines.get().warehouse_ref, "W001")
        self.assertEqual(active_reservation.lines.get().warehouse_ref, "W002")
        self.assertEqual(self.fulfillment_line.reserved_qty, Decimal("3"))
        self.assertEqual(old_packed.quantity, Decimal("5"))
        self.assertEqual(old_reserved.quantity, Decimal("0"))
        self.assertEqual(new_packed.quantity, Decimal("2"))
        self.assertEqual(new_reserved.quantity, Decimal("3"))

    def test_reassign_delivery_blocks_after_preparation_started(self):
        self.delivery.status = DeliveryOrder.DeliveryStatus.PREPARING
        self.delivery.save(update_fields=["status", "updated_at"])

        with self.assertRaisesRegex(FulfillmentRuleError, "Solo se puede reasignar"):
            reassign_confirmed_delivery_warehouse(
                delivery_id=str(self.delivery.id),
                target_warehouse_ref="W002",
                idempotency_key="reassign-preparing",
                actor="tester",
                authorized_warehouses=["W002"],
            )

    def test_legacy_delivery_date_uses_line_delivery_date_before_requested_shipping_date(self):
        requested_shipping_date = timezone.datetime(2026, 4, 20, tzinfo=timezone.get_current_timezone())
        line_delivery_date = timezone.datetime(2026, 4, 27, tzinfo=timezone.get_current_timezone())

        line = SimpleNamespace(
            line_delivery_date=line_delivery_date,
            requested_shipping_date=requested_shipping_date,
        )

        self.assertEqual(_line_delivery_date(line), line_delivery_date.date())

    def test_stock_check_does_not_reserve_or_change_status(self):
        result = check_delivery_stock(
            delivery_id=str(self.delivery.id),
            authorized_warehouses=["W001"],
        )

        self.delivery.refresh_from_db()
        packed = InventoryBalance.objects.get(warehouse_ref="W001", item_ref="ITEM-1", stock_state=StockState.PACKED)

        self.assertTrue(result["can_confirm"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["issues"], [])
        self.assertEqual(self.delivery.status, DeliveryOrder.DeliveryStatus.CREATED)
        self.assertEqual(InventoryReservation.objects.filter(source_type="delivery_order", source_ref=str(self.delivery.id)).count(), 0)
        self.assertEqual(packed.quantity, Decimal("5"))

    def test_stock_check_reports_insufficient_without_side_effects(self):
        balance = InventoryBalance.objects.get(warehouse_ref="W001", item_ref="ITEM-1", stock_state=StockState.PACKED)
        balance.quantity = Decimal("2")
        balance.save(update_fields=["quantity", "updated_at"])

        result = check_delivery_stock(
            delivery_id=str(self.delivery.id),
            authorized_warehouses=["W001"],
        )

        self.delivery.refresh_from_db()
        balance.refresh_from_db()
        self.assertFalse(result["can_confirm"])
        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["issues"][0]["item_ref"], "ITEM-1")
        self.assertEqual(self.delivery.status, DeliveryOrder.DeliveryStatus.CREATED)
        self.assertEqual(InventoryReservation.objects.count(), 0)
        self.assertEqual(balance.quantity, Decimal("2"))

    def test_fulfillment_stock_check_validates_split_without_creating_delivery(self):
        result = check_fulfillment_stock_for_split(
            fulfillment_id=str(self.fulfillment.id),
            lines=[{"fulfillment_line_id": str(self.fulfillment_line.id), "split_qty": "2"}],
            authorized_warehouses=["W001"],
        )

        self.assertTrue(result["can_confirm"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(DeliveryOrder.objects.count(), 1)
        self.assertEqual(InventoryReservation.objects.count(), 0)

    def test_split_delivery_accepts_delivery_units_and_calculates_capacity(self):
        snapshot = {
            "item_ref": "ITEM-1",
            "name": "Ceramica por caja",
            "long_name": "Ceramica por caja",
            "category": "Ceramicos",
            "coverage_group": "STK",
            "sales_uom": "m2",
            "delivery_uom": "caja",
            "conversion_factor": "1.440000",
            "unit_weight_kg": "15.000000",
            "unit_volume_m3": "0.020000",
            "source": "test",
        }
        customer = {"customer_ref": "CUST-1", "name": "Cliente Test", "address": {}, "source": "test"}
        with (
            patch("apps.fulfillment.services._resolve_line_item_snapshots", return_value={self.fulfillment_line.id: snapshot}),
            patch("apps.fulfillment.services._resolve_customer_snapshots", return_value={"CUST-1": customer}),
        ):
            result = split_fulfillment_delivery(
                fulfillment_id=str(self.fulfillment.id),
                lines=[{"fulfillment_line_id": str(self.fulfillment_line.id), "delivery_unit_qty": "1"}],
                delivery_mode="home",
                planned_date=None,
                reason="Entrega por cajas",
                idempotency_key="split-delivery-units",
                actor="tester",
                authorized_warehouses=["W001"],
                receiver="Cliente autorizado",
                reference="Retira con DNI",
            )

        delivery_line = DeliveryOrderLine.objects.get(delivery_id=result.payload["result"]["id"])
        self.assertEqual(delivery_line.delivery_unit_qty, Decimal("1.000000"))
        self.assertEqual(delivery_line.planned_qty, Decimal("1.440000"))
        self.assertEqual(delivery_line.delivery_uom, "caja")
        self.assertEqual(delivery_line.conversion_factor, Decimal("1.440000"))
        self.assertEqual(delivery_line.planned_weight_kg, Decimal("21.600000"))
        self.assertEqual(delivery_line.planned_volume_m3, Decimal("0.028800"))
        self.assertEqual(result.payload["result"]["address_snapshot"]["receiver"], "Cliente autorizado")
        self.assertEqual(result.payload["result"]["totals"]["planned_weight_kg"], "21.600000")

    def test_split_delivery_skips_virtual_freight_and_service_lines(self):
        service_line = FulfillmentOrderLine.objects.create(
            fulfillment=self.fulfillment,
            ordered_qty=Decimal("1"),
            uom="UN",
            item_ref="FLETE-AUTO",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-1",
            legacy_line_id="20",
        )
        snapshots = {
            self.fulfillment_line.id: {
                "item_ref": "ITEM-1",
                "name": "Producto fisico",
                "sales_uom": "UN",
                "delivery_uom": "UN",
                "conversion_factor": "1.000000",
                "unit_weight_kg": "1.000000",
                "unit_volume_m3": "0.001000",
                "freight_product": False,
                "service_product": False,
                "virtual_product": False,
            },
            service_line.id: {
                "item_ref": "FLETE-AUTO",
                "name": "Flete automatico",
                "sales_uom": "UN",
                "delivery_uom": "UN",
                "conversion_factor": "1.000000",
                "unit_weight_kg": "0.000000",
                "unit_volume_m3": "0.000000",
                "freight_product": True,
                "service_product": True,
                "virtual_product": True,
            },
        }

        with patch("apps.fulfillment.services._resolve_line_item_snapshots", return_value=snapshots):
            result = split_fulfillment_delivery(
                fulfillment_id=str(self.fulfillment.id),
                lines=[
                    {"fulfillment_line_id": str(self.fulfillment_line.id), "split_qty": "2"},
                    {"fulfillment_line_id": str(service_line.id), "split_qty": "1"},
                ],
                delivery_mode="home",
                planned_date=None,
                reason="Entrega sin virtuales",
                idempotency_key="split-skip-virtual-lines",
                actor="tester",
                authorized_warehouses=["W001"],
            )

        delivery_id = result.payload["result"]["id"]
        delivery_lines = DeliveryOrderLine.objects.filter(delivery_id=delivery_id)
        self.assertEqual(delivery_lines.count(), 1)
        self.assertEqual(delivery_lines.get().item_ref, "ITEM-1")
        self.assertNotIn("FLETE-AUTO", [line["item_ref"] for line in result.payload["result"]["lines"]])

    def test_expedition_queue_displays_sap_st_as_un(self):
        self.fulfillment_line.uom = "ST"
        self.fulfillment_line.save(update_fields=["uom"])
        InventoryBalance.objects.all().delete()
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            item_ref="ITEM-1",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="ST",
            quantity=Decimal("5"),
        )
        snapshot = {
            "item_ref": "ITEM-1",
            "name": "Producto SAP",
            "sales_uom": "ST",
            "delivery_uom": "ST",
            "conversion_factor": "1.000000",
            "unit_weight_kg": "0.000000",
            "unit_volume_m3": "0.000000",
        }
        customer = {"customer_ref": "CUST-1", "name": "Cliente Test", "address": {}, "source": "test"}
        with (
            patch("apps.fulfillment.services._resolve_line_item_snapshots", return_value={self.fulfillment_line.id: snapshot}),
            patch("apps.fulfillment.services._resolve_customer_snapshots", return_value={"CUST-1": customer}),
        ):
            result = expedition_queue(sales_order_number="SO-1", authorized_warehouses=["W001"])

        line = result[0]["lines"][0]
        self.assertEqual(line["uom"], "Un")
        self.assertEqual(line["sales_uom"], "Un")
        self.assertEqual(line["delivery_uom"], "Un")
        self.assertEqual(line["item_snapshot"]["sap_uom"], "ST")

    def test_expedition_queue_returns_fully_delivered_orders(self):
        self.fulfillment.status = FulfillmentOrder.FulfillmentStatus.DELIVERED
        self.fulfillment.save(update_fields=["status"])
        self.fulfillment_line.delivered_qty = self.fulfillment_line.ordered_qty
        self.fulfillment_line.save(update_fields=["delivered_qty"])
        self.delivery.status = DeliveryOrder.DeliveryStatus.DELIVERED_COMPLETE
        self.delivery.save(update_fields=["status"])
        customer = {"customer_ref": "CUST-1", "name": "Cliente Test", "address": {}, "source": "test"}

        with patch("apps.fulfillment.services._resolve_customer_snapshots", return_value={"CUST-1": customer}):
            result = expedition_queue(sales_order_number="SO-1", authorized_warehouses=["W001"])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], FulfillmentOrder.FulfillmentStatus.DELIVERED)
        self.assertEqual(result[0]["deliveries"][0]["status"], DeliveryOrder.DeliveryStatus.DELIVERED_COMPLETE)

    def test_expedition_queue_treats_open_remito_lines_as_not_pending(self):
        self.fulfillment_line.ordered_qty = Decimal("3")
        self.fulfillment_line.prepared_qty = Decimal("3")
        self.fulfillment_line.save(update_fields=["ordered_qty", "prepared_qty", "updated_at"])
        document = DeliveryDocument.objects.create(
            delivery=self.delivery,
            document_number="R-OPEN-1",
            document_type=DeliveryDocument.DocumentType.REMITO,
            status=DeliveryDocument.DocumentStatus.OPEN,
            issued_at=timezone.now(),
            customer_ref=self.fulfillment.customer_ref,
            legacy_sales_order_number="SO-1",
            warehouse_ref="W001",
            created_by="tester",
        )
        DeliveryDocumentLine.objects.create(
            document=document,
            delivery_line=self.delivery_line,
            item_ref=self.delivery_line.item_ref,
            quantity=Decimal("3"),
            delivery_unit_qty=Decimal("3"),
            uom=self.delivery_line.uom,
            legacy_sales_order_number="SO-1",
            legacy_line_id=self.delivery_line.legacy_line_id,
            warehouse_ref="W001",
            created_by="tester",
        )
        customer = {"customer_ref": "CUST-1", "name": "Cliente Test", "address": {}, "source": "test"}

        with patch("apps.fulfillment.services._resolve_customer_snapshots", return_value={"CUST-1": customer}):
            result = expedition_queue(sales_order_number="SO-1", authorized_warehouses=["W001"])
            stock_check = check_fulfillment_stock_for_split(
                fulfillment_id=str(self.fulfillment.id),
                lines=[{"fulfillment_line_id": str(self.fulfillment_line.id), "split_qty": "1"}],
                authorized_warehouses=["W001"],
            )

        line = result[0]["lines"][0]
        self.assertEqual(Decimal(line["pending_qty"]), Decimal("0"))
        self.assertEqual(Decimal(line["max_dispatchable_qty"]), Decimal("0"))
        self.assertFalse(stock_check["can_confirm"])
        self.assertEqual(Decimal(stock_check["lines"][0]["available_qty"]), Decimal("0"))

    def test_expedition_queue_ingests_invoiced_legacy_order_when_missing_locally(self):
        legacy_order = SimpleNamespace(
            sales_order_number="SO-LEGACY",
            modified_datetime=timezone.now(),
            invoice_date=timezone.now(),
        )

        def fake_ingest(**kwargs):
            fulfillment = FulfillmentOrder.objects.create(
                fulfillment_number="FUL-SO-LEGACY",
                status=FulfillmentOrder.FulfillmentStatus.PENDING,
                customer_ref="CUST-2",
                delivery_mode="home",
                warehouse_ref="W002",
                legacy_sales_order_number=kwargs["sales_order_number"],
                created_by=kwargs["actor"],
            )
            FulfillmentOrderLine.objects.create(
                fulfillment=fulfillment,
                ordered_qty=Decimal("2"),
                uom="UN",
                item_ref="ITEM-2",
                warehouse_ref="W002",
                legacy_sales_order_number=kwargs["sales_order_number"],
                legacy_line_id="20",
            )

        def snapshots(lines):
            return {
                line.id: {
                    "item_ref": line.item_ref,
                    "name": "Producto legacy",
                    "sales_uom": "UN",
                    "delivery_uom": "UN",
                    "conversion_factor": "1.000000",
                }
                for line in lines
            }

        with (
            patch("apps.fulfillment.services._legacy_orders_for_expedition_search", return_value=[legacy_order]),
            patch("apps.fulfillment.services.ingest_legacy_order", side_effect=fake_ingest),
            patch("apps.fulfillment.services._resolve_line_item_snapshots", side_effect=snapshots),
            patch("apps.fulfillment.services._resolve_customer_snapshots", return_value={"CUST-2": {"name": "Cliente Legacy", "address": {}}}),
        ):
            result = expedition_queue(sales_order_number="INV-LEGACY", authorized_warehouses=["W002"])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sales_order_number"], "SO-LEGACY")
        self.assertEqual(result[0]["warehouse_ref"], "W002")

    def test_expedition_queue_uses_target_warehouse_for_stock_availability(self):
        InventoryBalance.objects.create(
            warehouse_ref="W002",
            item_ref="ITEM-1",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("1"),
        )

        with patch("apps.fulfillment.services._resolve_customer_snapshots", return_value={"CUST-1": {"name": "Cliente", "address": {}}}):
            result = expedition_queue(sales_order_number="SO-1", target_warehouse_ref="W002")

        self.assertEqual(len(result), 1)
        line = result[0]["lines"][0]
        self.assertEqual(line["warehouse_ref"], "W001")
        self.assertEqual(line["stock_available"], "1")
        self.assertEqual(line["max_dispatchable_qty"], "1")

    def test_expedition_queue_serializes_delivery_route_and_document_movements(self):
        now = timezone.now()
        DeliveryDocument.objects.create(
            delivery=self.delivery,
            document_number="R-MOV-1",
            status=DeliveryDocument.DocumentStatus.CLOSED,
            issued_at=now,
            customer_ref=self.fulfillment.customer_ref,
            legacy_sales_order_number="SO-1",
            warehouse_ref="W001",
            created_by="remitos",
        )
        StatusHistory.objects.create(
            entity_type="delivery_order",
            entity_id=str(self.delivery.id),
            from_status=DeliveryOrder.DeliveryStatus.CREATED,
            to_status=DeliveryOrder.DeliveryStatus.CONFIRMED,
            actor="tester",
            reason="Confirmacion manual",
        )
        route = RouteSheet.objects.create(
            route_number="HR-MOV-1",
            status=RouteSheet.RouteStatus.IN_TRANSIT,
            branch_ref="BR-1",
            warehouse_ref="W001",
            planned_date=timezone.localdate(),
            created_by="planner",
        )
        stop = RouteStop.objects.create(
            route=route,
            sequence=1,
            status=RouteStop.StopStatus.DELIVERED,
            source_type="delivery_order",
            source_ref=str(self.delivery.id),
            customer_ref=self.fulfillment.customer_ref,
            completed_at=now,
            outcome_status=DeliveryExecution.ExecutionStatus.DELIVERED_PARTIAL,
            outcome_reason="Entrega parcial",
            created_by="planner",
            updated_by="driver",
        )
        StatusHistory.objects.create(
            entity_type="route_stop",
            entity_id=str(stop.id),
            from_status=RouteStop.StopStatus.EN_ROUTE,
            to_status=RouteStop.StopStatus.DELIVERED,
            actor="driver",
            reason="Ejecucion de parada",
        )
        DeliveryExecution.objects.create(
            delivery=self.delivery,
            route_stop_ref=str(stop.id),
            status=DeliveryExecution.ExecutionStatus.DELIVERED_PARTIAL,
            delivered_qty=Decimal("1"),
            returned_qty=Decimal("2"),
            executed_at=now,
            observations="Cliente recibio parcial",
            warehouse_ref="W001",
            created_by="driver",
        )
        customer = {"customer_ref": "CUST-1", "name": "Cliente Test", "address": {}, "source": "test"}

        with patch("apps.fulfillment.services._resolve_customer_snapshots", return_value={"CUST-1": customer}):
            result = expedition_queue(sales_order_number="SO-1", authorized_warehouses=["W001"])

        delivery_movements = result[0]["deliveries"][0]["movements"]
        labels = {movement["label"] for movement in delivery_movements}
        self.assertIn("Confirmacion manual", labels)
        self.assertIn("Remito emitido", labels)
        self.assertIn("Asignada a hoja de ruta", labels)
        self.assertIn("Ejecucion de reparto", labels)
        route_movements = [movement for movement in delivery_movements if movement["route_number"] == "HR-MOV-1"]
        self.assertTrue(route_movements)
        order_labels = {movement["label"] for movement in result[0]["movements"]}
        self.assertIn("Pedido ingresado a TMS/WMS", order_labels)
        self.assertIn("Ejecucion de reparto", order_labels)

    def test_expedition_queue_uses_prefetched_route_assignment_context(self):
        route = RouteSheet.objects.create(
            route_number="HR-BULK-1",
            status=RouteSheet.RouteStatus.IN_TRANSIT,
            branch_ref="BR-1",
            warehouse_ref="W001",
            planned_date=timezone.localdate(),
            created_by="planner",
        )
        RouteStop.objects.create(
            route=route,
            sequence=1,
            status=RouteStop.StopStatus.PLANNED,
            source_type="delivery_order",
            source_ref=str(self.delivery.id),
            customer_ref=self.fulfillment.customer_ref,
            created_by="planner",
        )
        customer = {"customer_ref": "CUST-1", "name": "Cliente Test", "address": {}, "source": "test"}

        with (
            patch("apps.fulfillment.services._resolve_customer_snapshots", return_value={"CUST-1": customer}),
            patch(
                "apps.fulfillment.services._delivery_route_assignment",
                side_effect=AssertionError("expedition queue must not query route assignment per delivery"),
            ),
        ):
            result = expedition_queue(sales_order_number="SO-1", authorized_warehouses=["W001"])

        route_sheet = result[0]["deliveries"][0]["route_sheet"]
        self.assertEqual(route_sheet["route_number"], "HR-BULK-1")
        self.assertEqual(route_sheet["stop_status"], RouteStop.StopStatus.PLANNED)

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
        reserved = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-RSV-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.RESERVED,
        )
        picking = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-PRE-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.PICKING,
        )
        packed_dispatch = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
        )
        packed_prepared = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-PRE-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
        )

        self.assertEqual(task.status, DeliveryPreparationTask.TaskStatus.PREPARED)
        self.assertEqual(self.delivery.status, DeliveryOrder.DeliveryStatus.PREPARED)
        self.assertEqual(self.fulfillment_line.prepared_qty, Decimal("3"))
        self.assertEqual(reserved.quantity, Decimal("0"))
        self.assertEqual(picking.quantity, Decimal("0.000000"))
        self.assertEqual(packed_dispatch.quantity, Decimal("2.000000"))
        self.assertEqual(packed_prepared.quantity, Decimal("3.000000"))

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
        packed_prepared.refresh_from_db()
        delivered = InventoryBalance.objects.get(
            warehouse_ref="W001",
            location_ref="W001-TRN-GEN",
            item_ref="ITEM-1",
            stock_state=StockState.DELIVERED,
        )

        self.assertEqual(document.document_number, "R-000000001")
        self.assertEqual(document.lines.get().quantity, Decimal("3"))
        self.assertEqual(self.delivery.status, DeliveryOrder.DeliveryStatus.DELIVERED_COMPLETE)
        self.assertEqual(self.fulfillment.status, FulfillmentOrder.FulfillmentStatus.PARTIALLY_DELIVERED)
        self.assertEqual(self.fulfillment_line.delivered_qty, Decimal("3"))
        self.assertEqual(self.fulfillment_line.prepared_qty, Decimal("0"))
        self.assertEqual(packed_prepared.quantity, Decimal("0.000000"))
        self.assertEqual(delivered.quantity, Decimal("3.000000"))

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
