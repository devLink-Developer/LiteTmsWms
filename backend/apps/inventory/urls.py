from django.urls import path

from apps.inventory import api


urlpatterns = [
    path("advanced-stock/", api.advanced_stock, name="inventory-advanced-stock"),
    path("balances/", api.balances, name="inventory-balances"),
    path("ledger/", api.ledger, name="inventory-ledger"),
    path("receipts/", api.receipts, name="inventory-receipts"),
    path("reservations/", api.reservations, name="inventory-reservations"),
]
