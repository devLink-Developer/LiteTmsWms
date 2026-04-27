from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from django.conf import settings
from django.db import DatabaseError, connections

from apps.logistics.models import MaterialMasterSnapshot


class MasterDataSourceError(RuntimeError):
    pass


def _parquet():
    try:
        import pyarrow.parquet as parquet
    except ModuleNotFoundError as exc:
        raise MasterDataSourceError("pyarrow no esta instalado para leer archivos Parquet.") from exc
    return parquet


def _candidate_dirs() -> list[Path]:
    raw_paths = [settings.MASTER_DATA_PARQUET_DIR, *settings.MASTER_DATA_PARQUET_FALLBACK_DIRS]
    paths: list[Path] = []
    for raw_path in raw_paths:
        path = Path(raw_path)
        if path not in paths:
            paths.append(path)
    return paths


def master_data_dir() -> Path:
    for path in _candidate_dirs():
        if path.exists() and any(path.glob("*.parquet")):
            return path
    checked = ", ".join(str(path) for path in _candidate_dirs())
    raise MasterDataSourceError(f"No se encontro directorio Parquet disponible. Rutas revisadas: {checked}")


def _safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()}
    return value


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _weight_to_kg(value: Any, uom: str) -> Decimal:
    weight = _to_decimal(value)
    unit = str(uom or "").strip().casefold()
    if unit in {"g", "gr", "gram", "grams", "gramo", "gramos"}:
        return weight / Decimal("1000")
    if unit in {"t", "tn", "ton", "tons", "tonelada", "toneladas"}:
        return weight * Decimal("1000")
    if unit in {"lb", "lbs"}:
        return weight * Decimal("0.45359237")
    return weight


def _volume_to_m3(value: Any, uom: str) -> Decimal:
    volume = _to_decimal(value)
    unit = str(uom or "").strip().casefold()
    if unit in {"ccm", "cm3", "cm^3"}:
        return volume / Decimal("1000000")
    if unit in {"dm3", "dm^3", "l", "lt", "lts", "litro", "litros"}:
        return volume / Decimal("1000")
    if unit in {"mm3", "mm^3"}:
        return volume / Decimal("1000000000")
    return volume


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "t", "yes", "y", "si", "s"}


def _material_cache_payload(row: dict[str, Any], *, source_file: str) -> dict[str, Any]:
    raw_weight = _to_decimal(row.get("weight") or row.get("peso"))
    raw_volume = _to_decimal(row.get("volume") or row.get("volumen"))
    weight_uom = str(row.get("weight_uom") or row.get("um_peso") or "KG").strip()
    volume_uom = str(row.get("volume_uom") or row.get("um_volumen") or "M3").strip()
    multiple = _to_decimal(row.get("multiple") or row.get("multiplo"), "1")
    if multiple <= 0:
        multiple = Decimal("1")
    freight_product = _truthy(row.get("freight_product") or row.get("producto_flete"))
    service_product = _truthy(row.get("service_product") or row.get("producto_servicio"))
    return {
        "sap_code": str(row.get("sap_code") or row.get("codigo_sap") or "").strip(),
        "sap_item_id": str(row.get("sap_item_id") or row.get("item_id_sap") or "").strip(),
        "name": str(row.get("name") or row.get("nombre_producto") or "").strip(),
        "long_name": str(row.get("long_name") or row.get("nombre_largo") or row.get("name") or row.get("nombre_producto") or "").strip(),
        "category": str(row.get("category") or row.get("categoria_producto") or "").strip(),
        "coverage_group": str(row.get("coverage_group") or row.get("grupo_cobertura") or "").strip(),
        "uom": str(row.get("uom") or row.get("unidad_medida") or "").strip(),
        "uom_code": str(row.get("uom_code") or row.get("unidad_medida_codigo") or row.get("unidad_medida") or "").strip(),
        "raw_weight": raw_weight,
        "weight_uom": weight_uom,
        "weight_kg": _weight_to_kg(raw_weight, weight_uom),
        "raw_volume": raw_volume,
        "volume_uom": volume_uom,
        "volume_m3": _volume_to_m3(raw_volume, volume_uom),
        "multiple": multiple,
        "freight_product": freight_product,
        "service_product": service_product,
        "source_file": source_file,
        "payload": _safe(row),
        "updated_by": "master-data-parquet",
    }


def _cache_material_snapshots(*, store: str, rows: Iterable[dict[str, Any]], source_file: str) -> None:
    store_ref = str(store or "").strip()
    for row in rows:
        item_ref = str(row.get("item_ref") or row.get("numero_producto") or "").strip()
        if not item_ref:
            continue
        defaults = _material_cache_payload(row, source_file=source_file)
        try:
            MaterialMasterSnapshot.objects.update_or_create(
                store_ref=store_ref,
                item_ref=item_ref,
                defaults={**defaults, "created_by": "master-data-parquet"},
            )
        except DatabaseError:
            continue


def _cached_material_snapshots(*, store: str, item_refs: Iterable[str]) -> dict[str, dict[str, Any]]:
    refs = [str(item_ref or "").strip() for item_ref in item_refs if str(item_ref or "").strip()]
    if not refs:
        return {}
    store_ref = str(store or "").strip()
    qs = MaterialMasterSnapshot.objects.filter(item_ref__in=refs)
    if store_ref:
        qs = qs.filter(store_ref__in=[store_ref, ""]).order_by("-store_ref")
    results: dict[str, dict[str, Any]] = {}
    try:
        freight_refs = pos_freight_product_refs(store_ref) | pos_freight_product_refs("")
    except MasterDataSourceError:
        freight_refs = set()
    try:
        rows = list(qs)
    except DatabaseError:
        return {}
    for row in rows:
        if row.item_ref in results:
            continue
        freight_product = row.freight_product or row.item_ref in freight_refs
        service_product = row.service_product
        results[row.item_ref] = {
            "item_ref": row.item_ref,
            "sap_code": row.sap_code,
            "sap_item_id": row.sap_item_id,
            "name": row.name,
            "long_name": row.long_name or row.name,
            "category": row.category,
            "coverage_group": row.coverage_group,
            "uom": row.uom,
            "uom_code": row.uom_code or row.uom,
            "store_number": row.store_ref,
            "store_name": "",
            "weight": str(row.weight_kg),
            "weight_uom": "KG",
            "volume": str(row.volume_m3),
            "volume_uom": "M3",
            "multiple": str(row.multiple),
            "freight_product": freight_product,
            "service_product": service_product,
            "virtual_product": freight_product or service_product,
            "source": "tmswms.material_master_snapshot",
        }
    return results


def _read_rows(file_name: str, *, columns: list[str] | None = None) -> tuple[Path, list[dict[str, Any]]]:
    base_dir = master_data_dir()
    path = base_dir / file_name
    if not path.exists():
        raise MasterDataSourceError(f"No existe el archivo Parquet {path}.")
    table = _parquet().read_table(path, columns=columns)
    return path, [_safe(row) for row in table.to_pylist()]


def _existing_columns(file_name: str, columns: list[str]) -> list[str]:
    path = master_data_dir() / file_name
    if not path.exists():
        return columns
    try:
        available = set(_parquet().ParquetFile(path).schema_arrow.names)
    except Exception:
        return columns
    return [column for column in columns if column in available]


def _contains(row: dict[str, Any], query: str, fields: list[str]) -> bool:
    if not query:
        return True
    normalized = query.lower()
    return any(normalized in str(row.get(field) or "").lower() for field in fields)


def _limit(value: str | None, default: int = 100, maximum: int = 500) -> int:
    try:
        parsed = int(value or default)
    except ValueError:
        parsed = default
    return min(max(parsed, 1), maximum)


def _parse_json_list(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _parse_json_object(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _read_legacy_warehouses(*, store: str = "", query: str = "", limit: int = 500) -> list[dict[str, Any]]:
    try:
        with connections["litecore"].cursor() as cursor:
            store_sql = """
                SELECT
                    "StoreCode",
                    "StoreName",
                    "PickupWarehouse",
                    "ShippingWarehouse",
                    "FulfillmentGroup_id",
                    "PickupGroup_id"
                FROM public.maestros_tiendas_store
                WHERE "Estado" IS TRUE
            """
            params: list[Any] = []
            if store:
                store_sql += ' AND lower("StoreCode") = lower(%s)'
                params.append(store)
            cursor.execute(store_sql, params)
            store_rows = cursor.fetchall()

            direct_codes = {
                str(value or "").strip()
                for row in store_rows
                for value in [row[2], row[3]]
                if str(value or "").strip()
            }
            fulfillment_group_ids = [row[4] for row in store_rows if row[4]]
            pickup_group_ids = [row[5] for row in store_rows if row[5]]

            warehouses_by_code: dict[str, dict[str, Any]] = {}

            def upsert_warehouse(row, *, store_code: str = "", store_name: str = "", role: str = "") -> None:
                rec_id, code, name, warehouse_type, is_pickup_allowed, is_shipping_allowed, external_reference = row
                if not code:
                    return
                current = warehouses_by_code.get(code, {})
                warehouses_by_code[code] = {
                    **current,
                    "warehouse_id": str(rec_id) if rec_id else current.get("warehouse_id"),
                    "warehouse_code": code,
                    "warehouse_name": name or current.get("warehouse_name") or code,
                    "warehouse_type": warehouse_type or current.get("warehouse_type") or role,
                    "store_code": store_code or current.get("store_code") or "",
                    "store_name": store_name or current.get("store_name") or "",
                    "external_reference": external_reference or current.get("external_reference") or "",
                    "is_pickup_allowed": bool(is_pickup_allowed) or current.get("is_pickup_allowed", False) or role == "pickup",
                    "is_shipping_allowed": bool(is_shipping_allowed) or current.get("is_shipping_allowed", False) or role == "shipping",
                    "source": "legacy_public",
                }

            if direct_codes:
                cursor.execute(
                    """
                    SELECT "RecId", "WarehouseId", "Name", "WarehouseType", "IsPickupAllowed", "IsShippingAllowed", "ExternalReference"
                    FROM public.maestros_tiendas_warehouse
                    WHERE "Estado" IS TRUE AND "WarehouseId" = ANY(%s)
                    """,
                    [list(direct_codes)],
                )
                warehouse_by_code = {row[1]: row for row in cursor.fetchall()}
                for store_code, store_name, pickup_code, shipping_code, *_ in store_rows:
                    if pickup_code in warehouse_by_code:
                        upsert_warehouse(warehouse_by_code[pickup_code], store_code=store_code, store_name=store_name, role="pickup")
                    if shipping_code in warehouse_by_code:
                        upsert_warehouse(warehouse_by_code[shipping_code], store_code=store_code, store_name=store_name, role="shipping")

            if fulfillment_group_ids:
                cursor.execute(
                    """
                    SELECT
                        gw.group_id,
                        w."RecId", w."WarehouseId", w."Name", w."WarehouseType",
                        w."IsPickupAllowed", w."IsShippingAllowed", w."ExternalReference"
                    FROM public.maestros_tiendas_storefulfillmentgroupwarehouse gw
                    INNER JOIN public.maestros_tiendas_warehouse w ON w."RecId" = gw.warehouse_id
                    WHERE w."Estado" IS TRUE AND gw.group_id = ANY(%s)
                    """,
                    [fulfillment_group_ids],
                )
                fulfillment_rows: dict[Any, list[tuple]] = {}
                for row in cursor.fetchall():
                    fulfillment_rows.setdefault(row[0], []).append(row[1:])
                for store_code, store_name, *_prefix, fulfillment_group_id, _pickup_group_id in store_rows:
                    for warehouse in fulfillment_rows.get(fulfillment_group_id, []):
                        upsert_warehouse(warehouse, store_code=store_code, store_name=store_name, role="shipping")

            if pickup_group_ids:
                cursor.execute(
                    """
                    SELECT
                        gw.group_id,
                        w."RecId", w."WarehouseId", w."Name", w."WarehouseType",
                        w."IsPickupAllowed", w."IsShippingAllowed", w."ExternalReference"
                    FROM public.maestros_tiendas_storepickupgroupwarehouse gw
                    INNER JOIN public.maestros_tiendas_warehouse w ON w."RecId" = gw.warehouse_id
                    WHERE w."Estado" IS TRUE AND gw.group_id = ANY(%s)
                    """,
                    [pickup_group_ids],
                )
                pickup_rows: dict[Any, list[tuple]] = {}
                for row in cursor.fetchall():
                    pickup_rows.setdefault(row[0], []).append(row[1:])
                for store_code, store_name, *_prefix, _fulfillment_group_id, pickup_group_id in store_rows:
                    for warehouse in pickup_rows.get(pickup_group_id, []):
                        upsert_warehouse(warehouse, store_code=store_code, store_name=store_name, role="pickup")
    except (DatabaseError, KeyError, OSError):
        return []

    rows = sorted(warehouses_by_code.values(), key=lambda row: str(row.get("warehouse_code") or ""))
    rows = [row for row in rows if _contains(row, query, ["warehouse_code", "warehouse_name", "store_code", "store_name"])]
    return rows[:limit]


def _normalize_lookup(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip())
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def _digits(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _employee_identity_candidates(row: dict[str, Any]) -> set[str]:
    candidates = {
        _normalize_lookup(row.get("employee_id")),
        _normalize_lookup(row.get("legajo")),
        _normalize_lookup(row.get("numero_sap")),
        _normalize_lookup(row.get("email")),
        _normalize_lookup(row.get("azure_upn")),
        _normalize_lookup(row.get("azure_mail")),
    }
    for key in ["email", "azure_upn", "azure_mail"]:
        value = _normalize_lookup(row.get(key))
        if "@" in value:
            candidates.add(value.split("@", 1)[0])

    first_name = _normalize_lookup(row.get("nombre")).split()
    last_name = _normalize_lookup(row.get("apellido")).replace(" ", "")
    if first_name and last_name:
        candidates.add(f"{first_name[0][0]}{last_name}")
        candidates.add(f"{first_name[0]}.{last_name}")
    return {candidate for candidate in candidates if candidate}


def _warehouse_codes_for_stores(store_codes: set[str]) -> set[str]:
    if not store_codes:
        return set()

    _, stores = _read_rows(
        "tiendas.parquet",
        columns=[
            "codigo",
            "deposito_pickup",
            "deposito_envio",
            "pickup_group_warehouses",
            "fulfillment_group_warehouses",
        ],
    )
    normalized_store_codes = {_normalize_lookup(code) for code in store_codes}
    warehouses: set[str] = set()
    for store in stores:
        if _normalize_lookup(store.get("codigo")) not in normalized_store_codes:
            continue
        for key in ["deposito_pickup", "deposito_envio"]:
            code = str(store.get(key) or "").strip()
            if code:
                warehouses.add(code)
    return warehouses


def _pos_store_matches(row: dict[str, Any], store: str) -> bool:
    if not store:
        return True
    expected = _normalize_lookup(store)
    store_keys = [
        "store",
        "store_code",
        "store_number",
        "tienda",
        "tienda_codigo",
        "codigo_tienda",
        "sucursal",
        "sucursal_codigo",
    ]
    values = [
        _normalize_lookup(row.get(key))
        for key in store_keys
        if row.get(key) not in [None, ""]
    ]
    return not values or expected in values


def _pos_freight_value(value: Any) -> str:
    if isinstance(value, bool):
        return ""
    text = str(value or "").strip()
    if not text or text.casefold() in {"true", "false", "si", "no", "none", "null"}:
        return ""
    if text.startswith("{") or text.startswith("["):
        return ""
    return text


def _pos_freight_refs_from_params(row: dict[str, Any]) -> set[str]:
    param_name = _normalize_lookup(row.get("ParamName") or row.get("param_name") or row.get("Parametro") or row.get("parametro"))
    params = _parse_json_object(row.get("Params") or row.get("params") or row.get("Valor") or row.get("valor"))
    if not params:
        return set()
    freight_param = "flete" in param_name or "freight" in param_name
    if not freight_param and not any("flete" in _normalize_lookup(key) or "freight" in _normalize_lookup(key) for key in params):
        return set()

    exact_param_keys = {
        "article_number",
        "article_code",
        "article_ref",
        "article_sku",
        "articulo",
        "articulo_codigo",
        "articulo_numero",
        "codigo_articulo",
        "codigo_producto",
        "freight_item",
        "freight_item_ref",
        "freight_product",
        "freight_product_code",
        "item_flete",
        "item_number",
        "item_ref",
        "numero_articulo",
        "numero_producto",
        "product_code",
        "product_number",
        "producto",
        "producto_flete",
        "sku",
        "sku_flete",
    }
    refs: set[str] = set()
    for key, value in params.items():
        normalized_key = _normalize_lookup(key)
        looks_like_ref = normalized_key in exact_param_keys or (
            ("flete" in normalized_key or "freight" in normalized_key)
            and any(token in normalized_key for token in ["codigo", "code", "numero", "number", "producto", "product", "articulo", "item", "sku"])
        )
        if not looks_like_ref:
            continue
        ref = _pos_freight_value(value)
        if ref:
            refs.add(ref)
    return refs


@lru_cache(maxsize=128)
def pos_freight_product_refs(store: str = "") -> set[str]:
    path = master_data_dir() / "parametros_pos.parquet"
    if not path.exists():
        return set()
    _, rows = _read_rows("parametros_pos.parquet")
    exact_keys = {
        "producto_flete",
        "producto_flete_automatico",
        "producto_flete_auto",
        "codigo_producto_flete",
        "articulo_flete",
        "articulo_flete_automatico",
        "item_flete",
        "sku_flete",
        "freight_product",
        "freight_product_code",
        "freight_item",
        "freight_item_ref",
        "automatic_freight_product",
        "automatic_freight_item",
    }
    refs: set[str] = set()
    for row in rows:
        if row.get("Estado") is False or row.get("estado") is False:
            continue
        if not _pos_store_matches(row, store):
            continue
        refs.update(_pos_freight_refs_from_params(row))
        for key, value in row.items():
            normalized_key = _normalize_lookup(key)
            looks_like_freight_product = (
                normalized_key in exact_keys
                or (
                    ("flete" in normalized_key or "freight" in normalized_key)
                    and any(token in normalized_key for token in ["producto", "product", "articulo", "item", "sku"])
                )
            )
            if not looks_like_freight_product:
                continue
            ref = _pos_freight_value(value)
            if ref:
                refs.add(ref)
    return refs


@lru_cache(maxsize=512)
def employee_delivery_permissions(actor: str) -> dict[str, Any]:
    actor_lookup = _normalize_lookup(actor)
    if not actor_lookup:
        return {"employee": None, "authorized_warehouses": [], "permissions": []}

    path, employees = _read_rows(
        "empleados.parquet",
        columns=[
            "employee_id",
            "legajo",
            "numero_sap",
            "nombre",
            "apellido",
            "email",
            "azure_upn",
            "azure_mail",
            "azure_display_name",
            "activo",
            "sucursal_codigo",
            "sucursal_nombre",
            "pos_groups",
            "pos_groups_json",
        ],
    )
    employee = None
    for row in employees:
        if actor_lookup in _employee_identity_candidates(row):
            employee = row
            break

    if not employee or employee.get("activo") is False:
        return {"source_file": str(path), "employee": None, "authorized_warehouses": [], "permissions": []}

    store_codes = {str(employee.get("sucursal_codigo") or "").strip()}
    for group in _parse_json_list(employee.get("pos_groups_json")):
        store_code = str(group.get("store_code") or "").strip()
        if store_code:
            store_codes.add(store_code)

    warehouses = sorted(_warehouse_codes_for_stores({code for code in store_codes if code}))
    permissions = [
        "receipts:view",
        "transfers:view",
        "orders:view",
        "deliveries:view",
        "deliveries:split",
        "deliveries:validate_stock",
        "deliveries:issue_remito",
        "routes:view",
        "vehicles:view",
        "stock:view",
        "audits:view",
        "dispatch:view",
        "shipping:view",
    ] if warehouses else []
    return {
        "source_file": str(path),
        "employee": {
            "employee_id": employee.get("employee_id"),
            "legajo": employee.get("legajo"),
            "name": " ".join(
                part
                for part in [
                    str(employee.get("nombre") or "").strip(),
                    str(employee.get("apellido") or "").strip(),
                ]
                if part
            ) or employee.get("azure_display_name"),
            "email": employee.get("email") or employee.get("azure_mail") or employee.get("azure_upn"),
            "branch_ref": employee.get("sucursal_codigo"),
            "branch_name": employee.get("sucursal_nombre"),
            "store_codes": sorted({code for code in store_codes if code}),
            "pos_groups": employee.get("pos_groups") or [],
        },
        "authorized_warehouses": warehouses,
        "permissions": permissions,
    }


@lru_cache(maxsize=1024)
def customer_refs_for_dni(dni: str) -> list[str]:
    dni_digits = _digits(dni)
    if not dni_digits:
        return []

    path = master_data_dir() / "clientes_cache.parquet"
    if not path.exists():
        raise MasterDataSourceError(f"No existe el archivo Parquet {path}.")
    try:
        import pyarrow.dataset as dataset
    except ModuleNotFoundError as exc:
        raise MasterDataSourceError("pyarrow no esta instalado para leer archivos Parquet.") from exc

    table = dataset.dataset(path, format="parquet").to_table(
        columns=["numero_cliente", "nif"],
        filter=dataset.field("nif") == dni_digits,
    )
    refs = {
        str(row.get("numero_cliente") or "").strip()
        for row in table.to_pylist()
    }
    if refs:
        return sorted(ref for ref in refs if ref)

    _, customers = _read_rows("clientes_cache.parquet", columns=["numero_cliente", "nif", "tif"])
    refs = {
        str(row.get("numero_cliente") or "").strip()
        for row in customers
        if _digits(row.get("nif")) == dni_digits
    }
    return sorted(ref for ref in refs if ref)


@lru_cache(maxsize=128)
def list_stores(*, query: str = "", active: str = "", limit: int = 200) -> dict[str, Any]:
    limit = min(max(limit, 1), 500)
    path, rows = _read_rows(
        "tiendas.parquet",
        columns=[
            "store_id",
            "codigo",
            "nombre",
            "activo",
            "estado_operativo",
            "zona",
            "zona_codigo",
            "provincia",
            "localidad",
            "commercial_site_code",
            "company",
            "deposito_pickup",
            "deposito_envio",
            "modos_entrega",
        ],
    )
    if active:
        expected = active.lower() in {"1", "true", "si", "yes", "activa", "activo"}
        rows = [row for row in rows if bool(row.get("activo")) is expected]
    rows = [row for row in rows if _contains(row, query, ["codigo", "nombre", "zona", "localidad"])]
    results = [
        {
            "id": row.get("store_id"),
            "store_code": row.get("codigo"),
            "store_name": row.get("nombre"),
            "active": row.get("activo"),
            "operational_status": row.get("estado_operativo"),
            "zone": row.get("zona"),
            "zone_code": row.get("zona_codigo"),
            "province": row.get("provincia"),
            "city": row.get("localidad"),
            "commercial_site_code": row.get("commercial_site_code"),
            "company": row.get("company"),
            "pickup_warehouse_ref": row.get("deposito_pickup"),
            "shipping_warehouse_ref": row.get("deposito_envio"),
            "delivery_modes": [
                {
                    "mode_id": mode.get("mode_id"),
                    "name": mode.get("name"),
                    "external_id": mode.get("external_id"),
                    "is_pickup_allowed": mode.get("is_pickup_allowed"),
                    "is_shipping_allowed": mode.get("is_shipping_allowed"),
                }
                for mode in _parse_json_list(row.get("modos_entrega"))
            ],
        }
        for row in rows[:limit]
    ]
    return {"source_file": str(path), "results": results}


@lru_cache(maxsize=128)
def list_warehouses(*, store: str = "", query: str = "", limit: int = 500) -> dict[str, Any]:
    limit = min(max(limit, 1), 1000)
    legacy_rows = _read_legacy_warehouses(store=store, query=query, limit=limit)
    if legacy_rows:
        return {"source_file": "legacy.public.maestros_tiendas_*", "results": legacy_rows}

    path, stores = _read_rows(
        "tiendas.parquet",
        columns=[
            "codigo",
            "nombre",
            "deposito_pickup",
            "deposito_envio",
            "pickup_group_warehouses",
            "fulfillment_group_warehouses",
        ],
    )
    if store:
        stores = [row for row in stores if str(row.get("codigo") or "").lower() == store.lower()]

    by_code: dict[str, dict[str, Any]] = {}
    for store_row in stores:
        store_code = store_row.get("codigo")
        store_name = store_row.get("nombre")
        for key, role in [("deposito_pickup", "pickup"), ("deposito_envio", "shipping")]:
            code = store_row.get(key)
            if code and code not in by_code:
                by_code[code] = {
                    "warehouse_code": code,
                    "warehouse_name": f"{role} {store_code}",
                    "warehouse_type": role,
                    "store_code": store_code,
                    "store_name": store_name,
                    "is_pickup_allowed": role == "pickup",
                    "is_shipping_allowed": role == "shipping",
                }
        for key in ["pickup_group_warehouses", "fulfillment_group_warehouses"]:
            for warehouse in _parse_json_list(store_row.get(key)):
                code = warehouse.get("warehouse_code")
                if not code:
                    continue
                current = by_code.get(code, {})
                by_code[code] = {
                    **current,
                    "warehouse_id": warehouse.get("warehouse_id") or current.get("warehouse_id"),
                    "warehouse_code": code,
                    "warehouse_name": warehouse.get("warehouse_name") or current.get("warehouse_name"),
                    "warehouse_type": warehouse.get("warehouse_type") or current.get("warehouse_type"),
                    "store_code": store_code,
                    "store_name": store_name,
                    "is_pickup_allowed": warehouse.get("is_pickup_allowed", current.get("is_pickup_allowed", False)),
                    "is_shipping_allowed": warehouse.get("is_shipping_allowed", current.get("is_shipping_allowed", False)),
                }

    rows = sorted(by_code.values(), key=lambda row: str(row.get("warehouse_code") or ""))
    rows = [row for row in rows if _contains(row, query, ["warehouse_code", "warehouse_name", "store_code", "store_name"])]
    return {"source_file": str(path), "results": rows[:limit]}


def _material_file(store: str) -> str:
    if store:
        store_file = master_data_dir() / f"materiales_{store}.parquet"
        if store_file.exists():
            return store_file.name
    return "productos_cache.parquet"


def list_materials(*, store: str = "", query: str = "", limit: int = 100) -> dict[str, Any]:
    limit = min(max(limit, 1), 500)
    file_name = _material_file(store)
    if file_name == "productos_cache.parquet":
        columns = [
            "numero_producto",
            "categoria_producto",
            "nombre_producto",
            "grupo_cobertura",
            "unidad_medida",
            "precio_final_con_iva",
            "precio_final_con_descuento",
            "store_number",
            "total_disponible_venta",
            "multiplo",
        ]
    else:
        columns = [
            "numero_producto",
            "codigo_sap",
            "item_id_sap",
            "categoria_producto",
            "nombre_producto",
            "nombre_largo",
            "grupo_cobertura",
            "unidad_medida",
            "unidad_medida_codigo",
            "largo",
            "ancho",
            "alto",
            "peso",
            "um_peso",
            "volumen",
            "um_volumen",
            "multiplo",
            "producto_flete",
            "producto_servicio",
            "precio_base_con_iva",
            "store_number",
            "store_name",
        ]
    path, rows = _read_rows(file_name, columns=_existing_columns(file_name, columns))
    freight_refs = pos_freight_product_refs(store) | pos_freight_product_refs("")
    if store and file_name == "productos_cache.parquet":
        rows = [row for row in rows if str(row.get("store_number") or "").lower() == store.lower()]
    rows = [
        row
        for row in rows
        if _contains(row, query, ["numero_producto", "codigo_sap", "item_id_sap", "nombre_producto", "nombre_largo", "categoria_producto"])
    ]
    results = [
        {
            "item_ref": row.get("numero_producto"),
            "sap_code": row.get("codigo_sap"),
            "sap_item_id": row.get("item_id_sap"),
            "name": row.get("nombre_producto"),
            "long_name": row.get("nombre_largo") or row.get("nombre_producto"),
            "category": row.get("categoria_producto"),
            "coverage_group": row.get("grupo_cobertura"),
            "uom": row.get("unidad_medida"),
            "uom_code": row.get("unidad_medida_codigo") or row.get("unidad_medida"),
            "store_number": row.get("store_number"),
            "store_name": row.get("store_name"),
            "price_with_tax": row.get("precio_base_con_iva") or row.get("precio_final_con_iva"),
            "discounted_price_with_tax": row.get("precio_final_con_descuento"),
            "available_for_sale": row.get("total_disponible_venta"),
            "length": row.get("largo"),
            "width": row.get("ancho"),
            "height": row.get("alto"),
            "weight": row.get("peso"),
            "weight_uom": row.get("um_peso"),
            "volume": row.get("volumen"),
            "volume_uom": row.get("um_volumen"),
            "multiple": row.get("multiplo"),
            "freight_product": _truthy(row.get("producto_flete")) or str(row.get("numero_producto") or "").strip() in freight_refs,
            "service_product": _truthy(row.get("producto_servicio")),
            "virtual_product": _truthy(row.get("producto_flete")) or _truthy(row.get("producto_servicio")) or str(row.get("numero_producto") or "").strip() in freight_refs,
        }
        for row in rows[:limit]
    ]
    _cache_material_snapshots(store=store, rows=results, source_file=str(path))
    return {"source_file": str(path), "results": results}


def material_snapshots_for_items(*, store: str = "", item_refs: Iterable[str]) -> dict[str, Any]:
    refs = sorted({str(item_ref or "").strip() for item_ref in item_refs if str(item_ref or "").strip()})
    if not refs:
        return {"source_file": "", "results": {}}

    cached_results = _cached_material_snapshots(store=store, item_refs=refs)
    missing_refs = sorted(set(refs) - set(cached_results))
    if not missing_refs:
        return {"source_file": "tmswms.logistics_materialmastersnapshot", "results": cached_results}

    file_name = _material_file(store)
    if file_name == "productos_cache.parquet":
        columns = [
            "numero_producto",
            "categoria_producto",
            "nombre_producto",
            "grupo_cobertura",
            "unidad_medida",
            "precio_final_con_iva",
            "precio_final_con_descuento",
            "store_number",
            "total_disponible_venta",
            "multiplo",
        ]
    else:
        columns = [
            "numero_producto",
            "codigo_sap",
            "item_id_sap",
            "categoria_producto",
            "nombre_producto",
            "nombre_largo",
            "grupo_cobertura",
            "unidad_medida",
            "unidad_medida_codigo",
            "unidad_medida_desc",
            "largo",
            "ancho",
            "alto",
            "peso",
            "um_peso",
            "volumen",
            "um_volumen",
            "multiplo",
            "producto_flete",
            "producto_servicio",
            "store_number",
            "store_name",
            "total_disponible_entrega",
        ]
    path = master_data_dir() / file_name
    if not path.exists():
        if cached_results:
            return {"source_file": "tmswms.logistics_materialmastersnapshot", "results": cached_results}
        raise MasterDataSourceError(f"No existe el archivo Parquet {path}.")

    try:
        import pyarrow.dataset as dataset

        filter_expression = dataset.field("numero_producto").isin(missing_refs)
        if store and file_name == "productos_cache.parquet":
            filter_expression = filter_expression & (dataset.field("store_number") == store)
        columns = _existing_columns(file_name, columns)
        table = dataset.dataset(path, format="parquet").to_table(columns=columns, filter=filter_expression)
        rows = [_safe(row) for row in table.to_pylist()]
    except Exception:
        try:
            _, rows = _read_rows(file_name, columns=_existing_columns(file_name, columns))
            refs_set = set(missing_refs)
            rows = [row for row in rows if str(row.get("numero_producto") or "").strip() in refs_set]
            if store and file_name == "productos_cache.parquet":
                rows = [row for row in rows if str(row.get("store_number") or "").lower() == store.lower()]
        except MasterDataSourceError:
            if cached_results:
                return {"source_file": "tmswms.logistics_materialmastersnapshot", "results": cached_results}
            raise

    results: dict[str, dict[str, Any]] = {}
    freight_refs = pos_freight_product_refs(store) | pos_freight_product_refs("")
    for row in rows:
        item_ref = str(row.get("numero_producto") or "").strip()
        if not item_ref or item_ref in results:
            continue
        freight_product = _truthy(row.get("producto_flete")) or item_ref in freight_refs
        service_product = _truthy(row.get("producto_servicio"))
        results[item_ref] = {
            "item_ref": item_ref,
            "sap_code": row.get("codigo_sap"),
            "sap_item_id": row.get("item_id_sap"),
            "name": row.get("nombre_producto"),
            "long_name": row.get("nombre_largo") or row.get("nombre_producto"),
            "category": row.get("categoria_producto"),
            "coverage_group": row.get("grupo_cobertura"),
            "uom": row.get("unidad_medida"),
            "uom_code": row.get("unidad_medida_codigo") or row.get("unidad_medida"),
            "store_number": row.get("store_number"),
            "store_name": row.get("store_name"),
            "weight": row.get("peso"),
            "weight_uom": row.get("um_peso"),
            "volume": row.get("volumen"),
            "volume_uom": row.get("um_volumen"),
            "multiple": row.get("multiplo"),
            "freight_product": freight_product,
            "service_product": service_product,
            "virtual_product": freight_product or service_product,
            "source": "parquet",
        }
    _cache_material_snapshots(store=store, rows=results.values(), source_file=str(path))
    missing_cached = _cached_material_snapshots(store=store, item_refs=set(missing_refs) - set(results))
    results.update({item_ref: row for item_ref, row in missing_cached.items() if item_ref not in results})
    merged_results = {**cached_results, **results}
    source_file = str(path) if results else "tmswms.logistics_materialmastersnapshot"
    return {"source_file": source_file, "results": merged_results}
