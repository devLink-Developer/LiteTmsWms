from django.urls import path

from apps.transfers import api


urlpatterns = [path("", api.transfer_orders, name="transfer-orders")]
