from django.urls import path

from apps.dispatch import api


urlpatterns = [path("", api.dispatches, name="store-dispatches")]
