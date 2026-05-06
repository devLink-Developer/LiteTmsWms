from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.fulfillment.models import DeliveryOrder, FulfillmentOrder
from apps.inventory.models import InventoryBalance, InventoryLedgerEntry, StockState


class OperationalDashboardTests(TestCase):
    def _set_active_warehouse(self, warehouse_ref: str, authorized: list[str] | None = None) -> None:
        session = self.client.session
        session["active_warehouse_ref"] = warehouse_ref
        session["authorized_warehouses"] = authorized or [warehouse_ref]
        session.save()

    def _dashboard(self) -> dict:
        response = self.client.get("/api/v1/logistics/dashboard/")
        self.assertEqual(response.status_code, 200, response.content)
        return json.loads(response.content)

    def _create_fulfillment(self, number: str, *, warehouse_ref: str, status: str, requested_date=None):
        return FulfillmentOrder.objects.create(
            fulfillment_number=number,
            status=status,
            customer_ref=f"CUST-{number}",
            delivery_mode="Repart Prg",
            warehouse_ref=warehouse_ref,
            requested_date=requested_date,
        )

    def _create_ledger(self, key: str, *, warehouse_ref: str, direction: str, posted_at) -> InventoryLedgerEntry:
        entry = InventoryLedgerEntry.objects.create(
            idempotency_key=key,
            movement_type=InventoryLedgerEntry.MovementType.DISPATCH,
            direction=direction,
            warehouse_ref=warehouse_ref,
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
            quantity=Decimal("2"),
            uom="UN",
            document_type="delivery",
            document_ref=key,
        )
        InventoryLedgerEntry.objects.filter(id=entry.id).update(posted_at=posted_at)
        return entry

    def test_dashboard_uses_active_warehouse_and_aggregates_all_rows(self):
        self._set_active_warehouse("WH-A", ["WH-A", "WH-B"])
        today = timezone.localdate()
        now = timezone.now()
        for index in range(105):
            self._create_fulfillment(
                f"FUL-A-{index}",
                warehouse_ref="WH-A",
                status=FulfillmentOrder.FulfillmentStatus.PENDING,
                requested_date=today,
            )
        for index in range(3):
            self._create_fulfillment(
                f"FUL-B-{index}",
                warehouse_ref="WH-B",
                status=FulfillmentOrder.FulfillmentStatus.PENDING,
                requested_date=today,
            )
        fulfillment = self._create_fulfillment(
            "FUL-A-DEL",
            warehouse_ref="WH-A",
            status=FulfillmentOrder.FulfillmentStatus.ALLOCATED,
            requested_date=today,
        )
        DeliveryOrder.objects.create(
            fulfillment=fulfillment,
            delivery_number="DEL-A-1",
            status=DeliveryOrder.DeliveryStatus.PREPARED,
            delivery_mode="Repart Prg",
            warehouse_ref="WH-A",
            planned_date=today,
        )
        DeliveryOrder.objects.create(
            fulfillment=fulfillment,
            delivery_number="DEL-B-1",
            status=DeliveryOrder.DeliveryStatus.PREPARED,
            delivery_mode="Repart Prg",
            warehouse_ref="WH-B",
            planned_date=today,
        )
        InventoryBalance.objects.create(
            warehouse_ref="WH-A",
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
            quantity=Decimal("5"),
            uom="UN",
        )
        InventoryBalance.objects.create(
            warehouse_ref="WH-B",
            item_ref="ITEM-1",
            stock_state=StockState.PACKED,
            quantity=Decimal("7"),
            uom="UN",
        )
        self._create_ledger(
            "ledger-a-increase",
            warehouse_ref="WH-A",
            direction=InventoryLedgerEntry.Direction.INCREASE,
            posted_at=now,
        )
        self._create_ledger(
            "ledger-a-decrease",
            warehouse_ref="WH-A",
            direction=InventoryLedgerEntry.Direction.DECREASE,
            posted_at=now,
        )
        self._create_ledger(
            "ledger-b-increase",
            warehouse_ref="WH-B",
            direction=InventoryLedgerEntry.Direction.INCREASE,
            posted_at=now,
        )

        payload = self._dashboard()

        self.assertEqual(payload["scope"]["warehouse_ref"], "WH-A")
        open_orders = next(kpi for kpi in payload["kpis"] if kpi["key"] == "open_orders")
        self.assertEqual(open_orders["value"], 106)
        fulfillment_pending = next(row for row in payload["charts"]["fulfillment_status"] if row["key"] == "pending")
        self.assertEqual(fulfillment_pending["count"], 105)
        delivery_prepared = next(row for row in payload["charts"]["delivery_pipeline"] if row["key"] == "prepared")
        self.assertEqual(delivery_prepared["count"], 1)
        packed_stock = next(row for row in payload["charts"]["stock_by_state"] if row["key"] == StockState.PACKED)
        self.assertEqual(packed_stock["buckets"], 1)
        today_ledger = next(row for row in payload["charts"]["ledger_by_day"] if row["date"] == today.isoformat())
        self.assertEqual(today_ledger["increase_count"], 1)
        self.assertEqual(today_ledger["decrease_count"], 1)

    def test_dashboard_reports_zero_modules_without_inventing_volume(self):
        self._set_active_warehouse("WH-Z")

        payload = self._dashboard()

        coverage = {row["key"]: row["count"] for row in payload["charts"]["module_coverage"]}
        self.assertEqual(coverage["receipts"], 0)
        self.assertEqual(coverage["transfers"], 0)
        self.assertEqual(coverage["shipping"], 0)
        self.assertEqual(coverage["write_offs"], 0)
        self.assertEqual(payload["modules"][0]["count"], 0)

    def test_dashboard_flags_open_items_past_local_date(self):
        self._set_active_warehouse("WH-A")
        today = timezone.localdate()
        overdue_date = today - timedelta(days=1)
        fulfillment = self._create_fulfillment(
            "FUL-OVERDUE",
            warehouse_ref="WH-A",
            status=FulfillmentOrder.FulfillmentStatus.PENDING,
            requested_date=overdue_date,
        )
        DeliveryOrder.objects.create(
            fulfillment=fulfillment,
            delivery_number="DEL-OVERDUE",
            status=DeliveryOrder.DeliveryStatus.CONFIRMED,
            delivery_mode="Repart Prg",
            warehouse_ref="WH-A",
            planned_date=overdue_date,
        )

        payload = self._dashboard()

        issues = {row["key"]: row["issues"] for row in payload["modules"]}
        self.assertEqual(issues["orders"], 1)
        self.assertEqual(issues["deliveries"], 1)
        alert_keys = {row["key"] for row in payload["alerts"]}
        self.assertIn("overdue_orders", alert_keys)
        self.assertIn("overdue_deliveries", alert_keys)
