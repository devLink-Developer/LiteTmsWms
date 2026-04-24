from django.views.decorators.http import require_GET

from apps.common.api import json_response
from apps.dispatch.models import StoreDispatch


@require_GET
def dispatches(request):
    rows = StoreDispatch.objects.order_by("-created_at")[:100]
    return json_response(
        {
            "results": [
                {
                    "id": str(row.id),
                    "dispatch_number": row.dispatch_number,
                    "status": row.status,
                    "customer_ref": row.customer_ref,
                    "warehouse_ref": row.warehouse_ref,
                }
                for row in rows
            ]
        }
    )
