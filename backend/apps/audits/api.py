from django.views.decorators.http import require_GET

from apps.audits.models import WarehouseAudit
from apps.common.api import json_response


@require_GET
def audits(request):
    rows = WarehouseAudit.objects.order_by("-created_at")[:100]
    return json_response(
        {
            "results": [
                {
                    "id": str(row.id),
                    "audit_number": row.audit_number,
                    "warehouse_ref": row.warehouse_ref,
                    "status": row.status,
                    "blind_count": row.blind_count,
                }
                for row in rows
            ]
        }
    )
