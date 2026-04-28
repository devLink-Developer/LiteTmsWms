from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.utils import timezone

from apps.inventory.models import InventoryBalance, StockState


STOCK_CACHE_FILE_NAME = "stock_cache.parquet"
STOCK_CACHE_KEY_COLUMNS = ("codigo", "almacen_365")
STOCK_CACHE_QUANTITY_COLUMNS = frozenset(
    {
        "stock_fisico",
        "disponible_venta",
        "disponible_entrega",
        "comprometido",
    }
)
QTY_SCALE = Decimal("0.000001")


class StockCacheImportError(ValueError):
    pass


@dataclass(frozen=True)
class StockCacheMapping:
    stock_state: str
    quantity_field: str


@dataclass(frozen=True)
class StockCacheImportResult:
    source_path: str
    mappings: tuple[StockCacheMapping, ...]
    source_rows: int
    candidate_balances: int
    written_balances: int
    deleted_balances: int
    skipped_missing_keys: int
    skipped_zero_quantity: int
    invalid_quantities: int
    clamped_negative_quantities: int
    dry_run: bool


def default_stock_cache_mappings() -> tuple[StockCacheMapping, ...]:
    return (StockCacheMapping(StockState.PACKED, "disponible_entrega"),)


def parse_stock_cache_mappings(raw_mappings: Iterable[str] | None) -> tuple[StockCacheMapping, ...]:
    mappings: list[StockCacheMapping] = []
    for raw_mapping in raw_mappings or []:
        state, separator, quantity_field = raw_mapping.partition("=")
        state = state.strip()
        quantity_field = quantity_field.strip()
        if separator != "=" or not state or not quantity_field:
            raise StockCacheImportError(
                "Cada mapping debe tener formato stock_state=columna, por ejemplo packed=disponible_entrega."
            )
        if state not in StockState.values:
            valid_states = ", ".join(StockState.values)
            raise StockCacheImportError(f"Estado de stock invalido '{state}'. Valores validos: {valid_states}.")
        if quantity_field not in STOCK_CACHE_QUANTITY_COLUMNS:
            valid_columns = ", ".join(sorted(STOCK_CACHE_QUANTITY_COLUMNS))
            raise StockCacheImportError(f"Columna de stock invalida '{quantity_field}'. Columnas validas: {valid_columns}.")
        mappings.append(StockCacheMapping(state, quantity_field))
    return tuple(mappings) or default_stock_cache_mappings()


def resolve_stock_cache_path(path: str | Path | None = None) -> Path:
    if path:
        resolved = Path(path).expanduser()
        if resolved.is_dir():
            resolved = resolved / STOCK_CACHE_FILE_NAME
        if not resolved.exists():
            raise StockCacheImportError(f"No se encontro el archivo de stock: {resolved}")
        return resolved

    checked: list[str] = []
    for raw_dir in [settings.MASTER_DATA_PARQUET_DIR, *settings.MASTER_DATA_PARQUET_FALLBACK_DIRS]:
        if not raw_dir:
            continue
        candidate = Path(raw_dir).expanduser() / STOCK_CACHE_FILE_NAME
        checked.append(str(candidate))
        if candidate.exists():
            return candidate

    raise StockCacheImportError(f"No se encontro {STOCK_CACHE_FILE_NAME}. Rutas revisadas: {', '.join(checked)}")


def _parquet():
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise StockCacheImportError("pyarrow es requerido para leer stock_cache.parquet.") from exc
    return parquet


def _clean_ref(value) -> str:
    return str(value or "").strip()


def _quantity(value) -> Decimal:
    if value in [None, ""]:
        return Decimal("0")
    if isinstance(value, float) and not math.isfinite(value):
        raise StockCacheImportError("Cantidad no finita.")
    try:
        return Decimal(str(value)).quantize(QTY_SCALE)
    except (InvalidOperation, ValueError) as exc:
        raise StockCacheImportError("Cantidad invalida.") from exc


def _flush_balances(balances_by_key: dict[tuple[str, str, str, str, str], InventoryBalance], *, batch_size: int, dry_run: bool) -> int:
    if not balances_by_key:
        return 0
    balances = list(balances_by_key.values())
    if dry_run:
        balances_by_key.clear()
        return 0
    InventoryBalance.objects.bulk_create(
        balances,
        batch_size=batch_size,
        update_conflicts=True,
        update_fields=["quantity", "updated_by", "updated_at"],
        unique_fields=["warehouse_ref", "item_ref", "lot_ref", "stock_state", "uom"],
    )
    balances_by_key.clear()
    return len(balances)


def import_stock_cache(
    *,
    path: str | Path | None = None,
    mappings: Iterable[StockCacheMapping] | None = None,
    actor: str = "stock-cache-import",
    batch_size: int = 5000,
    uom: str = "UN",
    include_zero: bool = False,
    allow_negative: bool = False,
    reset_state: bool = False,
    dry_run: bool = False,
) -> StockCacheImportResult:
    if batch_size < 1:
        raise StockCacheImportError("batch_size debe ser mayor a cero.")

    resolved_path = resolve_stock_cache_path(path)
    parsed_mappings = tuple(mappings or default_stock_cache_mappings())
    if not parsed_mappings:
        raise StockCacheImportError("Debe indicarse al menos un mapping de stock.")

    required_columns = [*STOCK_CACHE_KEY_COLUMNS, *sorted({mapping.quantity_field for mapping in parsed_mappings})]
    try:
        table = _parquet().read_table(resolved_path, columns=required_columns)
    except Exception as exc:
        raise StockCacheImportError(f"No se pudo leer {resolved_path}: {exc}") from exc

    source_rows = 0
    candidate_balances = 0
    written_balances = 0
    skipped_missing_keys = 0
    skipped_zero_quantity = 0
    invalid_quantities = 0
    clamped_negative_quantities = 0
    balances_by_key: dict[tuple[str, str, str, str, str], InventoryBalance] = {}
    now = timezone.now()
    actor = actor.strip() or "stock-cache-import"
    uom = uom.strip() or "UN"

    deleted_balances = 0
    if reset_state:
        reset_qs = InventoryBalance.objects.filter(
            stock_state__in=sorted({mapping.stock_state for mapping in parsed_mappings}),
            uom=uom,
        )
        deleted_balances = reset_qs.count()
        if not dry_run:
            reset_qs.delete()

    for row in table.to_pylist():
        source_rows += 1
        item_ref = _clean_ref(row.get("codigo"))
        warehouse_ref = _clean_ref(row.get("almacen_365"))
        if not item_ref or not warehouse_ref:
            skipped_missing_keys += 1
            continue

        for mapping in parsed_mappings:
            try:
                quantity = _quantity(row.get(mapping.quantity_field))
            except StockCacheImportError:
                invalid_quantities += 1
                continue
            if quantity < 0 and not allow_negative:
                quantity = Decimal("0").quantize(QTY_SCALE)
                clamped_negative_quantities += 1
            if quantity == 0 and not include_zero:
                skipped_zero_quantity += 1
                continue

            key = (warehouse_ref, item_ref, "", mapping.stock_state, uom)
            balances_by_key[key] = InventoryBalance(
                warehouse_ref=warehouse_ref,
                item_ref=item_ref,
                lot_ref="",
                stock_state=mapping.stock_state,
                uom=uom,
                quantity=quantity,
                created_by=actor,
                updated_by=actor,
                created_at=now,
                updated_at=now,
            )
            candidate_balances += 1
            if len(balances_by_key) >= batch_size:
                written_balances += _flush_balances(balances_by_key, batch_size=batch_size, dry_run=dry_run)

    written_balances += _flush_balances(balances_by_key, batch_size=batch_size, dry_run=dry_run)

    return StockCacheImportResult(
        source_path=str(resolved_path),
        mappings=parsed_mappings,
        source_rows=source_rows,
        candidate_balances=candidate_balances,
        written_balances=written_balances,
        deleted_balances=deleted_balances,
        skipped_missing_keys=skipped_missing_keys,
        skipped_zero_quantity=skipped_zero_quantity,
        invalid_quantities=invalid_quantities,
        clamped_negative_quantities=clamped_negative_quantities,
        dry_run=dry_run,
    )
