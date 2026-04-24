from django.views.decorators.http import require_GET

from apps.common.api import json_response
from apps.vehicles.models import Vehicle


@require_GET
def vehicles(request):
    rows = Vehicle.objects.select_related("capacity_profile").order_by("code")[:100]
    return json_response(
        {
            "results": [
                {
                    "id": str(row.id),
                    "code": row.code,
                    "plate": row.plate,
                    "status": row.status,
                    "max_weight_kg": str(row.capacity_profile.max_weight_kg),
                    "max_volume_m3": str(row.capacity_profile.max_volume_m3),
                }
                for row in rows
            ]
        }
    )
