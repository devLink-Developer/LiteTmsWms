from django.urls import path

from apps.core import api


urlpatterns = [
    path("status-events/", api.live_status_events, name="live-status-events"),
]
