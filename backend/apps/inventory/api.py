from __future__ import annotations

from decimal import Decimal

from django.db.models import Q, Sum
from django.http import HttpRequest
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.common.api import error_response, json_response, parse_json_body, require_idempotency_key
from apps.inventory.models import InventoryBalance, InventoryLedgerEntry, InventoryWriteOff, PurchaseOrderReceipt, StockState
from apps.inventory.services import (
    InventoryRuleError,
    adjust_inventory_manually,
    create_inventory_write_off,
    execute_inventory_exchange,
    execute_sheet_cutting,
    move_inventory_between_locations,
    post_inventory_write_off,
    receive_purchase_order,
    reserve_inventory,
    reverse_inventory_write_off,
    serialize_ledger_entry,
    serialize_receipt,
    serialize_transformation,
    serialize_write_off,
    validate_sheet_cutting_stock,
)
from apps.logistics.models import MaterialMasterSnapshot
from apps.logistics.models import WarehouseLocation
from apps.logistics.parquet_master_data import (
    MasterDataSourceError,
    employee_delivery_permissions,
    fulfillment_warehouse_codes_for_stores,
)


def _decimal(value: Decimal) -> str:
    if value == value.to_integral_value():
        return format(value.quantize(Decimal("1")), "f")
    return format(value.normalize(), "f")


def _query_alias(request: HttpRequest, *names: str) -> str:
    for name in names:
        value = request.GET.get(name)
        if value:
            return value
    return ""


def _limit(value: str | None, default: int = 500, maximum: int = 2000) -> int:
    try:
        parsed = int(value or default)
    except ValueError:
        parsed = default
    return min(max(parsed, 1), maximum)


def _parse_local_datetime(value: str):
    if "T" not in value and " " not in value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _iso_datetime(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _clean(value) -> str:
    return str(value or "").strip()


def _contains(value, query: str) -> bool:
    query = query.strip().casefold()
    if not query:
        return True
    return query in _clean(value).casefold()


def _request_actor(request: HttpRequest) -> str:
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user.get_username()
    return (
        request.headers.get("X-Actor", "")
        or request.headers.get("X-User", "")
        or request.headers.get("X-User-Email", "")
    ).strip()


def _session_authorized_warehouses(request: HttpRequest) -> list[str]:
    warehouses = request.session.get("authorized_warehouses") if hasattr(request, "session") else []
    return [str(warehouse).strip() for warehouse in (warehouses or []) if str(warehouse).strip()]


def _active_warehouse_ref(request: HttpRequest) -> str:
    active = str(request.session.get("active_warehouse_ref", "") if hasattr(request, "session") else "").strip()
    if active:
        return active
    session_warehouses = _session_authorized_warehouses(request)
    if session_warehouses:
        return session_warehouses[0]
    try:
        authorized = _stock_authorized_warehouses(request) or []
    except MasterDataSourceError:
        authorized = []
    return authorized[0] if authorized else ""


def _ensure_active_warehouse_payload(request: HttpRequest, payload: dict) -> dict:
    return _ensure_active_warehouse_operation_payload(request, payload, operation_label="baja")


def _ensure_active_warehouse_operation_payload(request: HttpRequest, payload: dict, *, operation_label: str) -> dict:
    active_warehouse = _active_warehouse_ref(request)
    if not active_warehouse:
        raise InventoryRuleError("No hay almacen activo para operar stock.")
    requested = str(payload.get("warehouse_ref") or "").strip()
    if requested and requested != active_warehouse:
        raise PermissionError(f"La {operation_label} solo se permite en el almacen activo.")
    return {**payload, "warehouse_ref": active_warehouse}


def _stock_authorized_warehouses(request: HttpRequest) -> list[str] | None:
    actor = _request_actor(request)
    if not actor:
        return None
    permissions = employee_delivery_permissions(actor)
    employee = permissions.get("employee") or {}
    store_codes = {
        str(code or "").strip()
        for code in (employee.get("store_codes") or [employee.get("branch_ref")])
        if str(code or "").strip()
    }
    return sorted(fulfillment_warehouse_codes_for_stores(store_codes))


def _forbidden_stock_response():
    return error_response(
        "forbidden",
        "El usuario no tiene almacenes del grupo de cumplimiento autorizados para visualizar stock.",
        status=403,
    )


def _apply_stock_warehouse_scope(request: HttpRequest, qs):
    session_warehouses = _session_authorized_warehouses(request)
    authorized_warehouses = session_warehouses if session_warehouses else _stock_authorized_warehouses(request)
    if authorized_warehouses is None:
        return qs, None, []
    if not authorized_warehouses:
        return qs.none(), _forbidden_stock_response(), []
    requested_warehouse = _query_alias(request, "warehouse", "warehouse_ref").strip()
    if requested_warehouse and requested_warehouse not in authorized_warehouses:
        return qs.none(), _forbidden_stock_response(), authorized_warehouses
    return qs.filter(warehouse_ref__in=authorized_warehouses), None, authorized_warehouses


def _inventory_error_response(exc: Exception):
    if isinstance(exc, InventoryWriteOff.DoesNotExist):
        return error_response("not_found", "Baja de inventario no encontrada.", status=404)
    if isinstance(exc, InventoryRuleError):
        return error_response("business_rule_violation", str(exc), status=422)
    if isinstance(exc, PermissionError):
        return error_response("forbidden", str(exc), status=403)
    if isinstance(exc, ValueError):
        return error_response("validation_error", str(exc), status=400)
    return error_response("server_error", str(exc), status=500)


ADVANCED_STOCK_STATES = {
    StockState.ON_HAND: ("available", "Disponible"),
    StockState.RESERVED: ("reserved", "Reservado"),
    StockState.PICKING: ("in_preparation", "En Preparacion"),
    StockState.PACKED: ("prepared", "Preparado"),
    StockState.IN_TRANSIT: ("in_transit", "En Transito"),
    StockState.SCRAPPED: ("damaged_waste", "Roto/Merma"),
}

ADVANCED_STOCK_STATE_ALIASES = {
    "available": StockState.ON_HAND,
    "on_hand": StockState.ON_HAND,
    "reserved": StockState.RESERVED,
    "in_preparation": StockState.PICKING,
    "picking": StockState.PICKING,
    "prepared": StockState.PACKED,
    "packed": StockState.PACKED,
    "in_transit": StockState.IN_TRANSIT,
    "transit": StockState.IN_TRANSIT,
    "damaged_waste": StockState.SCRAPPED,
    "scrapped": StockState.SCRAPPED,
}


def _empty_advanced_quantities() -> dict[str, Decimal]:
    quantities = {key: Decimal("0") for key, _label in ADVANCED_STOCK_STATES.values()}
    quantities["total"] = Decimal("0")
    return quantities


def _enrich_advanced_stock_rows(rows: list[dict]) -> None:
    item_refs = {row["item_ref"] for row in rows if row.get("item_ref")}
    if not item_refs:
        return
    snapshots = _cached_material_snapshots_for_items(item_refs)
    for row in rows:
        snapshot = snapshots.get(row["item_ref"]) or {}
        item_name = _clean(snapshot.get("name") or snapshot.get("long_name"))
        category = _clean(snapshot.get("category"))
        row["item_name"] = item_name
        row["item_long_name"] = _clean(snapshot.get("long_name") or item_name)
        row["category_ref"] = category
        row["category"] = category
        row["rubro_ref"] = category
        row["coverage_group"] = _clean(snapshot.get("coverage_group"))
        row["item_uom"] = _clean(snapshot.get("uom") or snapshot.get("uom_code"))


def _enrich_location_metadata(rows: list[dict]) -> None:
    keys = {
        (row.get("warehouse_ref") or "", row.get("location_ref") or "")
        for row in rows
        if row.get("warehouse_ref") and row.get("location_ref")
    }
    if not keys:
        return
    warehouses = {warehouse for warehouse, _location in keys}
    locations = {
        (row.warehouse_ref, row.location_ref): row
        for row in WarehouseLocation.objects.filter(warehouse_ref__in=warehouses, location_ref__in={location for _warehouse, location in keys})
    }
    for row in rows:
        location = locations.get((row.get("warehouse_ref") or "", row.get("location_ref") or ""))
        row["location_name"] = location.name if location else row.get("location_name") or ""
        row["purpose"] = location.purpose if location else row.get("purpose") or ""
        row["zone_ref"] = location.zone_ref if location else row.get("zone_ref") or ""
        row["aisle"] = location.aisle if location else row.get("aisle") or ""
        row["floor"] = location.floor if location else row.get("floor") or ""
        row["level"] = location.level if location else row.get("level") or ""
        row["position"] = location.position if location else row.get("position") or ""
        row["is_dispatchable"] = bool(location.is_dispatchable) if location else bool(row.get("is_dispatchable"))
        row["is_reservable"] = bool(location.is_reservable) if location else bool(row.get("is_reservable"))
        row["is_pickable"] = bool(location.is_pickable) if location else bool(row.get("is_pickable"))
        row["allows_scrap"] = bool(location.allows_scrap) if location else bool(row.get("allows_scrap"))
        row["system_location"] = bool(location.system_location) if location else bool(row.get("system_location"))
        row["warehouse_location_ref"] = row.get("warehouse_location_ref") or row.get("location_ref") or ""


def _advanced_stock_row_matches(row: dict, request: HttpRequest) -> bool:
    item_query = _query_alias(request, "item", "item_ref", "product").strip()
    category_query = _query_alias(request, "category", "category_ref", "rubro", "rubro_ref").strip()
    supplier_query = _query_alias(request, "supplier", "supplier_ref").strip()
    search_query = _query_alias(request, "search", "q").strip()
    if item_query and not any(
        _contains(row.get(field), item_query)
        for field in ["item_ref", "item_name", "item_long_name"]
    ):
        return False
    if category_query and not any(
        _contains(row.get(field), category_query)
        for field in ["category_ref", "category", "rubro_ref", "coverage_group"]
    ):
        return False
    if supplier_query and not _contains(row.get("supplier_ref"), supplier_query):
        return False
    if search_query and not any(
        _contains(row.get(field), search_query)
        for field in [
            "warehouse_ref",
            "item_ref",
            "item_name",
            "item_long_name",
            "category_ref",
            "coverage_group",
            "lot_ref",
            "location_ref",
            "location_name",
            "warehouse_location_ref",
        ]
    ):
        return False
    return True


def _serialize_material_snapshot(row: MaterialMasterSnapshot) -> dict:
    return {
        "item_ref": row.item_ref,
        "sap_code": row.sap_code,
        "sap_item_id": row.sap_item_id,
        "name": row.name,
        "long_name": row.long_name,
        "category": row.category,
        "coverage_group": row.coverage_group,
        "uom": row.uom,
        "uom_code": row.uom_code,
    }


@require_GET
def materials(request: HttpRequest):
    query = _query_alias(request, "q", "search", "item", "item_ref").strip()
    if not query:
        return json_response({"results": []})
    limit = _limit(request.GET.get("limit"), default=50, maximum=200)
    qs = (
        MaterialMasterSnapshot.objects.filter(
            Q(item_ref__icontains=query)
            | Q(sap_code__icontains=query)
            | Q(sap_item_id__icontains=query)
            | Q(name__icontains=query)
            | Q(long_name__icontains=query)
            | Q(category__icontains=query)
        )
        .order_by("item_ref", "store_ref")
        .only("item_ref", "sap_code", "sap_item_id", "name", "long_name", "category", "coverage_group", "uom", "uom_code")
    )
    rows = []
    seen_refs = set()
    for row in qs[: limit * 3]:
        if row.item_ref in seen_refs:
            continue
        seen_refs.add(row.item_ref)
        rows.append(_serialize_material_snapshot(row))
        if len(rows) >= limit:
            break
    return json_response({"results": rows})


def _cached_material_snapshots_for_items(item_refs: set[str]) -> dict[str, dict]:
    if not item_refs:
        return {}
    snapshots: dict[str, dict] = {}
    for row in (
        MaterialMasterSnapshot.objects.filter(item_ref__in=item_refs)
        .order_by("store_ref", "item_ref")
        .only("item_ref", "sap_code", "sap_item_id", "name", "long_name", "category", "coverage_group", "uom", "uom_code")
    ):
        snapshots.setdefault(row.item_ref, _serialize_material_snapshot(row))
    return snapshots


def _material_refs_for_query(query: str) -> set[str]:
    query = query.strip()
    if not query:
        return set()
    snapshot_filter = (
        Q(item_ref__icontains=query)
        | Q(sap_code__icontains=query)
        | Q(sap_item_id__icontains=query)
        | Q(name__icontains=query)
        | Q(long_name__icontains=query)
        | Q(category__icontains=query)
    )
    refs = set(
        MaterialMasterSnapshot.objects.filter(snapshot_filter)
        .values_list("item_ref", flat=True)
        .distinct()[:500]
    )
    return refs


@require_GET
def balances(request: HttpRequest):
    qs = InventoryBalance.objects.all().order_by("warehouse_ref", "item_ref", "stock_state")
    try:
        qs, forbidden, authorized_warehouses = _apply_stock_warehouse_scope(request, qs)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    if forbidden is not None:
        return forbidden
    if warehouse := request.GET.get("warehouse"):
        qs = qs.filter(warehouse_ref=warehouse)
    if item := request.GET.get("item"):
        qs = qs.filter(item_ref=item)
    if state := _query_alias(request, "state", "stock_state"):
        qs = qs.filter(stock_state=state)
    if location_ref := _query_alias(request, "location", "location_ref"):
        qs = qs.filter(Q(location_ref=location_ref) | Q(lot_ref=location_ref))
    data = [
        {
            "id": str(row.id),
            "warehouse_ref": row.warehouse_ref,
            "warehouse_location_ref": row.location_ref or row.lot_ref,
            "location_ref": row.location_ref,
            "location_ref_is_fallback": not bool(row.location_ref) and bool(row.lot_ref),
            "item_ref": row.item_ref,
            "lot_ref": row.lot_ref,
            "stock_state": row.stock_state,
            "quantity": _decimal(row.quantity),
            "uom": row.uom,
            "version": row.version,
        }
        for row in qs[: _limit(request.GET.get("limit"))]
    ]
    return json_response({"results": data, "allowed_warehouses": authorized_warehouses})


@require_GET
def advanced_stock(request: HttpRequest):
    qs = InventoryBalance.objects.filter(stock_state__in=tuple(ADVANCED_STOCK_STATES)).order_by(
        "warehouse_ref",
        "location_ref",
        "item_ref",
        "lot_ref",
        "uom",
    )
    try:
        qs, forbidden, authorized_warehouses = _apply_stock_warehouse_scope(request, qs)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    if forbidden is not None:
        return forbidden
    if warehouse := _query_alias(request, "warehouse", "warehouse_ref"):
        qs = qs.filter(warehouse_ref=warehouse)
    if state := _query_alias(request, "state", "stock_state"):
        requested_states = [
            ADVANCED_STOCK_STATE_ALIASES.get(part.strip().casefold(), part.strip())
            for part in state.split(",")
            if part.strip()
        ]
        requested_states = [state for state in requested_states if state in ADVANCED_STOCK_STATES]
        qs = qs.filter(stock_state__in=requested_states) if requested_states else qs.none()
    location_scope = _query_alias(request, "location_scope", "locationScope").strip().casefold()
    if location_scope == "available":
        location_qs = WarehouseLocation.objects.filter(active=True, is_dispatchable=True)
        if warehouse:
            location_qs = location_qs.filter(warehouse_ref=warehouse)
        elif authorized_warehouses:
            location_qs = location_qs.filter(warehouse_ref__in=authorized_warehouses)
        available_refs = list(location_qs.values_list("location_ref", flat=True).distinct())
        qs = qs.filter(location_ref__in=available_refs) if available_refs else qs.none()
    if lot_ref := _query_alias(request, "lot", "lot_ref", "location", "location_ref"):
        if location_scope == "available":
            qs = qs.filter(location_ref=lot_ref)
        else:
            qs = qs.filter(Q(location_ref=lot_ref) | Q(lot_ref=lot_ref))
    item_query = _query_alias(request, "item", "item_ref", "product").strip()
    category_query = _query_alias(request, "category", "category_ref", "rubro", "rubro_ref").strip()
    search_query = _query_alias(request, "search", "q").strip()
    supplier_query = _query_alias(request, "supplier", "supplier_ref").strip()
    metadata_filter_active = any([item_query, category_query, search_query, supplier_query])
    if item_query:
        material_refs = _material_refs_for_query(item_query)
        item_filter = Q(item_ref__icontains=item_query)
        if material_refs:
            item_filter |= Q(item_ref__in=material_refs)
        qs = qs.filter(item_filter)
    if category_query:
        category_refs = _material_refs_for_query(category_query)
        qs = qs.filter(item_ref__in=category_refs) if category_refs else qs.none()
    if search_query:
        search_refs = _material_refs_for_query(search_query)
        search_filter = (
            Q(warehouse_ref__icontains=search_query)
            | Q(item_ref__icontains=search_query)
            | Q(location_ref__icontains=search_query)
            | Q(lot_ref__icontains=search_query)
        )
        if search_refs:
            search_filter |= Q(item_ref__in=search_refs)
        qs = qs.filter(search_filter)
    rows = (
        qs.values("warehouse_ref", "location_ref", "item_ref", "lot_ref", "uom", "stock_state")
        .annotate(quantity=Sum("quantity"))
        .order_by("warehouse_ref", "location_ref", "item_ref", "lot_ref", "uom", "stock_state")
    )

    grouped: dict[tuple[str, str, str, str, str], dict] = {}
    for row in rows:
        location_ref = row["location_ref"] or ""
        warehouse_location_ref = location_ref or row["lot_ref"] or ""
        key = (
            row["warehouse_ref"],
            location_ref,
            row["item_ref"],
            row["lot_ref"] or "",
            row["uom"],
        )
        bucket = grouped.setdefault(
            key,
            {
                "warehouse_ref": row["warehouse_ref"],
                "item_ref": row["item_ref"],
                "lot_ref": row["lot_ref"] or "",
                "location_ref": location_ref,
                "warehouse_location_ref": warehouse_location_ref,
                "location_ref_is_fallback": not bool(location_ref) and bool(row["lot_ref"]),
                "location_name": "",
                "purpose": "",
                "zone_ref": "",
                "aisle": "",
                "floor": "",
                "level": "",
                "position": "",
                "is_dispatchable": False,
                "is_reservable": False,
                "is_pickable": False,
                "allows_scrap": False,
                "system_location": False,
                "uom": row["uom"],
                "quantities": _empty_advanced_quantities(),
            },
        )
        state_key, _label = ADVANCED_STOCK_STATES[row["stock_state"]]
        quantity = row["quantity"] or Decimal("0")
        bucket["quantities"][state_key] += quantity
        bucket["quantities"]["total"] += quantity

    grouped_rows = list(grouped.values())
    limit = _limit(request.GET.get("limit"), default=500, maximum=500)
    if metadata_filter_active:
        _enrich_advanced_stock_rows(grouped_rows)
        _enrich_location_metadata(grouped_rows)
        grouped_rows = [row for row in grouped_rows if _advanced_stock_row_matches(row, request)]
    else:
        grouped_rows = grouped_rows[:limit]
        _enrich_advanced_stock_rows(grouped_rows)
        _enrich_location_metadata(grouped_rows)

    data = []
    for row in grouped_rows[:limit]:
        quantities = row["quantities"]
        row["quantities"] = {key: _decimal(value) for key, value in quantities.items()}
        row["state_quantities"] = [
            {
                "state": state_key,
                "stock_state": stock_state,
                "label": label,
                "quantity": row["quantities"][state_key],
            }
            for stock_state, (state_key, label) in ADVANCED_STOCK_STATES.items()
        ]
        data.append(row)
    return json_response({"results": data, "allowed_warehouses": authorized_warehouses})


@require_GET
def ledger(request: HttpRequest):
    qs = InventoryLedgerEntry.objects.all().order_by("-posted_at")
    try:
        qs, forbidden, _authorized_warehouses = _apply_stock_warehouse_scope(request, qs)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    if forbidden is not None:
        return forbidden
    if search := _query_alias(request, "q", "search").strip():
        qs = qs.filter(
            Q(item_ref__icontains=search)
            | Q(warehouse_ref__icontains=search)
            | Q(location_ref__icontains=search)
            | Q(lot_ref__icontains=search)
            | Q(stock_state__icontains=search)
            | Q(movement_type__icontains=search)
            | Q(direction__icontains=search)
            | Q(document_type__icontains=search)
            | Q(document_ref__icontains=search)
            | Q(reason__icontains=search)
            | Q(created_by__icontains=search)
            | Q(legacy_transaction_number__icontains=search)
            | Q(legacy_sales_order_number__icontains=search)
            | Q(legacy_line_id__icontains=search)
        )
    if movement_type := request.GET.get("movement_type"):
        qs = qs.filter(movement_type=movement_type)
    if direction := request.GET.get("direction"):
        qs = qs.filter(direction=direction)
    if warehouse := request.GET.get("warehouse"):
        qs = qs.filter(warehouse_ref=warehouse)
    if item := request.GET.get("item"):
        qs = qs.filter(item_ref=item)
    if location_ref := _query_alias(request, "location", "location_ref"):
        qs = qs.filter(location_ref=location_ref)
    if lot_ref := _query_alias(request, "lot", "lot_ref"):
        qs = qs.filter(lot_ref=lot_ref)
    if stock_state := _query_alias(request, "stock_state", "state"):
        qs = qs.filter(stock_state=stock_state)
    if document_type := _query_alias(request, "document_type", "reference_type"):
        qs = qs.filter(document_type=document_type)
    if document_ref := _query_alias(request, "document_ref", "reference_id"):
        qs = qs.filter(document_ref=document_ref)
    single_date = _query_alias(request, "date", "posted_date", "planned_date", "fecha")
    date_from = request.GET.get("date_from") or single_date
    date_to = request.GET.get("date_to") or single_date
    if date_from:
        parsed_datetime = _parse_local_datetime(date_from)
        if parsed_datetime is not None:
            qs = qs.filter(posted_at__gte=parsed_datetime)
        else:
            parsed_date = parse_date(date_from)
            if parsed_date is None:
                return error_response("validation_error", "date_from debe tener formato YYYY-MM-DD o YYYY-MM-DDTHH:mm.", status=400)
            qs = qs.filter(posted_at__date__gte=parsed_date)
    if date_to:
        parsed_datetime = _parse_local_datetime(date_to)
        if parsed_datetime is not None:
            qs = qs.filter(posted_at__lte=parsed_datetime)
        else:
            parsed_date = parse_date(date_to)
            if parsed_date is None:
                return error_response("validation_error", "date_to debe tener formato YYYY-MM-DD o YYYY-MM-DDTHH:mm.", status=400)
            qs = qs.filter(posted_at__date__lte=parsed_date)
    data = [serialize_ledger_entry(row) for row in qs[: _limit(request.GET.get("limit"))]]
    return json_response({"results": data})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def receipts(request: HttpRequest):
    if request.method == "POST":
        try:
            actor = _request_actor(request)
            if not actor:
                raise PermissionError("La recepcion requiere un usuario operativo.")
            payload = _ensure_active_warehouse_operation_payload(
                request,
                parse_json_body(request),
                operation_label="recepcion",
            )
            result = receive_purchase_order(
                payload=payload,
                idempotency_key=require_idempotency_key(request),
                actor=actor,
            )
            return json_response(result.payload, status=result.status)
        except Exception as exc:
            return _inventory_error_response(exc)

    qs = PurchaseOrderReceipt.objects.all().order_by("-created_at")
    if purchase_order_ref := request.GET.get("purchase_order_ref"):
        qs = qs.filter(purchase_order_ref=purchase_order_ref)
    if warehouse := request.GET.get("warehouse"):
        qs = qs.filter(warehouse_ref=warehouse)
    if status := request.GET.get("status"):
        qs = qs.filter(status=status)
    if item := request.GET.get("item"):
        qs = qs.filter(lines__item_ref=item).distinct()
    data = [serialize_receipt(row) for row in qs[:100]]
    return json_response({"results": data})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def exchanges(request: HttpRequest):
    if request.method == "POST":
        try:
            actor = _request_actor(request)
            if not actor:
                raise PermissionError("El canje requiere un usuario operativo.")
            payload = _ensure_active_warehouse_operation_payload(
                request,
                parse_json_body(request),
                operation_label="canje",
            )
            result = execute_inventory_exchange(
                payload=payload,
                idempotency_key=require_idempotency_key(request),
                actor=actor,
            )
            return json_response(result.payload, status=result.status)
        except Exception as exc:
            return _inventory_error_response(exc)

    from apps.inventory.models import InventoryTransformation

    qs = InventoryTransformation.objects.filter(
        transformation_type=InventoryTransformation.TransformationType.EXCHANGE
    ).order_by("-created_at")
    if warehouse := _query_alias(request, "warehouse", "warehouse_ref"):
        qs = qs.filter(warehouse_ref=warehouse)
    return json_response({"results": [serialize_transformation(row) for row in qs[: _limit(request.GET.get("limit"), default=100, maximum=500)]]})


@csrf_exempt
@require_POST
def location_moves(request: HttpRequest):
    try:
        actor = _request_actor(request)
        if not actor:
            raise PermissionError("El movimiento requiere un usuario operativo.")
        payload = _ensure_active_warehouse_operation_payload(
            request,
            parse_json_body(request),
            operation_label="movimiento",
        )
        result = move_inventory_between_locations(
            payload=payload,
            idempotency_key=require_idempotency_key(request),
            actor=actor,
        )
        return json_response(result.payload, status=result.status)
    except Exception as exc:
        return _inventory_error_response(exc)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def manual_adjustments(request: HttpRequest):
    if request.method == "POST":
        try:
            actor = _request_actor(request)
            if not actor:
                raise PermissionError("El ajuste manual requiere un usuario operativo.")
            payload = _ensure_active_warehouse_operation_payload(
                request,
                parse_json_body(request),
                operation_label="ajuste manual",
            )
            result = adjust_inventory_manually(
                payload=payload,
                idempotency_key=require_idempotency_key(request),
                actor=actor,
            )
            return json_response(result.payload, status=result.status)
        except Exception as exc:
            return _inventory_error_response(exc)

    qs = InventoryLedgerEntry.objects.filter(
        movement_type=InventoryLedgerEntry.MovementType.ADJUSTMENT,
        document_type="inventory_manual_adjustment",
    ).order_by("-posted_at")
    try:
        qs, forbidden, authorized_warehouses = _apply_stock_warehouse_scope(request, qs)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    if forbidden is not None:
        return forbidden
    if warehouse := _query_alias(request, "warehouse", "warehouse_ref"):
        qs = qs.filter(warehouse_ref=warehouse)
    if item := _query_alias(request, "item", "item_ref"):
        qs = qs.filter(item_ref=item)
    if direction := request.GET.get("direction"):
        qs = qs.filter(direction=direction)
    return json_response(
        {
            "results": [serialize_ledger_entry(row) for row in qs[: _limit(request.GET.get("limit"), default=100, maximum=500)]],
            "allowed_warehouses": authorized_warehouses,
        }
    )


@csrf_exempt
@require_POST
def validate_sheet_cutting(request: HttpRequest):
    try:
        actor = _request_actor(request) or "system"
        payload = _ensure_active_warehouse_operation_payload(
            request,
            parse_json_body(request),
            operation_label="ejecucion de corte",
        )
        result = validate_sheet_cutting_stock(payload=payload, actor=actor)
        return json_response(result.payload, status=result.status)
    except Exception as exc:
        return _inventory_error_response(exc)


@csrf_exempt
@require_POST
def execute_sheet_cutting_view(request: HttpRequest):
    try:
        actor = _request_actor(request)
        if not actor:
            raise PermissionError("El corte requiere un usuario operativo.")
        payload = _ensure_active_warehouse_operation_payload(
            request,
            parse_json_body(request),
            operation_label="ejecucion de corte",
        )
        result = execute_sheet_cutting(
            payload=payload,
            idempotency_key=require_idempotency_key(request),
            actor=actor,
        )
        return json_response(result.payload, status=result.status)
    except Exception as exc:
        return _inventory_error_response(exc)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def write_offs(request: HttpRequest):
    if request.method == "POST":
        try:
            actor = _request_actor(request)
            if not actor:
                raise PermissionError("La baja requiere un usuario operativo.")
            result = create_inventory_write_off(
                payload=_ensure_active_warehouse_payload(request, parse_json_body(request)),
                idempotency_key=require_idempotency_key(request),
                actor=actor,
            )
            return json_response(result.payload, status=result.status)
        except Exception as exc:
            return _inventory_error_response(exc)

    qs = InventoryWriteOff.objects.prefetch_related("lines").order_by("-created_at")
    try:
        qs, forbidden, authorized_warehouses = _apply_stock_warehouse_scope(request, qs)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    if forbidden is not None:
        return forbidden
    if warehouse := _query_alias(request, "warehouse", "warehouse_ref"):
        qs = qs.filter(warehouse_ref=warehouse)
    if location_ref := _query_alias(request, "location", "location_ref"):
        qs = qs.filter(Q(location_ref=location_ref) | Q(lines__location_ref=location_ref)).distinct()
    if status := request.GET.get("status"):
        qs = qs.filter(status=status)
    if write_off_number := request.GET.get("write_off_number"):
        qs = qs.filter(write_off_number=write_off_number)
    rows = qs[: _limit(request.GET.get("limit"), default=100, maximum=500)]
    return json_response(
        {
            "results": [serialize_write_off(row) for row in rows],
            "allowed_warehouses": authorized_warehouses,
        }
    )


@csrf_exempt
@require_http_methods(["GET"])
def write_off_detail(request: HttpRequest, write_off_id):
    try:
        write_off = InventoryWriteOff.objects.get(id=write_off_id)
    except InventoryWriteOff.DoesNotExist as exc:
        return _inventory_error_response(exc)
    return json_response({"result": serialize_write_off(write_off)})


@csrf_exempt
@require_http_methods(["POST"])
def post_write_off(request: HttpRequest, write_off_id):
    try:
        write_off = InventoryWriteOff.objects.get(id=write_off_id)
        active_warehouse = _active_warehouse_ref(request)
        if active_warehouse and write_off.warehouse_ref != active_warehouse:
            raise PermissionError("El posteo solo se permite en el almacen activo.")
        result = post_inventory_write_off(
            write_off_id=str(write_off_id),
            payload=parse_json_body(request),
            idempotency_key=require_idempotency_key(request),
            actor=_request_actor(request) or "system",
        )
        return json_response(result.payload, status=result.status)
    except Exception as exc:
        return _inventory_error_response(exc)


@csrf_exempt
@require_http_methods(["POST"])
def reverse_write_off(request: HttpRequest, write_off_id):
    try:
        actor = _request_actor(request)
        if not actor:
            raise PermissionError("La reversa requiere un usuario operativo.")
        write_off = InventoryWriteOff.objects.get(id=write_off_id)
        active_warehouse = _active_warehouse_ref(request)
        if active_warehouse and write_off.warehouse_ref != active_warehouse:
            raise PermissionError("La reversa solo se permite en el almacen activo.")
        result = reverse_inventory_write_off(
            write_off_id=str(write_off_id),
            payload=parse_json_body(request),
            idempotency_key=require_idempotency_key(request),
            actor=actor,
        )
        return json_response(result.payload, status=result.status)
    except Exception as exc:
        return _inventory_error_response(exc)


@csrf_exempt
@require_POST
def reservations(request: HttpRequest):
    try:
        idempotency_key = require_idempotency_key(request)
        payload = parse_json_body(request)
        reservation = reserve_inventory(
            warehouse_ref=payload["warehouse_ref"],
            source_type=payload["source_type"],
            source_ref=payload["source_ref"],
            actor=payload.get("actor", "system"),
            lines=payload["lines"],
            idempotency_key=idempotency_key,
        )
    except KeyError as exc:
        return error_response("validation_error", f"Falta campo requerido: {exc}", status=400)
    except ValueError as exc:
        return error_response("validation_error", str(exc), status=400)
    except InventoryRuleError as exc:
        return error_response("business_rule_violation", str(exc), status=422)
    return json_response(
        {
            "id": str(reservation.id),
            "status": reservation.status,
            "source_type": reservation.source_type,
            "source_ref": reservation.source_ref,
        },
        status=201,
    )
