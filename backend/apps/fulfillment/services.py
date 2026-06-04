from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.utils import DatabaseError
from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.models import AuditTrail, DomainEventOutbox, IdempotencyKey, StatusHistory
from apps.core.sequences import allocate_sequence_number
from apps.fulfillment.delivery_modes import is_shipping_delivery_mode
from apps.fulfillment.models import (
    DeliveryDocument,
    DeliveryDocumentLine,
    DeliveryOrder,
    DeliveryOrderLine,
    DeliveryPreparationTask,
    DeliverySplit,
    FulfillmentOrder,
    FulfillmentOrderImpact,
    FulfillmentOrderImpactLine,
    FulfillmentOrderLine,
)
from apps.integrations.legacy.models import (
    LegacyCustomer,
    LegacyCustomerAddress,
    LegacyCustomerContact,
    LegacyItem,
    LegacyOrder,
    LegacyOrderInvoice,
    LegacyOrderLine,
)
from apps.inventory.models import InventoryBalance, InventoryLedgerEntry, InventoryReservation, InventoryReservationLine, StockState
from apps.inventory.services import (
    InventoryRuleError,
    LedgerCommand,
    available_stock_quantities_for_keys,
    location_ref_for_purpose,
    move_prepared_stock_to_state,
    move_reserved_inventory_to_preparation,
    pack_reserved_inventory,
    post_ledger_entry,
    release_inventory_reservation,
    reserve_inventory,
)
from apps.logistics.parquet_master_data import MasterDataSourceError, customer_refs_for_dni, material_snapshots_for_items, pos_freight_product_refs


DELIVERY_SEQUENCE_NAME = "Entregas"
REMITO_SEQUENCE_NAME = "Remitos"


class FulfillmentRuleError(ValueError):
    pass


class FulfillmentAuthorizationError(PermissionError):
    pass


@dataclass(frozen=True)
class IdempotentResult:
    payload: dict
    status: int = 200


ZERO = Decimal("0")
ONE = Decimal("1")
QTY_SCALE = Decimal("0.000001")
SAP_UOM_DISPLAY_MAP = {
    "ST": "Un",
    "UN": "Un",
    "UND": "Un",
    "UNIDAD": "Un",
    "UNIDADES": "Un",
    "M2": "m2",
    "M3": "m3",
    "KG": "kg",
}
LEGACY_ORDER_TYPE_DELIVERABLE = "P"
LEGACY_ORDER_TYPE_ANNULMENT = "A"
LEGACY_ORDER_TYPE_RETURN = "D"
LEGACY_IMPACT_TYPES = {LEGACY_ORDER_TYPE_ANNULMENT, LEGACY_ORDER_TYPE_RETURN}


def legacy_sales_order_type(order: LegacyOrder) -> str:
    return str(getattr(order, "sales_order_type", "") or LEGACY_ORDER_TYPE_DELIVERABLE).strip().upper()[:1] or LEGACY_ORDER_TYPE_DELIVERABLE


def legacy_order_is_deliverable(order: LegacyOrder) -> bool:
    return legacy_sales_order_type(order) == LEGACY_ORDER_TYPE_DELIVERABLE


def _to_decimal(value, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _quantize_qty(value: Decimal) -> Decimal:
    return value.quantize(QTY_SCALE)


def _display_qty(value) -> str:
    qty = _to_decimal(value)
    if qty == qty.to_integral_value():
        return format(qty.quantize(ONE), "f")
    return format(qty.normalize(), "f")


def _ledger_idempotency_key(value: str) -> str:
    key = str(value or "").strip()
    if len(key) <= 120:
        return key
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return f"ledger:{digest}"


def _clean(value) -> str:
    return str(value or "").strip()


def _coordinate_text(value) -> str:
    if value is None or value == "":
        return ""
    return str(value).strip()


def _coordinates_available(latitude, longitude) -> bool:
    lat = _coordinate_text(latitude)
    lng = _coordinate_text(longitude)
    if not lat or not lng:
        return False
    return _to_decimal(lat) != ZERO or _to_decimal(lng) != ZERO


def _legacy_truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return _clean(value).casefold() in {"1", "true", "t", "yes", "y", "si", "sí", "s"}


def _normalize_uom(value: str) -> str:
    normalized = _clean(value)
    return normalized or "un"


def _display_uom(value: str) -> str:
    normalized = _normalize_uom(value)
    return SAP_UOM_DISPLAY_MAP.get(normalized.upper(), normalized)


def _weight_to_kg(value, uom: str) -> Decimal:
    weight = _to_decimal(value)
    unit = _clean(uom).casefold()
    if unit in {"g", "gr", "gram", "grams", "gramo", "gramos"}:
        return weight / Decimal("1000")
    if unit in {"t", "tn", "ton", "tons", "tonelada", "toneladas"}:
        return weight * Decimal("1000")
    if unit in {"lb", "lbs"}:
        return weight * Decimal("0.45359237")
    return weight


def _volume_to_m3(value, uom: str) -> Decimal:
    volume = _to_decimal(value)
    unit = _clean(uom).casefold()
    if unit in {"ccm", "cm3", "cm^3", "cm³"}:
        return volume / Decimal("1000000")
    if unit in {"dm3", "dm^3", "dm³", "l", "lt", "lts", "litro", "litros"}:
        return volume / Decimal("1000")
    if unit in {"mm3", "mm^3", "mm³"}:
        return volume / Decimal("1000000000")
    return volume


def _normalize_item_snapshot(raw: dict, *, item_ref: str, sales_uom: str) -> dict:
    factor = _to_decimal(raw.get("multiple") or raw.get("multiplo"), "1")
    if factor <= ZERO:
        factor = ONE
    raw_sales_uom = _normalize_uom(raw.get("uom_code") or raw.get("uom") or sales_uom)
    sales_uom = _display_uom(raw_sales_uom)
    delivery_uom = "caja" if factor != ONE else sales_uom
    weight_kg = _weight_to_kg(raw.get("weight") or raw.get("peso"), raw.get("weight_uom") or raw.get("um_peso") or "kg")
    volume_m3 = _volume_to_m3(raw.get("volume") or raw.get("volumen"), raw.get("volume_uom") or raw.get("um_volumen") or "m3")
    name = _clean(raw.get("name") or raw.get("nombre_producto") or item_ref)
    freight_product = _legacy_truthy(raw.get("freight_product") or raw.get("producto_flete"))
    service_product = _legacy_truthy(raw.get("service_product") or raw.get("producto_servicio"))
    return {
        "item_ref": item_ref,
        "name": name,
        "long_name": _clean(raw.get("long_name") or raw.get("nombre_largo") or name),
        "category": _clean(raw.get("category") or raw.get("categoria_producto")),
        "coverage_group": _clean(raw.get("coverage_group") or raw.get("grupo_cobertura")),
        "sap_uom": raw_sales_uom,
        "sales_uom": sales_uom,
        "delivery_uom": delivery_uom,
        "conversion_factor": str(_quantize_qty(factor)),
        "unit_weight_kg": str(_quantize_qty(weight_kg)),
        "unit_volume_m3": str(_quantize_qty(volume_m3)),
        "freight_product": freight_product,
        "service_product": service_product,
        "virtual_product": freight_product or service_product,
        "source": _clean(raw.get("source")) or "fallback",
    }


def _default_item_snapshot(item_ref: str, sales_uom: str) -> dict:
    return _normalize_item_snapshot({}, item_ref=item_ref, sales_uom=sales_uom)


def _with_display_uom(snapshot: dict, *, fallback_uom: str) -> dict:
    normalized = dict(snapshot or {})
    raw_sales_uom = normalized.get("sap_uom") or normalized.get("sales_uom") or normalized.get("uom") or fallback_uom
    normalized["sap_uom"] = _normalize_uom(raw_sales_uom)
    normalized["sales_uom"] = _display_uom(raw_sales_uom)
    raw_delivery_uom = normalized.get("delivery_uom") or normalized["sales_uom"]
    normalized["delivery_uom"] = _display_uom(raw_delivery_uom)
    freight_product = _legacy_truthy(normalized.get("freight_product") or normalized.get("producto_flete"))
    service_product = _legacy_truthy(normalized.get("service_product") or normalized.get("producto_servicio"))
    normalized["freight_product"] = freight_product
    normalized["service_product"] = service_product
    normalized["virtual_product"] = freight_product or service_product or _legacy_truthy(normalized.get("virtual_product"))
    return normalized


def is_virtual_item_snapshot(snapshot: dict | None) -> bool:
    snapshot = snapshot or {}
    return (
        _legacy_truthy(snapshot.get("virtual_product"))
        or _legacy_truthy(snapshot.get("freight_product"))
        or _legacy_truthy(snapshot.get("service_product"))
        or _legacy_truthy(snapshot.get("producto_flete"))
        or _legacy_truthy(snapshot.get("producto_servicio"))
    )


def is_virtual_delivery_line(line: DeliveryOrderLine) -> bool:
    return is_virtual_item_snapshot(_delivery_line_snapshot(line))


def _pos_freight_refs_for_store(store_ref: str) -> set[str]:
    try:
        return pos_freight_product_refs(store_ref) | pos_freight_product_refs("")
    except MasterDataSourceError:
        return set()


def _mark_pos_freight_snapshot(snapshot: dict, *, item_ref: str, store_ref: str, freight_refs: set[str] | None = None) -> dict:
    if freight_refs is None:
        freight_refs = _pos_freight_refs_for_store(store_ref)
    if item_ref in freight_refs:
        snapshot = dict(snapshot)
        snapshot["freight_product"] = True
        snapshot["virtual_product"] = True
    return snapshot


def _item_conversion_factor(snapshot: dict) -> Decimal:
    factor = _to_decimal(snapshot.get("conversion_factor"), "1")
    return factor if factor > ZERO else ONE


def _commercial_qty_from_delivery_units(delivery_unit_qty: Decimal, snapshot: dict) -> Decimal:
    return _quantize_qty(delivery_unit_qty * _item_conversion_factor(snapshot))


def _delivery_unit_qty_from_commercial(commercial_qty: Decimal, snapshot: dict) -> Decimal:
    return _quantize_qty(commercial_qty / _item_conversion_factor(snapshot))


def _capacity_totals(commercial_qty: Decimal, snapshot: dict) -> tuple[Decimal, Decimal]:
    weight = _to_decimal(snapshot.get("unit_weight_kg")) * commercial_qty
    volume = _to_decimal(snapshot.get("unit_volume_m3")) * commercial_qty
    return _quantize_qty(weight), _quantize_qty(volume)


def _hash_payload(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_safe_payload(payload: dict) -> dict:
    return json.loads(json.dumps(payload, sort_keys=True, default=str))


def _warehouse_set(authorized_warehouses) -> set[str] | None:
    if authorized_warehouses is None:
        return None
    return {str(warehouse).strip() for warehouse in authorized_warehouses if str(warehouse).strip()}


def _ensure_warehouse_authorized(warehouse_ref: str, authorized_warehouses) -> None:
    allowed = _warehouse_set(authorized_warehouses)
    if allowed is None:
        return
    if not allowed or str(warehouse_ref or "").strip() not in allowed:
        raise FulfillmentAuthorizationError("El usuario no tiene permiso para operar entregas en este deposito.")


def _inactive_reservation_statuses() -> list[str]:
    return [
        InventoryReservation.ReservationStatus.RELEASED,
        InventoryReservation.ReservationStatus.CANCELLED,
        InventoryReservation.ReservationStatus.EXPIRED,
    ]


def _active_delivery_reservations():
    return InventoryReservation.objects.exclude(status__in=_inactive_reservation_statuses())


def _target_warehouse(warehouse_ref: str | None) -> str:
    return str(warehouse_ref or "").strip()


def _delivery_line_warehouse(line: DeliveryOrderLine, delivery: DeliveryOrder, target_warehouse_ref: str = "") -> str:
    return _target_warehouse(target_warehouse_ref) or line.warehouse_ref or delivery.warehouse_ref


def _fulfillment_line_warehouse(line: FulfillmentOrderLine, fulfillment: FulfillmentOrder, target_warehouse_ref: str = "") -> str:
    return _target_warehouse(target_warehouse_ref) or line.warehouse_ref or fulfillment.warehouse_ref


def _start_idempotent_command(
    *,
    key: str,
    operation_type: str,
    reference_type: str,
    reference_id: str,
    payload: dict,
) -> tuple[IdempotencyKey, bool]:
    request_hash = _hash_payload(payload)
    existing = IdempotencyKey.objects.filter(key=key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise FulfillmentRuleError("La Idempotency-Key ya fue usada con otro payload.")
        return existing, True

    return (
        IdempotencyKey.objects.create(
            key=key,
            operation_type=operation_type,
            reference_type=reference_type,
            reference_id=reference_id,
            request_hash=request_hash,
        ),
        False,
    )


def _finish_idempotent_command(record: IdempotencyKey, result: IdempotentResult) -> IdempotentResult:
    record.response_payload = result.payload
    record.response_status = result.status
    record.status = IdempotencyKey.ProcessingStatus.SUCCEEDED
    record.save(update_fields=["response_payload", "response_status", "status", "updated_at"])
    return result


def _order_is_effectively_invoiced(order: LegacyOrder) -> bool:
    if not order.invoice_number.strip() or order.invoice_date is None:
        return False

    invoice = (
        LegacyOrderInvoice.objects.using("litecore")
        .filter(sales_order_number=order.sales_order_number, invoice_number=order.invoice_number)
        .first()
    )
    if not invoice:
        return True

    rejected_states = {"rejected", "rechazada", "error", "failed", "cancelled", "canceled", "anulada"}
    return invoice.estado.strip().lower() not in rejected_states


def _line_remaining_qty(line: LegacyOrderLine) -> Decimal:
    if line.remain_sales_physical is not None:
        return max(Decimal("0"), line.remain_sales_physical)
    delivered = line.sales_quantity_delivered or Decimal("0")
    return max(Decimal("0"), line.ordered_sales_quantity - delivered)


def _line_delivery_datetime(line: LegacyOrderLine):
    return line.line_delivery_date or line.requested_shipping_date


def _line_delivery_date(line: LegacyOrderLine):
    delivery_datetime = _line_delivery_datetime(line)
    return delivery_datetime.date() if delivery_datetime else None


def _address_snapshot(
    line: LegacyOrderLine | None,
    *,
    fulfillment: FulfillmentOrder | None = None,
    customer: dict | None = None,
    customer_address: LegacyCustomerAddress | None = None,
) -> dict:
    if line is None:
        return {}

    receiver = (customer or {}).get("name") or (fulfillment.customer_ref if fulfillment else "")
    customer_payload = _serialize_customer_address(customer_address)
    line_payload = {
        "address_id": line.delivery_address_location_id,
        "location_id": line.delivery_address_location_id,
        "line_address_id": line.delivery_address_location_id,
        "country_region_iso_code": line.delivery_address_country_region_iso_code,
        "state": line.delivery_address_state_id,
        "city": line.delivery_address_city,
        "street": line.delivery_address_street,
        "street_number": line.delivery_address_street_number,
        "zip_code": line.delivery_address_zip_code,
        "description": line.delivery_address_description,
        "reference": line.delivery_address_description,
        "latitude": str(line.delivery_address_latitude) if line.delivery_address_latitude is not None else "",
        "longitude": str(line.delivery_address_longitude) if line.delivery_address_longitude is not None else "",
        "receiver": receiver,
        "customer_ref": fulfillment.customer_ref if fulfillment else "",
        "geo_source": "legacy_order_line" if _coordinates_available(line.delivery_address_latitude, line.delivery_address_longitude) else "",
    }
    payload = {key: value for key, value in customer_payload.items() if _clean(value)}
    for key, value in line_payload.items():
        if _clean(value):
            payload[key] = value
    if _coordinates_available(customer_payload.get("latitude"), customer_payload.get("longitude")):
        payload["latitude"] = customer_payload["latitude"]
        payload["longitude"] = customer_payload["longitude"]
        payload["geo_source"] = "legacy_customer_address"
    elif _coordinates_available(line_payload.get("latitude"), line_payload.get("longitude")):
        payload["geo_source"] = "legacy_order_line"
    return {key: value for key, value in payload.items() if _clean(value)}


def _address_text(address: dict) -> str:
    return (
        _clean(address.get("formatted"))
        or " ".join(
            part
            for part in [
                _clean(address.get("street")),
                _clean(address.get("street_number")),
                _clean(address.get("city")),
                _clean(address.get("state")),
                _clean(address.get("zip_code")),
            ]
            if part
        )
    )


def _default_customer_snapshot(customer_ref: str) -> dict:
    return {
        "customer_ref": customer_ref,
        "name": customer_ref,
        "document_type": "",
        "document_number": "",
        "phone": "",
        "email": "",
        "address": {},
        "address_text": "",
        "source": "fallback",
    }


def _serialize_customer_address(address: LegacyCustomerAddress | None) -> dict:
    if address is None:
        return {}
    payload = {
        "address_id": address.address_location_id,
        "location_id": address.address_location_id,
        "address_rec_id": str(address.rec_id),
        "customer_ref": address.customer_account_number,
        "country_region_iso_code": address.address_country_region_iso_code,
        "description": address.address_description,
        "street": address.address_street,
        "street_number": address.address_street_number,
        "city": address.address_city,
        "state": address.address_state,
        "zip_code": address.address_zip_code,
        "formatted": address.formatted_address,
        "attention_to": address.attention_to_address_line,
        "reference": address.address_reference,
        "latitude": _coordinate_text(address.address_latitude),
        "longitude": _coordinate_text(address.address_longitude),
        "geo_source": "legacy_customer_address",
    }
    return {key: value for key, value in payload.items() if _clean(value)}


def _select_customer_address(addresses: list[LegacyCustomerAddress]) -> LegacyCustomerAddress | None:
    if not addresses:
        return None
    return sorted(
        addresses,
        key=lambda row: (
            _legacy_truthy(row.is_primary),
            _legacy_truthy(row.is_role_delivery),
            row.modified_datetime.timestamp() if row.modified_datetime else 0,
        ),
        reverse=True,
    )[0]


def _resolve_customer_address_for_line(line: LegacyOrderLine | None, customer_ref: str = "") -> LegacyCustomerAddress | None:
    if line is None:
        return None
    location_id = _clean(getattr(line, "delivery_address_location_id", ""))
    customer_ref = _clean(customer_ref)
    try:
        if location_id:
            queryset = LegacyCustomerAddress.objects.using("litecore").filter(address_location_id=location_id, estado=True)
            if customer_ref:
                exact = queryset.filter(customer_account_number=customer_ref).first()
                if exact:
                    return exact
            by_location = queryset.first()
            if by_location:
                return by_location
        if customer_ref:
            addresses = list(
                LegacyCustomerAddress.objects.using("litecore")
                .filter(customer_account_number=customer_ref, estado=True)
                .order_by("customer_account_number")
            )
            return _select_customer_address(addresses)
    except (DatabaseError, OSError):
        return None
    return None


def _resolve_customer_contacts(contacts: list[LegacyCustomerContact]) -> tuple[str, str]:
    ordered = sorted(contacts, key=lambda row: _legacy_truthy(row.is_primary), reverse=True)
    email = ""
    phone = ""
    for contact in ordered:
        contact_type = f"{contact.type} {contact.purpose} {contact.description}".casefold()
        locator = _clean(contact.locator)
        if not email and ("@" in locator or "email" in contact_type or "correo" in contact_type):
            email = locator
        if not phone and ("phone" in contact_type or "tel" in contact_type or "movil" in contact_type or "móvil" in contact_type):
            phone = locator
    return phone, email


def _resolve_customer_snapshots(customer_refs: set[str]) -> dict[str, dict]:
    refs = {_clean(ref) for ref in customer_refs if _clean(ref)}
    snapshots = {ref: _default_customer_snapshot(ref) for ref in refs}
    if not refs:
        return snapshots

    try:
        customers = list(LegacyCustomer.objects.using("litecore").filter(customer_account__in=refs))
        addresses = list(
            LegacyCustomerAddress.objects.using("litecore")
            .filter(customer_account_number__in=refs, estado=True)
            .order_by("customer_account_number")
        )
        contacts = list(
            LegacyCustomerContact.objects.using("litecore")
            .filter(customer_account__in=refs, estado=True)
            .order_by("customer_account")
        )
    except (DatabaseError, OSError):
        return snapshots

    addresses_by_customer: dict[str, list[LegacyCustomerAddress]] = defaultdict(list)
    for address in addresses:
        addresses_by_customer[_clean(address.customer_account_number)].append(address)
    contacts_by_customer: dict[str, list[LegacyCustomerContact]] = defaultdict(list)
    for contact in contacts:
        contacts_by_customer[_clean(contact.customer_account)].append(contact)

    for customer in customers:
        customer_ref = _clean(customer.customer_account)
        address = _serialize_customer_address(_select_customer_address(addresses_by_customer.get(customer_ref, [])))
        phone, email = _resolve_customer_contacts(contacts_by_customer.get(customer_ref, []))
        name = " ".join(
            part
            for part in [
                _clean(customer.person_first_name),
                _clean(customer.person_last_name),
            ]
            if part
        ) or _clean(customer.organization_name) or customer_ref
        snapshots[customer_ref] = {
            "customer_ref": customer_ref,
            "name": name,
            "document_type": _clean(customer.tax_fiscal_identification_type),
            "document_number": _clean(customer.tax_exempt_number),
            "phone": phone or _clean(customer.primary_contact_phone),
            "email": email or _clean(customer.receipt_email),
            "address": address,
            "address_text": _address_text(address),
            "source": "legacy",
        }
    return snapshots


def _legacy_item_snapshots(item_refs: set[str], sales_uom_by_item: dict[str, str]) -> dict[str, dict]:
    if not item_refs:
        return {}
    try:
        items = list(LegacyItem.objects.using("litecore").filter(numero_producto__in=item_refs))
    except Exception:
        return {}
    return {
        item.numero_producto: _normalize_item_snapshot(
            {
                "name": item.nombre_producto,
                "uom": item.um_base_codigo,
                "weight": item.peso_bruto,
                "weight_uom": "kg",
                "volume": item.volumen,
                "volume_uom": "m3",
                "multiple": item.multiplo,
                "source": "legacy",
            },
            item_ref=item.numero_producto,
            sales_uom=sales_uom_by_item.get(item.numero_producto, ""),
        )
        for item in items
    }


def _resolve_line_item_snapshots(lines: list[FulfillmentOrderLine]) -> dict:
    snapshots = {}
    lines_by_store: dict[str, list[FulfillmentOrderLine]] = defaultdict(list)
    sales_uom_by_item: dict[str, str] = {}
    for line in lines:
        item_ref = _clean(line.item_ref)
        if not item_ref:
            continue
        store_ref = _clean(line.store_ref or line.warehouse_ref)
        lines_by_store[store_ref].append(line)
        sales_uom_by_item[item_ref] = line.uom

    for store_ref, store_lines in lines_by_store.items():
        item_refs = {_clean(line.item_ref) for line in store_lines if _clean(line.item_ref)}
        freight_refs = _pos_freight_refs_for_store(store_ref)
        parquet_results = {}
        try:
            parquet_results = material_snapshots_for_items(store=store_ref, item_refs=item_refs).get("results", {})
        except MasterDataSourceError:
            parquet_results = {}
        missing_item_refs = set(item_refs)
        for line in store_lines:
            raw = parquet_results.get(_clean(line.item_ref))
            if not raw:
                continue
            snapshots[line.id] = _mark_pos_freight_snapshot(
                _normalize_item_snapshot(raw, item_ref=line.item_ref, sales_uom=line.uom),
                item_ref=line.item_ref,
                store_ref=store_ref,
                freight_refs=freight_refs,
            )
            missing_item_refs.discard(_clean(line.item_ref))
        legacy_results = _legacy_item_snapshots(missing_item_refs, sales_uom_by_item)
        for line in store_lines:
            if line.id in snapshots:
                continue
            snapshots[line.id] = _mark_pos_freight_snapshot(
                legacy_results.get(_clean(line.item_ref), _default_item_snapshot(line.item_ref, line.uom)),
                item_ref=line.item_ref,
                store_ref=store_ref,
                freight_refs=freight_refs,
            )
    return snapshots


def physical_fulfillment_lines(lines: list[FulfillmentOrderLine]) -> list[FulfillmentOrderLine]:
    snapshots = _resolve_line_item_snapshots(lines)
    return physical_fulfillment_lines_from_snapshots(lines, snapshots)


def physical_fulfillment_lines_from_snapshots(
    lines: list[FulfillmentOrderLine],
    snapshots: dict,
) -> list[FulfillmentOrderLine]:
    return [line for line in lines if not is_virtual_item_snapshot(snapshots.get(line.id))]


def physical_delivery_lines(lines: list[DeliveryOrderLine]) -> list[DeliveryOrderLine]:
    snapshots = _resolve_line_item_snapshots([line.fulfillment_line for line in lines])
    return physical_delivery_lines_from_snapshots(lines, snapshots)


def physical_delivery_lines_from_snapshots(
    lines: list[DeliveryOrderLine],
    snapshots: dict,
) -> list[DeliveryOrderLine]:
    return [
        line
        for line in lines
        if not is_virtual_item_snapshot(line.item_snapshot or snapshots.get(line.fulfillment_line_id))
    ]


def _physical_delivery_lines_for_delivery(delivery: DeliveryOrder) -> list[DeliveryOrderLine]:
    lines = list(delivery.lines.all())
    snapshots = _resolve_line_item_snapshots([line.fulfillment_line for line in lines])
    return physical_delivery_lines_from_snapshots(lines, snapshots)


def _legacy_line_store_ref(line: LegacyOrderLine) -> str:
    return _clean(line.fulfillment_store_id or line.shipping_warehouse_id or line.warehouse)


def _resolve_legacy_line_item_snapshots(lines: list[LegacyOrderLine]) -> dict[str, dict]:
    snapshots: dict[str, dict] = {}
    lines_by_store: dict[str, list[LegacyOrderLine]] = defaultdict(list)
    for line in lines:
        if _clean(line.item_number):
            lines_by_store[_legacy_line_store_ref(line)].append(line)

    for store_ref, store_lines in lines_by_store.items():
        item_refs = {_clean(line.item_number) for line in store_lines if _clean(line.item_number)}
        freight_refs = _pos_freight_refs_for_store(store_ref)
        parquet_results = {}
        try:
            parquet_results = material_snapshots_for_items(store=store_ref, item_refs=item_refs).get("results", {})
        except MasterDataSourceError:
            parquet_results = {}
        for line in store_lines:
            item_ref = _clean(line.item_number)
            raw = parquet_results.get(item_ref)
            if raw:
                snapshot = _normalize_item_snapshot(raw, item_ref=item_ref, sales_uom=line.sales_unit_symbol)
            else:
                snapshot = _default_item_snapshot(item_ref, line.sales_unit_symbol)
            snapshots[str(line.retail_line_item_id)] = _mark_pos_freight_snapshot(
                snapshot,
                item_ref=item_ref,
                store_ref=store_ref,
                freight_refs=freight_refs,
            )
    return snapshots


def _delivery_address_snapshot(fulfillment: FulfillmentOrder, *, receiver: str = "", reference: str = "", customer: dict | None = None) -> dict:
    address = dict(fulfillment.address_snapshot or {})
    if not address:
        address = dict((customer or {}).get("address") or {})
    address.update(
        {
            "receiver": _clean(receiver) or (customer or {}).get("name") or fulfillment.customer_ref,
            "reference": _clean(reference) or _clean(address.get("reference")) or _clean(address.get("description")),
            "customer_ref": fulfillment.customer_ref,
        }
    )
    return {key: value for key, value in address.items() if _clean(value)}


def _pickup_authorization(fulfillment: FulfillmentOrder, deliveries: list[DeliveryOrder], customer: dict) -> dict:
    for delivery in reversed(deliveries):
        snapshot = delivery.address_snapshot or {}
        if _clean(snapshot.get("receiver")) or _clean(snapshot.get("reference")):
            return {
                "name": _clean(snapshot.get("receiver")) or customer.get("name") or fulfillment.customer_ref,
                "reference": _clean(snapshot.get("reference")),
                "source": "delivery_snapshot",
            }
    return {
        "name": customer.get("name") or fulfillment.customer_ref,
        "reference": "",
        "source": "customer",
    }


def _prefetched_list(instance, related_name: str):
    if related_name in getattr(instance, "_prefetched_objects_cache", {}):
        return list(getattr(instance, related_name).all())
    return None


def _max_dispatchable_from_values(
    fulfillment_line: FulfillmentOrderLine,
    *,
    already_planned: Decimal,
    packed_qty: Decimal,
) -> Decimal:
    remaining_qty = max(Decimal("0"), fulfillment_line.pending_qty - already_planned)
    packed_remaining = max(Decimal("0"), packed_qty - already_planned)
    return min(remaining_qty, packed_remaining)


def _effective_pending_qty(fulfillment_line: FulfillmentOrderLine, *, open_remito_qty: Decimal = ZERO) -> Decimal:
    documented_qty = max(fulfillment_line.delivered_qty, open_remito_qty)
    return max(ZERO, fulfillment_line.ordered_qty - documented_qty - fulfillment_line.cancelled_qty)


def _max_dispatchable_from_effective_pending(
    *,
    effective_pending_qty: Decimal,
    already_planned: Decimal,
    packed_qty: Decimal,
) -> Decimal:
    remaining_qty = max(ZERO, effective_pending_qty - already_planned)
    packed_remaining = max(ZERO, packed_qty - already_planned)
    return min(remaining_qty, packed_remaining)


def _active_delivery_lines_queryset():
    return DeliveryOrderLine.objects.exclude(
        delivery__documents__document_type=DeliveryDocument.DocumentType.REMITO,
        delivery__documents__status=DeliveryDocument.DocumentStatus.CLOSED,
    ).exclude(
        delivery__status__in=[
            DeliveryOrder.DeliveryStatus.DELIVERED_PARTIAL,
            DeliveryOrder.DeliveryStatus.DELIVERED_COMPLETE,
            DeliveryOrder.DeliveryStatus.RETURNED,
            DeliveryOrder.DeliveryStatus.CANCELLED,
        ]
    )


def _line_metrics(lines: list[FulfillmentOrderLine], *, target_warehouse_ref: str = "") -> dict:
    if not lines:
        return {}

    stock_warehouse_ref = _target_warehouse(target_warehouse_ref)
    line_ids = [line.id for line in lines]
    planned_by_line = {
        row["fulfillment_line_id"]: row["total"] or Decimal("0")
        for row in _active_delivery_lines_queryset()
        .filter(fulfillment_line_id__in=line_ids)
        .values("fulfillment_line_id")
        .annotate(total=Sum("planned_qty"))
    }
    returned_by_line = {
        row["fulfillment_line_id"]: row["total"] or Decimal("0")
        for row in FulfillmentOrderImpactLine.objects.filter(
            fulfillment_line_id__in=line_ids,
            impact__impact_type=FulfillmentOrderImpact.ImpactType.RETURN,
        )
        .values("fulfillment_line_id")
        .annotate(total=Sum("applied_qty"))
    }
    open_remito_by_line = {
        row["delivery_line__fulfillment_line_id"]: row["total"] or Decimal("0")
        for row in DeliveryDocumentLine.objects.filter(
            delivery_line__fulfillment_line_id__in=line_ids,
            document__document_type=DeliveryDocument.DocumentType.REMITO,
            document__status=DeliveryDocument.DocumentStatus.OPEN,
        )
        .exclude(document__delivery__status__in=[DeliveryOrder.DeliveryStatus.RETURNED, DeliveryOrder.DeliveryStatus.CANCELLED])
        .values("delivery_line__fulfillment_line_id")
        .annotate(total=Sum("quantity"))
    }

    packed_by_key = _packed_quantities_for_keys(
        {
            (stock_warehouse_ref or line.warehouse_ref, line.item_ref, line.uom)
            for line in lines
        }
    )

    return {
        line.id: {
            "planned_qty": planned_by_line.get(line.id, Decimal("0")),
            "packed_qty": packed_by_key.get((stock_warehouse_ref or line.warehouse_ref, line.item_ref, line.uom), Decimal("0")),
            "returned_qty": returned_by_line.get(line.id, Decimal("0")),
            "open_remito_qty": open_remito_by_line.get(line.id, Decimal("0")),
            "stock_warehouse_ref": stock_warehouse_ref or line.warehouse_ref,
        }
        for line in lines
    }


def _serialize_fulfillment_line(
    line: FulfillmentOrderLine,
    metrics: dict,
    item_snapshot: dict | None = None,
    *,
    target_warehouse_ref: str = "",
) -> dict:
    metric = metrics.get(line.id)
    if metric is None:
        planned_qty = _planned_elsewhere(line)
        packed_qty = _packed_balance_quantity(line)
        returned_qty = (
            FulfillmentOrderImpactLine.objects.filter(
                fulfillment_line=line,
                impact__impact_type=FulfillmentOrderImpact.ImpactType.RETURN,
            ).aggregate(total=Sum("applied_qty"))["total"]
            or Decimal("0")
        )
    else:
        planned_qty = metric["planned_qty"]
        packed_qty = metric["packed_qty"]
        returned_qty = metric.get("returned_qty", Decimal("0"))
    open_remito_qty = metric.get("open_remito_qty", ZERO) if metric is not None else _open_remito_qty_for_fulfillment_line(line)
    effective_pending_qty = _effective_pending_qty(line, open_remito_qty=open_remito_qty)
    item_snapshot = _with_display_uom(item_snapshot or _default_item_snapshot(line.item_ref, line.uom), fallback_uom=line.uom)
    conversion_factor = _item_conversion_factor(item_snapshot)
    planned_delivery_unit_qty = _delivery_unit_qty_from_commercial(planned_qty, item_snapshot)
    if _target_warehouse(target_warehouse_ref):
        max_dispatchable_qty = min(max(Decimal("0"), effective_pending_qty - planned_qty), max(Decimal("0"), packed_qty))
    else:
        max_dispatchable_qty = _max_dispatchable_from_effective_pending(
            effective_pending_qty=effective_pending_qty,
            already_planned=planned_qty,
            packed_qty=packed_qty,
        )
    max_dispatchable_delivery_unit_qty = _delivery_unit_qty_from_commercial(max_dispatchable_qty, item_snapshot)
    planned_weight_kg, planned_volume_m3 = _capacity_totals(planned_qty, item_snapshot)

    return {
        "id": str(line.id),
        "legacy_line_id": line.legacy_line_id,
        "legacy_line_rec_id": line.legacy_line_rec_id,
        "item_ref": line.item_ref,
        "item_name": item_snapshot.get("name", ""),
        "item_long_name": item_snapshot.get("long_name", ""),
        "category": item_snapshot.get("category", ""),
        "coverage_group": item_snapshot.get("coverage_group", ""),
        "warehouse_ref": line.warehouse_ref,
        "ordered_qty": str(line.ordered_qty),
        "reserved_qty": str(line.reserved_qty),
        "prepared_qty": str(line.prepared_qty),
        "delivered_qty": str(line.delivered_qty),
        "cancelled_qty": str(line.cancelled_qty),
        "returned_qty": _display_qty(returned_qty),
        "pending_qty": str(effective_pending_qty),
        "planned_qty": _display_qty(planned_qty),
        "stock_available": _display_qty(packed_qty),
        "max_dispatchable_qty": _display_qty(max_dispatchable_qty),
        "uom": item_snapshot.get("sales_uom") or _display_uom(line.uom),
        "sap_uom": item_snapshot.get("sap_uom") or line.uom,
        "sales_uom": item_snapshot.get("sales_uom") or line.uom,
        "delivery_uom": item_snapshot.get("delivery_uom") or line.uom,
        "conversion_factor": str(conversion_factor),
        "planned_delivery_unit_qty": _display_qty(planned_delivery_unit_qty),
        "max_dispatchable_delivery_unit_qty": _display_qty(max_dispatchable_delivery_unit_qty),
        "unit_weight_kg": item_snapshot.get("unit_weight_kg", "0"),
        "unit_volume_m3": item_snapshot.get("unit_volume_m3", "0"),
        "planned_weight_kg": str(planned_weight_kg),
        "planned_volume_m3": str(planned_volume_m3),
        "item_snapshot": item_snapshot,
    }


def _delivery_line_snapshot(line: DeliveryOrderLine) -> dict:
    return _with_display_uom(line.item_snapshot or _default_item_snapshot(line.item_ref, line.uom), fallback_uom=line.uom)


def refresh_delivery_capacity_from_master(delivery: DeliveryOrder, *, actor: str = "system") -> bool:
    lines = list(delivery.lines.select_related("fulfillment_line").all())
    if not lines:
        return False
    snapshots = _resolve_line_item_snapshots([line.fulfillment_line for line in lines])
    changed = False
    for line in lines:
        snapshot = _with_display_uom(
            snapshots.get(line.fulfillment_line_id, line.item_snapshot or _default_item_snapshot(line.item_ref, line.uom)),
            fallback_uom=line.uom,
        )
        planned_weight_kg, planned_volume_m3 = _capacity_totals(line.planned_qty, snapshot)
        computed_has_capacity = planned_weight_kg != ZERO or planned_volume_m3 != ZERO
        can_replace_capacity = computed_has_capacity or (line.planned_weight_kg == ZERO and line.planned_volume_m3 == ZERO)
        update_fields = ["updated_by", "updated_at"]

        if can_replace_capacity and (
            line.planned_weight_kg != planned_weight_kg or line.planned_volume_m3 != planned_volume_m3
        ):
            line.planned_weight_kg = planned_weight_kg
            line.planned_volume_m3 = planned_volume_m3
            update_fields.extend(["planned_weight_kg", "planned_volume_m3"])

        conversion_factor = _item_conversion_factor(snapshot)
        if line.conversion_factor != conversion_factor:
            line.conversion_factor = conversion_factor
            update_fields.append("conversion_factor")

        delivery_uom = snapshot.get("delivery_uom") or line.delivery_uom or line.uom
        if line.delivery_uom != delivery_uom:
            line.delivery_uom = delivery_uom
            update_fields.append("delivery_uom")

        if snapshot and snapshot != line.item_snapshot:
            line.item_snapshot = snapshot
            update_fields.append("item_snapshot")

        if len(update_fields) > 2:
            line.updated_by = actor
            line.save(update_fields=update_fields)
            changed = True
    return changed


def _delivery_line_operational_qty(line: DeliveryOrderLine, snapshot: dict | None = None) -> Decimal:
    snapshot = snapshot or _delivery_line_snapshot(line)
    if line.delivery_unit_qty > ZERO:
        return line.delivery_unit_qty
    return _delivery_unit_qty_from_commercial(line.planned_qty, snapshot)


def _delivery_totals(lines: list[DeliveryOrderLine]) -> dict:
    total_delivery_units = ZERO
    total_commercial_qty = ZERO
    total_weight_kg = ZERO
    total_volume_m3 = ZERO
    for line in lines:
        snapshot = _delivery_line_snapshot(line)
        total_delivery_units += _delivery_line_operational_qty(line, snapshot)
        total_commercial_qty += line.planned_qty
        weight_kg = line.planned_weight_kg
        volume_m3 = line.planned_volume_m3
        if weight_kg == ZERO and volume_m3 == ZERO:
            weight_kg, volume_m3 = _capacity_totals(line.planned_qty, snapshot)
        total_weight_kg += weight_kg
        total_volume_m3 += volume_m3
    return {
        "delivery_unit_qty": str(_quantize_qty(total_delivery_units)),
        "commercial_qty": str(_quantize_qty(total_commercial_qty)),
        "planned_weight_kg": str(_quantize_qty(total_weight_kg)),
        "planned_volume_m3": str(_quantize_qty(total_volume_m3)),
    }


def _serialize_delivery_line(line: DeliveryOrderLine) -> dict:
    snapshot = _delivery_line_snapshot(line)
    delivery_unit_qty = _delivery_line_operational_qty(line, snapshot)
    conversion_factor = line.conversion_factor if line.conversion_factor > ZERO else _item_conversion_factor(snapshot)
    weight_kg = line.planned_weight_kg
    volume_m3 = line.planned_volume_m3
    if weight_kg == ZERO and volume_m3 == ZERO:
        weight_kg, volume_m3 = _capacity_totals(line.planned_qty, snapshot)
    sales_uom = snapshot.get("sales_uom") or _display_uom(line.uom)
    delivery_uom = _display_uom(line.delivery_uom or snapshot.get("delivery_uom") or sales_uom)
    return {
        "id": str(line.id),
        "fulfillment_line_id": str(line.fulfillment_line_id),
        "legacy_line_id": line.legacy_line_id,
        "item_ref": line.item_ref,
        "item_name": snapshot.get("name", ""),
        "planned_qty": str(line.planned_qty),
        "delivery_unit_qty": str(delivery_unit_qty),
        "delivery_uom": delivery_uom,
        "conversion_factor": str(conversion_factor),
        "dispatched_qty": str(line.dispatched_qty),
        "delivered_qty": str(line.delivered_qty),
        "uom": sales_uom,
        "warehouse_ref": line.warehouse_ref,
        "store_ref": line.store_ref,
        "planned_weight_kg": str(weight_kg),
        "planned_volume_m3": str(volume_m3),
        "item_snapshot": snapshot,
    }


def _movement_event(
    *,
    key: str,
    at,
    label: str,
    status: str = "",
    detail: str = "",
    actor: str = "",
    source_type: str = "",
    source_ref: str = "",
    route_number: str = "",
    document_number: str = "",
    delivered_qty: Decimal | None = None,
    returned_qty: Decimal | None = None,
    uom: str = "",
) -> dict:
    return {
        "key": key,
        "at": at.isoformat() if at else None,
        "label": label,
        "status": status,
        "detail": detail,
        "actor": actor,
        "source_type": source_type,
        "source_ref": str(source_ref) if source_ref else "",
        "route_number": route_number,
        "document_number": document_number,
        "delivered_qty": str(_quantize_qty(delivered_qty)) if delivered_qty is not None else "",
        "returned_qty": str(_quantize_qty(returned_qty)) if returned_qty is not None else "",
        "uom": uom,
    }


def _movement_sort_key(event: dict) -> str:
    return str(event.get("at") or "")


def _movement_context_histories(context: dict | None, entity_type: str, entity_ids: list[str]) -> list[StatusHistory] | None:
    if context is None:
        return None
    histories = context.get("histories_by_entity", {})
    rows: list[StatusHistory] = []
    for entity_id in entity_ids:
        rows.extend(histories.get((entity_type, entity_id), []))
    return sorted(rows, key=lambda history: history.created_at)


def _route_assignment_payload(route_stop) -> dict:
    return {
        "id": str(route_stop.route_id),
        "route_number": route_stop.route.route_number,
        "status": route_stop.route.status,
        "stop_id": str(route_stop.id),
        "stop_status": route_stop.status,
    }


def _route_assignment_from_context(delivery_id: str, movement_context: dict | None) -> dict | None:
    if movement_context is None:
        return None
    return movement_context.get("route_assignments_by_delivery", {}).get(str(delivery_id))


def _delivery_movements(delivery: DeliveryOrder, *, movement_context: dict | None = None) -> list[dict]:
    events = [
        _movement_event(
            key=f"delivery:{delivery.id}:created",
            at=delivery.created_at,
            label="Entrega creada",
            status=delivery.status,
            detail=delivery.delivery_number,
            actor=delivery.created_by,
            source_type="delivery_order",
            source_ref=delivery.id,
        )
    ]

    delivery_histories = _movement_context_histories(movement_context, "delivery_order", [str(delivery.id)])
    if delivery_histories is None:
        delivery_histories = list(StatusHistory.objects.filter(entity_type="delivery_order", entity_id=str(delivery.id)).order_by("created_at"))
    for history in delivery_histories:
        events.append(
            _movement_event(
                key=f"status:{history.id}",
                at=history.created_at,
                label=history.reason or "Cambio de estado de entrega",
                status=history.to_status,
                detail=f"{history.from_status or 'inicio'} -> {history.to_status}",
                actor=history.actor,
                source_type="delivery_order",
                source_ref=delivery.id,
            )
        )

    task = getattr(delivery, "preparation_task", None)
    if task is not None:
        events.append(
            _movement_event(
                key=f"preparation:{task.id}:assigned",
                at=task.assigned_at,
                label="Preparacion asignada",
                status=task.status,
                detail=task.assigned_to,
                actor=task.created_by or task.assigned_to,
                source_type="preparation_task",
                source_ref=task.id,
            )
        )
        if task.prepared_at:
            events.append(
                _movement_event(
                    key=f"preparation:{task.id}:prepared",
                    at=task.prepared_at,
                    label="Preparacion completada",
                    status=DeliveryPreparationTask.TaskStatus.PREPARED,
                    detail=task.notes,
                    actor=task.prepared_by,
                    source_type="preparation_task",
                    source_ref=task.id,
            )
        )

    documents = _prefetched_list(delivery, "documents")
    if documents is None:
        documents = list(delivery.documents.all())
    for document in documents:
        events.append(
            _movement_event(
                key=f"document:{document.id}:issued",
                at=document.issued_at,
                label="Remito emitido",
                status=document.status,
                detail=document.document_number,
                actor=document.created_by,
                source_type="delivery_document",
                source_ref=document.id,
                document_number=document.document_number,
            )
        )
        if document.voided_at:
            events.append(
                _movement_event(
                    key=f"document:{document.id}:voided",
                    at=document.voided_at,
                    label="Remito anulado",
                    status=DeliveryDocument.DocumentStatus.VOIDED,
                    detail=document.void_reason,
                    actor=document.updated_by,
                    source_type="delivery_document",
                    source_ref=document.id,
                    document_number=document.document_number,
                )
            )

    document_ids = [str(document.id) for document in documents]
    if document_ids:
        document_histories = _movement_context_histories(movement_context, "delivery_document", document_ids)
        if document_histories is None:
            document_histories = list(StatusHistory.objects.filter(entity_type="delivery_document", entity_id__in=document_ids).order_by("created_at"))
        for history in document_histories:
            document = next((item for item in documents if str(item.id) == history.entity_id), None)
            events.append(
                _movement_event(
                    key=f"document-status:{history.id}",
                    at=history.created_at,
                    label=history.reason or "Cambio de estado de remito",
                    status=history.to_status,
                    detail=f"{history.from_status or 'inicio'} -> {history.to_status}",
                    actor=history.actor,
                    source_type="delivery_document",
                    source_ref=history.entity_id,
                    document_number=document.document_number if document else "",
                )
            )

    executions = _prefetched_list(delivery, "executions")
    if executions is None:
        executions = list(delivery.executions.all().order_by("executed_at"))
    else:
        executions = sorted(executions, key=lambda execution: execution.executed_at or execution.created_at)
    for execution in executions:
        events.append(
            _movement_event(
                key=f"execution:{execution.id}",
                at=execution.executed_at,
                label="Ejecucion de reparto",
                status=execution.status,
                detail=execution.observations or execution.reason,
                actor=execution.created_by,
                source_type="delivery_execution",
                source_ref=execution.id,
                delivered_qty=execution.delivered_qty,
                returned_qty=execution.returned_qty,
                uom="",
            )
        )

    try:
        from apps.routes.models import RouteSheet, RouteStop, RouteStopLine

        if movement_context is not None and "route_stops_by_delivery" in movement_context:
            route_stops = movement_context["route_stops_by_delivery"].get(str(delivery.id), [])
        else:
            direct_stop_ids = set(
                RouteStop.objects.filter(source_type="delivery_order", source_ref=str(delivery.id)).values_list("id", flat=True)
            )
            line_stop_ids = set(RouteStopLine.objects.filter(delivery_ref=str(delivery.id)).values_list("stop_id", flat=True))
            route_stops = list(
                RouteStop.objects.select_related("route")
                .filter(id__in=direct_stop_ids | line_stop_ids)
                .order_by("route__created_at", "sequence")
            )
        for stop in route_stops:
            events.append(
                _movement_event(
                    key=f"route-stop:{stop.id}:assigned",
                    at=stop.created_at,
                    label="Asignada a hoja de ruta",
                    status=stop.status,
                    detail=f"Parada {stop.sequence}",
                    actor=stop.created_by,
                    source_type="route_stop",
                    source_ref=stop.id,
                    route_number=stop.route.route_number,
                )
            )
            if stop.planned_arrival_at:
                events.append(
                    _movement_event(
                        key=f"route-stop:{stop.id}:planned-arrival",
                        at=stop.planned_arrival_at,
                        label="Llegada planificada",
                        status=stop.status,
                        detail=f"Parada {stop.sequence}",
                        source_type="route_stop",
                        source_ref=stop.id,
                        route_number=stop.route.route_number,
                    )
                )
            if stop.arrived_at:
                events.append(
                    _movement_event(
                        key=f"route-stop:{stop.id}:arrived",
                        at=stop.arrived_at,
                        label="Arribo registrado",
                        status=stop.status,
                        detail=stop.outcome_reason,
                        actor=stop.updated_by,
                        source_type="route_stop",
                        source_ref=stop.id,
                        route_number=stop.route.route_number,
                    )
                )
            if stop.completed_at:
                events.append(
                    _movement_event(
                        key=f"route-stop:{stop.id}:completed",
                        at=stop.completed_at,
                        label="Parada ejecutada",
                        status=stop.outcome_status or stop.status,
                        detail=stop.outcome_reason,
                        actor=stop.updated_by,
                        source_type="route_stop",
                        source_ref=stop.id,
                        route_number=stop.route.route_number,
                    )
                )

        stop_ids = [str(stop.id) for stop in route_stops]
        route_ids = [str(stop.route_id) for stop in route_stops]
        if stop_ids:
            stop_histories = _movement_context_histories(movement_context, "route_stop", stop_ids)
            if stop_histories is None:
                stop_histories = list(StatusHistory.objects.filter(entity_type="route_stop", entity_id__in=stop_ids).order_by("created_at"))
            for history in stop_histories:
                stop = next((item for item in route_stops if str(item.id) == history.entity_id), None)
                events.append(
                    _movement_event(
                        key=f"route-stop-status:{history.id}",
                        at=history.created_at,
                        label=history.reason or "Movimiento de parada",
                        status=history.to_status,
                        detail=f"{history.from_status or 'inicio'} -> {history.to_status}",
                        actor=history.actor,
                        source_type="route_stop",
                        source_ref=history.entity_id,
                        route_number=stop.route.route_number if stop else "",
                    )
                )
        if route_ids:
            route_numbers = movement_context.get("route_numbers", {}) if movement_context is not None else {}
            if not route_numbers:
                route_numbers = {
                    str(route.id): route.route_number
                    for route in RouteSheet.objects.filter(id__in=route_ids)
                }
            route_histories = _movement_context_histories(movement_context, "route_sheet", route_ids)
            if route_histories is None:
                route_histories = list(StatusHistory.objects.filter(entity_type="route_sheet", entity_id__in=route_ids).order_by("created_at"))
            for history in route_histories:
                events.append(
                    _movement_event(
                        key=f"route-status:{history.id}",
                        at=history.created_at,
                        label=history.reason or "Movimiento de hoja de ruta",
                        status=history.to_status,
                        detail=f"{history.from_status or 'inicio'} -> {history.to_status}",
                        actor=history.actor,
                        source_type="route_sheet",
                        source_ref=history.entity_id,
                        route_number=route_numbers.get(history.entity_id, ""),
                    )
                )
    except Exception:
        pass

    return sorted(events, key=_movement_sort_key)


def _serialize_order_impact(impact: FulfillmentOrderImpact) -> dict:
    lines = list(impact.lines.all()) if hasattr(impact, "_prefetched_objects_cache") else list(impact.lines.select_related("fulfillment_line").all())
    return {
        "id": str(impact.id),
        "type": "anulacion" if impact.impact_type == FulfillmentOrderImpact.ImpactType.ANNULMENT else "devolucion",
        "impact_type": impact.impact_type,
        "status": impact.status,
        "sales_order_number": impact.impact_sales_order_number,
        "transaction_number": impact.impact_transaction_number,
        "original_sales_order_number": impact.legacy_sales_order_number,
        "warehouse_ref": impact.warehouse_ref,
        "impact_date": impact.impact_date.isoformat() if impact.impact_date else None,
        "lines": [
            {
                "id": str(line.id),
                "fulfillment_line_id": str(line.fulfillment_line_id) if line.fulfillment_line_id else "",
                "item_ref": line.item_ref,
                "warehouse_ref": line.warehouse_ref,
                "quantity": str(line.quantity),
                "applied_qty": str(line.applied_qty),
                "uom": line.uom,
            }
            for line in lines
        ],
    }


def _fulfillment_impacts(fulfillment: FulfillmentOrder) -> list[FulfillmentOrderImpact]:
    prefetched = _prefetched_list(fulfillment, "impacts")
    if prefetched is not None:
        return sorted(prefetched, key=lambda impact: impact.impact_date or impact.created_at)
    return list(
        FulfillmentOrderImpact.objects.prefetch_related("lines")
        .filter(fulfillment=fulfillment)
        .order_by("impact_date", "created_at")
    )


def _impact_movements(fulfillment: FulfillmentOrder) -> list[dict]:
    events: list[dict] = []
    for impact in _fulfillment_impacts(fulfillment):
        total_qty_by_uom: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for line in impact.lines.all():
            total_qty_by_uom[line.uom] += line.applied_qty or line.quantity
        if len(total_qty_by_uom) == 1:
            [(uom, qty)] = total_qty_by_uom.items()
        else:
            uom = ""
            qty = None
        if impact.impact_type == FulfillmentOrderImpact.ImpactType.ANNULMENT:
            events.append(
                _movement_event(
                    key=f"impact:{impact.id}:annulment",
                    at=impact.impact_date or impact.created_at,
                    label="Anulacion aplicada",
                    status=impact.status,
                    detail=impact.impact_sales_order_number,
                    actor=impact.updated_by or impact.created_by,
                    source_type="fulfillment_order_impact",
                    source_ref=impact.id,
                    returned_qty=None,
                    uom=uom,
                )
            )
        else:
            events.append(
                _movement_event(
                    key=f"impact:{impact.id}:return",
                    at=impact.impact_date or impact.created_at,
                    label="Devolucion recibida",
                    status=impact.status,
                    detail=impact.impact_sales_order_number,
                    actor=impact.updated_by or impact.created_by,
                    source_type="fulfillment_order_impact",
                    source_ref=impact.id,
                    returned_qty=qty,
                    uom=uom,
                )
            )
            events.append(
                _movement_event(
                    key=f"impact:{impact.id}:return-stock",
                    at=impact.updated_at,
                    label="Stock ingresado",
                    status=impact.status,
                    detail=impact.warehouse_ref,
                    actor=impact.updated_by or impact.created_by,
                    source_type="inventory_ledger_entry",
                    source_ref=impact.id,
                    returned_qty=qty,
                    uom=uom,
                )
            )
    return events


def _fulfillment_movements(fulfillment: FulfillmentOrder, deliveries: list[dict], *, movement_context: dict | None = None) -> list[dict]:
    events = [
        _movement_event(
            key=f"fulfillment:{fulfillment.id}:created",
            at=fulfillment.created_at,
            label="Pedido ingresado a TMS/WMS",
            status=fulfillment.status,
            detail=fulfillment.legacy_sales_order_number,
            actor=fulfillment.created_by,
            source_type="fulfillment_order",
            source_ref=fulfillment.id,
        )
    ]
    fulfillment_histories = _movement_context_histories(movement_context, "fulfillment_order", [str(fulfillment.id)])
    if fulfillment_histories is None:
        fulfillment_histories = list(StatusHistory.objects.filter(entity_type="fulfillment_order", entity_id=str(fulfillment.id)).order_by("created_at"))
    for history in fulfillment_histories:
        events.append(
            _movement_event(
                key=f"fulfillment-status:{history.id}",
                at=history.created_at,
                label=history.reason or "Cambio de estado de pedido",
                status=history.to_status,
                detail=f"{history.from_status or 'inicio'} -> {history.to_status}",
                actor=history.actor,
                source_type="fulfillment_order",
                source_ref=fulfillment.id,
            )
        )
    for delivery in deliveries:
        events.extend(delivery.get("movements") or [])
    events.extend(_impact_movements(fulfillment))
    return sorted(events, key=_movement_sort_key)


def _build_movement_context(fulfillments: list[FulfillmentOrder]) -> dict:
    fulfillment_ids = [str(fulfillment.id) for fulfillment in fulfillments]
    deliveries = [
        delivery
        for fulfillment in fulfillments
        for delivery in (_prefetched_list(fulfillment, "deliveries") or list(fulfillment.deliveries.all()))
    ]
    delivery_ids = [str(delivery.id) for delivery in deliveries]
    documents = [
        document
        for delivery in deliveries
        for document in (_prefetched_list(delivery, "documents") or list(delivery.documents.all()))
    ]
    document_ids = [str(document.id) for document in documents]
    histories_by_entity: dict[tuple[str, str], list[StatusHistory]] = defaultdict(list)
    base_entity_ids = set(fulfillment_ids + delivery_ids + document_ids)
    if base_entity_ids:
        for history in StatusHistory.objects.filter(
            entity_type__in=["fulfillment_order", "delivery_order", "delivery_document"],
            entity_id__in=base_entity_ids,
        ).order_by("created_at"):
            histories_by_entity[(history.entity_type, history.entity_id)].append(history)

    route_stops_by_delivery: dict[str, list] = defaultdict(list)
    route_assignments_by_delivery: dict[str, dict] = {}
    route_numbers: dict[str, str] = {}
    try:
        from apps.routes.models import RouteSheet, RouteStop, RouteStopLine

        direct_stops = list(
            RouteStop.objects.select_related("route")
            .filter(source_type="delivery_order", source_ref__in=delivery_ids)
            .order_by("route__created_at", "sequence")
        )
        line_links = list(RouteStopLine.objects.filter(delivery_ref__in=delivery_ids).values("delivery_ref", "stop_id"))
        stop_ids_from_lines = {row["stop_id"] for row in line_links if row["stop_id"]}
        line_stops = list(
            RouteStop.objects.select_related("route")
            .filter(id__in=stop_ids_from_lines)
            .order_by("route__created_at", "sequence")
        )
        stops_by_id = {stop.id: stop for stop in direct_stops + line_stops}
        direct_stops_by_delivery: dict[str, list] = defaultdict(list)
        line_stops_by_delivery: dict[str, list] = defaultdict(list)
        for stop in direct_stops:
            delivery_ref = str(stop.source_ref)
            direct_stops_by_delivery[delivery_ref].append(stop)
            route_stops_by_delivery[delivery_ref].append(stop)
        for row in line_links:
            stop = stops_by_id.get(row["stop_id"])
            if stop is not None:
                delivery_ref = str(row["delivery_ref"])
                line_stops_by_delivery[delivery_ref].append(stop)
                route_stops_by_delivery[delivery_ref].append(stop)
        for delivery_id, stops in list(route_stops_by_delivery.items()):
            route_stops_by_delivery[delivery_id] = sorted(
                {stop.id: stop for stop in stops}.values(),
                key=lambda stop: (stop.route.created_at, stop.sequence),
            )
        for delivery_id in set(direct_stops_by_delivery) | set(line_stops_by_delivery):
            direct_candidates = [
                stop
                for stop in direct_stops_by_delivery.get(delivery_id, [])
                if stop.status != RouteStop.StopStatus.CANCELLED and stop.route.status != RouteSheet.RouteStatus.CANCELLED
            ]
            line_candidates = [
                stop
                for stop in line_stops_by_delivery.get(delivery_id, [])
                if stop.status != RouteStop.StopStatus.CANCELLED and stop.route.status != RouteSheet.RouteStatus.CANCELLED
            ]
            candidates = direct_candidates or line_candidates
            if candidates:
                route_stop = sorted(
                    candidates,
                    key=lambda stop: (stop.route.created_at, stop.created_at),
                    reverse=True,
                )[0]
                route_assignments_by_delivery[delivery_id] = _route_assignment_payload(route_stop)
        stop_ids = [str(stop.id) for stop in stops_by_id.values()]
        route_ids = [str(stop.route_id) for stop in stops_by_id.values()]
        if route_ids:
            route_numbers = {
                str(route.id): route.route_number
                for route in RouteSheet.objects.filter(id__in=route_ids)
            }
        route_entity_ids = set(stop_ids + route_ids)
        if route_entity_ids:
            for history in StatusHistory.objects.filter(
                entity_type__in=["route_stop", "route_sheet"],
                entity_id__in=route_entity_ids,
            ).order_by("created_at"):
                histories_by_entity[(history.entity_type, history.entity_id)].append(history)
    except Exception:
        route_stops_by_delivery = defaultdict(list)
        route_assignments_by_delivery = {}
        route_numbers = {}

    return {
        "histories_by_entity": histories_by_entity,
        "route_stops_by_delivery": route_stops_by_delivery,
        "route_assignments_by_delivery": route_assignments_by_delivery,
        "route_numbers": route_numbers,
    }


def _serialize_fulfillment(
    fulfillment: FulfillmentOrder,
    *,
    line_metrics: dict | None = None,
    customer_snapshot: dict | None = None,
    item_snapshots: dict | None = None,
    movement_context: dict | None = None,
    target_warehouse_ref: str = "",
) -> dict:
    prefetched_lines = _prefetched_list(fulfillment, "lines")
    lines = sorted(prefetched_lines, key=lambda line: line.legacy_line_id) if prefetched_lines is not None else list(fulfillment.lines.order_by("legacy_line_id"))
    prefetched_deliveries = _prefetched_list(fulfillment, "deliveries")
    deliveries = (
        sorted(prefetched_deliveries, key=lambda delivery: delivery.created_at)
        if prefetched_deliveries is not None
        else list(
            fulfillment.deliveries.prefetch_related(
                "lines__fulfillment_line",
                "documents",
                "executions",
                "preparation_task",
            ).order_by("created_at")
        )
    )
    metrics = line_metrics or {}
    customer_snapshot = customer_snapshot or _default_customer_snapshot(fulfillment.customer_ref)
    item_snapshots = item_snapshots if item_snapshots is not None else _resolve_line_item_snapshots(lines)
    physical_lines = physical_fulfillment_lines_from_snapshots(lines, item_snapshots)

    def serialize_delivery(delivery: DeliveryOrder) -> dict:
        delivery_lines = physical_delivery_lines_from_snapshots(list(delivery.lines.all()), item_snapshots)
        route_assignment = _route_assignment_from_context(str(delivery.id), movement_context)
        if route_assignment is None and (movement_context is None or "route_assignments_by_delivery" not in movement_context):
            route_assignment = _delivery_route_assignment(str(delivery.id))
        return {
            "id": str(delivery.id),
            "created_at": delivery.created_at.isoformat(),
            "updated_at": delivery.updated_at.isoformat(),
            "delivery_number": delivery.delivery_number,
            "status": delivery.status,
            "delivery_mode": delivery.delivery_mode,
            "planned_date": delivery.planned_date.isoformat() if delivery.planned_date else None,
            "warehouse_ref": delivery.warehouse_ref,
            "store_ref": delivery.store_ref,
            "address_snapshot": delivery.address_snapshot,
            "route_sheet": route_assignment,
            "documents": [
                {
                    "id": str(document.id),
                    "document_number": document.document_number,
                    "document_type": document.document_type,
                    "status": document.status,
                    "issued_at": document.issued_at.isoformat(),
                }
                for document in delivery.documents.all()
            ],
            "preparation_task": _serialize_task(delivery.preparation_task) if hasattr(delivery, "preparation_task") else None,
            "lines": [_serialize_delivery_line(delivery_line) for delivery_line in delivery_lines],
            "totals": _delivery_totals(delivery_lines),
            "movements": _delivery_movements(delivery, movement_context=movement_context),
        }

    serialized_deliveries = [serialize_delivery(delivery) for delivery in deliveries]
    impacts = _fulfillment_impacts(fulfillment)
    return {
        "id": str(fulfillment.id),
        "created_at": fulfillment.created_at.isoformat(),
        "updated_at": fulfillment.updated_at.isoformat(),
        "fulfillment_number": fulfillment.fulfillment_number,
        "status": fulfillment.status,
        "sales_order_type": LEGACY_ORDER_TYPE_DELIVERABLE,
        "sales_order_number": fulfillment.legacy_sales_order_number,
        "transaction_number": fulfillment.legacy_transaction_number,
        "customer_ref": fulfillment.customer_ref,
        "delivery_mode": fulfillment.delivery_mode,
        "requested_date": fulfillment.requested_date.isoformat() if fulfillment.requested_date else None,
        "warehouse_ref": fulfillment.warehouse_ref,
        "source_hash": fulfillment.source_hash,
        "address_snapshot": fulfillment.address_snapshot,
        "customer": customer_snapshot,
        "customer_dni": customer_snapshot.get("document_number", ""),
        "customer_document": customer_snapshot.get("document_number", ""),
        "pickup_authorization": _pickup_authorization(fulfillment, deliveries, customer_snapshot),
        "lines": [
            _serialize_fulfillment_line(
                line,
                metrics,
                item_snapshots.get(line.id),
                target_warehouse_ref=target_warehouse_ref,
            )
            for line in physical_lines
        ],
        "deliveries": serialized_deliveries,
        "impacts": [_serialize_order_impact(impact) for impact in impacts],
        "movements": _fulfillment_movements(fulfillment, serialized_deliveries, movement_context=movement_context),
    }


def _bootstrap_packed_balance(line: FulfillmentOrderLine, quantity: Decimal) -> None:
    balance, created = InventoryBalance.objects.get_or_create(
        warehouse_ref=line.warehouse_ref,
        item_ref=line.item_ref,
        lot_ref="",
        stock_state=StockState.PACKED,
        uom=line.uom,
        defaults={"quantity": quantity},
    )
    if created:
        return
    if balance.quantity < quantity:
        balance.quantity = quantity
        balance.version += 1
        balance.save(update_fields=["quantity", "version", "updated_at"])


def _legacy_impact_type(order: LegacyOrder) -> str:
    order_type = legacy_sales_order_type(order)
    if order_type == LEGACY_ORDER_TYPE_ANNULMENT:
        return FulfillmentOrderImpact.ImpactType.ANNULMENT
    if order_type == LEGACY_ORDER_TYPE_RETURN:
        return FulfillmentOrderImpact.ImpactType.RETURN
    raise FulfillmentRuleError("El documento legacy no es una anulacion o devolucion.")


def _impact_line_quantity(line: LegacyOrderLine) -> Decimal:
    for value in [line.ordered_sales_quantity, line.remain_sales_physical, line.sales_quantity_delivered]:
        qty = _to_decimal(value)
        if qty != ZERO:
            return abs(qty)
    return ZERO


def _legacy_line_warehouse(order: LegacyOrder, line: LegacyOrderLine) -> str:
    return str(line.shipping_warehouse_id or line.fulfillment_store_id or line.warehouse or order.warehouse or "").strip()


def _find_matching_fulfillment_line(fulfillment: FulfillmentOrder | None, legacy_line: LegacyOrderLine) -> FulfillmentOrderLine | None:
    if fulfillment is None:
        return None
    queryset = fulfillment.lines.select_for_update().filter(item_ref=legacy_line.item_number)
    uom = str(legacy_line.sales_unit_symbol or "").strip()
    if uom:
        queryset = queryset.filter(uom=uom)
    rec_id = str(legacy_line.sales_order_line_rec_id or "").strip()
    if rec_id:
        exact = queryset.filter(legacy_line_rec_id=rec_id).first()
        if exact:
            return exact
    return queryset.order_by("legacy_line_id", "created_at").first()


def _post_return_stock_increase(
    *,
    impact: FulfillmentOrderImpact,
    line: FulfillmentOrderImpactLine,
    quantity: Decimal,
    actor: str,
) -> None:
    if quantity <= ZERO:
        return
    warehouse_ref = line.warehouse_ref or impact.warehouse_ref
    post_ledger_entry(
        LedgerCommand(
            idempotency_key=_ledger_idempotency_key(f"legacy-impact:{impact.id}:{line.id}:return:{line.applied_qty}:{quantity}"),
            movement_type=InventoryLedgerEntry.MovementType.INBOUND_RECEIPT,
            direction=InventoryLedgerEntry.Direction.INCREASE,
            warehouse_ref=warehouse_ref,
            location_ref=location_ref_for_purpose(warehouse_ref, "available", actor=actor),
            item_ref=line.item_ref,
            stock_state=StockState.PACKED,
            quantity=quantity,
            uom=line.uom,
            document_type="legacy_return",
            document_ref=impact.impact_sales_order_number or impact.source_pk,
            actor=actor,
            reason="Devolucion legacy",
            legacy_sales_order_number=impact.legacy_sales_order_number,
            legacy_line_id=line.legacy_line_id,
        )
    )


def _release_reservation_line_for_annulment(
    *,
    reservation_line: InventoryReservationLine,
    reservation: InventoryReservation,
    quantity: Decimal,
    stock_state: str,
    actor: str,
    idempotency_key: str,
) -> Decimal:
    release_qty = min(quantity, reservation_line.reserved_qty)
    if release_qty <= ZERO:
        return ZERO
    warehouse_ref = reservation_line.warehouse_ref or reservation.warehouse_ref
    source_purpose = "reserved" if stock_state == StockState.RESERVED else "preparation"
    source_location_ref = reservation_line.location_ref or location_ref_for_purpose(warehouse_ref, source_purpose, actor=actor)
    target_location_ref = reservation_line.source_location_ref or location_ref_for_purpose(warehouse_ref, "available", actor=actor)
    post_ledger_entry(
        LedgerCommand(
            idempotency_key=_ledger_idempotency_key(f"{idempotency_key}:source"),
            movement_type=InventoryLedgerEntry.MovementType.RESERVATION_RELEASE,
            direction=InventoryLedgerEntry.Direction.DECREASE,
            warehouse_ref=warehouse_ref,
            location_ref=source_location_ref,
            item_ref=reservation_line.item_ref,
            stock_state=stock_state,
            quantity=release_qty,
            uom=reservation_line.uom,
            document_type="legacy_annulment",
            document_ref=reservation.source_ref,
            actor=actor,
            reason="Anulacion legacy",
            legacy_sales_order_number=reservation_line.legacy_sales_order_number,
            legacy_line_id=reservation_line.legacy_line_id,
        )
    )
    post_ledger_entry(
        LedgerCommand(
            idempotency_key=_ledger_idempotency_key(f"{idempotency_key}:packed"),
            movement_type=InventoryLedgerEntry.MovementType.RESERVATION_RELEASE,
            direction=InventoryLedgerEntry.Direction.INCREASE,
            warehouse_ref=warehouse_ref,
            location_ref=target_location_ref,
            item_ref=reservation_line.item_ref,
            stock_state=StockState.PACKED,
            quantity=release_qty,
            uom=reservation_line.uom,
            document_type="legacy_annulment",
            document_ref=reservation.source_ref,
            actor=actor,
            reason="Anulacion legacy",
            legacy_sales_order_number=reservation_line.legacy_sales_order_number,
            legacy_line_id=reservation_line.legacy_line_id,
        )
    )
    reservation_line.reserved_qty = max(ZERO, reservation_line.reserved_qty - release_qty)
    reservation_line.requested_qty = max(ZERO, reservation_line.requested_qty - release_qty)
    reservation_line.updated_by = actor
    reservation_line.save(update_fields=["reserved_qty", "requested_qty", "updated_by", "updated_at"])
    return release_qty


def _release_non_remitted_delivery_qty(
    *,
    fulfillment_line: FulfillmentOrderLine,
    quantity: Decimal,
    actor: str,
    idempotency_key: str,
) -> tuple[Decimal, Decimal]:
    remaining = quantity
    reserved_released = ZERO
    prepared_released = ZERO
    delivery_lines = (
        _active_delivery_lines_queryset()
        .select_for_update()
        .select_related("delivery")
        .filter(fulfillment_line=fulfillment_line, planned_qty__gt=ZERO)
        .order_by("delivery__created_at", "created_at")
    )
    for delivery_line in delivery_lines:
        if remaining <= ZERO:
            break
        reduce_qty = min(remaining, delivery_line.planned_qty)
        if reduce_qty <= ZERO:
            continue
        delivery = delivery_line.delivery
        reservation = (
            InventoryReservation.objects.select_for_update()
            .prefetch_related("lines")
            .filter(source_type="delivery_order", source_ref=str(delivery.id))
            .exclude(
                status__in=[
                    InventoryReservation.ReservationStatus.RELEASED,
                    InventoryReservation.ReservationStatus.CANCELLED,
                    InventoryReservation.ReservationStatus.EXPIRED,
                ]
            )
            .first()
        )
        if reservation is not None:
            reservation_line = reservation.lines.filter(
                item_ref=delivery_line.item_ref,
                uom=delivery_line.uom,
                legacy_line_id=delivery_line.legacy_line_id,
            ).first()
            if reservation_line is None:
                reservation_line = reservation.lines.filter(item_ref=delivery_line.item_ref, uom=delivery_line.uom).first()
            if reservation_line is not None and reservation.status == InventoryReservation.ReservationStatus.ALLOCATED:
                released = _release_reservation_line_for_annulment(
                    reservation_line=reservation_line,
                    reservation=reservation,
                    quantity=reduce_qty,
                    stock_state=StockState.RESERVED,
                    actor=actor,
                    idempotency_key=f"{idempotency_key}:delivery:{delivery.id}:reserved",
                )
                reserved_released += released
            elif reservation_line is not None and reservation.status == InventoryReservation.ReservationStatus.PREPARING:
                released = _release_reservation_line_for_annulment(
                    reservation_line=reservation_line,
                    reservation=reservation,
                    quantity=reduce_qty,
                    stock_state=StockState.PICKING,
                    actor=actor,
                    idempotency_key=f"{idempotency_key}:delivery:{delivery.id}:picking",
                )
                reserved_released += released
            elif reservation.status == InventoryReservation.ReservationStatus.CONSUMED:
                prepared_released += reduce_qty

        previous_qty = delivery_line.planned_qty
        ratio = reduce_qty / previous_qty if previous_qty > ZERO else Decimal("1")
        delivery_line.planned_qty = max(ZERO, previous_qty - reduce_qty)
        delivery_line.delivery_unit_qty = max(ZERO, delivery_line.delivery_unit_qty - (delivery_line.delivery_unit_qty * ratio))
        delivery_line.updated_by = actor
        delivery_line.save(update_fields=["planned_qty", "delivery_unit_qty", "updated_by", "updated_at"])
        if not delivery.lines.exclude(planned_qty=ZERO).exists():
            from_status = delivery.status
            delivery.status = DeliveryOrder.DeliveryStatus.CANCELLED
            delivery.updated_by = actor
            delivery.save(update_fields=["status", "updated_by", "updated_at"])
            task = getattr(delivery, "preparation_task", None)
            if task is not None and task.status != DeliveryPreparationTask.TaskStatus.PREPARED:
                task.status = DeliveryPreparationTask.TaskStatus.CANCELLED
                task.updated_by = actor
                task.save(update_fields=["status", "updated_by", "updated_at"])
            StatusHistory.objects.create(
                entity_type="delivery_order",
                entity_id=str(delivery.id),
                from_status=from_status,
                to_status=delivery.status,
                actor=actor,
                reason="Anulacion aplicada",
            )
        remaining -= reduce_qty
    return reserved_released, prepared_released


def _apply_order_impact(impact: FulfillmentOrderImpact, *, actor: str) -> FulfillmentOrderImpact:
    impact = (
        FulfillmentOrderImpact.objects.select_for_update()
        .prefetch_related("lines__fulfillment_line")
        .get(id=impact.id)
    )
    if impact.fulfillment is None and impact.impact_type != FulfillmentOrderImpact.ImpactType.RETURN:
        return impact

    now = timezone.now()
    all_lines_done = True
    for line in impact.lines.all():
        if line.quantity <= line.applied_qty:
            continue
        remaining = line.quantity - line.applied_qty
        if impact.impact_type == FulfillmentOrderImpact.ImpactType.RETURN:
            _post_return_stock_increase(impact=impact, line=line, quantity=remaining, actor=actor)
            line.applied_qty += remaining
            line.updated_by = actor
            line.updated_at = now
            line.save(update_fields=["applied_qty", "updated_by", "updated_at"])
            continue

        fulfillment_line = line.fulfillment_line
        if fulfillment_line is None:
            all_lines_done = False
            continue
        remitted_qty = _remitted_qty_for_fulfillment_line(fulfillment_line)
        max_cancelable = max(ZERO, fulfillment_line.ordered_qty - remitted_qty - fulfillment_line.cancelled_qty)
        apply_qty = min(remaining, max_cancelable)
        if apply_qty <= ZERO:
            line.applied_qty = line.quantity
            line.updated_by = actor
            line.updated_at = now
            line.save(update_fields=["applied_qty", "updated_by", "updated_at"])
            continue
        reserved_released, prepared_released = _release_non_remitted_delivery_qty(
            fulfillment_line=fulfillment_line,
            quantity=apply_qty,
            actor=actor,
            idempotency_key=f"legacy-impact:{impact.id}:{line.id}:release",
        )
        fulfillment_line.reserved_qty = max(ZERO, fulfillment_line.reserved_qty - reserved_released)
        fulfillment_line.prepared_qty = max(ZERO, fulfillment_line.prepared_qty - prepared_released)
        fulfillment_line.cancelled_qty += apply_qty
        fulfillment_line.updated_by = actor
        fulfillment_line.updated_at = now
        fulfillment_line.save(update_fields=["reserved_qty", "prepared_qty", "cancelled_qty", "updated_by", "updated_at"])
        line.applied_qty += apply_qty
        if line.applied_qty < line.quantity:
            line.applied_qty = line.quantity
        line.updated_by = actor
        line.updated_at = now
        line.save(update_fields=["applied_qty", "updated_by", "updated_at"])

    if all_lines_done and impact.fulfillment is not None:
        impact.status = FulfillmentOrderImpact.ImpactStatus.APPLIED
        impact.updated_by = actor
        impact.save(update_fields=["status", "updated_by", "updated_at"])
    return impact


def _legacy_impact_source_version(order: LegacyOrder) -> str:
    return str(order.modified_datetime or order.invoice_date or "")


def _legacy_impact_source_key(order: LegacyOrder) -> tuple[str, str]:
    return (str(order.transaction_id), _legacy_impact_source_version(order))


def _applied_legacy_impact_source_keys(orders: list[LegacyOrder]) -> set[tuple[str, str]]:
    source_pks = {str(order.transaction_id) for order in orders if str(order.transaction_id)}
    if not source_pks:
        return set()
    return set(
        FulfillmentOrderImpact.objects.filter(
            source_table="transactions_orders_transaction",
            source_pk__in=source_pks,
            status=FulfillmentOrderImpact.ImpactStatus.APPLIED,
        ).values_list("source_pk", "source_version")
    )


@transaction.atomic
def process_legacy_order_impact(*, sales_order_number: str, idempotency_key: str, actor: str) -> IdempotentResult:
    command_payload = {"sales_order_number": sales_order_number}
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="fulfillment.legacy_order_impact",
        reference_type="sales_order",
        reference_id=sales_order_number,
        payload=command_payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)

    order = LegacyOrder.objects.using("litecore").get(sales_order_number=sales_order_number)
    impact_type = _legacy_impact_type(order)
    original_order_number = str(order.sales_order_number_orig or "").strip()
    if not original_order_number:
        raise FulfillmentRuleError("El documento legacy no informa SalesOrderNumberOrig.")
    legacy_lines = list(
        LegacyOrderLine.objects.using("litecore")
        .filter(sales_order_number=sales_order_number)
        .order_by("line_number", "retail_line_item_id")
    )
    if not legacy_lines:
        raise FulfillmentRuleError("El documento legacy no tiene lineas operables.")

    legacy_item_snapshots = _resolve_legacy_line_item_snapshots(legacy_lines)
    physical_legacy_lines = [
        line
        for line in legacy_lines
        if not is_virtual_item_snapshot(
            legacy_item_snapshots.get(
                str(line.retail_line_item_id),
                _default_item_snapshot(line.item_number, line.sales_unit_symbol),
            )
        )
    ]
    if not physical_legacy_lines:
        raise FulfillmentRuleError("El documento legacy no tiene lineas fisicas.")

    fulfillment = FulfillmentOrder.objects.select_for_update().filter(legacy_sales_order_number=original_order_number).first()
    source_payload = {
        "order": {
            "transaction_id": order.transaction_id,
            "sales_order_number": order.sales_order_number,
            "sales_order_number_orig": original_order_number,
            "sales_order_type": legacy_sales_order_type(order),
            "transaction_number": order.transaction_number,
            "invoice_number": order.invoice_number,
            "invoice_date": order.invoice_date,
            "warehouse": order.warehouse,
        },
        "lines": [
            {
                "retail_line_item_id": line.retail_line_item_id,
                "sales_order_line_rec_id": line.sales_order_line_rec_id,
                "item_number": line.item_number,
                "quantity": _impact_line_quantity(line),
                "uom": line.sales_unit_symbol,
                "warehouse": _legacy_line_warehouse(order, line),
            }
            for line in physical_legacy_lines
        ],
    }
    source_hash = _hash_payload(source_payload)
    safe_source_payload = _json_safe_payload(source_payload)
    impact, created = FulfillmentOrderImpact.objects.get_or_create(
        source_table="transactions_orders_transaction",
        source_pk=str(order.transaction_id),
        defaults={
            "fulfillment": fulfillment,
            "impact_type": impact_type,
            "status": FulfillmentOrderImpact.ImpactStatus.PENDING,
            "impact_sales_order_number": order.sales_order_number,
            "impact_transaction_number": order.transaction_number,
            "impact_date": order.invoice_date or order.modified_datetime,
            "legacy_sales_order_number": original_order_number,
            "legacy_transaction_number": order.transaction_number,
            "legacy_rec_id": str(order.rec_id),
            "warehouse_ref": order.warehouse,
            "store_ref": order.store_id or "",
            "source_hash": source_hash,
            "source_version": _legacy_impact_source_version(order),
            "payload": safe_source_payload,
            "created_by": actor,
        },
    )
    if not created:
        impact.fulfillment = fulfillment or impact.fulfillment
        impact.impact_type = impact_type
        impact.impact_sales_order_number = order.sales_order_number
        impact.impact_transaction_number = order.transaction_number
        impact.impact_date = order.invoice_date or order.modified_datetime
        impact.legacy_sales_order_number = original_order_number
        impact.legacy_transaction_number = order.transaction_number
        impact.legacy_rec_id = str(order.rec_id)
        impact.warehouse_ref = order.warehouse
        impact.store_ref = order.store_id or ""
        impact.source_hash = source_hash
        impact.source_version = _legacy_impact_source_version(order)
        impact.payload = safe_source_payload
        impact.updated_by = actor
        impact.save(
            update_fields=[
                "fulfillment",
                "impact_type",
                "impact_sales_order_number",
                "impact_transaction_number",
                "impact_date",
                "legacy_sales_order_number",
                "legacy_transaction_number",
                "legacy_rec_id",
                "warehouse_ref",
                "store_ref",
                "source_hash",
                "source_version",
                "payload",
                "updated_by",
                "updated_at",
            ]
        )

    for legacy_line in physical_legacy_lines:
        quantity = _impact_line_quantity(legacy_line)
        if quantity <= ZERO:
            continue
        fulfillment_line = _find_matching_fulfillment_line(fulfillment or impact.fulfillment, legacy_line)
        impact_line, created_line = FulfillmentOrderImpactLine.objects.get_or_create(
            impact=impact,
            source_pk=str(legacy_line.retail_line_item_id),
            defaults={
                "fulfillment_line": fulfillment_line,
                "source_table": "transactions_orders_retailLineItem",
                "legacy_sales_order_number": original_order_number,
                "legacy_transaction_number": order.transaction_number,
                "legacy_line_id": str(legacy_line.retail_line_item_id),
                "legacy_line_rec_id": str(legacy_line.sales_order_line_rec_id),
                "legacy_rec_id": str(legacy_line.rec_id),
                "item_ref": legacy_line.item_number,
                "warehouse_ref": _legacy_line_warehouse(order, legacy_line),
                "store_ref": legacy_line.fulfillment_store_id,
                "quantity": quantity,
                "applied_qty": ZERO,
                "uom": legacy_line.sales_unit_symbol,
                "source_hash": source_hash,
                "created_by": actor,
            },
        )
        if not created_line:
            impact_line.fulfillment_line = fulfillment_line or impact_line.fulfillment_line
            impact_line.legacy_sales_order_number = original_order_number
            impact_line.legacy_transaction_number = order.transaction_number
            impact_line.legacy_line_id = str(legacy_line.retail_line_item_id)
            impact_line.legacy_line_rec_id = str(legacy_line.sales_order_line_rec_id)
            impact_line.legacy_rec_id = str(legacy_line.rec_id)
            impact_line.item_ref = legacy_line.item_number
            impact_line.warehouse_ref = _legacy_line_warehouse(order, legacy_line)
            impact_line.store_ref = legacy_line.fulfillment_store_id
            impact_line.quantity = quantity
            impact_line.uom = legacy_line.sales_unit_symbol
            impact_line.source_hash = source_hash
            impact_line.updated_by = actor
            impact_line.save(
                update_fields=[
                    "fulfillment_line",
                    "legacy_sales_order_number",
                    "legacy_transaction_number",
                    "legacy_line_id",
                    "legacy_line_rec_id",
                    "legacy_rec_id",
                    "item_ref",
                    "warehouse_ref",
                    "store_ref",
                    "quantity",
                    "uom",
                    "source_hash",
                    "updated_by",
                    "updated_at",
                ]
            )

    impact = _apply_order_impact(impact, actor=actor)
    DomainEventOutbox.objects.create(
        event_type="fulfillment.legacy_impact.processed",
        aggregate_type="fulfillment_order_impact",
        aggregate_id=str(impact.id),
        payload={
            "sales_order_number": impact.legacy_sales_order_number,
            "impact_sales_order_number": impact.impact_sales_order_number,
            "impact_type": impact.impact_type,
            "status": impact.status,
        },
    )
    result = IdempotentResult({"result": _serialize_order_impact(impact)}, 201 if created else 200)
    return _finish_idempotent_command(idempotency, result)


def _process_legacy_impact_order(order: LegacyOrder, *, actor: str) -> None:
    source_version = _legacy_impact_source_version(order)
    source_hash = hashlib.sha1(source_version.encode("utf-8")).hexdigest()[:10]
    process_legacy_order_impact(
        sales_order_number=order.sales_order_number,
        idempotency_key=f"legacy-impact-link:{order.sales_order_number}:{source_hash}",
        actor=actor,
    )


def _legacy_impact_orders_for_order_numbers(order_numbers: set[str]) -> list[LegacyOrder]:
    clean_order_numbers = {str(order_number or "").strip() for order_number in order_numbers if str(order_number or "").strip()}
    if not clean_order_numbers:
        return []
    try:
        return list(
            LegacyOrder.objects.using("litecore")
            .filter(sales_order_number_orig__in=clean_order_numbers)
            .filter(
                Q(sales_order_type__iexact=LEGACY_ORDER_TYPE_ANNULMENT)
                | Q(sales_order_type__iexact=LEGACY_ORDER_TYPE_RETURN)
            )
            .order_by("sales_order_number_orig", "modified_datetime", "invoice_date", "sales_order_number")
        )
    except Exception:
        return []


def process_legacy_impacts_for_order(*, sales_order_number: str, actor: str) -> int:
    order_number = str(sales_order_number or "").strip()
    if not order_number:
        return 0
    processed = 0
    try:
        queryset = LegacyOrder.objects.using("litecore").filter(
            sales_order_number_orig=order_number,
        ).filter(
            Q(sales_order_type__iexact=LEGACY_ORDER_TYPE_ANNULMENT)
            | Q(sales_order_type__iexact=LEGACY_ORDER_TYPE_RETURN)
        )
        orders = list(queryset.order_by("modified_datetime", "invoice_date", "sales_order_number")[:50])
        applied_source_keys = _applied_legacy_impact_source_keys(orders)
        for order in orders:
            if _legacy_impact_source_key(order) in applied_source_keys:
                continue
            _process_legacy_impact_order(order, actor=actor)
            processed += 1
    except Exception:
        return processed
    return processed


def refresh_legacy_impacts_for_fulfillments(
    fulfillments: list[FulfillmentOrder] | tuple[FulfillmentOrder, ...],
    *,
    actor: str,
) -> int:
    seen_order_numbers: set[str] = set()
    for fulfillment in fulfillments:
        order_number = str(fulfillment.legacy_sales_order_number or "").strip()
        if not order_number or order_number in seen_order_numbers:
            continue
        seen_order_numbers.add(order_number)
    if not seen_order_numbers:
        return 0
    if len(seen_order_numbers) == 1:
        order_number = next(iter(seen_order_numbers))
        return process_legacy_impacts_for_order(sales_order_number=order_number, actor=actor)

    impact_orders = _legacy_impact_orders_for_order_numbers(seen_order_numbers)
    applied_source_keys = _applied_legacy_impact_source_keys(impact_orders)
    processed = 0
    processed_by_original: dict[str, int] = defaultdict(int)
    for order in impact_orders:
        original_order_number = str(order.sales_order_number_orig or "").strip()
        if not original_order_number or processed_by_original[original_order_number] >= 50:
            continue
        if _legacy_impact_source_key(order) in applied_source_keys:
            continue
        try:
            _process_legacy_impact_order(order, actor=actor)
        except Exception:
            continue
        processed_by_original[original_order_number] += 1
        processed += 1
    return processed


@transaction.atomic
def ingest_legacy_order(*, sales_order_number: str, idempotency_key: str, actor: str) -> IdempotentResult:
    command_payload = {"sales_order_number": sales_order_number}
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="fulfillment.from_legacy_order",
        reference_type="sales_order",
        reference_id=sales_order_number,
        payload=command_payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)

    order = LegacyOrder.objects.using("litecore").get(sales_order_number=sales_order_number)
    if not legacy_order_is_deliverable(order):
        raise FulfillmentRuleError("El documento legacy no es un pedido entregable.")
    legacy_lines = list(
        LegacyOrderLine.objects.using("litecore")
        .filter(sales_order_number=sales_order_number)
        .order_by("line_number", "retail_line_item_id")
    )
    if not legacy_lines:
        raise FulfillmentRuleError("El pedido legacy no tiene lineas operables.")
    if not _order_is_effectively_invoiced(order):
        raise FulfillmentRuleError("El pedido legacy no tiene evidencia funcional de facturacion.")

    legacy_item_snapshots = _resolve_legacy_line_item_snapshots(legacy_lines)
    physical_legacy_lines = [
        line
        for line in legacy_lines
        if not is_virtual_item_snapshot(
            legacy_item_snapshots.get(
                str(line.retail_line_item_id),
                _default_item_snapshot(line.item_number, line.sales_unit_symbol),
            )
        )
    ]
    if not physical_legacy_lines:
        raise FulfillmentRuleError("El pedido legacy solo contiene articulos virtuales de servicio/flete; no genera entrega fisica.")

    source_payload = {
        "order": {
            "transaction_id": order.transaction_id,
            "sales_order_number": order.sales_order_number,
            "transaction_number": order.transaction_number,
            "invoice_number": order.invoice_number,
            "invoice_date": order.invoice_date,
            "order_status": order.order_status,
            "sales_order_type": legacy_sales_order_type(order),
            "sales_order_number_orig": order.sales_order_number_orig,
            "warehouse": order.warehouse,
        },
        "lines": [
            {
                "retail_line_item_id": line.retail_line_item_id,
                "sales_order_line_rec_id": line.sales_order_line_rec_id,
                "item_number": line.item_number,
                "ordered_qty": line.ordered_sales_quantity,
                "remaining_qty": _line_remaining_qty(line),
                "warehouse": line.shipping_warehouse_id or line.fulfillment_store_id or line.warehouse,
                "delivery_mode": line.delivery_mode_code,
                "line_delivery_date": _line_delivery_datetime(line),
                "requested_shipping_date": line.requested_shipping_date,
                "delivery_address_location_id": line.delivery_address_location_id,
                "delivery_address_country_region_iso_code": line.delivery_address_country_region_iso_code,
                "delivery_address_state_id": line.delivery_address_state_id,
                "delivery_address_city": line.delivery_address_city,
                "delivery_address_street": line.delivery_address_street,
                "delivery_address_street_number": line.delivery_address_street_number,
                "delivery_address_zip_code": line.delivery_address_zip_code,
                "delivery_address_description": line.delivery_address_description,
                "delivery_address_latitude": line.delivery_address_latitude,
                "delivery_address_longitude": line.delivery_address_longitude,
            }
            for line in legacy_lines
        ],
    }
    source_hash = _hash_payload(source_payload)
    first_line = physical_legacy_lines[0]
    delivery_date = _line_delivery_date(first_line)
    customer_address = _resolve_customer_address_for_line(first_line, order.customer_account)
    address_snapshot = _address_snapshot(first_line, customer_address=customer_address)
    address_snapshot["customer_ref"] = order.customer_account
    address_snapshot.setdefault("receiver", order.sales_order_name or order.customer_account)

    fulfillment, created = FulfillmentOrder.objects.get_or_create(
        fulfillment_number=f"FUL-{order.sales_order_number}",
        defaults={
            "legacy_sales_order_number": order.sales_order_number,
            "legacy_transaction_number": order.transaction_number,
            "source_table": "transactions_orders_transaction",
            "source_pk": order.transaction_id,
            "source_hash": source_hash,
            "legacy_rec_id": str(order.rec_id),
            "warehouse_ref": order.warehouse,
            "store_ref": order.store_id or "",
            "customer_ref": order.customer_account,
            "delivery_mode": first_line.delivery_mode_code,
            "requested_date": delivery_date,
            "address_snapshot": address_snapshot,
            "created_by": actor,
        },
    )
    if not created and fulfillment.status == FulfillmentOrder.FulfillmentStatus.PENDING:
        fulfillment.source_hash = source_hash
        fulfillment.legacy_transaction_number = order.transaction_number
        fulfillment.customer_ref = order.customer_account
        fulfillment.delivery_mode = first_line.delivery_mode_code
        fulfillment.requested_date = delivery_date
        fulfillment.address_snapshot = address_snapshot
        fulfillment.warehouse_ref = order.warehouse
        fulfillment.updated_by = actor
        fulfillment.save(
            update_fields=[
                "source_hash",
                "legacy_transaction_number",
                "customer_ref",
                "delivery_mode",
                "requested_date",
                "address_snapshot",
                "warehouse_ref",
                "updated_by",
                "updated_at",
            ]
        )

    operable_lines = 0
    for legacy_line in legacy_lines:
        line_snapshot = legacy_item_snapshots.get(str(legacy_line.retail_line_item_id), _default_item_snapshot(legacy_line.item_number, legacy_line.sales_unit_symbol))
        if is_virtual_item_snapshot(line_snapshot):
            continue
        remaining_qty = _line_remaining_qty(legacy_line)
        legacy_delivered_qty = legacy_line.sales_quantity_delivered or Decimal("0")
        fulfillment_line, created_line = FulfillmentOrderLine.objects.get_or_create(
            fulfillment=fulfillment,
            source_table="transactions_orders_retailLineItem",
            source_pk=str(legacy_line.retail_line_item_id),
            defaults={
                "legacy_sales_order_number": order.sales_order_number,
                "legacy_transaction_number": order.transaction_number,
                "legacy_line_id": str(legacy_line.retail_line_item_id),
                "legacy_line_rec_id": str(legacy_line.sales_order_line_rec_id),
                "legacy_rec_id": str(legacy_line.rec_id),
                "item_ref": legacy_line.item_number,
                "warehouse_ref": legacy_line.shipping_warehouse_id or legacy_line.fulfillment_store_id or legacy_line.warehouse,
                "store_ref": legacy_line.fulfillment_store_id,
                "ordered_qty": legacy_line.ordered_sales_quantity,
                "reserved_qty": Decimal("0"),
                "prepared_qty": Decimal("0"),
                "delivered_qty": legacy_delivered_qty,
                "cancelled_qty": Decimal("0"),
                "uom": legacy_line.sales_unit_symbol,
                "source_hash": source_hash,
                "created_by": actor,
            },
        )
        if not created_line:
            fulfillment_line.legacy_sales_order_number = order.sales_order_number
            fulfillment_line.legacy_transaction_number = order.transaction_number
            fulfillment_line.legacy_line_id = str(legacy_line.retail_line_item_id)
            fulfillment_line.legacy_line_rec_id = str(legacy_line.sales_order_line_rec_id)
            fulfillment_line.legacy_rec_id = str(legacy_line.rec_id)
            fulfillment_line.item_ref = legacy_line.item_number
            fulfillment_line.warehouse_ref = legacy_line.shipping_warehouse_id or legacy_line.fulfillment_store_id or legacy_line.warehouse
            fulfillment_line.store_ref = legacy_line.fulfillment_store_id
            fulfillment_line.ordered_qty = legacy_line.ordered_sales_quantity
            fulfillment_line.delivered_qty = max(legacy_delivered_qty, _remitted_qty_for_fulfillment_line(fulfillment_line))
            fulfillment_line.uom = legacy_line.sales_unit_symbol
            fulfillment_line.source_hash = source_hash
            fulfillment_line.updated_by = actor
            fulfillment_line.save(
                update_fields=[
                    "legacy_sales_order_number",
                    "legacy_transaction_number",
                    "legacy_line_id",
                    "legacy_line_rec_id",
                    "legacy_rec_id",
                    "item_ref",
                    "warehouse_ref",
                    "store_ref",
                    "ordered_qty",
                    "delivered_qty",
                    "uom",
                    "source_hash",
                    "updated_by",
                    "updated_at",
                ]
        )
        _bootstrap_packed_balance(fulfillment_line, max(ZERO, remaining_qty - fulfillment_line.cancelled_qty))
        operable_lines += 1

    if created:
        StatusHistory.objects.create(
            entity_type="fulfillment_order",
            entity_id=str(fulfillment.id),
            to_status=fulfillment.status,
            actor=actor,
            reason="Ingesta desde Litecore local",
        )
        DomainEventOutbox.objects.create(
            event_type="fulfillment.ingested",
            aggregate_type="fulfillment_order",
            aggregate_id=str(fulfillment.id),
            payload={"sales_order_number": order.sales_order_number},
        )

    process_legacy_impacts_for_order(sales_order_number=order.sales_order_number, actor=actor)
    fulfillment = FulfillmentOrder.objects.prefetch_related("lines", "deliveries", "impacts__lines").get(id=fulfillment.id)
    result = IdempotentResult({"result": _serialize_fulfillment(fulfillment)}, 201 if created else 200)
    return _finish_idempotent_command(idempotency, result)


def _planned_elsewhere(fulfillment_line: FulfillmentOrderLine, exclude_delivery_id: str | None = None) -> Decimal:
    queryset = _active_delivery_lines_queryset().filter(fulfillment_line=fulfillment_line)
    if exclude_delivery_id:
        queryset = queryset.exclude(delivery_id=exclude_delivery_id)
    return queryset.aggregate(total=Sum("planned_qty"))["total"] or Decimal("0")


def _packed_balance_quantity(fulfillment_line: FulfillmentOrderLine) -> Decimal:
    return _packed_quantities_for_keys(
        {(fulfillment_line.warehouse_ref, fulfillment_line.item_ref, fulfillment_line.uom)}
    ).get((fulfillment_line.warehouse_ref, fulfillment_line.item_ref, fulfillment_line.uom), ZERO)


def _remitted_qty_for_fulfillment_line(fulfillment_line: FulfillmentOrderLine) -> Decimal:
    return (
        DeliveryDocumentLine.objects.filter(
            delivery_line__fulfillment_line=fulfillment_line,
            document__status=DeliveryDocument.DocumentStatus.CLOSED,
            document__document_type=DeliveryDocument.DocumentType.REMITO,
        ).aggregate(total=Sum("quantity"))["total"]
        or Decimal("0")
    )


def _open_remito_qty_for_fulfillment_line(fulfillment_line: FulfillmentOrderLine) -> Decimal:
    return (
        DeliveryDocumentLine.objects.filter(
            delivery_line__fulfillment_line=fulfillment_line,
            document__status=DeliveryDocument.DocumentStatus.OPEN,
            document__document_type=DeliveryDocument.DocumentType.REMITO,
        )
        .exclude(document__delivery__status__in=[DeliveryOrder.DeliveryStatus.RETURNED, DeliveryOrder.DeliveryStatus.CANCELLED])
        .aggregate(total=Sum("quantity"))["total"]
        or ZERO
    )


def _max_dispatchable(fulfillment_line: FulfillmentOrderLine, exclude_delivery_id: str | None = None) -> Decimal:
    already_planned = _planned_elsewhere(fulfillment_line, exclude_delivery_id)
    return _max_dispatchable_from_values(
        fulfillment_line,
        already_planned=already_planned,
        packed_qty=_packed_balance_quantity(fulfillment_line),
    )


@transaction.atomic
def split_fulfillment_delivery(
    *,
    fulfillment_id: str,
    lines: list[dict],
    delivery_mode: str,
    planned_date,
    reason: str,
    idempotency_key: str,
    actor: str,
    authorized_warehouses=None,
    receiver: str = "",
    reference: str = "",
    target_warehouse_ref: str = "",
) -> IdempotentResult:
    target_warehouse_ref = _target_warehouse(target_warehouse_ref)
    command_payload = {
        "fulfillment_id": fulfillment_id,
        "lines": lines,
        "delivery_mode": delivery_mode,
        "planned_date": str(planned_date or ""),
        "reason": reason,
    }
    if target_warehouse_ref:
        command_payload["target_warehouse_ref"] = target_warehouse_ref
    if receiver:
        command_payload["receiver"] = receiver
    if reference:
        command_payload["reference"] = reference
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="fulfillment.split",
        reference_type="fulfillment_order",
        reference_id=fulfillment_id,
        payload=command_payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)

    fulfillment = FulfillmentOrder.objects.select_for_update().get(id=fulfillment_id)
    delivery_warehouse_ref = target_warehouse_ref or fulfillment.warehouse_ref
    _ensure_warehouse_authorized(delivery_warehouse_ref, authorized_warehouses)
    customer = _default_customer_snapshot(fulfillment.customer_ref)
    if receiver or reference:
        customer = _resolve_customer_snapshots({fulfillment.customer_ref}).get(fulfillment.customer_ref, customer)
    delivery = DeliveryOrder.objects.create(
        fulfillment=fulfillment,
        delivery_number=allocate_sequence_number(DELIVERY_SEQUENCE_NAME, actor=actor),
        delivery_mode=delivery_mode or fulfillment.delivery_mode,
        planned_date=planned_date or fulfillment.requested_date,
        status=DeliveryOrder.DeliveryStatus.CREATED,
        legacy_sales_order_number=fulfillment.legacy_sales_order_number,
        legacy_transaction_number=fulfillment.legacy_transaction_number,
        warehouse_ref=delivery_warehouse_ref,
        store_ref=fulfillment.store_ref,
        address_snapshot=_delivery_address_snapshot(fulfillment, receiver=receiver, reference=reference, customer=customer),
        created_by=actor,
    )

    requested_line_ids = [
        str(payload_line.get("fulfillment_line_id") or "")
        for payload_line in lines
        if str(payload_line.get("fulfillment_line_id") or "")
    ]
    fulfillment_lines = {
        str(line.id): line
        for line in fulfillment.lines.select_for_update().filter(id__in=requested_line_ids)
    }
    item_snapshots = _resolve_line_item_snapshots(list(fulfillment_lines.values()))
    physical_fulfillment_lines = physical_fulfillment_lines_from_snapshots(list(fulfillment_lines.values()), item_snapshots)
    line_metrics = _line_metrics(physical_fulfillment_lines)
    planned_in_this_delivery: dict = defaultdict(lambda: ZERO)
    created_lines = 0
    for payload_line in lines:
        line_id = str(payload_line.get("fulfillment_line_id") or "")
        fulfillment_line = fulfillment_lines.get(line_id)
        if fulfillment_line is None:
            raise FulfillmentRuleError("La linea de fulfillment indicada no existe para este pedido.")
        has_delivery_unit_qty = payload_line.get("delivery_unit_qty") not in [None, ""]
        item_snapshot = _with_display_uom(
            item_snapshots.get(fulfillment_line.id, _default_item_snapshot(fulfillment_line.item_ref, fulfillment_line.uom)),
            fallback_uom=fulfillment_line.uom,
        )
        if is_virtual_item_snapshot(item_snapshot):
            continue
        if has_delivery_unit_qty:
            delivery_unit_qty = _to_decimal(payload_line.get("delivery_unit_qty"))
            split_qty = _commercial_qty_from_delivery_units(delivery_unit_qty, item_snapshot)
        else:
            split_qty = _to_decimal(payload_line.get("split_qty"))
            delivery_unit_qty = _delivery_unit_qty_from_commercial(split_qty, item_snapshot)
        if split_qty <= ZERO:
            continue
        line_warehouse_ref = _fulfillment_line_warehouse(fulfillment_line, fulfillment, target_warehouse_ref)
        _ensure_warehouse_authorized(line_warehouse_ref, authorized_warehouses)
        metric = line_metrics.get(fulfillment_line.id, {})
        already_planned = metric.get("planned_qty", ZERO) + planned_in_this_delivery[fulfillment_line.id]
        effective_pending_qty = _effective_pending_qty(
            fulfillment_line,
            open_remito_qty=metric.get("open_remito_qty", ZERO),
        )
        if target_warehouse_ref:
            packed_qty = _packed_quantity_for_key(
                warehouse_ref=line_warehouse_ref,
                item_ref=fulfillment_line.item_ref,
                uom=fulfillment_line.uom,
            )
            max_qty = min(max(ZERO, effective_pending_qty - already_planned), packed_qty)
        else:
            max_qty = _max_dispatchable_from_effective_pending(
                effective_pending_qty=effective_pending_qty,
                already_planned=already_planned,
                packed_qty=metric.get("packed_qty", ZERO),
            )
        if split_qty > max_qty:
            raise FulfillmentRuleError(
                f"La linea {fulfillment_line.item_ref} solicita {split_qty} y solo permite {max_qty}."
            )
        planned_weight_kg, planned_volume_m3 = _capacity_totals(split_qty, item_snapshot)
        delivery_line = DeliveryOrderLine.objects.create(
            delivery=delivery,
            fulfillment_line=fulfillment_line,
            planned_qty=split_qty,
            delivery_unit_qty=delivery_unit_qty,
            delivery_uom=item_snapshot.get("delivery_uom") or fulfillment_line.uom,
            conversion_factor=_item_conversion_factor(item_snapshot),
            uom=fulfillment_line.uom,
            legacy_sales_order_number=fulfillment_line.legacy_sales_order_number,
            legacy_transaction_number=fulfillment_line.legacy_transaction_number,
            legacy_line_id=fulfillment_line.legacy_line_id,
            legacy_line_rec_id=fulfillment_line.legacy_line_rec_id,
            item_ref=fulfillment_line.item_ref,
            warehouse_ref=line_warehouse_ref,
            store_ref=fulfillment_line.store_ref,
            item_snapshot=item_snapshot,
            planned_weight_kg=planned_weight_kg,
            planned_volume_m3=planned_volume_m3,
            created_by=actor,
        )
        planned_in_this_delivery[fulfillment_line.id] += split_qty
        DeliverySplit.objects.create(
            fulfillment_line=fulfillment_line,
            delivery_line=delivery_line,
            split_qty=split_qty,
            remaining_after_split=max(
                Decimal("0"),
                effective_pending_qty - (metric.get("planned_qty", ZERO) + planned_in_this_delivery[fulfillment_line.id]),
            ),
            reason=reason,
            legacy_sales_order_number=fulfillment_line.legacy_sales_order_number,
            legacy_transaction_number=fulfillment_line.legacy_transaction_number,
            legacy_line_id=fulfillment_line.legacy_line_id,
            legacy_line_rec_id=fulfillment_line.legacy_line_rec_id,
            item_ref=fulfillment_line.item_ref,
            warehouse_ref=line_warehouse_ref,
            created_by=actor,
        )
        created_lines += 1

    if not created_lines:
        raise FulfillmentRuleError("La entrega no tiene cantidades positivas.")

    result = IdempotentResult({"result": _serialize_delivery(delivery)}, 201)
    return _finish_idempotent_command(idempotency, result)


def _serialize_task(task: DeliveryPreparationTask) -> dict:
    return {
        "id": str(task.id),
        "delivery_id": str(task.delivery_id),
        "status": task.status,
        "assigned_employee_ref": task.assigned_to,
        "assigned_at": task.assigned_at.isoformat() if task.assigned_at else None,
        "prepared_by": task.prepared_by,
        "prepared_at": task.prepared_at.isoformat() if task.prepared_at else None,
        "notes": task.notes,
    }


def _serialize_delivery(delivery: DeliveryOrder) -> dict:
    delivery = (
        DeliveryOrder.objects.prefetch_related("lines__fulfillment_line", "documents", "executions")
        .select_related("fulfillment", "preparation_task")
        .get(id=delivery.id)
    )
    delivery_lines = _physical_delivery_lines_for_delivery(delivery)
    return {
        "id": str(delivery.id),
        "delivery_number": delivery.delivery_number,
        "status": delivery.status,
        "delivery_mode": delivery.delivery_mode,
        "planned_date": delivery.planned_date.isoformat() if delivery.planned_date else None,
        "fulfillment_id": str(delivery.fulfillment_id),
        "sales_order_number": delivery.legacy_sales_order_number,
        "warehouse_ref": delivery.warehouse_ref,
        "store_ref": delivery.store_ref,
        "address_snapshot": delivery.address_snapshot,
        "route_sheet": _delivery_route_assignment(str(delivery.id)),
        "lines": [_serialize_delivery_line(line) for line in delivery_lines],
        "totals": _delivery_totals(delivery_lines),
        "documents": [
            {
                "id": str(document.id),
                "document_number": document.document_number,
                "document_type": document.document_type,
                "status": document.status,
                "issued_at": document.issued_at.isoformat(),
            }
            for document in delivery.documents.all()
        ],
        "preparation_task": _serialize_task(delivery.preparation_task) if hasattr(delivery, "preparation_task") else None,
        "movements": _delivery_movements(delivery),
    }


def _stock_check_result(
    *,
    reference_type: str,
    reference_id: str,
    reference_number: str = "",
    lines: list[dict],
    issues: list[dict],
) -> dict:
    return {
        "reference_type": reference_type,
        "reference_id": reference_id,
        "reference_number": reference_number,
        "status": "insufficient" if issues else "ok",
        "can_confirm": not issues,
        "issues": issues,
        "lines": lines,
    }


def _packed_quantity_for_key(*, warehouse_ref: str, item_ref: str, uom: str) -> Decimal:
    return _packed_quantities_for_keys({(warehouse_ref, item_ref, uom)}).get((warehouse_ref, item_ref, uom), ZERO)


def _packed_quantities_for_keys(keys: set[tuple[str, str, str]]) -> dict[tuple[str, str, str], Decimal]:
    return available_stock_quantities_for_keys(keys, stock_state=StockState.PACKED, actor="fulfillment")


def _stock_issue_payload(
    *,
    line_id: str,
    item_ref: str,
    warehouse_ref: str,
    planned_qty: Decimal,
    available_qty: Decimal,
    uom: str,
    reason: str,
) -> dict:
    return {
        "line_id": line_id,
        "item_ref": item_ref,
        "warehouse_ref": warehouse_ref,
        "planned_qty": str(planned_qty),
        "available_qty": str(max(available_qty, ZERO)),
        "uom": uom,
        "reason": reason,
    }


def check_delivery_stock(*, delivery_id: str, authorized_warehouses=None, target_warehouse_ref: str = "") -> dict:
    target_warehouse_ref = _target_warehouse(target_warehouse_ref)
    delivery = (
        DeliveryOrder.objects.select_related("fulfillment")
        .prefetch_related("lines__fulfillment_line")
        .get(id=delivery_id)
    )
    _ensure_warehouse_authorized(target_warehouse_ref or delivery.warehouse_ref, authorized_warehouses)
    existing_reservation = _active_delivery_reservations().filter(source_type="delivery_order", source_ref=str(delivery.id)).exists()
    if target_warehouse_ref and delivery.warehouse_ref != target_warehouse_ref:
        existing_reservation = False
    lines = _physical_delivery_lines_for_delivery(delivery)
    return _check_delivery_stock_for_lines(
        delivery=delivery,
        lines=lines,
        authorized_warehouses=authorized_warehouses,
        existing_reservation=existing_reservation,
        target_warehouse_ref=target_warehouse_ref,
    )


def _check_delivery_stock_for_lines(
    *,
    delivery: DeliveryOrder,
    lines: list[DeliveryOrderLine],
    authorized_warehouses=None,
    existing_reservation: bool = False,
    target_warehouse_ref: str = "",
) -> dict:
    target_warehouse_ref = _target_warehouse(target_warehouse_ref)
    rows: list[dict] = []
    issues: list[dict] = []
    requested_by_bucket: dict[tuple[str, str, str], Decimal] = defaultdict(lambda: ZERO)
    packed_by_key = _packed_quantities_for_keys(
        {
            (_delivery_line_warehouse(line, delivery, target_warehouse_ref), line.item_ref, line.uom)
            for line in lines
        }
    )

    for line in lines:
        warehouse_ref = _delivery_line_warehouse(line, delivery, target_warehouse_ref)
        _ensure_warehouse_authorized(warehouse_ref, authorized_warehouses)
        key = (warehouse_ref, line.item_ref, line.uom)
        requested_by_bucket[key] += line.planned_qty
        available_qty = packed_by_key.get(key, ZERO)
        rows.append(
            {
                "line_id": str(line.id),
                "fulfillment_line_id": str(line.fulfillment_line_id),
                "item_ref": line.item_ref,
                "warehouse_ref": warehouse_ref,
                "planned_qty": str(line.planned_qty),
                "available_qty": str(available_qty),
                "uom": line.uom,
            }
        )

    if not existing_reservation:
        for warehouse_ref, item_ref, uom in requested_by_bucket:
            requested_qty = requested_by_bucket[(warehouse_ref, item_ref, uom)]
            available_qty = packed_by_key.get((warehouse_ref, item_ref, uom), ZERO)
            if requested_qty <= available_qty:
                continue
            affected_lines = [
                line
                for line in lines
                if _delivery_line_warehouse(line, delivery, target_warehouse_ref) == warehouse_ref
                and line.item_ref == item_ref
                and line.uom == uom
            ]
            for line in affected_lines:
                issues.append(
                    _stock_issue_payload(
                        line_id=str(line.id),
                        item_ref=line.item_ref,
                        warehouse_ref=warehouse_ref,
                        planned_qty=line.planned_qty,
                        available_qty=available_qty,
                        uom=line.uom,
                        reason="stock_packed_insufficient",
                    )
                )

    return _stock_check_result(
        reference_type="delivery_order",
        reference_id=str(delivery.id),
        reference_number=delivery.delivery_number,
        lines=rows,
        issues=issues,
    )


def check_fulfillment_stock_for_split(
    *,
    fulfillment_id: str,
    lines: list[dict],
    authorized_warehouses=None,
    target_warehouse_ref: str = "",
) -> dict:
    target_warehouse_ref = _target_warehouse(target_warehouse_ref)
    fulfillment = FulfillmentOrder.objects.prefetch_related("lines").get(id=fulfillment_id)
    _ensure_warehouse_authorized(target_warehouse_ref or fulfillment.warehouse_ref, authorized_warehouses)
    requested_line_ids = [
        str(payload_line.get("fulfillment_line_id") or "")
        for payload_line in lines
        if str(payload_line.get("fulfillment_line_id") or "")
    ]
    fulfillment_lines = {
        str(line.id): line
        for line in fulfillment.lines.filter(id__in=requested_line_ids)
    }
    item_snapshots = _resolve_line_item_snapshots(list(fulfillment_lines.values()))
    physical_lines = physical_fulfillment_lines_from_snapshots(list(fulfillment_lines.values()), item_snapshots)
    metrics = _line_metrics(physical_lines)
    packed_by_key = _packed_quantities_for_keys(
        {
            (_fulfillment_line_warehouse(line, fulfillment, target_warehouse_ref), line.item_ref, line.uom)
            for line in physical_lines
        }
    )
    rows: list[dict] = []
    issues: list[dict] = []
    requested_by_bucket: dict[tuple[str, str, str], Decimal] = defaultdict(lambda: ZERO)

    for payload_line in lines:
        line_id = str(payload_line.get("fulfillment_line_id") or "")
        fulfillment_line = fulfillment_lines.get(line_id)
        if fulfillment_line is None:
            raise FulfillmentRuleError("La linea de fulfillment indicada no existe para este pedido.")
        warehouse_ref = _fulfillment_line_warehouse(fulfillment_line, fulfillment, target_warehouse_ref)
        _ensure_warehouse_authorized(warehouse_ref, authorized_warehouses)
        item_snapshot = _with_display_uom(
            item_snapshots.get(fulfillment_line.id, _default_item_snapshot(fulfillment_line.item_ref, fulfillment_line.uom)),
            fallback_uom=fulfillment_line.uom,
        )
        if is_virtual_item_snapshot(item_snapshot):
            continue
        if payload_line.get("delivery_unit_qty") not in [None, ""]:
            requested_qty = _commercial_qty_from_delivery_units(_to_decimal(payload_line.get("delivery_unit_qty")), item_snapshot)
        else:
            requested_qty = _to_decimal(payload_line.get("split_qty"))
        if requested_qty <= ZERO:
            continue
        key = (warehouse_ref, fulfillment_line.item_ref, fulfillment_line.uom)
        requested_by_bucket[key] += requested_qty
        metric = metrics.get(fulfillment_line.id, {})
        effective_pending_qty = _effective_pending_qty(
            fulfillment_line,
            open_remito_qty=metric.get("open_remito_qty", ZERO),
        )
        if target_warehouse_ref:
            max_qty = min(max(ZERO, effective_pending_qty - metric.get("planned_qty", ZERO)), packed_by_key.get(key, ZERO))
        else:
            max_qty = _max_dispatchable_from_effective_pending(
                effective_pending_qty=effective_pending_qty,
                already_planned=metric.get("planned_qty", ZERO),
                packed_qty=metric.get("packed_qty", ZERO),
            )
        available_qty = packed_by_key.get(key, ZERO)
        rows.append(
            {
                "line_id": str(fulfillment_line.id),
                "item_ref": fulfillment_line.item_ref,
                "warehouse_ref": warehouse_ref,
                "planned_qty": str(requested_qty),
                "available_qty": str(max_qty),
                "packed_qty": str(available_qty),
                "uom": fulfillment_line.uom,
            }
        )
        if requested_qty > max_qty:
            issues.append(
                _stock_issue_payload(
                    line_id=str(fulfillment_line.id),
                    item_ref=fulfillment_line.item_ref,
                    warehouse_ref=warehouse_ref,
                    planned_qty=requested_qty,
                    available_qty=max_qty,
                    uom=fulfillment_line.uom,
                    reason="max_dispatchable_insufficient",
                )
            )

    for warehouse_ref, item_ref, uom in requested_by_bucket:
        requested_qty = requested_by_bucket[(warehouse_ref, item_ref, uom)]
        available_qty = packed_by_key.get((warehouse_ref, item_ref, uom), ZERO)
        if requested_qty <= available_qty:
            continue
        for row in rows:
            if row["warehouse_ref"] == warehouse_ref and row["item_ref"] == item_ref and row["uom"] == uom:
                issues.append(
                    _stock_issue_payload(
                        line_id=row["line_id"],
                        item_ref=item_ref,
                        warehouse_ref=warehouse_ref,
                        planned_qty=_to_decimal(row["planned_qty"]),
                        available_qty=available_qty,
                        uom=uom,
                        reason="stock_packed_insufficient",
                    )
                )

    return _stock_check_result(
        reference_type="fulfillment_order",
        reference_id=str(fulfillment.id),
        reference_number=fulfillment.fulfillment_number,
        lines=rows,
        issues=issues,
    )


def _apply_delivery_warehouse(delivery: DeliveryOrder, target_warehouse_ref: str, actor: str) -> None:
    target_warehouse_ref = _target_warehouse(target_warehouse_ref)
    if not target_warehouse_ref or delivery.warehouse_ref == target_warehouse_ref:
        return
    previous_warehouse_ref = delivery.warehouse_ref
    delivery.warehouse_ref = target_warehouse_ref
    delivery.updated_by = actor
    delivery.save(update_fields=["warehouse_ref", "updated_by", "updated_at"])
    DeliveryOrderLine.objects.filter(delivery=delivery).update(warehouse_ref=target_warehouse_ref, updated_by=actor, updated_at=timezone.now())
    DeliverySplit.objects.filter(delivery_line__delivery=delivery).update(
        warehouse_ref=target_warehouse_ref,
        updated_by=actor,
        updated_at=timezone.now(),
    )
    StatusHistory.objects.create(
        entity_type="delivery_order",
        entity_id=str(delivery.id),
        from_status=delivery.status,
        to_status=delivery.status,
        actor=actor,
        reason="Cambio de deposito operativo",
        payload={"from_warehouse_ref": previous_warehouse_ref, "to_warehouse_ref": target_warehouse_ref},
    )


@transaction.atomic
def confirm_available_delivery_stock(
    *,
    delivery_id: str,
    lines: list[dict],
    idempotency_key: str,
    actor: str,
    authorized_warehouses=None,
    target_warehouse_ref: str = "",
) -> IdempotentResult:
    target_warehouse_ref = _target_warehouse(target_warehouse_ref)
    command_payload = {"delivery_id": delivery_id, "lines": lines}
    if target_warehouse_ref:
        command_payload["target_warehouse_ref"] = target_warehouse_ref
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="delivery.confirm_available",
        reference_type="delivery_order",
        reference_id=delivery_id,
        payload=command_payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)

    delivery = (
        DeliveryOrder.objects.select_for_update()
        .select_related("fulfillment")
        .prefetch_related("lines__fulfillment_line", "documents", "preparation_task")
        .get(id=delivery_id)
    )
    _ensure_warehouse_authorized(target_warehouse_ref or delivery.warehouse_ref, authorized_warehouses)
    if delivery.status not in [DeliveryOrder.DeliveryStatus.CREATED, DeliveryOrder.DeliveryStatus.PLANNED]:
        raise FulfillmentRuleError("La entrega solo se puede confirmar parcialmente desde creada o planificada.")
    if _active_delivery_reservations().filter(source_type="delivery_order", source_ref=str(delivery.id)).exists():
        raise FulfillmentRuleError("La entrega ya tiene stock reservado.")
    if delivery.documents.filter(document_type=DeliveryDocument.DocumentType.REMITO).exists():
        raise FulfillmentRuleError("La entrega ya tiene remito.")
    if hasattr(delivery, "preparation_task") and delivery.preparation_task.status != DeliveryPreparationTask.TaskStatus.CANCELLED:
        raise FulfillmentRuleError("La entrega ya inicio preparacion.")

    requested_by_line_id: dict[str, Decimal] = {}
    for payload_line in lines:
        line_id = str(payload_line.get("delivery_line_id") or "").strip()
        if not line_id:
            raise FulfillmentRuleError("delivery_line_id es obligatorio.")
        if line_id in requested_by_line_id:
            raise FulfillmentRuleError("La linea de entrega esta duplicada.")
        requested_qty = _to_decimal(payload_line.get("planned_qty"))
        if requested_qty < ZERO:
            raise FulfillmentRuleError("La cantidad a confirmar no puede ser negativa.")
        requested_by_line_id[line_id] = requested_qty

    delivery_lines = list(delivery.lines.select_for_update().select_related("fulfillment_line"))
    physical_lines = physical_delivery_lines(delivery_lines)
    physical_line_ids = {str(line.id) for line in physical_lines}
    unknown_line_ids = set(requested_by_line_id) - physical_line_ids
    if unknown_line_ids:
        raise FulfillmentRuleError("La linea de entrega indicada no existe para esta entrega.")

    kept_lines = 0
    changed_lines: list[dict] = []
    for line in physical_lines:
        line_id = str(line.id)
        next_qty = _quantize_qty(requested_by_line_id.get(line_id, ZERO))
        previous_qty = line.planned_qty
        if next_qty > previous_qty:
            raise FulfillmentRuleError(f"La linea {line.item_ref} no puede aumentar cantidad en confirmacion parcial.")
        if next_qty <= ZERO:
            changed_lines.append(
                {
                    "delivery_line_id": line_id,
                    "item_ref": line.item_ref,
                    "from_qty": str(previous_qty),
                    "to_qty": "0",
                    "uom": line.uom,
                }
            )
            line.delete()
            continue

        snapshot = _delivery_line_snapshot(line)
        planned_weight_kg, planned_volume_m3 = _capacity_totals(next_qty, snapshot)
        next_delivery_unit_qty = _delivery_unit_qty_from_commercial(next_qty, snapshot)
        if next_qty != previous_qty:
            changed_lines.append(
                {
                    "delivery_line_id": line_id,
                    "item_ref": line.item_ref,
                    "from_qty": str(previous_qty),
                    "to_qty": str(next_qty),
                    "uom": line.uom,
                }
            )
        line.planned_qty = next_qty
        line.delivery_unit_qty = next_delivery_unit_qty
        line.planned_weight_kg = planned_weight_kg
        line.planned_volume_m3 = planned_volume_m3
        line.updated_by = actor
        line.save(
            update_fields=[
                "planned_qty",
                "delivery_unit_qty",
                "planned_weight_kg",
                "planned_volume_m3",
                "updated_by",
                "updated_at",
            ]
        )
        remaining_after_split = max(
            ZERO,
            line.fulfillment_line.pending_qty - (_planned_elsewhere(line.fulfillment_line, exclude_delivery_id=str(delivery.id)) + next_qty),
        )
        DeliverySplit.objects.filter(delivery_line=line).update(
            split_qty=next_qty,
            remaining_after_split=remaining_after_split,
            updated_by=actor,
            updated_at=timezone.now(),
        )
        kept_lines += 1

    if kept_lines <= 0:
        raise FulfillmentRuleError("La entrega no tiene cantidades disponibles para confirmar.")

    if changed_lines:
        StatusHistory.objects.create(
            entity_type="delivery_order",
            entity_id=str(delivery.id),
            from_status=delivery.status,
            to_status=delivery.status,
            actor=actor,
            reason="Confirmacion parcial por stock disponible",
            payload={"lines": changed_lines},
        )

    result = validate_delivery_stock(
        delivery_id=delivery_id,
        idempotency_key=f"{idempotency_key}:validate",
        actor=actor,
        authorized_warehouses=authorized_warehouses,
        target_warehouse_ref=target_warehouse_ref,
    )
    return _finish_idempotent_command(idempotency, result)


@transaction.atomic
def validate_delivery_stock(
    *,
    delivery_id: str,
    idempotency_key: str,
    actor: str,
    authorized_warehouses=None,
    target_warehouse_ref: str = "",
) -> IdempotentResult:
    target_warehouse_ref = _target_warehouse(target_warehouse_ref)
    command_payload = {"delivery_id": delivery_id}
    if target_warehouse_ref:
        command_payload["target_warehouse_ref"] = target_warehouse_ref
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="delivery.confirm",
        reference_type="delivery_order",
        reference_id=delivery_id,
        payload=command_payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)

    delivery = (
        DeliveryOrder.objects.select_for_update()
        .select_related("fulfillment")
        .prefetch_related("lines__fulfillment_line")
        .get(id=delivery_id)
    )
    _ensure_warehouse_authorized(target_warehouse_ref or delivery.warehouse_ref, authorized_warehouses)
    if delivery.status not in [
        DeliveryOrder.DeliveryStatus.CREATED,
        DeliveryOrder.DeliveryStatus.PLANNED,
        DeliveryOrder.DeliveryStatus.CONFIRMED,
    ]:
        raise FulfillmentRuleError("La entrega solo se puede confirmar desde creada o planificada.")

    existing_reservation = _active_delivery_reservations().filter(source_type="delivery_order", source_ref=str(delivery.id)).exists()
    delivery_lines_to_reserve = _physical_delivery_lines_for_delivery(delivery)
    if not delivery_lines_to_reserve:
        raise FulfillmentRuleError("La entrega no tiene lineas fisicas para reservar.")
    stock_check = _check_delivery_stock_for_lines(
        delivery=delivery,
        lines=delivery_lines_to_reserve,
        authorized_warehouses=authorized_warehouses,
        existing_reservation=existing_reservation,
        target_warehouse_ref=target_warehouse_ref,
    )
    issues = [] if existing_reservation else stock_check["issues"]
    if issues:
        raise FulfillmentRuleError(f"Stock insuficiente para confirmar la entrega: {issues}")
    if target_warehouse_ref and not existing_reservation:
        _apply_delivery_warehouse(delivery, target_warehouse_ref, actor)
        delivery = (
            DeliveryOrder.objects.select_for_update()
            .select_related("fulfillment")
            .prefetch_related("lines__fulfillment_line")
            .get(id=delivery_id)
        )
        delivery_lines_to_reserve = _physical_delivery_lines_for_delivery(delivery)

    if not existing_reservation:
        try:
            reserve_inventory(
                warehouse_ref=delivery.warehouse_ref,
                source_type="delivery_order",
                source_ref=str(delivery.id),
                actor=actor,
                lines=[
                    {
                        "item_ref": line.item_ref,
                        "warehouse_ref": line.warehouse_ref or delivery.warehouse_ref,
                        "quantity": str(line.planned_qty),
                        "uom": line.uom,
                        "legacy_sales_order_number": line.legacy_sales_order_number,
                        "legacy_line_id": line.legacy_line_id,
                    }
                    for line in delivery_lines_to_reserve
                ],
                idempotency_key=f"{idempotency_key}:inventory",
                source_stock_state=StockState.PACKED,
            )
        except InventoryRuleError as exc:
            raise FulfillmentRuleError(str(exc)) from exc
        fulfillment_lines_by_id: dict = {}
        reserved_by_line: dict = defaultdict(lambda: ZERO)
        for line in delivery_lines_to_reserve:
            fulfillment_lines_by_id[line.fulfillment_line_id] = line.fulfillment_line
            reserved_by_line[line.fulfillment_line_id] += line.planned_qty
        for line_id, fulfillment_line in fulfillment_lines_by_id.items():
            fulfillment_line.reserved_qty += reserved_by_line[line_id]
            fulfillment_line.updated_by = actor
            fulfillment_line.updated_at = timezone.now()
        FulfillmentOrderLine.objects.bulk_update(
            fulfillment_lines_by_id.values(),
            ["reserved_qty", "updated_by", "updated_at"],
        )

    from_status = delivery.status
    delivery.status = DeliveryOrder.DeliveryStatus.CONFIRMED
    delivery.updated_by = actor
    delivery.save(update_fields=["status", "updated_by", "updated_at"])
    fulfillment = delivery.fulfillment
    if fulfillment.status == FulfillmentOrder.FulfillmentStatus.PENDING:
        fulfillment.status = FulfillmentOrder.FulfillmentStatus.ALLOCATED
        fulfillment.updated_by = actor
        fulfillment.save(update_fields=["status", "updated_by", "updated_at"])
    StatusHistory.objects.create(
        entity_type="delivery_order",
        entity_id=str(delivery.id),
        from_status=from_status,
        to_status=delivery.status,
        actor=actor,
        reason="Confirmacion de entrega",
    )
    result = IdempotentResult({"result": _serialize_delivery(delivery)})
    return _finish_idempotent_command(idempotency, result)


@transaction.atomic
def reassign_confirmed_delivery_warehouse(
    *,
    delivery_id: str,
    target_warehouse_ref: str,
    idempotency_key: str,
    actor: str,
    authorized_warehouses=None,
) -> IdempotentResult:
    target_warehouse_ref = _target_warehouse(target_warehouse_ref)
    if not target_warehouse_ref:
        raise FulfillmentRuleError("target_warehouse_ref es obligatorio.")
    command_payload = {"delivery_id": delivery_id, "target_warehouse_ref": target_warehouse_ref}
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="delivery.reassign_warehouse",
        reference_type="delivery_order",
        reference_id=delivery_id,
        payload=command_payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)

    _ensure_warehouse_authorized(target_warehouse_ref, authorized_warehouses)
    delivery = (
        DeliveryOrder.objects.select_for_update()
        .select_related("fulfillment")
        .prefetch_related("lines__fulfillment_line", "documents")
        .get(id=delivery_id)
    )
    if delivery.warehouse_ref == target_warehouse_ref:
        result = IdempotentResult({"result": _serialize_delivery(delivery)})
        return _finish_idempotent_command(idempotency, result)
    if delivery.status != DeliveryOrder.DeliveryStatus.CONFIRMED:
        raise FulfillmentRuleError("Solo se puede reasignar una entrega confirmada antes de prepararla.")
    if delivery.documents.filter(document_type=DeliveryDocument.DocumentType.REMITO).exists():
        raise FulfillmentRuleError("No se puede reasignar una entrega con remito.")
    if DeliveryPreparationTask.objects.filter(delivery=delivery).exclude(status=DeliveryPreparationTask.TaskStatus.CANCELLED).exists():
        raise FulfillmentRuleError("No se puede reasignar una entrega enviada a preparacion.")
    if _delivery_route_assignment(str(delivery.id)):
        raise FulfillmentRuleError("No se puede reasignar una entrega asignada a hoja de ruta.")
    if not _active_delivery_reservations().filter(
        source_type="delivery_order",
        source_ref=str(delivery.id),
        status=InventoryReservation.ReservationStatus.ALLOCATED,
    ).exists():
        raise FulfillmentRuleError("La entrega confirmada no tiene una reserva asignada para reasignar.")

    delivery_lines = _physical_delivery_lines_for_delivery(delivery)
    stock_check = _check_delivery_stock_for_lines(
        delivery=delivery,
        lines=delivery_lines,
        authorized_warehouses=[target_warehouse_ref],
        existing_reservation=False,
        target_warehouse_ref=target_warehouse_ref,
    )
    if stock_check["issues"]:
        raise FulfillmentRuleError(f"Stock insuficiente en el deposito actual para reasignar la entrega: {stock_check['issues']}")

    release_inventory_reservation(
        source_type="delivery_order",
        source_ref=str(delivery.id),
        actor=actor,
        idempotency_key=f"{idempotency_key}:release",
        target_stock_state=StockState.PACKED,
    )
    reserved_by_line: dict = defaultdict(lambda: ZERO)
    fulfillment_lines_by_id: dict = {}
    for line in delivery_lines:
        fulfillment_lines_by_id[line.fulfillment_line_id] = line.fulfillment_line
        reserved_by_line[line.fulfillment_line_id] += line.planned_qty
    now = timezone.now()
    for line_id, fulfillment_line in fulfillment_lines_by_id.items():
        fulfillment_line.reserved_qty = max(ZERO, fulfillment_line.reserved_qty - reserved_by_line[line_id])
        fulfillment_line.updated_by = actor
        fulfillment_line.updated_at = now
    FulfillmentOrderLine.objects.bulk_update(
        fulfillment_lines_by_id.values(),
        ["reserved_qty", "updated_by", "updated_at"],
    )

    _apply_delivery_warehouse(delivery, target_warehouse_ref, actor)
    confirmed = validate_delivery_stock(
        delivery_id=delivery_id,
        idempotency_key=f"{idempotency_key}:confirm",
        actor=actor,
        authorized_warehouses=[target_warehouse_ref],
        target_warehouse_ref=target_warehouse_ref,
    )
    result = IdempotentResult(confirmed.payload, confirmed.status)
    return _finish_idempotent_command(idempotency, result)


@transaction.atomic
def send_delivery_to_prepare(
    *,
    delivery_id: str,
    idempotency_key: str,
    actor: str,
    assigned_employee_ref: str = "",
    notes: str = "",
    authorized_warehouses=None,
) -> IdempotentResult:
    command_payload = {
        "delivery_id": delivery_id,
        "assigned_employee_ref": assigned_employee_ref,
        "notes": notes,
    }
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="delivery.send_to_prepare",
        reference_type="delivery_order",
        reference_id=delivery_id,
        payload=command_payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)

    delivery = DeliveryOrder.objects.select_for_update().select_related("fulfillment").prefetch_related("lines__fulfillment_line").get(id=delivery_id)
    _ensure_warehouse_authorized(delivery.warehouse_ref, authorized_warehouses)
    physical_lines = _physical_delivery_lines_for_delivery(delivery)
    for line in physical_lines:
        _ensure_warehouse_authorized(line.warehouse_ref or delivery.warehouse_ref, authorized_warehouses)
    if delivery.status not in [DeliveryOrder.DeliveryStatus.CONFIRMED, DeliveryOrder.DeliveryStatus.PREPARING]:
        raise FulfillmentRuleError("La entrega debe estar confirmada para enviarse a preparar.")
    if not _active_delivery_reservations().filter(
        source_type="delivery_order",
        source_ref=str(delivery.id),
        status=InventoryReservation.ReservationStatus.ALLOCATED,
    ).exists():
        raise FulfillmentRuleError("La entrega debe tener reserva de inventario antes de prepararse.")

    assigned_employee_ref = (assigned_employee_ref or actor).strip()
    task = DeliveryPreparationTask.objects.select_for_update().filter(delivery=delivery).first()
    created = False
    if task is None:
        if not assigned_employee_ref:
            raise FulfillmentRuleError("assigned_employee_ref es obligatorio para crear la tarea de preparacion.")
        task = DeliveryPreparationTask.objects.create(
            delivery=delivery,
            status=DeliveryPreparationTask.TaskStatus.ASSIGNED,
            assigned_to=assigned_employee_ref,
            assigned_at=timezone.now(),
            notes=notes,
            legacy_sales_order_number=delivery.legacy_sales_order_number,
            legacy_transaction_number=delivery.legacy_transaction_number,
            warehouse_ref=delivery.warehouse_ref,
            store_ref=delivery.store_ref,
            created_by=actor,
        )
        created = True
    elif assigned_employee_ref or notes:
        if task.status in [DeliveryPreparationTask.TaskStatus.PREPARED, DeliveryPreparationTask.TaskStatus.CANCELLED]:
            raise FulfillmentRuleError("La tarea de preparacion no puede reasignarse en su estado actual.")
        if assigned_employee_ref:
            task.assigned_to = assigned_employee_ref
            task.assigned_at = task.assigned_at or timezone.now()
            task.status = DeliveryPreparationTask.TaskStatus.ASSIGNED
        if notes:
            task.notes = notes
        task.updated_by = actor
        task.save(update_fields=["assigned_to", "assigned_at", "status", "notes", "updated_by", "updated_at"])

    try:
        move_reserved_inventory_to_preparation(
            source_type="delivery_order",
            source_ref=str(delivery.id),
            actor=actor,
            idempotency_key=f"{idempotency_key}:inventory",
        )
    except (InventoryRuleError, InventoryReservation.DoesNotExist) as exc:
        raise FulfillmentRuleError(str(exc)) from exc

    from_status = delivery.status
    delivery.status = DeliveryOrder.DeliveryStatus.PREPARING
    delivery.updated_by = actor
    delivery.save(update_fields=["status", "updated_by", "updated_at"])
    fulfillment = delivery.fulfillment
    if fulfillment.status in [FulfillmentOrder.FulfillmentStatus.PENDING, FulfillmentOrder.FulfillmentStatus.ALLOCATED]:
        fulfillment.status = FulfillmentOrder.FulfillmentStatus.PREPARING
        fulfillment.updated_by = actor
        fulfillment.save(update_fields=["status", "updated_by", "updated_at"])
    StatusHistory.objects.create(
        entity_type="delivery_order",
        entity_id=str(delivery.id),
        from_status=from_status,
        to_status=delivery.status,
        actor=actor,
        reason="Envio a preparacion",
        payload={"preparation_task_id": str(task.id)},
    )
    result = IdempotentResult({"result": _serialize_delivery(delivery), "preparation_task": _serialize_task(task)}, 201 if created else 200)
    return _finish_idempotent_command(idempotency, result)


@transaction.atomic
def mark_preparation_task_prepared(
    *,
    task_id: str,
    idempotency_key: str,
    actor: str,
    notes: str = "",
    authorized_warehouses=None,
) -> IdempotentResult:
    command_payload = {"task_id": task_id, "notes": notes}
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="preparation_task.mark_prepared",
        reference_type="preparation_task",
        reference_id=task_id,
        payload=command_payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)

    task = DeliveryPreparationTask.objects.select_for_update().select_related("delivery", "delivery__fulfillment").get(id=task_id)
    delivery = DeliveryOrder.objects.select_for_update().prefetch_related("lines__fulfillment_line").get(id=task.delivery_id)
    _ensure_warehouse_authorized(delivery.warehouse_ref, authorized_warehouses)
    physical_lines = _physical_delivery_lines_for_delivery(delivery)
    for line in physical_lines:
        _ensure_warehouse_authorized(line.warehouse_ref or delivery.warehouse_ref, authorized_warehouses)
    if task.status == DeliveryPreparationTask.TaskStatus.PREPARED:
        result = IdempotentResult({"result": _serialize_delivery(delivery), "preparation_task": _serialize_task(task)})
        return _finish_idempotent_command(idempotency, result)
    if task.status == DeliveryPreparationTask.TaskStatus.CANCELLED:
        raise FulfillmentRuleError("La tarea de preparacion esta cancelada.")
    if delivery.status != DeliveryOrder.DeliveryStatus.PREPARING:
        raise FulfillmentRuleError("La entrega debe estar en preparacion para marcarla preparada.")
    if task.assigned_to.strip().casefold() != actor.strip().casefold():
        raise FulfillmentAuthorizationError("Solo el encargado asignado puede marcar la tarea como preparada.")

    try:
        pack_reserved_inventory(
            source_type="delivery_order",
            source_ref=str(delivery.id),
            actor=actor,
            idempotency_key=f"{idempotency_key}:inventory",
        )
    except (InventoryRuleError, InventoryReservation.DoesNotExist) as exc:
        raise FulfillmentRuleError(str(exc)) from exc

    fulfillment_lines_by_id: dict = {}
    planned_by_line: dict = defaultdict(lambda: ZERO)
    for line in physical_lines:
        fulfillment_lines_by_id[line.fulfillment_line_id] = line.fulfillment_line
        planned_by_line[line.fulfillment_line_id] += line.planned_qty
    now = timezone.now()
    for line_id, fulfillment_line in fulfillment_lines_by_id.items():
        planned_qty = planned_by_line[line_id]
        fulfillment_line.reserved_qty = max(Decimal("0"), fulfillment_line.reserved_qty - planned_qty)
        fulfillment_line.prepared_qty += planned_qty
        fulfillment_line.updated_by = actor
        fulfillment_line.updated_at = now
    FulfillmentOrderLine.objects.bulk_update(
        fulfillment_lines_by_id.values(),
        ["reserved_qty", "prepared_qty", "updated_by", "updated_at"],
    )

    task.status = DeliveryPreparationTask.TaskStatus.PREPARED
    task.prepared_by = actor
    task.prepared_at = timezone.now()
    if notes:
        task.notes = notes
    task.updated_by = actor
    task.save(update_fields=["status", "prepared_by", "prepared_at", "notes", "updated_by", "updated_at"])

    from_status = delivery.status
    delivery.status = DeliveryOrder.DeliveryStatus.PREPARED
    delivery.updated_by = actor
    delivery.save(update_fields=["status", "updated_by", "updated_at"])
    fulfillment = delivery.fulfillment
    fulfillment.status = FulfillmentOrder.FulfillmentStatus.READY_FOR_DISPATCH
    fulfillment.updated_by = actor
    fulfillment.save(update_fields=["status", "updated_by", "updated_at"])
    StatusHistory.objects.create(
        entity_type="delivery_order",
        entity_id=str(delivery.id),
        from_status=from_status,
        to_status=delivery.status,
        actor=actor,
        reason="Entrega preparada",
        payload={"preparation_task_id": str(task.id)},
    )
    result = IdempotentResult({"result": _serialize_delivery(delivery), "preparation_task": _serialize_task(task)})
    return _finish_idempotent_command(idempotency, result)


def delivery_uses_reparto_flow(delivery: DeliveryOrder) -> bool:
    if is_shipping_delivery_mode(delivery.delivery_mode):
        return True
    return _delivery_route_assignment(str(delivery.id)) is not None


def _delivery_route_assignment(delivery_id: str) -> dict | None:
    try:
        from apps.routes.models import RouteSheet, RouteStop, RouteStopLine

        route_stop = (
            RouteStop.objects.select_related("route")
            .filter(source_type="delivery_order", source_ref=str(delivery_id))
            .exclude(route__status=RouteSheet.RouteStatus.CANCELLED)
            .exclude(status=RouteStop.StopStatus.CANCELLED)
            .order_by("-route__created_at")
            .first()
        )
        if route_stop is None:
            route_line = (
                RouteStopLine.objects.select_related("stop", "stop__route")
                .filter(delivery_ref=str(delivery_id))
                .exclude(stop__route__status=RouteSheet.RouteStatus.CANCELLED)
                .exclude(stop__status=RouteStop.StopStatus.CANCELLED)
                .order_by("-stop__route__created_at")
                .first()
            )
            route_stop = route_line.stop if route_line else None
        if route_stop is None:
            return None
        return {
            "id": str(route_stop.route_id),
            "route_number": route_stop.route.route_number,
            "status": route_stop.route.status,
            "stop_id": str(route_stop.id),
            "stop_status": route_stop.status,
        }
    except Exception:
        return None


@transaction.atomic
def issue_remito(
    *,
    delivery_id: str,
    idempotency_key: str,
    actor: str,
    authorized_warehouses=None,
    allow_route_delivery: bool = False,
) -> IdempotentResult:
    command_payload = {"delivery_id": delivery_id}
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type="delivery.issue_remito",
        reference_type="delivery_order",
        reference_id=delivery_id,
        payload=command_payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)

    delivery = DeliveryOrder.objects.select_for_update().select_related("fulfillment").prefetch_related("lines__fulfillment_line").get(id=delivery_id)
    _ensure_warehouse_authorized(delivery.warehouse_ref, authorized_warehouses)
    delivery_lines = physical_delivery_lines(list(delivery.lines.all()))
    for line in delivery_lines:
        _ensure_warehouse_authorized(line.warehouse_ref or delivery.warehouse_ref, authorized_warehouses)

    route_assignment = _delivery_route_assignment(str(delivery.id))
    if route_assignment and not allow_route_delivery:
        raise FulfillmentRuleError(
            f"La entrega pertenece a la hoja de ruta {route_assignment['route_number']}; debe entregarse desde Ejecucion chofer."
        )

    existing = delivery.documents.filter(document_type=DeliveryDocument.DocumentType.REMITO).first()
    if existing:
        result = IdempotentResult({"result": _serialize_document(existing)})
        return _finish_idempotent_command(idempotency, result)
    is_reparto = delivery_uses_reparto_flow(delivery)
    allowed_statuses = [DeliveryOrder.DeliveryStatus.PREPARED]
    if is_reparto:
        allowed_statuses.extend([DeliveryOrder.DeliveryStatus.ASSIGNED, DeliveryOrder.DeliveryStatus.LOADED])
    if delivery.status not in allowed_statuses:
        raise FulfillmentRuleError("El remito solo se puede emitir para una entrega preparada o asignada a reparto.")
    document = DeliveryDocument.objects.create(
        delivery=delivery,
        document_number=allocate_sequence_number(REMITO_SEQUENCE_NAME, actor=actor),
        document_type=DeliveryDocument.DocumentType.REMITO,
        status=DeliveryDocument.DocumentStatus.OPEN if is_reparto else DeliveryDocument.DocumentStatus.CLOSED,
        issued_at=timezone.now(),
        customer_ref=delivery.fulfillment.customer_ref,
        address_snapshot=delivery.address_snapshot,
        payload=_serialize_delivery(delivery),
        legacy_sales_order_number=delivery.legacy_sales_order_number,
        legacy_transaction_number=delivery.legacy_transaction_number,
        warehouse_ref=delivery.warehouse_ref,
        created_by=actor,
    )
    for line in [line for line in delivery_lines if line.planned_qty > ZERO]:
        DeliveryDocumentLine.objects.create(
            document=document,
            delivery_line=line,
            item_ref=line.item_ref,
            quantity=line.planned_qty,
            delivery_unit_qty=_delivery_line_operational_qty(line),
            delivery_uom=line.delivery_uom,
            conversion_factor=line.conversion_factor,
            uom=line.uom,
            item_snapshot=line.item_snapshot,
            planned_weight_kg=line.planned_weight_kg,
            planned_volume_m3=line.planned_volume_m3,
            legacy_sales_order_number=line.legacy_sales_order_number,
            legacy_transaction_number=line.legacy_transaction_number,
            legacy_line_id=line.legacy_line_id,
            legacy_line_rec_id=line.legacy_line_rec_id,
            warehouse_ref=line.warehouse_ref,
            created_by=actor,
        )
    if is_reparto:
        StatusHistory.objects.create(
            entity_type="delivery_document",
            entity_id=str(document.id),
            from_status="",
            to_status=document.status,
            actor=actor,
            reason="Remito abierto para reparto",
            payload={"delivery_id": str(delivery.id)},
        )
        AuditTrail.objects.create(
            entity_type="delivery_document",
            entity_id=str(document.id),
            action="opened",
            actor=actor,
            after={"document_number": document.document_number, "delivery_id": str(delivery.id), "route_flow": True},
        )
        result = IdempotentResult({"result": _serialize_document(document)}, 201)
        return _finish_idempotent_command(idempotency, result)

    for index, line in enumerate([line for line in delivery_lines if line.planned_qty > ZERO], start=1):
        qty_to_dispatch = max(Decimal("0"), line.planned_qty - line.delivered_qty)
        if qty_to_dispatch <= 0:
            continue
        try:
            move_prepared_stock_to_state(
                warehouse_ref=line.warehouse_ref or delivery.warehouse_ref,
                item_ref=line.item_ref,
                quantity=qty_to_dispatch,
                uom=line.uom,
                to_state=StockState.DELIVERED,
                target_location_purpose="transit",
                source_type="delivery_order",
                source_ref=str(delivery.id),
                document_type="delivery_document",
                document_ref=str(document.id),
                actor=actor,
                idempotency_key=f"{idempotency_key}:dispatch:{index}",
                reason="Remito de entrega",
                legacy_sales_order_number=line.legacy_sales_order_number,
                legacy_line_id=line.legacy_line_id,
            )
        except InventoryRuleError as exc:
            raise FulfillmentRuleError(str(exc)) from exc

        line.delivered_qty += qty_to_dispatch
        line.updated_by = actor
        line.save(update_fields=["delivered_qty", "updated_by", "updated_at"])

        fulfillment_line = line.fulfillment_line
        fulfillment_line.prepared_qty = max(Decimal("0"), fulfillment_line.prepared_qty - qty_to_dispatch)
        fulfillment_line.delivered_qty = min(fulfillment_line.ordered_qty, fulfillment_line.delivered_qty + qty_to_dispatch)
        fulfillment_line.updated_by = actor
        fulfillment_line.save(update_fields=["prepared_qty", "delivered_qty", "updated_by", "updated_at"])

    from_status = delivery.status
    delivery.status = DeliveryOrder.DeliveryStatus.DELIVERED_COMPLETE
    delivery.updated_by = actor
    delivery.save(update_fields=["status", "updated_by", "updated_at"])
    fulfillment = delivery.fulfillment
    has_pending = any(line.delivered_qty < line.ordered_qty for line in physical_fulfillment_lines(list(fulfillment.lines.all())))
    fulfillment.status = (
        FulfillmentOrder.FulfillmentStatus.PARTIALLY_DELIVERED
        if has_pending
        else FulfillmentOrder.FulfillmentStatus.DELIVERED
    )
    fulfillment.updated_by = actor
    fulfillment.save(update_fields=["status", "updated_by", "updated_at"])
    StatusHistory.objects.create(
        entity_type="delivery_order",
        entity_id=str(delivery.id),
        from_status=from_status,
        to_status=delivery.status,
        actor=actor,
        reason="Remito emitido",
        payload={"document_id": str(document.id)},
    )
    AuditTrail.objects.create(
        entity_type="delivery_document",
        entity_id=str(document.id),
        action="issued",
        actor=actor,
        after={"document_number": document.document_number, "delivery_id": str(delivery.id)},
    )
    result = IdempotentResult({"result": _serialize_document(document)}, 201)
    return _finish_idempotent_command(idempotency, result)


def _serialize_document(document: DeliveryDocument) -> dict:
    document = DeliveryDocument.objects.prefetch_related("lines").select_related("delivery").get(id=document.id)
    document_lines = list(document.lines.all())

    def serialize_document_line(line: DeliveryDocumentLine) -> dict:
        snapshot = _with_display_uom(line.item_snapshot or {}, fallback_uom=line.uom)
        return {
            "id": str(line.id),
            "item_ref": line.item_ref,
            "quantity": str(line.quantity),
            "delivery_unit_qty": str(line.delivery_unit_qty),
            "delivery_uom": _display_uom(line.delivery_uom or snapshot.get("delivery_uom") or ""),
            "conversion_factor": str(line.conversion_factor),
            "uom": snapshot.get("sales_uom") or _display_uom(line.uom),
            "legacy_line_id": line.legacy_line_id,
            "item_snapshot": snapshot,
            "planned_weight_kg": str(line.planned_weight_kg),
            "planned_volume_m3": str(line.planned_volume_m3),
        }

    return {
        "id": str(document.id),
        "document_number": document.document_number,
        "document_type": document.document_type,
        "status": document.status,
        "issued_at": document.issued_at.isoformat(),
        "delivery_id": str(document.delivery_id),
        "sales_order_number": document.legacy_sales_order_number,
        "address_snapshot": document.address_snapshot,
        "lines": [serialize_document_line(line) for line in document_lines],
        "totals": {
            "delivery_unit_qty": str(_quantize_qty(sum((line.delivery_unit_qty for line in document_lines), ZERO))),
            "commercial_qty": str(_quantize_qty(sum((line.quantity for line in document_lines), ZERO))),
            "planned_weight_kg": str(_quantize_qty(sum((line.planned_weight_kg for line in document_lines), ZERO))),
            "planned_volume_m3": str(_quantize_qty(sum((line.planned_volume_m3 for line in document_lines), ZERO))),
        },
    }


FULFILLMENT_PENDING_DELIVERY_STATUSES = {
    FulfillmentOrder.FulfillmentStatus.PENDING,
    FulfillmentOrder.FulfillmentStatus.ALLOCATED,
    FulfillmentOrder.FulfillmentStatus.PREPARING,
    FulfillmentOrder.FulfillmentStatus.READY_FOR_DISPATCH,
    FulfillmentOrder.FulfillmentStatus.PARTIALLY_DELIVERED,
    FulfillmentOrder.FulfillmentStatus.RESCHEDULED,
}


def _legacy_orders_for_expedition_search(
    *,
    sales_order_number: str = "",
    customer_refs: set[str] | None = None,
    limit: int = 100,
) -> list[LegacyOrder]:
    sales_order_candidates = _lookup_candidates(sales_order_number)
    try:
        queryset = LegacyOrder.objects.using("litecore").filter(invoice_number__gt="", invoice_date__isnull=False).filter(
            Q(sales_order_type__iexact=LEGACY_ORDER_TYPE_DELIVERABLE)
            | Q(sales_order_type__isnull=True)
            | Q(sales_order_type="")
        )
        if sales_order_number:
            queryset = queryset.filter(
                Q(sales_order_number__in=sales_order_candidates)
                | Q(transaction_number__in=sales_order_candidates)
                | Q(invoice_number__in=sales_order_candidates)
            )
        elif customer_refs:
            queryset = queryset.filter(
                Q(customer_account__in=customer_refs)
                | Q(invoice_customer_account_number__in=customer_refs)
            )
        else:
            return []
        return list(queryset.order_by("-invoice_date", "-modified_datetime")[:limit])
    except Exception:
        return []


def _ensure_legacy_orders_available_for_expedition(
    *,
    sales_order_number: str = "",
    customer_refs: set[str] | None = None,
    actor: str = "expedition.search",
) -> set[str]:
    available_order_numbers: set[str] = set()
    for order in _legacy_orders_for_expedition_search(
        sales_order_number=sales_order_number,
        customer_refs=customer_refs,
    ):
        order_number = str(order.sales_order_number or "").strip()
        if not order_number:
            continue
        available_order_numbers.add(order_number)
        if FulfillmentOrder.objects.filter(legacy_sales_order_number=order_number).exists():
            continue
        source_version = str(order.modified_datetime or order.invoice_date or "")
        source_hash = hashlib.sha1(source_version.encode("utf-8")).hexdigest()[:10]
        try:
            ingest_legacy_order(
                sales_order_number=order_number,
                idempotency_key=f"expedition-search:{order_number}:{source_hash}",
                actor=actor,
            )
        except Exception:
            continue
    return available_order_numbers


def _lookup_candidates(value: str) -> list[str]:
    cleaned = str(value or "").strip()
    if not cleaned:
        return []
    candidates = [cleaned, cleaned.upper(), cleaned.lower()]
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def expedition_queue(
    *,
    sales_order_number: str = "",
    customer_ref: str = "",
    customer_dni: str = "",
    authorized_warehouses: list[str] | tuple[str, ...] | set[str] | None = None,
    target_warehouse_ref: str = "",
) -> list[dict]:
    sales_order_number = sales_order_number.strip()
    customer_ref = customer_ref.strip()
    customer_dni = customer_dni.strip()
    target_warehouse_ref = _target_warehouse(target_warehouse_ref)
    authorized_warehouse_set = (
        None
        if authorized_warehouses is None
        else {str(warehouse).strip() for warehouse in authorized_warehouses if str(warehouse).strip()}
    )

    if not (sales_order_number or customer_ref or customer_dni):
        return []
    if authorized_warehouses is not None and not authorized_warehouse_set:
        return []

    customer_refs = set(_lookup_candidates(customer_ref)) if customer_ref else set()
    if customer_dni:
        customer_refs.update(customer_refs_for_dni(customer_dni))
        if not customer_refs:
            return []

    filters = Q()
    sales_order_candidates = _lookup_candidates(sales_order_number)
    if sales_order_number:
        filters &= (
            Q(legacy_sales_order_number__in=sales_order_candidates)
            | Q(legacy_transaction_number__in=sales_order_candidates)
            | Q(fulfillment_number__in=sales_order_candidates)
        )
    if customer_refs:
        filters &= Q(customer_ref__in=customer_refs)

    def fulfillment_queryset():
        queryset = (
            FulfillmentOrder.objects.prefetch_related(
                "lines",
                "deliveries__lines__fulfillment_line",
                "deliveries__documents",
                "deliveries__executions",
                "deliveries__preparation_task",
                "impacts__lines",
            )
            .filter(filters)
            .order_by("-updated_at", "-created_at")
        )
        if authorized_warehouse_set is not None:
            queryset = queryset.filter(warehouse_ref__in=authorized_warehouse_set)
        return queryset

    fulfillment_qs = fulfillment_queryset()
    fulfillments = list(fulfillment_qs[:100])
    if not fulfillments:
        fallback_order_numbers = _ensure_legacy_orders_available_for_expedition(
            sales_order_number=sales_order_number,
            customer_refs=customer_refs if not sales_order_number else None,
        )
        if sales_order_number and fallback_order_numbers:
            filters |= Q(legacy_sales_order_number__in=fallback_order_numbers)
        fulfillments = list(fulfillment_queryset()[:100])

    if fulfillments:
        processed_impacts = refresh_legacy_impacts_for_fulfillments(fulfillments, actor="expedition.search")
        if processed_impacts:
            fulfillments = list(fulfillment_queryset()[:100])

    lines = [
        line
        for fulfillment in fulfillments
        for line in list(fulfillment.lines.all())
    ]
    metrics = _line_metrics(lines, target_warehouse_ref=target_warehouse_ref)
    customers = _resolve_customer_snapshots({fulfillment.customer_ref for fulfillment in fulfillments})
    item_snapshots = _resolve_line_item_snapshots(lines)
    movement_context = _build_movement_context(fulfillments)
    return [
        _serialize_fulfillment(
            fulfillment,
            line_metrics=metrics,
            customer_snapshot=customers.get(fulfillment.customer_ref),
            item_snapshots=item_snapshots,
            movement_context=movement_context,
            target_warehouse_ref=target_warehouse_ref,
        )
        for fulfillment in fulfillments
    ]

def build_remito_pdf(document: DeliveryDocument) -> bytes:
    document = DeliveryDocument.objects.select_related("delivery", "delivery__fulfillment").prefetch_related("lines").get(id=document.id)

    def document_line_parts(line: DeliveryDocumentLine) -> list[str]:
        snapshot = _with_display_uom(line.item_snapshot or {}, fallback_uom=line.uom)
        delivery_uom = _display_uom(line.delivery_uom or snapshot.get("delivery_uom") or "un")
        sales_uom = snapshot.get("sales_uom") or _display_uom(line.uom)
        return [
            line.item_ref,
            _clean(snapshot.get("name")),
            f"{line.delivery_unit_qty.normalize()} {delivery_uom}",
            f"equiv. {line.quantity.normalize()} {sales_uom}",
            f"{line.planned_weight_kg.normalize()} kg",
            f"{line.planned_volume_m3.normalize()} m3",
            f"Legacy line {line.legacy_line_id}",
        ]

    lines = [
        f"Remito de entrega {document.document_number}",
        f"Pedido: {document.legacy_sales_order_number} / Transaccion: {document.legacy_transaction_number}",
        f"Cliente: {document.customer_ref}",
        f"Warehouse: {document.warehouse_ref} / Entrega: {document.delivery.delivery_number}",
        f"Emitido: {document.issued_at:%Y-%m-%d %H:%M}",
        "Lineas despachadas:",
    ]
    lines.extend(
        " - ".join(
            part
            for part in document_line_parts(line)
            if part
        )
        for line in document.lines.all()
        if line.quantity > 0
    )

    content = "\n".join(
        f"BT {'/F2 16 Tf' if index == 0 else '/F1 9 Tf'} 50 {800 - index * 18} Td ({_pdf_escape(line)}) Tj ET"
        for index, line in enumerate(lines[:38])
    )
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
    ]
    pdf = "%PDF-1.4\n"
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n{obj}\nendobj\n"
    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n"
    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
    return pdf.encode("latin-1", errors="ignore")


def _pdf_escape(value: str) -> str:
    normalized = value.encode("ascii", "ignore").decode("ascii")
    return normalized.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
