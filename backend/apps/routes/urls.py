from django.urls import path

from apps.routes import api


urlpatterns = [
    path("", api.route_sheets, name="route-sheets"),
    path("pending-deliveries/", api.pending_deliveries, name="route-pending-deliveries"),
    path("optimize", api.optimize, name="route-optimize"),
    path("optimize/", api.optimize, name="route-optimize-slash"),
    path("<uuid:route_id>/", api.route_sheet_detail, name="route-sheet-detail"),
    path("<uuid:route_id>/stops", api.patch_stops, name="route-stops"),
    path("<uuid:route_id>/confirm", api.confirm, name="route-confirm"),
    path("<uuid:route_id>/send-to-preparation", api.send_to_preparation, name="route-send-to-preparation"),
    path("<uuid:route_id>/start-loading", api.start_loading, name="route-start-loading"),
    path("<uuid:route_id>/depart", api.depart, name="route-depart"),
    path("<uuid:route_id>/close", api.close, name="route-close"),
]
