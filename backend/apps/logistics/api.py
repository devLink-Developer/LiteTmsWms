from django.conf import settings
from django.db.models import Q
from django.http import HttpRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from apps.common.api import error_response, json_response, parse_json_body, require_idempotency_key
from apps.fulfillment.models import DeliveryDocument, DeliveryOrder, FulfillmentOrder
from apps.inventory.models import InventoryBalance
from apps.logistics.models import WarehouseLocation, WarehouseMaster
from apps.logistics.dashboard import build_operational_dashboard
from apps.logistics.parquet_master_data import (
    MasterDataSourceError,
    calculate_sheet_cutting_plan,
    employee_delivery_permissions,
    list_sheet_cutting_options,
    list_materials,
    list_stores,
    list_warehouses,
)
from apps.logistics.services import (
    LogisticsRuleError,
    generate_default_locations,
    serialize_location,
    serialize_warehouse,
    sync_warehouse_from_master_data_row,
    upsert_warehouse,
)


def _request_actor(request: HttpRequest) -> str:
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user.get_username()
    return (
        request.headers.get("X-Actor", "")
        or request.headers.get("X-User", "")
        or request.headers.get("X-User-Email", "")
        or settings.TMSWMS_DEFAULT_ACTOR
        or ""
    ).strip()


def _logistics_error_response(exc: Exception):
    if isinstance(exc, LogisticsRuleError):
        return error_response("business_rule_violation", str(exc), status=422)
    if isinstance(exc, WarehouseMaster.DoesNotExist):
        return error_response("not_found", "Almacen no encontrado.", status=404)
    if isinstance(exc, PermissionError):
        return error_response("forbidden", str(exc), status=403)
    if isinstance(exc, ValueError):
        return error_response("validation_error", str(exc), status=400)
    return error_response("server_error", str(exc), status=500)


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
def operational_dashboard(request: HttpRequest):
    try:
        return json_response(build_operational_dashboard(request, actor=_request_actor(request)))
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)


@require_GET
def operational_context(request: HttpRequest):
    actor = _request_actor(request)
    try:
        delivery_permissions = employee_delivery_permissions(actor)
    except MasterDataSourceError as exc:
        return json_response({"error": {"code": "master_data_unavailable", "message": str(exc), "details": {}}}, status=503)

    employee = delivery_permissions.get("employee") or {}
    warehouses = delivery_permissions.get("authorized_warehouses") or []
    session_active = str(request.session.get("active_warehouse_ref", "") if hasattr(request, "session") else "").strip()
    active_warehouse = session_active if session_active in warehouses else warehouses[0] if warehouses else "sin-warehouse"
    return json_response(
        {
            "warehouse_ref": active_warehouse,
            "branch_ref": employee.get("branch_ref") or "sin-sucursal",
            "role": employee.get("name") or actor or "Sin usuario operativo",
            "permissions": delivery_permissions.get("permissions") or [],
            "authorized_warehouses": warehouses,
            "employee": employee,
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def active_warehouse(request: HttpRequest):
    actor = _request_actor(request)
    if not actor:
        return error_response("forbidden", "No hay usuario operativo.", status=403)
    payload = parse_json_body(request)
    warehouse_ref = str(payload.get("warehouse_ref") or "").strip()
    if not warehouse_ref:
        return error_response("validation_error", "warehouse_ref es obligatorio.", status=400)
    try:
        permissions = employee_delivery_permissions(actor)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    authorized = {str(warehouse).strip() for warehouse in (permissions.get("authorized_warehouses") or []) if str(warehouse).strip()}
    if warehouse_ref not in authorized:
        return error_response("forbidden", "El almacen no esta autorizado para el usuario.", status=403)
    request.session["active_warehouse_ref"] = warehouse_ref
    request.session["authorized_warehouses"] = sorted(authorized)
    request.session.modified = True
    employee = permissions.get("employee") or {}
    return json_response(
        {
            "warehouse_ref": warehouse_ref,
            "branch_ref": employee.get("branch_ref") or "sin-sucursal",
            "role": employee.get("name") or actor,
            "permissions": permissions.get("permissions") or [],
            "authorized_warehouses": sorted(authorized),
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


@csrf_exempt
@require_http_methods(["GET", "POST"])
def warehouses(request: HttpRequest):
    if request.method == "POST":
        try:
            result = upsert_warehouse(
                payload=parse_json_body(request),
                idempotency_key=require_idempotency_key(request),
                actor=_request_actor(request) or "system",
            )
            return json_response(result.payload, status=result.status)
        except Exception as exc:
            return _logistics_error_response(exc)

    qs = WarehouseMaster.objects.order_by("warehouse_ref")
    if active := request.GET.get("active", "").strip().casefold():
        if active in {"1", "true", "yes", "si", "s"}:
            qs = qs.filter(active=True)
        elif active in {"0", "false", "no", "n"}:
            qs = qs.filter(active=False)
    if store_ref := request.GET.get("store", "").strip():
        qs = qs.filter(store_ref=store_ref)
    if query := request.GET.get("q", "").strip():
        qs = qs.filter(Q(warehouse_ref__icontains=query) | Q(name__icontains=query) | Q(store_ref__icontains=query))
    try:
        limit = min(max(int(request.GET.get("limit", "300")), 1), 1000)
    except ValueError:
        return error_response("validation_error", "limit debe ser numerico.", status=400)
    rows = qs[:limit]
    return json_response({"results": [serialize_warehouse(row) for row in rows]})


@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def warehouse_detail(request: HttpRequest, warehouse_ref: str):
    if request.method == "PATCH":
        try:
            result = upsert_warehouse(
                payload=parse_json_body(request),
                idempotency_key=require_idempotency_key(request),
                actor=_request_actor(request) or "system",
                warehouse_ref=warehouse_ref,
            )
            return json_response(result.payload, status=result.status)
        except Exception as exc:
            return _logistics_error_response(exc)
    try:
        warehouse = WarehouseMaster.objects.get(warehouse_ref=warehouse_ref)
    except Exception as exc:
        return _logistics_error_response(exc)
    return json_response({"result": serialize_warehouse(warehouse, include_locations=True)})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def warehouse_locations(request: HttpRequest, warehouse_ref: str):
    if request.method == "POST":
        try:
            locations = generate_default_locations(
                warehouse_ref=warehouse_ref,
                actor=_request_actor(request) or "system",
                layout=parse_json_body(request).get("layout"),
            )
            return json_response({"results": [serialize_location(row) for row in locations]}, status=201)
        except Exception as exc:
            return _logistics_error_response(exc)

    qs = WarehouseLocation.objects.filter(warehouse_ref=warehouse_ref).order_by("sort_order", "location_ref")
    if active := request.GET.get("active", "").strip().casefold():
        if active in {"1", "true", "yes", "si", "s"}:
            qs = qs.filter(active=True)
        elif active in {"0", "false", "no", "n"}:
            qs = qs.filter(active=False)
    if purpose := request.GET.get("purpose", "").strip():
        qs = qs.filter(purpose=purpose)
    return json_response({"results": [serialize_location(row) for row in qs[:1000]]})


@csrf_exempt
@require_http_methods(["POST"])
def warehouse_locations_generate(request: HttpRequest, warehouse_ref: str):
    try:
        locations = generate_default_locations(
            warehouse_ref=warehouse_ref,
            actor=_request_actor(request) or "system",
            layout=parse_json_body(request).get("layout"),
        )
        return json_response({"results": [serialize_location(row) for row in locations]}, status=201)
    except Exception as exc:
        return _logistics_error_response(exc)


@csrf_exempt
@require_http_methods(["POST"])
def warehouses_sync(request: HttpRequest):
    actor = _request_actor(request) or "system"
    try:
        payload = list_warehouses(limit=1000)
        rows = [sync_warehouse_from_master_data_row(row, actor=actor) for row in payload.get("results", [])]
    except (MasterDataSourceError, ValueError) as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    except Exception as exc:
        return _logistics_error_response(exc)
    return json_response({"results": [serialize_warehouse(row) for row in rows], "source_file": payload.get("source_file")})


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


@require_GET
def master_sheet_cutting_options(request: HttpRequest):
    try:
        payload = list_sheet_cutting_options(
            store=request.GET.get("store", "").strip(),
            category=request.GET.get("category", "").strip(),
            query=request.GET.get("q", "").strip(),
            limit=int(request.GET.get("limit", "200")),
        )
    except (MasterDataSourceError, ValueError) as exc:
        return json_response({"error": {"code": "master_data_unavailable", "message": str(exc), "details": {}}}, status=503)
    return json_response(payload)


@csrf_exempt
@require_http_methods(["POST"])
def master_sheet_cutting_plan(request: HttpRequest):
    try:
        payload = parse_json_body(request)
        result = calculate_sheet_cutting_plan(
            store=str(payload.get("store") or "").strip(),
            category=str(payload.get("category") or "").strip(),
            source_item_ref=str(payload.get("source_item_ref") or "").strip(),
            source_length_cm=payload.get("source_length_cm"),
            source_quantity=payload.get("source_quantity") or 1,
            cuts=payload.get("cuts") or [],
        )
    except MasterDataSourceError as exc:
        return json_response({"error": {"code": "master_data_unavailable", "message": str(exc), "details": {}}}, status=503)
    except ValueError as exc:
        return error_response("validation_error", str(exc), status=400)
    return json_response({"result": result})
