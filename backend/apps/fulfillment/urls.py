from django.urls import path

from apps.fulfillment import api


urlpatterns = [
    path("from-legacy-order", api.from_legacy_order, name="fulfillment-from-legacy-order"),
    path("expedition-queue/", api.expedition_queue_view, name="fulfillment-expedition-queue"),
    path("reparto-confirmation/", api.reparto_confirmation_queue, name="fulfillment-reparto-confirmation"),
    path("preparation-tasks/", api.preparation_tasks, name="preparation-tasks"),
    path("<uuid:fulfillment_id>/stock-check", api.check_fulfillment_stock, name="fulfillment-stock-check"),
    path("<uuid:fulfillment_id>/split", api.split_fulfillment, name="fulfillment-split"),
    path("", api.fulfillment_orders, name="fulfillment-orders"),
    path("deliveries/", api.delivery_orders, name="delivery-orders"),
    path("deliveries/<uuid:delivery_id>/stock-check", api.stock_check, name="delivery-stock-check"),
    path("deliveries/<uuid:delivery_id>/confirm", api.validate_stock, name="delivery-confirm"),
    path("deliveries/<uuid:delivery_id>/validate-stock", api.validate_stock, name="delivery-validate-stock"),
    path("deliveries/<uuid:delivery_id>/confirm-available", api.confirm_available_stock, name="delivery-confirm-available"),
    path("deliveries/<uuid:delivery_id>/reassign-warehouse", api.reassign_delivery_warehouse, name="delivery-reassign-warehouse"),
    path("deliveries/<uuid:delivery_id>/send-to-prepare", api.send_to_prepare, name="delivery-send-to-prepare"),
    path("deliveries/<uuid:delivery_id>/mark-prepared", api.mark_delivery_prepared, name="delivery-mark-prepared"),
    path("preparation-tasks/<uuid:task_id>/mark-prepared", api.mark_prepared, name="preparation-task-mark-prepared"),
    path("deliveries/<uuid:delivery_id>/remito", api.remito, name="delivery-remito"),
    path("deliveries/<uuid:delivery_id>/remito.pdf", api.remito_pdf, name="delivery-remito-pdf"),
]
