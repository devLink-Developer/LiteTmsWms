from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction

from apps.core.models import AuditTrail, DomainEventOutbox, IdempotencyKey
from apps.logistics.models import WarehouseLocation, WarehouseMaster


class LogisticsRuleError(ValueError):
    pass


@dataclass(frozen=True)
class LogisticsCommandResult:
    payload: dict
    status: int = 200


DEFAULT_LOCATION_SPECS = [
    ("available", "DSP", "GEN", "Disponible entrega", True, False, True, False),
    ("reserved", "RSV", "GEN", "Reservado", False, True, False, False),
    ("preparation", "PRE", "GEN", "En preparacion", False, False, True, False),
    ("transit", "TRN", "GEN", "Transito / carga", False, False, False, False),
    ("breakage", "BAJ", "ROT", "Baja rotura", False, False, False, True),
    ("loss", "BAJ", "PER", "Baja perdida", False, False, False, True),
]


def _clean(value) -> str:
    return str(value or "").strip()


def _bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return _clean(value).casefold() in {"1", "true", "t", "yes", "y", "si", "s"}


def _int(value, default: int = 0, *, maximum: int = 200) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 0), maximum)


def _request_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _start_idempotent_command(
    *,
    key: str,
    operation_type: str,
    reference_type: str,
    reference_id: str,
    payload: dict,
) -> tuple[IdempotencyKey, bool]:
    request_hash = _request_hash(payload)
    existing = IdempotencyKey.objects.filter(key=key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise LogisticsRuleError("La Idempotency-Key ya fue usada con otro payload.")
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


def _finish_idempotent_command(record: IdempotencyKey, result: LogisticsCommandResult) -> LogisticsCommandResult:
    record.response_payload = result.payload
    record.response_status = result.status
    record.status = IdempotencyKey.ProcessingStatus.SUCCEEDED
    record.save(update_fields=["response_payload", "response_status", "status", "updated_at"])
    return result


def default_location_ref(warehouse_ref: str, purpose: str) -> str:
    wh = _clean(warehouse_ref).upper()
    purpose_map = {
        "available": "DSP-GEN",
        "reserved": "RSV-GEN",
        "preparation": "PRE-GEN",
        "transit": "TRN-GEN",
        "breakage": "BAJ-ROT",
        "loss": "BAJ-PER",
    }
    suffix = purpose_map.get(purpose)
    if not wh or not suffix:
        raise LogisticsRuleError("Ubicacion default invalida.")
    return f"{wh}-{suffix}"


def serialize_location(location: WarehouseLocation) -> dict:
    return {
        "id": str(location.id),
        "warehouse_ref": location.warehouse_ref,
        "location_ref": location.location_ref,
        "location_name": location.name,
        "name": location.name,
        "location_type": location.location_type,
        "purpose": location.purpose,
        "zone_ref": location.zone_ref,
        "aisle": location.aisle,
        "floor": location.floor,
        "level": location.level,
        "position": location.position,
        "is_dispatchable": location.is_dispatchable,
        "is_reservable": location.is_reservable,
        "is_pickable": location.is_pickable,
        "allows_scrap": location.allows_scrap,
        "system_location": location.system_location,
        "generated": location.generated,
        "active": location.active,
        "sort_order": location.sort_order,
        "created_at": location.created_at.isoformat() if location.created_at else None,
        "updated_at": location.updated_at.isoformat() if location.updated_at else None,
    }


def serialize_warehouse(warehouse: WarehouseMaster, *, include_locations: bool = False) -> dict:
    payload = {
        "id": str(warehouse.id),
        "warehouse_ref": warehouse.warehouse_ref,
        "warehouse_code": warehouse.warehouse_ref,
        "warehouse_name": warehouse.name,
        "name": warehouse.name,
        "warehouse_type": warehouse.warehouse_type,
        "branch_ref": warehouse.branch_ref,
        "store_ref": warehouse.store_ref,
        "store_code": warehouse.store_ref,
        "store_name": warehouse.store_name,
        "is_pickup_allowed": warehouse.is_pickup_allowed,
        "is_shipping_allowed": warehouse.is_shipping_allowed,
        "active": warehouse.active,
        "default_available_location_ref": warehouse.default_available_location_ref,
        "default_reserved_location_ref": warehouse.default_reserved_location_ref,
        "default_preparation_location_ref": warehouse.default_preparation_location_ref,
        "default_transit_location_ref": warehouse.default_transit_location_ref,
        "default_breakage_location_ref": warehouse.default_breakage_location_ref,
        "default_loss_location_ref": warehouse.default_loss_location_ref,
        "source_system": warehouse.source_system,
        "created_at": warehouse.created_at.isoformat() if warehouse.created_at else None,
        "updated_at": warehouse.updated_at.isoformat() if warehouse.updated_at else None,
    }
    if include_locations:
        payload["locations"] = [
            serialize_location(location)
            for location in WarehouseLocation.objects.filter(warehouse_ref=warehouse.warehouse_ref).order_by("sort_order", "location_ref")
        ]
    return payload


def _warehouse_payload(payload: dict, *, existing: WarehouseMaster | None = None) -> dict:
    warehouse_ref = _clean(payload.get("warehouse_ref") or payload.get("warehouse_code") or (existing.warehouse_ref if existing else "")).upper()
    if not warehouse_ref:
        raise LogisticsRuleError("El codigo de almacen es obligatorio.")
    name = _clean(payload.get("name") or payload.get("warehouse_name") or (existing.name if existing else warehouse_ref))
    return {
        "warehouse_ref": warehouse_ref,
        "name": name,
        "warehouse_type": _clean(payload.get("warehouse_type") if "warehouse_type" in payload else existing.warehouse_type if existing else ""),
        "branch_ref": _clean(payload.get("branch_ref") if "branch_ref" in payload else existing.branch_ref if existing else ""),
        "store_ref": _clean(payload.get("store_ref") or payload.get("store_code") or (existing.store_ref if existing else "")),
        "store_name": _clean(payload.get("store_name") if "store_name" in payload else existing.store_name if existing else ""),
        "is_pickup_allowed": _bool(payload.get("is_pickup_allowed"), existing.is_pickup_allowed if existing else False),
        "is_shipping_allowed": _bool(payload.get("is_shipping_allowed"), existing.is_shipping_allowed if existing else True),
        "active": _bool(payload.get("active"), existing.active if existing else True),
        "source_system": _clean(payload.get("source_system") if "source_system" in payload else existing.source_system if existing else "tmswms") or "tmswms",
        "payload": payload.get("payload") if isinstance(payload.get("payload"), dict) else existing.payload if existing else {},
    }


def _location_defaults(warehouse_ref: str) -> dict[str, str]:
    return {
        "default_available_location_ref": default_location_ref(warehouse_ref, "available"),
        "default_reserved_location_ref": default_location_ref(warehouse_ref, "reserved"),
        "default_preparation_location_ref": default_location_ref(warehouse_ref, "preparation"),
        "default_transit_location_ref": default_location_ref(warehouse_ref, "transit"),
        "default_breakage_location_ref": default_location_ref(warehouse_ref, "breakage"),
        "default_loss_location_ref": default_location_ref(warehouse_ref, "loss"),
    }


def _upsert_location(*, warehouse_ref: str, location_ref: str, actor: str, defaults: dict[str, Any]) -> WarehouseLocation:
    location, created = WarehouseLocation.objects.get_or_create(
        warehouse_ref=warehouse_ref,
        location_ref=location_ref,
        defaults={**defaults, "created_by": actor, "updated_by": actor},
    )
    if not created:
        changed = False
        for key, value in defaults.items():
            if getattr(location, key) != value:
                setattr(location, key, value)
                changed = True
        if changed:
            location.updated_by = actor
            location.save()
    return location


@transaction.atomic
def generate_default_locations(*, warehouse_ref: str, actor: str, layout: dict | None = None) -> list[WarehouseLocation]:
    wh = _clean(warehouse_ref).upper()
    if not wh:
        raise LogisticsRuleError("warehouse_ref es obligatorio.")
    created_locations: list[WarehouseLocation] = []
    for sort_order, (purpose, area, suffix, name, dispatchable, reservable, pickable, scrap) in enumerate(DEFAULT_LOCATION_SPECS, start=10):
        location_ref = f"{wh}-{area}-{suffix}"
        created_locations.append(
            _upsert_location(
                warehouse_ref=wh,
                location_ref=location_ref,
                actor=actor,
                defaults={
                    "name": name,
                    "location_type": "system",
                    "purpose": purpose,
                    "zone_ref": area,
                    "is_dispatchable": dispatchable,
                    "is_reservable": reservable,
                    "is_pickable": pickable,
                    "allows_scrap": scrap,
                    "system_location": True,
                    "generated": True,
                    "active": True,
                    "sort_order": sort_order,
                    "payload": {},
                },
            )
        )

    layout = layout if isinstance(layout, dict) else {}
    zones = _int(layout.get("zones"), 0, maximum=20)
    aisles = _int(layout.get("aisles"), 0, maximum=100)
    floors = _int(layout.get("floors"), 1, maximum=20) or 1
    levels = _int(layout.get("levels"), 0, maximum=20)
    positions = _int(layout.get("positions"), _int(layout.get("positions_per_level"), 0), maximum=500)
    if zones and aisles and levels and positions:
        sort_order = 1000
        for zone in range(1, zones + 1):
            for aisle in range(1, aisles + 1):
                for floor in range(1, floors + 1):
                    for level in range(1, levels + 1):
                        for position in range(1, positions + 1):
                            location_ref = f"{wh}-DSP-Z{zone:02d}-A{aisle:02d}-F{floor:02d}-N{level:02d}-P{position:03d}"
                            created_locations.append(
                                _upsert_location(
                                    warehouse_ref=wh,
                                    location_ref=location_ref,
                                    actor=actor,
                                    defaults={
                                        "name": location_ref,
                                        "location_type": "rack",
                                        "purpose": "available",
                                        "zone_ref": f"Z{zone:02d}",
                                        "aisle": f"A{aisle:02d}",
                                        "floor": f"F{floor:02d}",
                                        "level": f"N{level:02d}",
                                        "position": f"P{position:03d}",
                                        "is_dispatchable": True,
                                        "is_reservable": False,
                                        "is_pickable": True,
                                        "allows_scrap": False,
                                        "system_location": False,
                                        "generated": True,
                                        "active": True,
                                        "sort_order": sort_order,
                                        "payload": {"layout": layout},
                                    },
                                )
                            )
                            sort_order += 1
    return created_locations


@transaction.atomic
def upsert_warehouse(*, payload: dict, idempotency_key: str, actor: str, warehouse_ref: str = "") -> LogisticsCommandResult:
    reference_id = _clean(warehouse_ref or payload.get("warehouse_ref") or payload.get("warehouse_code") or "new").upper()
    operation = "warehouse.update" if warehouse_ref else "warehouse.create"
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type=operation,
        reference_type="warehouse",
        reference_id=reference_id,
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return LogisticsCommandResult(idempotency.response_payload, idempotency.response_status)

    before = {}
    try:
        if warehouse_ref:
            warehouse = WarehouseMaster.objects.select_for_update().get(warehouse_ref=_clean(warehouse_ref).upper())
            before = serialize_warehouse(warehouse)
            data = _warehouse_payload(payload, existing=warehouse)
            if data["warehouse_ref"] != warehouse.warehouse_ref:
                raise LogisticsRuleError("No se puede modificar el codigo del almacen.")
            for key, value in {**data, **_location_defaults(warehouse.warehouse_ref)}.items():
                setattr(warehouse, key, value)
            warehouse.updated_by = actor
            warehouse.save()
            status = 200
            action = "updated"
        else:
            data = _warehouse_payload(payload)
            warehouse = WarehouseMaster.objects.create(**data, **_location_defaults(data["warehouse_ref"]), created_by=actor, updated_by=actor)
            status = 201
            action = "created"
    except WarehouseMaster.DoesNotExist as exc:
        raise LogisticsRuleError("Almacen no encontrado.") from exc
    except IntegrityError as exc:
        raise LogisticsRuleError("Ya existe un almacen con ese codigo.") from exc

    generate_default_locations(warehouse_ref=warehouse.warehouse_ref, actor=actor, layout=payload.get("layout"))
    after = serialize_warehouse(warehouse, include_locations=True)
    AuditTrail.objects.create(entity_type="warehouse", entity_id=str(warehouse.id), action=action, actor=actor, before=before, after=after)
    DomainEventOutbox.objects.create(
        event_type=f"warehouse.{action}",
        aggregate_type="warehouse",
        aggregate_id=str(warehouse.id),
        payload={"warehouse_ref": warehouse.warehouse_ref, "actor": actor},
    )
    return _finish_idempotent_command(idempotency, LogisticsCommandResult({"result": after}, status))


def sync_warehouse_from_master_data_row(row: dict, *, actor: str) -> WarehouseMaster:
    data = _warehouse_payload(
        {
            "warehouse_ref": row.get("warehouse_code") or row.get("warehouse_ref"),
            "name": row.get("warehouse_name") or row.get("name"),
            "warehouse_type": row.get("warehouse_type"),
            "store_ref": row.get("store_code") or row.get("store_ref"),
            "store_name": row.get("store_name"),
            "is_pickup_allowed": row.get("is_pickup_allowed"),
            "is_shipping_allowed": row.get("is_shipping_allowed"),
            "source_system": row.get("source") or "master-data",
            "payload": row,
        }
    )
    warehouse, created = WarehouseMaster.objects.update_or_create(
        warehouse_ref=data["warehouse_ref"],
        defaults={**data, **_location_defaults(data["warehouse_ref"]), "updated_by": actor},
    )
    if created:
        warehouse.created_by = actor
        warehouse.save(update_fields=["created_by", "updated_at"])
    generate_default_locations(warehouse_ref=warehouse.warehouse_ref, actor=actor)
    return warehouse
