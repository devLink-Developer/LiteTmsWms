import json

from django.test import Client, TestCase

from apps.core.models import AuditTrail, StatusHistory
from apps.vehicles.models import Driver, Vehicle, VehicleCapacityProfile


class FleetAdminApiTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_X_ACTOR="fleet-admin")

    def _post(self, path: str, payload: dict, key: str):
        return self.client.post(path, json.dumps(payload), content_type="application/json", HTTP_IDEMPOTENCY_KEY=key)

    def _patch(self, path: str, payload: dict, key: str):
        return self.client.patch(path, json.dumps(payload), content_type="application/json", HTTP_IDEMPOTENCY_KEY=key)

    def test_vehicle_abm_persists_profile_vehicle_and_audit(self):
        profile_response = self._post(
            "/api/v1/vehicles/profiles/",
            {"name": "Camion liviano", "max_weight_kg": "1200", "max_volume_m3": "8.5", "notes": "Base reparto"},
            "profile-create",
        )
        self.assertEqual(profile_response.status_code, 201)
        profile_id = profile_response.json()["result"]["id"]

        vehicle_response = self._post(
            "/api/v1/vehicles/",
            {
                "code": "VH-TEST",
                "plate": "AB123CD",
                "description": "Unidad test",
                "status": "available",
                "capacity_profile_id": profile_id,
                "branch_ref": "BR-1",
                "active": True,
            },
            "vehicle-create",
        )
        self.assertEqual(vehicle_response.status_code, 201)
        vehicle_payload = vehicle_response.json()["result"]
        vehicle = Vehicle.objects.get(id=vehicle_payload["id"])
        self.assertEqual(vehicle.capacity_profile_id, VehicleCapacityProfile.objects.get(id=profile_id).id)
        self.assertEqual(vehicle_payload["max_weight_kg"], "1200.000")

        update_response = self._patch(
            f"/api/v1/vehicles/{vehicle.id}/",
            {
                "code": "VH-TEST",
                "plate": "AB123CD",
                "description": "Unidad test",
                "status": "maintenance",
                "capacity_profile_id": profile_id,
                "branch_ref": "BR-1",
                "active": True,
            },
            "vehicle-update",
        )
        self.assertEqual(update_response.status_code, 200)
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, "maintenance")
        self.assertTrue(StatusHistory.objects.filter(entity_type="vehicle", entity_id=str(vehicle.id), to_status="maintenance").exists())
        self.assertTrue(AuditTrail.objects.filter(entity_type="vehicle", entity_id=str(vehicle.id), action="updated").exists())

    def test_driver_abm_persists_in_tmswms_and_updates_status(self):
        create_response = self._post(
            "/api/v1/vehicles/drivers/",
            {
                "code": "CH-TEST",
                "full_name": "Chofer Test",
                "document_number": "12345678",
                "phone": "3764000000",
                "email": "chofer@example.com",
                "license_number": "LIC-1",
                "license_category": "B2",
                "license_expires_at": "2027-01-31",
                "status": "available",
                "branch_ref": "BR-1",
                "warehouse_ref": "WH-1",
                "active": True,
                "notes": "Alta test",
            },
            "driver-create",
        )
        self.assertEqual(create_response.status_code, 201)
        driver = Driver.objects.get(id=create_response.json()["result"]["id"])
        self.assertEqual(driver.code, "CH-TEST")
        self.assertEqual(str(driver.license_expires_at), "2027-01-31")

        update_response = self._patch(
            f"/api/v1/vehicles/drivers/{driver.id}/",
            {
                "code": "CH-TEST",
                "full_name": "Chofer Test",
                "status": "suspended",
                "branch_ref": "BR-1",
                "warehouse_ref": "WH-1",
                "active": False,
            },
            "driver-update",
        )
        self.assertEqual(update_response.status_code, 200)
        driver.refresh_from_db()
        self.assertEqual(driver.status, "suspended")
        self.assertFalse(driver.active)
        self.assertTrue(StatusHistory.objects.filter(entity_type="driver", entity_id=str(driver.id), to_status="suspended").exists())
