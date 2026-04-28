from __future__ import annotations

from decimal import Decimal

from django.db.models import Q, Sum
from django.http import HttpRequest
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.common.api import error_response, json_response, parse_json_body, require_idempotency_key
from apps.inventory.models import InventoryBalance, InventoryLedgerEntry, PurchaseOrderReceipt, StockState
from apps.inventory.services import InventoryRuleError, reserve_inventory
from apps.logistics.models import MaterialMasterSnapshot
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
    authorized_warehouses = _stock_authorized_warehouses(request)
    if authorized_warehouses is None:
        return qs, None, []
    if not authorized_warehouses:
        return qs.none(), _forbidden_stock_response(), []
    requested_warehouse = _query_alias(request, "warehouse", "warehouse_ref").strip()
    if requested_warehouse and requested_warehouse not in authorized_warehouses:
        return qs.none(), _forbidden_stock_response(), authorized_warehouses
    return qs.filter(warehouse_ref__in=authorized_warehouses), None, authorized_warehouses


ADVANCED_STOCK_STATES = {
    StockState.ON_HAND: ("available", "Disponible"),
    StockState.RESERVED: ("reserved", "Reservado"),
    StockState.PICKING: ("in_preparation", "En Preparacion"),
    StockState.PACKED: ("prepared", "Preparado"),
    StockState.IN_TRANSIT: ("in_transit", "En Transito"),
    StockState.SCRAPPED: ("damaged_waste", "Roto/Merma"),
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
    data = [
        {
            "id": str(row.id),
            "warehouse_ref": row.warehouse_ref,
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
    qs = InventoryBalance.objects.filter(stock_state__in=tuple(ADVANCED_STOCK_STATES)).order_by("warehouse_ref", "item_ref", "lot_ref", "uom")
    try:
        qs, forbidden, authorized_warehouses = _apply_stock_warehouse_scope(request, qs)
    except MasterDataSourceError as exc:
        return error_response("master_data_unavailable", str(exc), status=503)
    if forbidden is not None:
        return forbidden
    if warehouse := _query_alias(request, "warehouse", "warehouse_ref"):
        qs = qs.filter(warehouse_ref=warehouse)
    if lot_ref := _query_alias(request, "lot", "lot_ref", "location", "location_ref"):
        qs = qs.filter(lot_ref=lot_ref)
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
        search_filter = Q(warehouse_ref__icontains=search_query) | Q(item_ref__icontains=search_query) | Q(lot_ref__icontains=search_query)
        if search_refs:
            search_filter |= Q(item_ref__in=search_refs)
        qs = qs.filter(search_filter)
    rows = (
        qs.values("warehouse_ref", "item_ref", "lot_ref", "uom", "stock_state")
        .annotate(quantity=Sum("quantity"))
        .order_by("warehouse_ref", "item_ref", "lot_ref", "uom", "stock_state")
    )

    grouped: dict[tuple[str, str, str, str], dict] = {}
    for row in rows:
        key = (
            row["warehouse_ref"],
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
                "location_ref": row["lot_ref"] or "",
                "location_name": "",
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
        grouped_rows = [row for row in grouped_rows if _advanced_stock_row_matches(row, request)]
    else:
        grouped_rows = grouped_rows[:limit]
        _enrich_advanced_stock_rows(grouped_rows)

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
    if movement_type := request.GET.get("movement_type"):
        qs = qs.filter(movement_type=movement_type)
    if direction := request.GET.get("direction"):
        qs = qs.filter(direction=direction)
    if warehouse := request.GET.get("warehouse"):
        qs = qs.filter(warehouse_ref=warehouse)
    if item := request.GET.get("item"):
        qs = qs.filter(item_ref=item)
    if stock_state := _query_alias(request, "stock_state", "state"):
        qs = qs.filter(stock_state=stock_state)
    if document_type := _query_alias(request, "document_type", "reference_type"):
        qs = qs.filter(document_type=document_type)
    if document_ref := _query_alias(request, "document_ref", "reference_id"):
        qs = qs.filter(document_ref=document_ref)
    if date_from := request.GET.get("date_from"):
        parsed = parse_date(date_from)
        if parsed is None:
            return error_response("validation_error", "date_from debe tener formato YYYY-MM-DD.", status=400)
        qs = qs.filter(posted_at__date__gte=parsed)
    if date_to := request.GET.get("date_to"):
        parsed = parse_date(date_to)
        if parsed is None:
            return error_response("validation_error", "date_to debe tener formato YYYY-MM-DD.", status=400)
        qs = qs.filter(posted_at__date__lte=parsed)
    data = [
        {
            "id": str(row.id),
            "movement_type": row.movement_type,
            "direction": row.direction,
            "warehouse_ref": row.warehouse_ref,
            "item_ref": row.item_ref,
            "stock_state": row.stock_state,
            "quantity": _decimal(row.quantity),
            "uom": row.uom,
            "document_type": row.document_type,
            "document_ref": row.document_ref,
            "posted_at": row.posted_at.isoformat(),
        }
        for row in qs[: _limit(request.GET.get("limit"))]
    ]
    return json_response({"results": data})


@require_GET
def receipts(request: HttpRequest):
    qs = PurchaseOrderReceipt.objects.all().order_by("-created_at")
    if purchase_order_ref := request.GET.get("purchase_order_ref"):
        qs = qs.filter(purchase_order_ref=purchase_order_ref)
    if warehouse := request.GET.get("warehouse"):
        qs = qs.filter(warehouse_ref=warehouse)
    if status := request.GET.get("status"):
        qs = qs.filter(status=status)
    if item := request.GET.get("item"):
        qs = qs.filter(lines__item_ref=item).distinct()
    data = [
        {
            "id": str(row.id),
            "purchase_order_ref": row.purchase_order_ref,
            "supplier_ref": row.supplier_ref,
            "status": row.status,
            "warehouse_ref": row.warehouse_ref,
            "lines_count": row.lines.count(),
            "received_at": _iso_datetime(row.received_at),
            "closed_at": _iso_datetime(row.closed_at),
        }
        for row in qs[:100]
    ]
    return json_response({"results": data})


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
