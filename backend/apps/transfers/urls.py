from django.urls import path

from apps.transfers import api


urlpatterns = [
    path("", api.transfer_orders, name="transfer-orders"),
    path("<uuid:transfer_id>/approve", api.approve, name="transfer-approve"),
    path("<uuid:transfer_id>/prepare", api.prepare, name="transfer-prepare"),
    path("<uuid:transfer_id>/dispatch", api.dispatch, name="transfer-dispatch"),
    path("<uuid:transfer_id>/ship", api.dispatch, name="transfer-ship"),
    path("<uuid:transfer_id>/receive", api.receive, name="transfer-receive"),
    path("<uuid:transfer_id>/close", api.close, name="transfer-close"),
]
