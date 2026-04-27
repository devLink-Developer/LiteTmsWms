from __future__ import annotations

from django.db import models

from apps.common.models import TimestampedModel


class VehicleCapacityProfile(TimestampedModel):
    name = models.CharField(max_length=80, unique=True)
    max_weight_kg = models.DecimalField(max_digits=12, decimal_places=3)
    max_volume_m3 = models.DecimalField(max_digits=12, decimal_places=3)
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name


class Vehicle(TimestampedModel):
    class VehicleStatus(models.TextChoices):
        AVAILABLE = "available", "Disponible"
        RESERVED = "reserved", "Reservado"
        IN_ROUTE = "in_route", "En ruta"
        MAINTENANCE = "maintenance", "Mantenimiento"
        OUT_OF_SERVICE = "out_of_service", "Fuera de servicio"
        RETIRED = "retired", "Baja"

    code = models.CharField(max_length=40, unique=True)
    plate = models.CharField(max_length=40, unique=True)
    description = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=30, choices=VehicleStatus.choices, default=VehicleStatus.AVAILABLE)
    capacity_profile = models.ForeignKey(
        VehicleCapacityProfile,
        related_name="vehicles",
        on_delete=models.PROTECT,
    )
    branch_ref = models.CharField(max_length=80, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "branch_ref"]),
            models.Index(fields=["active"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.plate}"


class Driver(TimestampedModel):
    class DriverStatus(models.TextChoices):
        AVAILABLE = "available", "Disponible"
        ASSIGNED = "assigned", "Asignado"
        IN_ROUTE = "in_route", "En ruta"
        SUSPENDED = "suspended", "Suspendido"
        INACTIVE = "inactive", "Inactivo"

    code = models.CharField(max_length=40, unique=True)
    full_name = models.CharField(max_length=160)
    document_number = models.CharField(max_length=40, blank=True)
    phone = models.CharField(max_length=60, blank=True)
    email = models.EmailField(blank=True)
    license_number = models.CharField(max_length=80, blank=True)
    license_category = models.CharField(max_length=40, blank=True)
    license_expires_at = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=DriverStatus.choices, default=DriverStatus.AVAILABLE)
    branch_ref = models.CharField(max_length=80, blank=True)
    warehouse_ref = models.CharField(max_length=80, blank=True)
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "branch_ref"]),
            models.Index(fields=["warehouse_ref", "active"]),
            models.Index(fields=["document_number"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.full_name}"
