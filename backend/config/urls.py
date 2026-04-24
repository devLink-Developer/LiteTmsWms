from django.contrib import admin
from django.urls import include, path

from apps.logistics.api import healthcheck


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/health/", healthcheck, name="healthcheck"),
    path("api/v1/inventory/", include("apps.inventory.urls")),
    path("api/v1/transfers/", include("apps.transfers.urls")),
    path("api/v1/fulfillment/", include("apps.fulfillment.urls")),
    path("api/v1/routes/", include("apps.routes.urls")),
    path("api/v1/vehicles/", include("apps.vehicles.urls")),
    path("api/v1/audits/", include("apps.audits.urls")),
    path("api/v1/dispatch/", include("apps.dispatch.urls")),
    path("api/v1/shipping/", include("apps.shipping.urls")),
    path("api/v1/logistics/", include("apps.logistics.urls")),
]
