import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase


def permissions_payload(*, employee=True, warehouses=True):
    return {
        "employee": {
            "employee_id": "E-1",
            "name": "Operador Logistic",
            "email": "operator@example.com",
            "branch_ref": "S001",
            "branch_name": "Sucursal Norte",
        }
        if employee
        else None,
        "authorized_warehouses": ["W001"] if warehouses else [],
        "permissions": ["deliveries:view"],
    }


class AuthApiTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_session_is_unauthenticated_and_sets_csrf_cookie(self):
        response = self.client.get("/auth/api/session/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["authenticated"])
        self.assertEqual(payload["appName"], "Lite Logistic")
        self.assertIsNone(payload["user"])
        self.assertIsNone(payload["workspace"])
        self.assertIn("csrftoken", response.cookies)

    @patch("apps.authentication.api.employee_delivery_permissions")
    @patch("apps.authentication.api.authenticate_ldap")
    def test_login_creates_django_session(self, authenticate_ldap, employee_delivery_permissions):
        authenticate_ldap.return_value = (True, None, "operator@example.com")
        employee_delivery_permissions.return_value = permissions_payload()

        response = self.client.post(
            "/auth/api/login/",
            json.dumps({"username": "operator", "password": "secret"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["redirectTo"], "/pedidos/entrega")
        self.assertTrue(payload["session"]["authenticated"])
        self.assertEqual(payload["session"]["appName"], "Lite Logistic")
        self.assertEqual(payload["session"]["workspace"]["authorized_warehouses"], ["W001"])
        self.assertTrue(get_user_model().objects.filter(username="operator@example.com").exists())

    @patch("apps.authentication.api.authenticate_ldap")
    def test_login_rejects_invalid_credentials(self, authenticate_ldap):
        authenticate_ldap.return_value = (False, "Credenciales invalidas", None)

        response = self.client.post(
            "/auth/api/login/",
            json.dumps({"username": "operator", "password": "bad"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn("Credenciales incorrectas", response.json()["error"])

    @patch("apps.authentication.api.employee_delivery_permissions")
    @patch("apps.authentication.api.authenticate_ldap")
    def test_login_rejects_missing_employee(self, authenticate_ldap, employee_delivery_permissions):
        authenticate_ldap.return_value = (True, None, "missing@example.com")
        employee_delivery_permissions.return_value = permissions_payload(employee=False)

        response = self.client.post(
            "/auth/api/login/",
            json.dumps({"username": "missing", "password": "secret"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("No se encontraron datos", response.json()["error"])

    @patch("apps.authentication.api.employee_delivery_permissions")
    @patch("apps.authentication.api.authenticate_ldap")
    def test_login_rejects_user_without_authorized_warehouses(self, authenticate_ldap, employee_delivery_permissions):
        authenticate_ldap.return_value = (True, None, "operator@example.com")
        employee_delivery_permissions.return_value = permissions_payload(warehouses=False)

        response = self.client.post(
            "/auth/api/login/",
            json.dumps({"username": "operator", "password": "secret"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("depositos autorizados", response.json()["error"])

    def test_logout_clears_session(self):
        get_user_model().objects.create_user(username="operator@example.com")
        self.client.force_login(get_user_model().objects.get(username="operator@example.com"))

        response = self.client.post("/auth/api/logout/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        session_response = self.client.get("/auth/api/session/")
        self.assertFalse(session_response.json()["authenticated"])


class EmployeeDeliveryPermissionsTests(TestCase):
    def tearDown(self):
        from apps.logistics import parquet_master_data

        parquet_master_data.employee_delivery_permissions.cache_clear()
        super().tearDown()

    @patch("apps.logistics.parquet_master_data._read_rows")
    def test_store_warehouse_uses_shipping_deposit_only(self, read_rows):
        from apps.logistics import parquet_master_data

        read_rows.return_value = (
            "tiendas.parquet",
            [
                {
                    "codigo": "S001",
                    "deposito_pickup": "W-PICKUP",
                    "deposito_envio": "W-SHIPPING",
                }
            ],
        )

        self.assertEqual(parquet_master_data._warehouse_codes_for_stores({"S001"}), {"W-SHIPPING"})

    @patch("apps.logistics.parquet_master_data._read_rows")
    def test_store_warehouse_falls_back_to_pickup_deposit(self, read_rows):
        from apps.logistics import parquet_master_data

        read_rows.return_value = (
            "tiendas.parquet",
            [
                {
                    "codigo": "S001",
                    "deposito_pickup": "W-PICKUP",
                    "deposito_envio": "",
                }
            ],
        )

        self.assertEqual(parquet_master_data._warehouse_codes_for_stores({"S001"}), {"W-PICKUP"})

    @patch("apps.logistics.parquet_master_data._read_rows")
    def test_stock_warehouses_use_fulfillment_group(self, read_rows):
        from apps.logistics import parquet_master_data

        read_rows.return_value = (
            "tiendas.parquet",
            [
                {
                    "codigo": "S001",
                    "deposito_pickup": "W-PICKUP",
                    "deposito_envio": "W-SHIPPING",
                    "fulfillment_group_warehouses": [
                        {"warehouse_code": "W-FUL-1"},
                        {"warehouse_code": "W-FUL-2"},
                    ],
                }
            ],
        )

        self.assertEqual(parquet_master_data.fulfillment_warehouse_codes_for_stores({"S001"}), {"W-FUL-1", "W-FUL-2"})

    @patch("apps.logistics.parquet_master_data._read_rows")
    def test_stock_warehouses_fall_back_to_pickup_group_when_fulfillment_group_is_empty(self, read_rows):
        from apps.logistics import parquet_master_data

        read_rows.return_value = (
            "tiendas.parquet",
            [
                {
                    "codigo": "S001",
                    "deposito_pickup": "W-PICKUP",
                    "deposito_envio": "W-SHIPPING",
                    "fulfillment_group_warehouses": None,
                    "pickup_group_warehouses": '[{"warehouse_code": "W-PICK-1"}, {"warehouse_code": "W-PICK-2"}]',
                }
            ],
        )

        self.assertEqual(parquet_master_data.fulfillment_warehouse_codes_for_stores({"S001"}), {"W-PICK-1", "W-PICK-2"})

    @patch("apps.logistics.parquet_master_data._warehouse_codes_for_stores")
    @patch("apps.logistics.parquet_master_data._read_rows")
    def test_permissions_use_only_employee_configured_store(self, read_rows, warehouse_codes_for_stores):
        from apps.logistics import parquet_master_data

        read_rows.return_value = (
            "empleados.parquet",
            [
                {
                    "employee_id": "E-1",
                    "nombre": "Operador",
                    "apellido": "Logistic",
                    "email": "operator@example.com",
                    "activo": True,
                    "sucursal_codigo": "S001",
                    "sucursal_nombre": "Sucursal Uno",
                    "pos_groups_json": '[{"store_code": "S002"}]',
                }
            ],
        )
        warehouse_codes_for_stores.return_value = {"W001"}

        result = parquet_master_data.employee_delivery_permissions("operator@example.com")

        warehouse_codes_for_stores.assert_called_once_with({"S001"})
        self.assertEqual(result["authorized_warehouses"], ["W001"])
        self.assertEqual(result["employee"]["store_codes"], ["S001"])
