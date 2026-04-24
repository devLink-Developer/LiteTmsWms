from django.views.decorators.http import require_GET

from apps.common.api import json_response
from apps.routes.models import RouteSheet


@require_GET
def route_sheets(request):
    rows = RouteSheet.objects.select_related("vehicle", "vehicle__capacity_profile").order_by("-planned_date")[:100]
    return json_response(
        {
            "results": [
                {
                    "id": str(row.id),
                    "route_number": row.route_number,
                    "status": row.status,
                    "planned_date": row.planned_date.isoformat(),
                    "warehouse_ref": row.warehouse_ref,
                    "vehicle": row.vehicle.code if row.vehicle else None,
                    "planned_weight_kg": str(row.planned_weight_kg),
                    "planned_volume_m3": str(row.planned_volume_m3),
                }
                for row in rows
            ]
        }
    )
