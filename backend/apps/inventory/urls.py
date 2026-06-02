from django.urls import path

from apps.inventory import api


urlpatterns = [
    path("advanced-stock/", api.advanced_stock, name="inventory-advanced-stock"),
    path("materials/", api.materials, name="inventory-materials"),
    path("balances/", api.balances, name="inventory-balances"),
    path("ledger/", api.ledger, name="inventory-ledger"),
    path("receipts/", api.receipts, name="inventory-receipts"),
    path("exchanges/", api.exchanges, name="inventory-exchanges"),
    path("location-moves/", api.location_moves, name="inventory-location-moves"),
    path("manual-adjustments/", api.manual_adjustments, name="inventory-manual-adjustments"),
    path("reservations/", api.reservations, name="inventory-reservations"),
    path("sheet-cutting/validate/", api.validate_sheet_cutting, name="inventory-sheet-cutting-validate"),
    path("sheet-cutting/execute/", api.execute_sheet_cutting_view, name="inventory-sheet-cutting-execute"),
    path("write-offs/", api.write_offs, name="inventory-write-offs"),
    path("write-offs/<uuid:write_off_id>/", api.write_off_detail, name="inventory-write-off-detail"),
    path("write-offs/<uuid:write_off_id>/post/", api.post_write_off, name="inventory-write-off-post"),
    path("write-offs/<uuid:write_off_id>/reverse/", api.reverse_write_off, name="inventory-write-off-reverse"),
]
