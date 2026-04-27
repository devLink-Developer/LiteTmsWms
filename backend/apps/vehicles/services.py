from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils.dateparse import parse_date

from apps.core.models import AuditTrail, DomainEventOutbox, IdempotencyKey, StatusHistory
from apps.fulfillment.services import IdempotentResult
from apps.vehicles.models import Driver, Vehicle, VehicleCapacityProfile


class VehicleRuleError(ValueError):
    pass


ZERO = Decimal("0")


def _decimal(value, default: str = "0") -> Decimal:
    if value in [None, ""]:
        value = default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _clean(value) -> str:
    return str(value or "").strip()


def _bool(value, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return _clean(value).casefold() in {"1", "true", "t", "yes", "y", "si", "s"}


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
            raise VehicleRuleError("La Idempotency-Key ya fue usada con otro payload.")
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


def _status_history(entity_type: str, entity_id: str, from_status: str, to_status: str, actor: str, reason: str, payload=None) -> None:
    if from_status == to_status:
        return
    StatusHistory.objects.create(
        entity_type=entity_type,
        entity_id=entity_id,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        reason=reason,
        payload=payload or {},
    )


def _audit(entity_type: str, entity_id: str, action: str, actor: str, *, before=None, after=None) -> None:
    AuditTrail.objects.create(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
        before=before or {},
        after=after or {},
    )
    DomainEventOutbox.objects.create(
        event_type=f"{entity_type}.{action}",
        aggregate_type=entity_type,
        aggregate_id=entity_id,
        payload={"before": before or {}, "after": after or {}, "actor": actor},
    )


def serialize_capacity_profile(profile: VehicleCapacityProfile) -> dict:
    return {
        "id": str(profile.id),
        "name": profile.name,
        "max_weight_kg": str(profile.max_weight_kg),
        "max_volume_m3": str(profile.max_volume_m3),
        "notes": profile.notes,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def serialize_vehicle(vehicle: Vehicle) -> dict:
    vehicle = Vehicle.objects.select_related("capacity_profile").get(id=vehicle.id)
    return {
        "id": str(vehicle.id),
        "code": vehicle.code,
        "plate": vehicle.plate,
        "description": vehicle.description,
        "status": vehicle.status,
        "capacity_profile_id": str(vehicle.capacity_profile_id),
        "capacity_profile_name": vehicle.capacity_profile.name,
        "max_weight_kg": str(vehicle.capacity_profile.max_weight_kg),
        "max_volume_m3": str(vehicle.capacity_profile.max_volume_m3),
        "branch_ref": vehicle.branch_ref,
        "active": vehicle.active,
        "created_at": vehicle.created_at.isoformat() if vehicle.created_at else None,
        "updated_at": vehicle.updated_at.isoformat() if vehicle.updated_at else None,
    }


def serialize_driver(driver: Driver) -> dict:
    return {
        "id": str(driver.id),
        "code": driver.code,
        "full_name": driver.full_name,
        "document_number": driver.document_number,
        "phone": driver.phone,
        "email": driver.email,
        "license_number": driver.license_number,
        "license_category": driver.license_category,
        "license_expires_at": driver.license_expires_at.isoformat() if driver.license_expires_at else None,
        "status": driver.status,
        "branch_ref": driver.branch_ref,
        "warehouse_ref": driver.warehouse_ref,
        "active": driver.active,
        "notes": driver.notes,
        "created_at": driver.created_at.isoformat() if driver.created_at else None,
        "updated_at": driver.updated_at.isoformat() if driver.updated_at else None,
    }


def _profile_payload(payload: dict) -> dict:
    name = _clean(payload.get("name"))
    max_weight_kg = _decimal(payload.get("max_weight_kg"))
    max_volume_m3 = _decimal(payload.get("max_volume_m3"))
    if not name:
        raise VehicleRuleError("El nombre del perfil es obligatorio.")
    if max_weight_kg <= ZERO or max_volume_m3 <= ZERO:
        raise VehicleRuleError("La capacidad debe ser mayor a cero en peso y volumen.")
    return {
        "name": name,
        "max_weight_kg": max_weight_kg,
        "max_volume_m3": max_volume_m3,
        "notes": _clean(payload.get("notes")),
    }


@transaction.atomic
def upsert_capacity_profile(*, payload: dict, idempotency_key: str, actor: str, profile_id: str = "") -> IdempotentResult:
    operation = "vehicle.profile.update" if profile_id else "vehicle.profile.create"
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type=operation,
        reference_type="vehicle_capacity_profile",
        reference_id=profile_id or payload.get("name", "new"),
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)
    data = _profile_payload(payload)
    before = {}
    try:
        if profile_id:
            profile = VehicleCapacityProfile.objects.select_for_update().get(id=profile_id)
            before = serialize_capacity_profile(profile)
            for key, value in data.items():
                setattr(profile, key, value)
            profile.updated_by = actor
            profile.save()
            status = 200
            action = "updated"
        else:
            profile = VehicleCapacityProfile.objects.create(**data, created_by=actor, updated_by=actor)
            status = 201
            action = "created"
    except IntegrityError as exc:
        raise VehicleRuleError("Ya existe un perfil con ese nombre.") from exc
    after = serialize_capacity_profile(profile)
    _audit("vehicle_capacity_profile", str(profile.id), action, actor, before=before, after=after)
    return _finish_idempotent_command(idempotency, IdempotentResult({"result": after}, status))


def _vehicle_payload(payload: dict, *, existing: Vehicle | None = None) -> dict:
    code = _clean(payload.get("code") if "code" in payload else existing.code if existing else "")
    plate = _clean(payload.get("plate") if "plate" in payload else existing.plate if existing else "").upper()
    capacity_profile_id = _clean(
        payload.get("capacity_profile_id")
        if "capacity_profile_id" in payload
        else str(existing.capacity_profile_id) if existing else ""
    )
    status = _clean(payload.get("status") if "status" in payload else existing.status if existing else Vehicle.VehicleStatus.AVAILABLE)
    if not code:
        raise VehicleRuleError("El codigo del vehiculo es obligatorio.")
    if not plate:
        raise VehicleRuleError("La patente del vehiculo es obligatoria.")
    if not capacity_profile_id:
        raise VehicleRuleError("El perfil de capacidad es obligatorio.")
    if status not in Vehicle.VehicleStatus.values:
        raise VehicleRuleError("Estado de vehiculo invalido.")
    return {
        "code": code,
        "plate": plate,
        "description": _clean(payload.get("description") if "description" in payload else existing.description if existing else ""),
        "status": status,
        "capacity_profile": VehicleCapacityProfile.objects.get(id=capacity_profile_id),
        "branch_ref": _clean(payload.get("branch_ref") if "branch_ref" in payload else existing.branch_ref if existing else ""),
        "active": _bool(payload.get("active"), existing.active if existing else True),
    }


@transaction.atomic
def upsert_vehicle(*, payload: dict, idempotency_key: str, actor: str, vehicle_id: str = "") -> IdempotentResult:
    operation = "vehicle.update" if vehicle_id else "vehicle.create"
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type=operation,
        reference_type="vehicle",
        reference_id=vehicle_id or payload.get("code", "new"),
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)
    before = {}
    try:
        if vehicle_id:
            vehicle = Vehicle.objects.select_for_update().get(id=vehicle_id)
            before = serialize_vehicle(vehicle)
            previous_status = vehicle.status
            data = _vehicle_payload(payload, existing=vehicle)
            for key, value in data.items():
                setattr(vehicle, key, value)
            vehicle.updated_by = actor
            vehicle.save()
            status = 200
            action = "updated"
        else:
            data = _vehicle_payload(payload)
            previous_status = ""
            vehicle = Vehicle.objects.create(**data, created_by=actor, updated_by=actor)
            status = 201
            action = "created"
    except VehicleCapacityProfile.DoesNotExist as exc:
        raise VehicleRuleError("El perfil de capacidad indicado no existe.") from exc
    except IntegrityError as exc:
        raise VehicleRuleError("Ya existe un vehiculo con ese codigo o patente.") from exc
    after = serialize_vehicle(vehicle)
    _status_history("vehicle", str(vehicle.id), previous_status, vehicle.status, actor, action, after)
    _audit("vehicle", str(vehicle.id), action, actor, before=before, after=after)
    return _finish_idempotent_command(idempotency, IdempotentResult({"result": after}, status))


def _driver_payload(payload: dict, *, existing: Driver | None = None) -> dict:
    code = _clean(payload.get("code") if "code" in payload else existing.code if existing else "")
    full_name = _clean(payload.get("full_name") if "full_name" in payload else existing.full_name if existing else "")
    status = _clean(payload.get("status") if "status" in payload else existing.status if existing else Driver.DriverStatus.AVAILABLE)
    if not code:
        raise VehicleRuleError("El codigo del chofer es obligatorio.")
    if not full_name:
        raise VehicleRuleError("El nombre del chofer es obligatorio.")
    if status not in Driver.DriverStatus.values:
        raise VehicleRuleError("Estado de chofer invalido.")
    license_expires_at = payload.get("license_expires_at") if "license_expires_at" in payload else existing.license_expires_at if existing else None
    if isinstance(license_expires_at, str):
        license_expires_at = parse_date(license_expires_at) if license_expires_at else None
    return {
        "code": code,
        "full_name": full_name,
        "document_number": _clean(payload.get("document_number") if "document_number" in payload else existing.document_number if existing else ""),
        "phone": _clean(payload.get("phone") if "phone" in payload else existing.phone if existing else ""),
        "email": _clean(payload.get("email") if "email" in payload else existing.email if existing else ""),
        "license_number": _clean(payload.get("license_number") if "license_number" in payload else existing.license_number if existing else ""),
        "license_category": _clean(payload.get("license_category") if "license_category" in payload else existing.license_category if existing else ""),
        "license_expires_at": license_expires_at,
        "status": status,
        "branch_ref": _clean(payload.get("branch_ref") if "branch_ref" in payload else existing.branch_ref if existing else ""),
        "warehouse_ref": _clean(payload.get("warehouse_ref") if "warehouse_ref" in payload else existing.warehouse_ref if existing else ""),
        "active": _bool(payload.get("active"), existing.active if existing else True),
        "notes": _clean(payload.get("notes") if "notes" in payload else existing.notes if existing else ""),
    }


@transaction.atomic
def upsert_driver(*, payload: dict, idempotency_key: str, actor: str, driver_id: str = "") -> IdempotentResult:
    operation = "driver.update" if driver_id else "driver.create"
    idempotency, replay = _start_idempotent_command(
        key=idempotency_key,
        operation_type=operation,
        reference_type="driver",
        reference_id=driver_id or payload.get("code", "new"),
        payload=payload,
    )
    if replay and idempotency.status == IdempotencyKey.ProcessingStatus.SUCCEEDED:
        return IdempotentResult(idempotency.response_payload, idempotency.response_status)
    before = {}
    try:
        if driver_id:
            driver = Driver.objects.select_for_update().get(id=driver_id)
            before = serialize_driver(driver)
            previous_status = driver.status
            data = _driver_payload(payload, existing=driver)
            for key, value in data.items():
                setattr(driver, key, value)
            driver.updated_by = actor
            driver.save()
            status = 200
            action = "updated"
        else:
            data = _driver_payload(payload)
            previous_status = ""
            driver = Driver.objects.create(**data, created_by=actor, updated_by=actor)
            status = 201
            action = "created"
    except IntegrityError as exc:
        raise VehicleRuleError("Ya existe un chofer con ese codigo.") from exc
    after = serialize_driver(driver)
    _status_history("driver", str(driver.id), previous_status, driver.status, actor, action, after)
    _audit("driver", str(driver.id), action, actor, before=before, after=after)
    return _finish_idempotent_command(idempotency, IdempotentResult({"result": after}, status))
