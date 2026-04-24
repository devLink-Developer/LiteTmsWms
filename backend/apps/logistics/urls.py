from django.urls import path

from apps.logistics import api


urlpatterns = [
    path("overview/", api.operational_overview, name="operational-overview"),
    path("context/", api.operational_context, name="operational-context"),
    path("master-data/stores/", api.master_stores, name="master-stores"),
    path("master-data/warehouses/", api.master_warehouses, name="master-warehouses"),
    path("master-data/materials/", api.master_materials, name="master-materials"),
]
