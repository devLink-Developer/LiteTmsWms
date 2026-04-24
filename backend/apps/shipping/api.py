from django.views.decorators.http import require_GET

from apps.common.api import json_response
from apps.shipping.models import Shipment


@require_GET
def shipments(request):
    rows = Shipment.objects.order_by("-created_at")[:100]
    return json_response(
        {
            "results": [
                {
                    "id": str(row.id),
                    "shipment_number": row.shipment_number,
                    "status": row.status,
                    "delivery_ref": row.delivery_ref,
                    "route_ref": row.route_ref,
                }
                for row in rows
            ]
        }
    )
