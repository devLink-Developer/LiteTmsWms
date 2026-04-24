from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.routes.models import RouteSheet


class RouteCapacityError(ValueError):
    pass


@transaction.atomic
def validate_route_capacity(route: RouteSheet, *, allow_override: bool = False) -> RouteSheet:
    if not route.vehicle:
        raise RouteCapacityError("La hoja de ruta no tiene vehiculo asignado.")
    profile = route.vehicle.capacity_profile
    stops = route.stops.select_for_update().all()
    planned_weight = sum((stop.planned_weight_kg for stop in stops), Decimal("0"))
    planned_volume = sum((stop.planned_volume_m3 for stop in stops), Decimal("0"))
    route.planned_weight_kg = planned_weight
    route.planned_volume_m3 = planned_volume
    if (planned_weight > profile.max_weight_kg or planned_volume > profile.max_volume_m3) and not allow_override:
        route.save(update_fields=["planned_weight_kg", "planned_volume_m3", "updated_at"])
        raise RouteCapacityError("La hoja de ruta excede la capacidad del vehiculo.")
    route.status = RouteSheet.RouteStatus.CAPACITY_CHECKED
    route.save(update_fields=["planned_weight_kg", "planned_volume_m3", "status", "updated_at"])
    return route
