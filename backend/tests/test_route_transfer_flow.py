from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.db import connection
from django.test import override_settings
from django.test import TestCase
from django.utils import timezone

from apps.fulfillment.models import DeliveryDocument, DeliveryOrder, DeliveryOrderLine, FulfillmentOrder, FulfillmentOrderLine
from apps.inventory.models import InventoryBalance, StockState
from apps.fulfillment.services import FulfillmentRuleError, issue_remito
from apps.routes.models import RouteSheet
from apps.routes.services import (
    RouteRuleError,
    _geometry_with_origin_coordinate,
    close_route,
    confirm_route,
    depart_route,
    execute_delivery_stop,
    optimize_route,
    pending_reparto_deliveries,
    start_loading_route,
    update_route_stops,
)
from apps.transfers.models import TransferOrder
from apps.transfers.services import approve_transfer, create_transfer, dispatch_transfer, prepare_transfer, receive_transfer
from apps.vehicles.models import Vehicle, VehicleCapacityProfile


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


def _reset_sequence(name: str, *, prefix: str) -> None:
    _ensure_sequence_table()
    now = timezone.now()
    with connection.cursor() as cursor:
        cursor.execute(f'DELETE FROM {_sequence_table_ref()} WHERE "Name" = %s', [name])
        cursor.execute(
            f"""
            INSERT INTO {_sequence_table_ref()} (
                "RecId", "Estado", "CreadoEn", "CreadoPor", "ModificadoEn", "ModificadoPor",
                "Module", "Prefix", "Suffix", "PaddingLength", "CurrentNumber", "Increment", "Active", "Name"
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [str(uuid4()), True, now, "test", now, "test", "OTHER", prefix, "", 9, 0, 1, True, name],
        )


class RouteExecutionFlowTests(TestCase):
    def setUp(self):
        _reset_sequence("Remitos", prefix="R-")
        _reset_sequence("Hojas de Ruta", prefix="HR-")
        profile = VehicleCapacityProfile.objects.create(name="Camioneta", max_weight_kg=Decimal("100"), max_volume_m3=Decimal("10"))
        self.vehicle = Vehicle.objects.create(code="VH-1", plate="AA100AA", capacity_profile=profile)
        self.fulfillment = FulfillmentOrder.objects.create(
            fulfillment_number="FUL-R-1",
            status=FulfillmentOrder.FulfillmentStatus.READY_FOR_DISPATCH,
            customer_ref="CUST-R",
            delivery_mode="Reparto programado",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-R-1",
            address_snapshot={"receiver": "Cliente Uno"},
        )
        self.fulfillment_line = FulfillmentOrderLine.objects.create(
            fulfillment=self.fulfillment,
            ordered_qty=Decimal("3"),
            prepared_qty=Decimal("3"),
            uom="UN",
            item_ref="ITEM-R",
            warehouse_ref="W001",
            legacy_sales_order_number="SO-R-1",
            legacy_line_id="1",
        )
        self.delivery = DeliveryOrder.objects.create(
            fulfillment=self.fulfillment,
            delivery_number="DEL-R-1",
            status=DeliveryOrder.DeliveryStatus.PREPARED,
            delivery_mode="Reparto programado",
            planned_date=timezone.localdate(),
            warehouse_ref="W001",
            legacy_sales_order_number="SO-R-1",
            address_snapshot={"latitude": "-34.60", "longitude": "-58.38", "street": "Calle 1"},
        )
        self.delivery_line = DeliveryOrderLine.objects.create(
            delivery=self.delivery,
            fulfillment_line=self.fulfillment_line,
            planned_qty=Decimal("3"),
            uom="UN",
            item_ref="ITEM-R",
            warehouse_ref="W001",
            planned_weight_kg=Decimal("9"),
            planned_volume_m3=Decimal("0.300000"),
            legacy_sales_order_number="SO-R-1",
            legacy_line_id="1",
        )
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            item_ref="ITEM-R",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=Decimal("3"),
        )

    def _preview_route(self):
        return optimize_route(
            payload={
                "warehouse_ref": "W001",
                "branch_ref": "BR-1",
                "planned_date": timezone.localdate().isoformat(),
                "vehicle_id": str(self.vehicle.id),
                "driver_ref": "driver-1",
                "deliveries": [{"delivery_id": str(self.delivery.id), "lat": "-34.60", "lng": "-58.38"}],
            },
            idempotency_key="route-preview",
            actor="planner",
        ).payload["result"]

    def _create_prepared_delivery(self, suffix: str, *, lat: str, lng: str, weight: str = "4"):
        fulfillment = FulfillmentOrder.objects.create(
            fulfillment_number=f"FUL-R-{suffix}",
            status=FulfillmentOrder.FulfillmentStatus.READY_FOR_DISPATCH,
            customer_ref=f"CUST-{suffix}",
            delivery_mode="Reparto programado",
            warehouse_ref="W001",
            legacy_sales_order_number=f"SO-R-{suffix}",
        )
        fulfillment_line = FulfillmentOrderLine.objects.create(
            fulfillment=fulfillment,
            ordered_qty=Decimal("1"),
            prepared_qty=Decimal("1"),
            uom="UN",
            item_ref=f"ITEM-{suffix}",
            warehouse_ref="W001",
            legacy_sales_order_number=f"SO-R-{suffix}",
            legacy_line_id="1",
        )
        delivery = DeliveryOrder.objects.create(
            fulfillment=fulfillment,
            delivery_number=f"DEL-R-{suffix}",
            status=DeliveryOrder.DeliveryStatus.PREPARED,
            delivery_mode="Reparto programado",
            planned_date=timezone.localdate(),
            warehouse_ref="W001",
            legacy_sales_order_number=f"SO-R-{suffix}",
            address_snapshot={"latitude": lat, "longitude": lng, "street": f"Calle {suffix}"},
        )
        DeliveryOrderLine.objects.create(
            delivery=delivery,
            fulfillment_line=fulfillment_line,
            planned_qty=Decimal("1"),
            uom="UN",
            item_ref=f"ITEM-{suffix}",
            warehouse_ref="W001",
            planned_weight_kg=Decimal(weight),
            planned_volume_m3=Decimal("0.100000"),
            legacy_sales_order_number=f"SO-R-{suffix}",
            legacy_line_id="1",
        )
        return delivery

    def test_route_requires_review_before_confirm_and_preview_is_idempotent(self):
        first = self._preview_route()
        replay = optimize_route(
            payload={
                "warehouse_ref": "W001",
                "branch_ref": "BR-1",
                "planned_date": timezone.localdate().isoformat(),
                "vehicle_id": str(self.vehicle.id),
                "driver_ref": "driver-1",
                "deliveries": [{"delivery_id": str(self.delivery.id), "lat": "-34.60", "lng": "-58.38"}],
            },
            idempotency_key="route-preview",
            actor="planner",
        ).payload["result"]

        self.assertEqual(first["id"], replay["id"])
        self.assertEqual(first["stops"][0]["customer_name"], "Cliente Uno")
        self.assertEqual(RouteSheet.objects.count(), 1)
        with self.assertRaises(RouteRuleError):
            confirm_route(route_id=first["id"], payload={"vehicle_id": str(self.vehicle.id)}, idempotency_key="route-confirm-blocked", actor="planner")

    def test_confirmed_reparto_delivery_is_pending_for_route_preview(self):
        self.delivery.status = DeliveryOrder.DeliveryStatus.CONFIRMED
        self.delivery.save(update_fields=["status"])

        pending = pending_reparto_deliveries(warehouse_ref="W001", planned_date=timezone.localdate())
        self.assertEqual([row["delivery_number"] for row in pending], ["DEL-R-1"])
        self.assertEqual(pending[0]["status"], DeliveryOrder.DeliveryStatus.CONFIRMED)

        route = optimize_route(
            payload={
                "warehouse_ref": "W001",
                "branch_ref": "BR-1",
                "planned_date": timezone.localdate().isoformat(),
                "vehicle_id": str(self.vehicle.id),
                "driver_ref": "driver-1",
                "deliveries": [{"delivery_id": str(self.delivery.id), "lat": "-34.60", "lng": "-58.38"}],
            },
            idempotency_key="route-preview-confirmed",
            actor="planner",
        ).payload["result"]

        self.assertEqual(route["stops"][0]["source_ref"], str(self.delivery.id))

    def test_draft_route_stop_can_be_removed_and_delivery_returns_to_pending_pool(self):
        self.delivery.status = DeliveryOrder.DeliveryStatus.PREPARED
        self.delivery.save(update_fields=["status"])
        route = self._preview_route()
        stop_id = route["stops"][0]["id"]

        updated = update_route_stops(
            route_id=route["id"],
            payload={"stops": [], "remove_stop_ids": [stop_id]},
            idempotency_key="route-remove-stop",
            actor="planner",
        ).payload["result"]

        self.assertEqual(updated["stops"], [])
        self.assertEqual(Decimal(updated["planned_weight_kg"]), Decimal("0"))
        self.assertEqual(Decimal(updated["planned_volume_m3"]), Decimal("0"))
        pending = pending_reparto_deliveries(warehouse_ref="W001", planned_date=timezone.localdate())
        self.assertEqual([row["delivery_number"] for row in pending], ["DEL-R-1"])

    def test_reoptimization_consolidates_existing_draft_stops(self):
        first_route = self._preview_route()
        second_delivery = self._create_prepared_delivery("2", lat="-34.61", lng="-58.39")

        route = optimize_route(
            payload={
                "warehouse_ref": "W001",
                "branch_ref": "BR-1",
                "planned_date": timezone.localdate().isoformat(),
                "vehicle_id": str(self.vehicle.id),
                "driver_ref": "driver-1",
                "deliveries": [{"delivery_id": str(second_delivery.id), "lat": "-34.61", "lng": "-58.39"}],
            },
            idempotency_key="route-preview-merge-drafts",
            actor="planner",
        ).payload["result"]

        self.assertEqual({stop["delivery_number"] for stop in route["stops"]}, {"DEL-R-1", "DEL-R-2"})
        self.assertEqual(RouteSheet.objects.filter(status=RouteSheet.RouteStatus.DRAFT).count(), 1)
        self.assertEqual(RouteSheet.objects.get(id=first_route["id"]).status, RouteSheet.RouteStatus.CANCELLED)
        self.assertEqual(route["preview_payload"]["superseded_draft_routes"], [first_route["id"]])

    def test_reoptimization_without_payload_uses_existing_draft_stops(self):
        first_route = self._preview_route()

        route = optimize_route(
            payload={
                "warehouse_ref": "W001",
                "branch_ref": "BR-1",
                "planned_date": timezone.localdate().isoformat(),
                "vehicle_id": str(self.vehicle.id),
                "driver_ref": "driver-1",
            },
            idempotency_key="route-preview-merge-existing-draft",
            actor="planner",
        ).payload["result"]

        self.assertEqual([stop["delivery_number"] for stop in route["stops"]], ["DEL-R-1"])
        self.assertEqual(RouteSheet.objects.filter(status=RouteSheet.RouteStatus.DRAFT).count(), 1)
        self.assertEqual(RouteSheet.objects.get(id=first_route["id"]).status, RouteSheet.RouteStatus.CANCELLED)
        self.assertEqual(route["preview_payload"]["superseded_draft_routes"], [first_route["id"]])

    def test_route_preview_without_deliveries_rejects_empty_route(self):
        with self.assertRaisesRegex(RouteRuleError, "No hay entregas"):
            optimize_route(
                payload={
                    "warehouse_ref": "W001",
                    "branch_ref": "BR-1",
                    "planned_date": timezone.localdate().isoformat(),
                    "vehicle_id": str(self.vehicle.id),
                    "driver_ref": "driver-1",
                    "deliveries": [],
                },
                idempotency_key="route-preview-empty",
                actor="planner",
            )

        self.assertEqual(RouteSheet.objects.count(), 0)

    @override_settings(ORS_API_KEY="")
    @patch("apps.routes.services.warehouse_origin_snapshot")
    def test_route_origin_defaults_to_warehouse_address(self, warehouse_origin_snapshot):
        warehouse_origin_snapshot.return_value = {
            "warehouse_ref": "W001",
            "formatted": "Deposito W001",
            "latitude": "-34.590000",
            "longitude": "-58.370000",
            "source": "test",
        }

        route = optimize_route(
            payload={
                "warehouse_ref": "W001",
                "branch_ref": "BR-1",
                "planned_date": timezone.localdate().isoformat(),
                "vehicle_id": str(self.vehicle.id),
                "driver_ref": "driver-1",
                "deliveries": [{"delivery_id": str(self.delivery.id), "lat": "-34.60", "lng": "-58.38"}],
            },
            idempotency_key="route-preview-origin",
            actor="planner",
        ).payload["result"]

        self.assertEqual(route["preview_payload"]["input"]["origin"]["lat"], "-34.590000")
        self.assertEqual(route["preview_payload"]["input"]["origin"]["lng"], "-58.370000")
        self.assertEqual(route["route_geometry"]["coordinates"][0], [-58.37, -34.59])
        self.assertEqual(route["route_geometry"]["coordinates"][1], [-58.38, -34.6])

    @override_settings(
        ORS_API_KEY="",
        WAREHOUSE_ORIGINS={
            "W001": {
                "lat": "-34.590001",
                "lng": "-58.370002",
                "formatted": "Origen manual W001",
                "source": "test_manual",
            }
        },
    )
    @patch("apps.routes.services.warehouse_origin_snapshot")
    def test_route_origin_uses_configured_warehouse_coordinates(self, warehouse_origin_snapshot):
        route = optimize_route(
            payload={
                "warehouse_ref": "W001",
                "branch_ref": "BR-1",
                "planned_date": timezone.localdate().isoformat(),
                "vehicle_id": str(self.vehicle.id),
                "driver_ref": "driver-1",
                "deliveries": [{"delivery_id": str(self.delivery.id), "lat": "-34.60", "lng": "-58.38"}],
            },
            idempotency_key="route-preview-configured-origin",
            actor="planner",
        ).payload["result"]

        warehouse_origin_snapshot.assert_not_called()
        self.assertEqual(route["preview_payload"]["input"]["origin"]["lat"], "-34.590001")
        self.assertEqual(route["preview_payload"]["input"]["origin"]["lng"], "-58.370002")
        self.assertEqual(route["preview_payload"]["input"]["origin"]["source"], "test_manual")
        self.assertEqual(route["route_geometry"]["coordinates"][0], [-58.370002, -34.590001])

    def test_route_geometry_keeps_exact_origin_coordinate(self):
        geometry = {"type": "LineString", "coordinates": [[-58.400000, -34.700000], [-58.380000, -34.600000]]}

        fixed = _geometry_with_origin_coordinate(geometry, (Decimal("-34.590001"), Decimal("-58.370002")))

        self.assertEqual(fixed["coordinates"][0], [-58.370002, -34.590001])
        self.assertEqual(fixed["coordinates"][1], [-58.38, -34.6])

    def test_direct_remito_is_blocked_when_delivery_is_in_route_sheet(self):
        route = self._preview_route()

        with self.assertRaisesRegex(FulfillmentRuleError, route["route_number"]):
            issue_remito(
                delivery_id=str(self.delivery.id),
                idempotency_key="direct-remito-route-blocked",
                actor="counter",
                authorized_warehouses=["W001"],
            )

        self.assertFalse(DeliveryDocument.objects.filter(delivery=self.delivery).exists())

    def test_reparto_remito_stays_open_until_rendition_closes_it(self):
        route_payload = self._preview_route()
        route = confirm_route(
            route_id=route_payload["id"],
            payload={"vehicle_id": str(self.vehicle.id), "driver_ref": "driver-1", "reviewed": True},
            idempotency_key="route-confirm",
            actor="planner",
        ).payload["result"]
        route = start_loading_route(route_id=route["id"], payload={}, idempotency_key="route-load", actor="dock").payload["result"]

        document = DeliveryDocument.objects.get(delivery=self.delivery)
        self.delivery.refresh_from_db()
        packed = InventoryBalance.objects.get(warehouse_ref="W001", item_ref="ITEM-R", stock_state=StockState.PACKED)
        transit = InventoryBalance.objects.get(warehouse_ref="W001", item_ref="ITEM-R", stock_state=StockState.IN_TRANSIT)
        self.assertEqual(document.status, DeliveryDocument.DocumentStatus.OPEN)
        self.assertEqual(self.delivery.status, DeliveryOrder.DeliveryStatus.LOADED)
        self.assertEqual(packed.quantity, Decimal("0"))
        self.assertEqual(transit.quantity, Decimal("3"))

        route = depart_route(route_id=route["id"], payload={}, idempotency_key="route-depart", actor="driver-1").payload["result"]
        stop_id = route["stops"][0]["id"]
        route = execute_delivery_stop(
            payload={"route_stop_id": stop_id, "status": "delivered_complete"},
            idempotency_key="route-execute",
            actor="driver-1",
        ).payload["result"]
        close_route(route_id=route["id"], payload={}, idempotency_key="route-close", actor="supervisor")

        document.refresh_from_db()
        self.delivery.refresh_from_db()
        self.fulfillment_line.refresh_from_db()
        delivered = InventoryBalance.objects.get(warehouse_ref="W001", item_ref="ITEM-R", stock_state=StockState.DELIVERED)
        transit.refresh_from_db()
        self.assertEqual(document.status, DeliveryDocument.DocumentStatus.CLOSED)
        self.assertEqual(self.delivery.status, DeliveryOrder.DeliveryStatus.DELIVERED_COMPLETE)
        self.assertEqual(self.fulfillment_line.delivered_qty, Decimal("3"))
        self.assertEqual(transit.quantity, Decimal("0"))
        self.assertEqual(delivered.quantity, Decimal("3"))

    def test_direct_remito_closes_immediately(self):
        self.delivery.delivery_mode = "Retiro en tienda"
        self.delivery.save(update_fields=["delivery_mode"])

        result = issue_remito(
            delivery_id=str(self.delivery.id),
            idempotency_key="direct-remito",
            actor="counter",
            authorized_warehouses=["W001"],
        )

        document = DeliveryDocument.objects.get(id=result.payload["result"]["id"])
        self.delivery.refresh_from_db()
        self.assertEqual(document.status, DeliveryDocument.DocumentStatus.CLOSED)
        self.assertEqual(self.delivery.status, DeliveryOrder.DeliveryStatus.DELIVERED_COMPLETE)


class TransferFlowTests(TestCase):
    def setUp(self):
        _reset_sequence("Transferencias", prefix="TR-")
        _reset_sequence("Despachos TR", prefix="DTR-")
        _reset_sequence("Recepciones TR", prefix="RTR-")
        InventoryBalance.objects.create(
            warehouse_ref="WH-A",
            item_ref="ITEM-T",
            lot_ref="",
            stock_state=StockState.ON_HAND,
            uom="UN",
            quantity=Decimal("5"),
        )

    def test_transfer_dispatch_and_partial_receive_moves_stock(self):
        transfer = create_transfer(
            payload={
                "origin_warehouse_ref": "WH-A",
                "destination_warehouse_ref": "WH-B",
                "lines": [{"item_ref": "ITEM-T", "requested_qty": "2", "uom": "UN"}],
            },
            idempotency_key="transfer-create",
            actor="requester",
        ).payload["result"]
        transfer_id = transfer["id"]
        approve_transfer(transfer_id=transfer_id, payload={}, idempotency_key="transfer-approve", actor="approver")
        prepare_transfer(transfer_id=transfer_id, payload={}, idempotency_key="transfer-prepare", actor="origin")
        dispatch_transfer(transfer_id=transfer_id, payload={}, idempotency_key="transfer-dispatch", actor="origin")

        origin_on_hand = InventoryBalance.objects.get(warehouse_ref="WH-A", item_ref="ITEM-T", stock_state=StockState.ON_HAND)
        transit = InventoryBalance.objects.get(warehouse_ref="WH-A", item_ref="ITEM-T", stock_state=StockState.IN_TRANSIT)
        self.assertEqual(origin_on_hand.quantity, Decimal("3"))
        self.assertEqual(transit.quantity, Decimal("2"))

        line = TransferOrder.objects.get(id=transfer_id).lines.get()
        receive_transfer(
            transfer_id=transfer_id,
            payload={"lines": [{"line_id": str(line.id), "received_qty": "1"}]},
            idempotency_key="transfer-receive",
            actor="dest",
        )
        line.refresh_from_db()
        destination_on_hand = InventoryBalance.objects.get(warehouse_ref="WH-B", item_ref="ITEM-T", stock_state=StockState.ON_HAND)
        transit.refresh_from_db()
        self.assertEqual(line.received_qty, Decimal("1"))
        self.assertEqual(line.difference_qty, Decimal("1"))
        self.assertEqual(destination_on_hand.quantity, Decimal("1"))
        self.assertEqual(transit.quantity, Decimal("1"))
