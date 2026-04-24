from django.urls import path

from apps.shipping import api


urlpatterns = [path("", api.shipments, name="shipments")]
