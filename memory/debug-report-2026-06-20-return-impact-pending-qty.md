# Debug Report: Return Impact Pending Qty

Date: 2026-06-20

## Symptom

En expedicion, el pedido `VENT8-100002531` mostraba lineas con `Pedido 1`, `Devuelto 1`, pero `Pendiente 1` y cantidad despachable.

La busqueda de un solo pedido tambien fue reportada como lenta, por encima de 15 segundos.

## Root Cause

Las devoluciones legacy tipo `D` se procesaban como `FulfillmentOrderImpact.RETURN`: ingresaban stock y se exponian como `returned_qty`, pero `_effective_pending_qty` no las consideraba. El pendiente efectivo solo descontaba `delivered_qty`, remito abierto y `cancelled_qty`.

Cuando el remito/entrega original no existe como entrega local, una devolucion aplicada es la unica evidencia de que esa unidad ya no debe ser operable. Por eso una linea `ordered=1`, `returned=1`, `delivered=0`, `cancelled=0` seguia calculando `pending=1`.

## Fix

`_effective_pending_qty` ahora toma `returned_qty` aplicado y calcula la cantidad documentada como:

`max(delivered_qty, open_remito_qty, returned_qty)`

Esto evita doble descuento cuando ya existe entrega/remito local, pero cierra el pendiente cuando la devolucion legacy es la evidencia disponible.

La misma cantidad efectiva se usa para:

- serializar la cola de expedicion,
- validar stock para split,
- crear splits de entrega.
- serializar fulfillments sin entrega en reparto.

## Evidence

Reproduccion antes del fix:

- `106705`: `ordered=1`, `returned=1`, `delivered=0`, `pending=1`, `max=1`.
- `106710`: `ordered=1`, `returned=1`, `delivered=0`, `pending=1`, `max=1`.

Verificacion despues del fix contra el pedido real:

- `106705`: `ordered=1`, `returned=1`, `delivered=0`, `pending=0`, `max=0`.
- `106710`: `ordered=1`, `returned=1`, `delivered=0`, `pending=0`, `max=0`.

Medicion local:

- Primera corrida: ~3.0s.
- Corridas siguientes con caches calientes: ~1.2s.

No se reprodujeron los 15s localmente. El perfil mostro costo repartido entre consulta base, refresh legacy, metricas y snapshots de materiales.

## Regression Test

- `DeliveryPreparationFlowTests.test_return_impact_reduces_effective_pending_qty_when_delivery_is_not_local`
- `ApiFilterTests.test_reparto_confirmation_queue_excludes_fully_returned_uncreated_fulfillment`

## Test Results

- `python manage.py test tests.test_fulfillment_delivery_flow.DeliveryPreparationFlowTests.test_return_impact_reduces_effective_pending_qty_when_delivery_is_not_local --keepdb`: OK
- `python manage.py test tests.test_api_filters.ApiFilterTests.test_reparto_confirmation_queue_excludes_fully_returned_uncreated_fulfillment --keepdb`: OK
- `python manage.py test tests.test_fulfillment_delivery_flow tests.test_api_filters --keepdb`: OK, 67 tests
- `python manage.py makemigrations --check --dry-run`: OK, no changes detected
- `python manage.py test tests --keepdb`: OK, 129 tests

## Status

DONE_WITH_CONCERNS: calculo corregido y verificado; la latencia de 15s no se reprodujo localmente, aunque la consulta sigue dependiendo de legacy/parquet y puede variar con cache fria o red.
