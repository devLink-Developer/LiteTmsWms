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
