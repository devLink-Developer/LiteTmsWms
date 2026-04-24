from django.urls import path

from apps.audits import api


urlpatterns = [path("", api.audits, name="warehouse-audits")]
