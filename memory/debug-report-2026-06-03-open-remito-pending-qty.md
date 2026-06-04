# Debug Report: Open Remito Pending Qty

Date: 2026-06-03

## Symptom

El pedido `VENT8-100001370` tenia remito generado por la totalidad de sus lineas, pero `/pedidos/entrega` mostraba las lineas como `PENDIENTE` con cantidad pendiente.

## Root Cause

La cola de expedicion serializaba `pending_qty` directamente desde `FulfillmentOrderLine.pending_qty`, que depende de `delivered_qty`.

En flujo de reparto, `issue_remito` deja el remito en estado `open` hasta la rendicion de ruta y no incrementa `delivered_qty` al emitir el remito. Para la pantalla de expedicion, esas cantidades ya no son operables porque estan documentadas en un remito abierto, pero el calculo de la cola no las descontaba.

## Fix

- La cola ahora calcula `open_remito_qty` en bulk desde `DeliveryDocumentLine` para remitos `open`.
- `pending_qty` y `max_dispatchable_qty` de la respuesta descuentan esas cantidades documentadas.
- `split_fulfillment_delivery` y `check_fulfillment_stock_for_split` usan el mismo pending efectivo, evitando generar otra entrega sobre lineas ya cubiertas por remito abierto.
- No se cambio el lifecycle de reparto: el remito sigue `open` hasta rendicion y `delivered_qty` sigue actualizandose al cierre/ejecucion correspondiente.

## Evidence

Verificacion real por HTTP despues del restart de backend:

`/api/v1/fulfillment/expedition-queue/?sales_order_number=VENT8-100001370&target_warehouse_ref=PR03DP`

Resultado:

- `106589`: `pending_qty=0`, `max_dispatchable_qty=0`
- `107226`: `pending_qty=0`, `max_dispatchable_qty=0`
- `118844`: `pending_qty=0`, `max_dispatchable_qty=0`

Tests:

- `python manage.py test tests.test_fulfillment_delivery_flow --keepdb`
- `python manage.py test tests.test_api_filters --keepdb`
- `python manage.py makemigrations --check --dry-run`

Suite completa:

- `python manage.py test tests --keepdb` encuentra 118 tests y falla por entorno: falta `pyarrow` en `.venv`, requerido por tests Parquet/ruteo. No esta relacionado con este cambio.

## Regression Test

- `test_expedition_queue_treats_open_remito_lines_as_not_pending`

## Status

DONE_WITH_CONCERNS: fix verificado y backend reiniciado; suite completa bloqueada por dependencia local faltante `pyarrow`.
