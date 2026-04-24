from django.views.decorators.http import require_GET

from apps.common.api import json_response
from apps.transfers.models import TransferOrder


@require_GET
def transfer_orders(request):
    qs = TransferOrder.objects.order_by("-created_at")
    if origin_warehouse := request.GET.get("origin_warehouse"):
        qs = qs.filter(origin_warehouse_ref=origin_warehouse)
    if destination_warehouse := request.GET.get("destination_warehouse"):
        qs = qs.filter(destination_warehouse_ref=destination_warehouse)
    if status := request.GET.get("status"):
        qs = qs.filter(status=status)
    if transfer_number := request.GET.get("transfer_number"):
        qs = qs.filter(transfer_number=transfer_number)
    rows = qs[:100]
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
