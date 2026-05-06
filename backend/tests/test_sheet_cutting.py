from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
from django.test import Client, TestCase

from apps.inventory.models import InventoryBalance, InventoryLedgerEntry, StockState
from apps.logistics import parquet_master_data
from apps.logistics.models import WarehouseLocation


class SheetCuttingCatalogTests(TestCase):
    def setUp(self):
        self.client = Client()

    def _write_materials(self, base_dir: Path) -> None:
        rows = [
            {
                "numero_producto": "CH-1300",
                "codigo_sap": "SAP-1300",
                "item_id_sap": "SAPITEM-1300",
                "categoria_producto": "Chapa Test",
                "nombre_producto": "Chapa Test x 13m",
                "nombre_largo": "Chapa Test x 13.00m",
                "unidad_medida": "un",
                "unidad_medida_codigo": "ST",
                "largo": 1300.0,
                "ancho": 122.0,
                "alto": 1.0,
                "precio_base_con_iva": 13000.0,
                "total_disponible_entrega": 4.0,
                "store_number": "TEST",
                "store_name": "Test",
            },
            {
                "numero_producto": "CH-600",
                "codigo_sap": "SAP-600",
                "item_id_sap": "SAPITEM-600",
                "categoria_producto": "Chapa Test",
                "nombre_producto": "Chapa Test x 6m",
                "nombre_largo": "Chapa Test x 6.00m",
                "unidad_medida": "un",
                "unidad_medida_codigo": "ST",
                "largo": 600.0,
                "ancho": 122.0,
                "alto": 1.0,
                "precio_base_con_iva": 6000.0,
                "total_disponible_entrega": 2.0,
                "store_number": "TEST",
                "store_name": "Test",
            },
            {
                "numero_producto": "CH-100",
                "codigo_sap": "SAP-100",
                "item_id_sap": "SAPITEM-100",
                "categoria_producto": "Chapa Test",
                "nombre_producto": "Chapa Test x 1m",
                "nombre_largo": "Chapa Test x 1.00m",
                "unidad_medida": "un",
                "unidad_medida_codigo": "ST",
                "largo": 100.0,
                "ancho": 122.0,
                "alto": 1.0,
                "precio_base_con_iva": 1000.0,
                "total_disponible_entrega": 8.0,
                "store_number": "TEST",
                "store_name": "Test",
            },
            {
                "numero_producto": "CER-600",
                "codigo_sap": "SAP-CER",
                "item_id_sap": "SAPITEM-CER",
                "categoria_producto": "Ceramicos",
                "nombre_producto": "Ceramico 60cm",
                "nombre_largo": "Ceramico 60cm",
                "unidad_medida": "un",
                "unidad_medida_codigo": "ST",
                "largo": 60.0,
                "ancho": 60.0,
                "alto": 1.0,
                "precio_base_con_iva": 100.0,
                "total_disponible_entrega": 20.0,
                "store_number": "TEST",
                "store_name": "Test",
            },
        ]
        pq.write_table(pa.Table.from_pylist(rows), base_dir / "materiales_TEST.parquet")

    def test_sheet_cutting_options_list_only_sheet_categories_and_cm_lengths(self):
        with TemporaryDirectory() as tmp_dir:
            master_dir = Path(tmp_dir)
            self._write_materials(master_dir)
            with patch.object(parquet_master_data, "master_data_dir", return_value=master_dir):
                response = self.client.get(
                    "/api/v1/logistics/master-data/sheet-cutting/",
                    {"store": "TEST", "category": "Chapa Test"},
                )

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["unit"], "cm")
        self.assertEqual([row["category"] for row in payload["categories"]], ["Chapa Test"])
        self.assertEqual([row["length_cm"] for row in payload["length_options"]], [100, 600, 1300])
        self.assertEqual(payload["materials"][0]["length_cm"], 100)
        self.assertEqual(payload["materials"][0]["length_m"], 1)

    def test_sheet_cutting_plan_validates_category_lengths(self):
        with TemporaryDirectory() as tmp_dir:
            master_dir = Path(tmp_dir)
            self._write_materials(master_dir)
            with patch.object(parquet_master_data, "master_data_dir", return_value=master_dir):
                response = self.client.post(
                    "/api/v1/logistics/master-data/sheet-cutting/plan/",
                    json.dumps(
                        {
                            "store": "TEST",
                            "category": "Chapa Test",
                            "source_item_ref": "CH-1300",
                            "cuts": [
                                {"length_cm": 600, "quantity": 2},
                                {"length_cm": 100, "quantity": 1},
                            ],
                        }
                    ),
                    content_type="application/json",
                )

        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()["result"]
        self.assertTrue(result["valid"])
        self.assertEqual(result["source"]["length_cm"], 1300)
        self.assertEqual(result["used_cm"], 1300)
        self.assertEqual(result["waste_cm"], 0)
        self.assertEqual([row["quantity"] for row in result["outputs"]], [2, 1])

    def test_sheet_cutting_plan_marks_overconsumption_invalid(self):
        with TemporaryDirectory() as tmp_dir:
            master_dir = Path(tmp_dir)
            self._write_materials(master_dir)
            with patch.object(parquet_master_data, "master_data_dir", return_value=master_dir):
                response = self.client.post(
                    "/api/v1/logistics/master-data/sheet-cutting/plan/",
                    json.dumps(
                        {
                            "store": "TEST",
                            "category": "Chapa Test",
                            "source_length_cm": 1300,
                            "cuts": [{"length_cm": 600, "quantity": 3}],
                        }
                    ),
                    content_type="application/json",
                )

        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()["result"]
        self.assertFalse(result["valid"])
        self.assertEqual(result["used_cm"], 1800)
        self.assertEqual(result["waste_cm"], -500)

    def test_sheet_cutting_validation_checks_origin_stock_and_execution_posts_ledger(self):
        session = self.client.session
        session["authorized_warehouses"] = ["W001"]
        session["active_warehouse_ref"] = "W001"
        session.save()
        WarehouseLocation.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            name="Disponible entrega",
            location_type="system",
            purpose="available",
            is_dispatchable=True,
            is_pickable=True,
            system_location=True,
            active=True,
        )
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="CH-1300",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=1,
        )

        payload = {
            "store": "TEST",
            "category": "Chapa Test",
            "source_item_ref": "CH-1300",
            "source_quantity": 1,
            "cuts": [
                {"length_cm": 600, "quantity": 2},
                {"length_cm": 100, "quantity": 1},
            ],
        }
        with TemporaryDirectory() as tmp_dir:
            master_dir = Path(tmp_dir)
            self._write_materials(master_dir)
            with patch.object(parquet_master_data, "master_data_dir", return_value=master_dir):
                validation = self.client.post(
                    "/api/v1/inventory/sheet-cutting/validate/",
                    json.dumps(payload),
                    content_type="application/json",
                    HTTP_X_ACTOR="stock-operator",
                )
                execution = self.client.post(
                    "/api/v1/inventory/sheet-cutting/execute/",
                    json.dumps(payload),
                    content_type="application/json",
                    HTTP_X_ACTOR="stock-operator",
                    HTTP_IDEMPOTENCY_KEY="sheet-cut-1",
                )

        self.assertEqual(validation.status_code, 200, validation.content)
        self.assertTrue(validation.json()["result"]["stock"]["has_stock"])
        self.assertEqual(execution.status_code, 201, execution.content)
        self.assertEqual(
            InventoryBalance.objects.get(
                warehouse_ref="W001",
                location_ref="W001-DSP-GEN",
                item_ref="CH-1300",
                stock_state=StockState.PACKED,
                uom="UN",
            ).quantity,
            0,
        )
        self.assertEqual(
            InventoryBalance.objects.get(
                warehouse_ref="W001",
                location_ref="W001-DSP-GEN",
                item_ref="CH-600",
                stock_state=StockState.PACKED,
                uom="UN",
            ).quantity,
            2,
        )
        self.assertEqual(
            InventoryBalance.objects.get(
                warehouse_ref="W001",
                location_ref="W001-DSP-GEN",
                item_ref="CH-100",
                stock_state=StockState.PACKED,
                uom="UN",
            ).quantity,
            1,
        )
        self.assertEqual(InventoryLedgerEntry.objects.filter(document_type="inventory_sheet_cutting").count(), 3)

    def test_sheet_cutting_validation_checks_origin_stock_without_destination_cuts(self):
        session = self.client.session
        session["authorized_warehouses"] = ["W001"]
        session["active_warehouse_ref"] = "W001"
        session.save()
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="CH-1300",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=1,
        )

        payload = {
            "store": "TEST",
            "category": "Chapa Test",
            "source_item_ref": "CH-1300",
            "source_quantity": 1,
            "cuts": [],
        }
        with TemporaryDirectory() as tmp_dir:
            master_dir = Path(tmp_dir)
            self._write_materials(master_dir)
            with patch.object(parquet_master_data, "master_data_dir", return_value=master_dir):
                response = self.client.post(
                    "/api/v1/inventory/sheet-cutting/validate/",
                    json.dumps(payload),
                    content_type="application/json",
                    HTTP_X_ACTOR="stock-operator",
                )

        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()["result"]
        self.assertFalse(result["valid"])
        self.assertTrue(result["stock"]["has_stock"])
        self.assertEqual(result["message"], "Origen validado con stock disponible.")
        self.assertEqual(result["plan"]["outputs"], [])

    def test_sheet_cutting_execution_rejects_non_zero_leftover(self):
        session = self.client.session
        session["authorized_warehouses"] = ["W001"]
        session["active_warehouse_ref"] = "W001"
        session.save()
        WarehouseLocation.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            name="Disponible entrega",
            location_type="system",
            purpose="available",
            is_dispatchable=True,
            is_pickable=True,
            system_location=True,
            active=True,
        )
        InventoryBalance.objects.create(
            warehouse_ref="W001",
            location_ref="W001-DSP-GEN",
            item_ref="CH-1300",
            lot_ref="",
            stock_state=StockState.PACKED,
            uom="UN",
            quantity=1,
        )

        payload = {
            "store": "TEST",
            "category": "Chapa Test",
            "source_item_ref": "CH-1300",
            "source_quantity": 1,
            "cuts": [{"length_cm": 600, "quantity": 2}],
        }
        with TemporaryDirectory() as tmp_dir:
            master_dir = Path(tmp_dir)
            self._write_materials(master_dir)
            with patch.object(parquet_master_data, "master_data_dir", return_value=master_dir):
                validation = self.client.post(
                    "/api/v1/inventory/sheet-cutting/validate/",
                    json.dumps(payload),
                    content_type="application/json",
                    HTTP_X_ACTOR="stock-operator",
                )
                execution = self.client.post(
                    "/api/v1/inventory/sheet-cutting/execute/",
                    json.dumps(payload),
                    content_type="application/json",
                    HTTP_X_ACTOR="stock-operator",
                    HTTP_IDEMPOTENCY_KEY="sheet-cut-leftover",
                )

        self.assertEqual(validation.status_code, 200, validation.content)
        result = validation.json()["result"]
        self.assertFalse(result["valid"])
        self.assertEqual(result["plan"]["waste_cm"], 100)
        self.assertEqual(result["message"], "El sobrante debe ser 0 cm para ejecutar el corte.")
        self.assertEqual(execution.status_code, 422, execution.content)
        self.assertEqual(
            InventoryBalance.objects.get(
                warehouse_ref="W001",
                location_ref="W001-DSP-GEN",
                item_ref="CH-1300",
                stock_state=StockState.PACKED,
                uom="UN",
            ).quantity,
            1,
        )

    def test_sheet_cutting_validation_rejects_missing_origin_stock(self):
        session = self.client.session
        session["authorized_warehouses"] = ["W001"]
        session["active_warehouse_ref"] = "W001"
        session.save()
        payload = {
            "store": "TEST",
            "category": "Chapa Test",
            "source_item_ref": "CH-1300",
            "source_quantity": 1,
            "cuts": [{"length_cm": 600, "quantity": 2}],
        }
        with TemporaryDirectory() as tmp_dir:
            master_dir = Path(tmp_dir)
            self._write_materials(master_dir)
            with patch.object(parquet_master_data, "master_data_dir", return_value=master_dir):
                response = self.client.post(
                    "/api/v1/inventory/sheet-cutting/validate/",
                    json.dumps(payload),
                    content_type="application/json",
                    HTTP_X_ACTOR="stock-operator",
                )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["result"]["stock"]["has_stock"])
