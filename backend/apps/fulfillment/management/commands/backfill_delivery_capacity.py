from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.fulfillment.models import DeliveryOrder, DeliveryOrderLine
from apps.fulfillment.services import refresh_delivery_capacity_from_master
from apps.routes.models import RouteSheet


ZERO = Decimal("0")


class Command(BaseCommand):
    help = "Actualiza snapshots, peso y volumen de entregas desde materiales y recalcula hojas de ruta."

    def add_arguments(self, parser):
        parser.add_argument("--delivery-number", default="", help="Numero de entrega puntual.")
        parser.add_argument("--route-number", default="", help="Numero de hoja de ruta puntual.")

    def handle(self, *args, **options):
        delivery_number = str(options.get("delivery_number") or "").strip()
        route_number = str(options.get("route_number") or "").strip()

        deliveries = DeliveryOrder.objects.select_related("fulfillment").prefetch_related("lines")
        if delivery_number:
            deliveries = deliveries.filter(delivery_number=delivery_number)

        refreshed_deliveries = 0
        for delivery in deliveries.iterator(chunk_size=200):
            if refresh_delivery_capacity_from_master(delivery, actor="capacity-backfill"):
                refreshed_deliveries += 1

        routes = RouteSheet.objects.prefetch_related("stops__lines")
        if route_number:
            routes = routes.filter(route_number=route_number)

        refreshed_routes = 0
        for route in routes.iterator(chunk_size=100):
            if self._refresh_route(route):
                refreshed_routes += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Capacidad actualizada. entregas={refreshed_deliveries} hojas_ruta={refreshed_routes}"
            )
        )

    @transaction.atomic
    def _refresh_route(self, route: RouteSheet) -> bool:
        changed = False
        route_weight = ZERO
        route_volume = ZERO
        route = RouteSheet.objects.select_for_update().prefetch_related("stops__lines").get(id=route.id)

        for stop in route.stops.select_for_update().all():
            stop_weight = ZERO
            stop_volume = ZERO
            for line in stop.lines.select_for_update().all():
                delivery_line = None
                if line.source_line_ref:
                    delivery_line = DeliveryOrderLine.objects.filter(id=line.source_line_ref).first()
                if delivery_line is not None:
                    if line.weight_kg != delivery_line.planned_weight_kg or line.volume_m3 != delivery_line.planned_volume_m3:
                        line.weight_kg = delivery_line.planned_weight_kg
                        line.volume_m3 = delivery_line.planned_volume_m3
                        line.updated_by = "capacity-backfill"
                        line.save(update_fields=["weight_kg", "volume_m3", "updated_by", "updated_at"])
                        changed = True
                stop_weight += line.weight_kg
                stop_volume += line.volume_m3

            if stop.planned_weight_kg != stop_weight or stop.planned_volume_m3 != stop_volume:
                stop.planned_weight_kg = stop_weight
                stop.planned_volume_m3 = stop_volume
                stop.updated_by = "capacity-backfill"
                stop.save(update_fields=["planned_weight_kg", "planned_volume_m3", "updated_by", "updated_at"])
                changed = True

            route_weight += stop_weight
            route_volume += stop_volume

        if route.planned_weight_kg != route_weight or route.planned_volume_m3 != route_volume:
            route.planned_weight_kg = route_weight
            route.planned_volume_m3 = route_volume
            route.updated_by = "capacity-backfill"
            route.save(update_fields=["planned_weight_kg", "planned_volume_m3", "updated_by", "updated_at"])
            changed = True

        return changed
