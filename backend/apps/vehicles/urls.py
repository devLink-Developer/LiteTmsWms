from django.urls import path

from apps.vehicles import api


urlpatterns = [
    path("", api.vehicles, name="vehicles"),
    path("<uuid:vehicle_id>/", api.vehicle_detail, name="vehicle-detail"),
    path("profiles/", api.capacity_profiles, name="vehicle-capacity-profiles"),
    path("profiles/<uuid:profile_id>/", api.capacity_profile_detail, name="vehicle-capacity-profile-detail"),
    path("drivers/", api.drivers, name="drivers"),
    path("drivers/<uuid:driver_id>/", api.driver_detail, name="driver-detail"),
]
