from django.urls import path

from apps.logistics import api


urlpatterns = [
    path("dashboard/", api.operational_dashboard, name="operational-dashboard"),
    path("overview/", api.operational_overview, name="operational-overview"),
    path("context/", api.operational_context, name="operational-context"),
    path("context/active-warehouse/", api.active_warehouse, name="active-warehouse"),
    path("warehouses/", api.warehouses, name="warehouses"),
    path("warehouses/sync/", api.warehouses_sync, name="warehouses-sync"),
    path("warehouses/<str:warehouse_ref>/", api.warehouse_detail, name="warehouse-detail"),
    path("warehouses/<str:warehouse_ref>/locations/", api.warehouse_locations, name="warehouse-locations"),
    path("warehouses/<str:warehouse_ref>/locations/generate/", api.warehouse_locations_generate, name="warehouse-locations-generate"),
    path("master-data/stores/", api.master_stores, name="master-stores"),
    path("master-data/warehouses/", api.master_warehouses, name="master-warehouses"),
    path("master-data/materials/", api.master_materials, name="master-materials"),
    path("master-data/sheet-cutting/", api.master_sheet_cutting_options, name="master-sheet-cutting-options"),
    path("master-data/sheet-cutting/plan/", api.master_sheet_cutting_plan, name="master-sheet-cutting-plan"),
]
