from django.conf import settings
from django.http import HttpRequest
from django.views.decorators.http import require_GET

from apps.common.api import json_response
from apps.fulfillment.models import DeliveryDocument, DeliveryOrder, FulfillmentOrder
from apps.inventory.models import InventoryBalance
from apps.logistics.parquet_master_data import (
    MasterDataSourceError,
    employee_delivery_permissions,
    list_materials,
    list_stores,
    list_warehouses,
)


@require_GET
def healthcheck(request: HttpRequest):
    return json_response(
        {
            "status": "ok",
            "service": "lite-tms-wms",
            "api_version": "v1",
            "stack": {
                "backend": "Django 6.0.1",
                "frontend": "React 19.2.4 + Vite 8.x",
            },
        }
    )


@require_GET
def operational_overview(request: HttpRequest):
    fulfillment_count = FulfillmentOrder.objects.count()
    delivery_count = DeliveryOrder.objects.count()
    remito_count = DeliveryDocument.objects.filter(document_type=DeliveryDocument.DocumentType.REMITO).count()
    inventory_count = InventoryBalance.objects.count()
    return json_response(
        {
            "modules": [
                "inventory",
                "receipts",
                "transfers",
                "fulfillment",
                "deliveries",
                "routes",
                "vehicles",
                "audits",
                "dispatch",
                "shipping",
            ],
            "principles": [
                f"tmswms.fulfillment_orders={fulfillment_count}",
                f"tmswms.delivery_orders={delivery_count}",
                f"tmswms.remitos={remito_count}",
                f"tmswms.inventory_balances={inventory_count}",
            ],
        }
    )


@require_GET
def operational_context(request: HttpRequest):
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        actor = user.get_username()
    else:
        actor = (
            request.headers.get("X-Actor", "")
            or request.headers.get("X-User", "")
            or request.headers.get("X-User-Email", "")
            or settings.TMSWMS_DEFAULT_ACTOR
            or ""
        ).strip()
    try:
        delivery_permissions = employee_delivery_permissions(actor)
    except MasterDataSourceError as exc:
        return json_response({"error": {"code": "master_data_unavailable", "message": str(exc), "details": {}}}, status=503)

    employee = delivery_permissions.get("employee") or {}
    warehouses = delivery_permissions.get("authorized_warehouses") or []
    return json_response(
        {
            "warehouse_ref": warehouses[0] if warehouses else "sin-warehouse",
            "branch_ref": employee.get("branch_ref") or "sin-sucursal",
            "role": employee.get("name") or actor or "Sin usuario operativo",
            "permissions": delivery_permissions.get("permissions") or [],
            "authorized_warehouses": warehouses,
            "employee": employee,
        }
    )


@require_GET
def master_stores(request: HttpRequest):
    try:
        payload = list_stores(
            query=request.GET.get("q", "").strip(),
            active=request.GET.get("active", "").strip(),
            limit=int(request.GET.get("limit", "200")),
        )
    except (MasterDataSourceError, ValueError) as exc:
        return json_response({"error": {"code": "master_data_unavailable", "message": str(exc), "details": {}}}, status=503)
    return json_response(payload)


@require_GET
def master_warehouses(request: HttpRequest):
    try:
        payload = list_warehouses(
            store=request.GET.get("store", "").strip(),
            query=request.GET.get("q", "").strip(),
            limit=int(request.GET.get("limit", "500")),
        )
    except (MasterDataSourceError, ValueError) as exc:
        return json_response({"error": {"code": "master_data_unavailable", "message": str(exc), "details": {}}}, status=503)
    return json_response(payload)


@require_GET
def master_materials(request: HttpRequest):
    try:
        payload = list_materials(
            store=request.GET.get("store", "").strip(),
            query=request.GET.get("q", "").strip(),
            limit=int(request.GET.get("limit", "100")),
        )
    except (MasterDataSourceError, ValueError) as exc:
        return json_response({"error": {"code": "master_data_unavailable", "message": str(exc), "details": {}}}, status=503)
    return json_response(payload)
