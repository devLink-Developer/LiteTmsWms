# Debug Report: Stock Warehouse Location Detail

Date: 2026-06-02

## Symptom

En `/stock/almacenes`, el panel de detalle mostraba una opcion operativa para hacer movimientos internos. La pantalla debia ser solo de consulta y mostrar cantidades por posicion del articulo seleccionado.

## Root Cause

La pantalla mezclaba dos responsabilidades:

- Consulta de stock por almacen.
- Ejecucion de movimientos entre posiciones.

Ademas, la consulta estaba limitada a `location_scope=available` y `state=packed,on_hand`, por lo que no representaba todas las ubicaciones/estados del almacen.

## Fix

- Se removio el formulario y POST de movimiento interno desde `StockBalancesPage`.
- La consulta de stock ya no envia `location_scope=available` ni `state=packed,on_hand`; permite ver todas las ubicaciones y estados devueltos por `advanced-stock`.
- El panel lateral ahora es `Detalle por posiciones`.
- Para el articulo seleccionado, lista las ubicaciones del almacen con cantidades por estado: disponible entrega, reservado, preparacion, fisico, transito y merma.

## Evidence

Tests:

- `npm test -- --run StockBalancesPage`
- Resultado: 1 archivo aprobado, 2 tests aprobados.

Ruta local:

- `http://localhost:8021/stock/almacenes` responde `200`.

## Regression Test

`frontend/src/features/stock/StockBalancesPage.test.tsx`

- Verifica que la consulta no use `location_scope` ni `state`.
- Verifica que el detalle liste varias ubicaciones para el mismo articulo.
- Verifica que no aparezca `Movimiento interno`, `Confirmar movimiento` ni llamadas a `/inventory/location-moves/`.

## Status

DONE
