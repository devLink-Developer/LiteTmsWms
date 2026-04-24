from django.views.decorators.http import require_GET

from apps.common.api import json_response
from apps.transfers.models import TransferOrder


@require_GET
def transfer_orders(request):
    rows = TransferOrder.objects.order_by("-created_at")[:100]
    return json_response(
        {
            "results": [
                {
                    "id": str(row.id),
                    "transfer_number": row.transfer_number,
                    "status": row.status,
                    "origin_warehouse_ref": row.origin_warehouse_ref,
                    "destination_warehouse_ref": row.destination_warehouse_ref,
                }
                for row in rows
            ]
        }
    )
