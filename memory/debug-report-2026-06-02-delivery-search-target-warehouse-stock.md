# Debug Report: Delivery Search Target Warehouse Stock

Date: 2026-06-02

## Symptom

En `/pedidos/entrega`, la busqueda de pedidos no devolvia disponibilidad para entrega aunque la consulta de stock mostraba stock en el deposito operativo.

## Root Cause

La cola de expedicion calculaba `stock_available` y `max_dispatchable_qty` usando el `warehouse_ref` legacy de la linea del pedido. En los casos revisados, el pedido tenia lineas en `PS03DP`, pero el stock operativo cargado por alta manual estaba en `PR03DP-DSP-GEN`. La validacion/confirmacion ya usaba `target_warehouse_ref`, pero la busqueda no lo enviaba ni lo aplicaba al calculo de disponibilidad.

## Fix

- Frontend: `/pedidos/entrega` ahora envia el deposito activo como `target_warehouse_ref` en la busqueda de cola.
- Backend API: `expedition_queue_view` recibe `target_warehouse_ref`.
- Backend service: `expedition_queue` y `_line_metrics` calculan disponibilidad `packed` contra el deposito objetivo cuando se informa.
- El calculo de `max_dispatchable_qty` con deposito objetivo queda alineado con `check_fulfillment_stock_for_split`.

## Evidence

Consulta real despues del fix:

- Pedido: `VENT8-100001983`
- Articulo: `100100`
- Pedido legacy: `PS03DP`
- Deposito objetivo: `PR03DP`
- Resultado: `stock_available=1000.000000`, `max_dispatchable_qty=1.000000`

Tests:

- `python manage.py test tests.test_fulfillment_delivery_flow.DeliveryPreparationFlowTests.test_expedition_queue_uses_target_warehouse_for_stock_availability --keepdb`
- `python manage.py test tests.test_fulfillment_delivery_flow --keepdb`
- `npm test -- --run DeliveryExpeditionPage`

## Regression Test

- Backend: la cola de expedicion usa stock del deposito objetivo aunque la linea del pedido pertenezca a otro deposito legacy.
- Frontend: la busqueda de `/pedidos/entrega` incluye `target_warehouse_ref`.

## Status

DONE
