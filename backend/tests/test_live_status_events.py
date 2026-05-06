from __future__ import annotations

from unittest.mock import patch

from django.test import Client, TestCase
from django.utils import timezone

from apps.core.models import StatusHistory
from apps.fulfillment.models import DeliveryOrder, FulfillmentOrder
from apps.routes.models import RouteSheet


class LiveStatusEventsTests(TestCase):
    def setUp(self):
        self.client = Client()
        session = self.client.session
        session["authorized_warehouses"] = ["W001"]
        session.save()

    def test_live_status_events_returns_authorized_delivery_and_route_changes(self):
        fulfillment = FulfillmentOrder.objects.create(
            fulfillment_number="PED-1",
            status=FulfillmentOrder.FulfillmentStatus.PENDING,
            customer_ref="C001",
            delivery_mode="Reparto",
            warehouse_ref="W001",
        )
        delivery = DeliveryOrder.objects.create(
            delivery_number="ENT-1",
            fulfillment=fulfillment,
            status=DeliveryOrder.DeliveryStatus.CONFIRMED,
            delivery_mode="Reparto",
            warehouse_ref="W001",
        )
        other_fulfillment = FulfillmentOrder.objects.create(
            fulfillment_number="PED-2",
            status=FulfillmentOrder.FulfillmentStatus.PENDING,
            customer_ref="C002",
            delivery_mode="Reparto",
            warehouse_ref="W002",
        )
        other_delivery = DeliveryOrder.objects.create(
            delivery_number="ENT-2",
            fulfillment=other_fulfillment,
            status=DeliveryOrder.DeliveryStatus.CONFIRMED,
            delivery_mode="Reparto",
            warehouse_ref="W002",
        )
        route = RouteSheet.objects.create(
            route_number="HR-1",
            status=RouteSheet.RouteStatus.PLANNED,
            branch_ref="B001",
            warehouse_ref="W001",
            planned_date=timezone.localdate(),
        )
        StatusHistory.objects.create(
            entity_type="delivery_order",
            entity_id=str(delivery.id),
            from_status="created",
            to_status="confirmed",
            actor="tester",
            reason="test",
        )
        StatusHistory.objects.create(
            entity_type="delivery_order",
            entity_id=str(other_delivery.id),
            from_status="created",
            to_status="confirmed",
            actor="tester",
            reason="test",
        )
        StatusHistory.objects.create(
            entity_type="route_sheet",
            entity_id=str(route.id),
            from_status="draft",
            to_status="planned",
            actor="tester",
            reason="test",
        )

        response = self.client.get("/api/v1/live/status-events/")

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual([row["warehouse_ref"] for row in payload["results"]], ["W001", "W001"])
        self.assertEqual({row["entity_type"] for row in payload["results"]}, {"delivery_order", "route_sheet"})
        self.assertTrue(payload["cursor"])

    def test_live_status_events_requires_authorized_warehouse(self):
        client = Client()
        with patch("apps.core.api.employee_delivery_permissions", return_value={"authorized_warehouses": []}):
            response = client.get("/api/v1/live/status-events/", HTTP_X_ACTOR="")

        self.assertEqual(response.status_code, 403, response.content)
