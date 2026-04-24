from django.urls import path

from apps.vehicles import api


urlpatterns = [path("", api.vehicles, name="vehicles")]
