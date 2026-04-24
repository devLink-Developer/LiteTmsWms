from django.urls import path

from apps.routes import api


urlpatterns = [path("", api.route_sheets, name="route-sheets")]
