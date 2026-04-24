from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.conf import settings


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


def _read_rows(file_name: str, *, columns: list[str] | None = None) -> tuple[Path, list[dict[str, Any]]]:
    base_dir = master_data_dir()
    path = base_dir / file_name
    if not path.exists():
        raise MasterDataSourceError(f"No existe el archivo Parquet {path}.")
    table = _parquet().read_table(path, columns=columns)
    return path, [_safe(row) for row in table.to_pylist()]


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


def list_warehouses(*, store: str = "", query: str = "", limit: int = 500) -> dict[str, Any]:
    limit = min(max(limit, 1), 1000)
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
            "volumen",
            "multiplo",
            "producto_flete",
            "precio_base_con_iva",
            "store_number",
            "store_name",
        ]
    path, rows = _read_rows(file_name, columns=columns)
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
            "volume": row.get("volumen"),
            "multiple": row.get("multiplo"),
            "freight_product": row.get("producto_flete"),
        }
        for row in rows[:limit]
    ]
    return {"source_file": str(path), "results": results}
