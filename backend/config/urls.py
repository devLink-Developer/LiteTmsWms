from django.contrib import admin
from django.urls import include, path

from apps.logistics.api import healthcheck
from apps.routes import api as routes_api


urlpatterns = [
    path("admin/", admin.site.urls),
    path("auth/", include("apps.authentication.urls")),
    path("api/v1/health/", healthcheck, name="healthcheck"),
    path("api/v1/inventory/", include("apps.inventory.urls")),
    path("api/v1/transfers/", include("apps.transfers.urls")),
    path("api/v1/fulfillment/", include("apps.fulfillment.urls")),
    path("api/v1/routes/", include("apps.routes.urls")),
    path("api/v1/routing/", include("apps.routes.urls")),
    path("api/v1/routesheets/", include("apps.routes.urls")),
    path("api/v1/deliveries/execute", routes_api.execute_delivery, name="delivery-execute"),
    path("api/v1/deliveries/execute/", routes_api.execute_delivery, name="delivery-execute-slash"),
    path("api/v1/vehicles/", include("apps.vehicles.urls")),
    path("api/v1/audits/", include("apps.audits.urls")),
    path("api/v1/dispatch/", include("apps.dispatch.urls")),
    path("api/v1/shipping/", include("apps.shipping.urls")),
    path("api/v1/logistics/", include("apps.logistics.urls")),
]
