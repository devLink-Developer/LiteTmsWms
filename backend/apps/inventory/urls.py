from django.urls import path

from apps.inventory import api


urlpatterns = [
    path("balances/", api.balances, name="inventory-balances"),
    path("ledger/", api.ledger, name="inventory-ledger"),
    path("reservations/", api.reservations, name="inventory-reservations"),
]
