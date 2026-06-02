# Debug Report: Manual Stock Search

Date: 2026-06-02

## Symptom

En `Alta y baja de articulos`, al cambiar el criterio de busqueda en modo Baja no aparecia otro articulo si no estaba dentro del lote inicial de stock cargado.

## Root Cause

`ManualStockAdjustmentPage` cargaba stock una sola vez con `fetchInventoryStockReport({ warehouse, state: "packed", locationScope: "available", limit: 500 })` y luego filtraba solo en memoria. El texto de busqueda no se enviaba al backend, por lo que los articulos fuera de los primeros 500 buckets nunca se recuperaban.

## Fix

La pantalla ahora:

- Usa `search` en la consulta a `fetchInventoryStockReport`.
- Recarga stock con debounce de 250 ms cuando cambia la busqueda en modo Baja.
- Usa una secuencia de requests para evitar que una respuesta vieja pise una busqueda mas nueva.

## Evidence

`npm test -- --run ManualStockAdjustmentPage` paso con 3 tests.

## Regression Test

`frontend/src/features/operations/ManualStockAdjustmentPage.test.tsx` valida que buscar `ITEM-2` en modo Baja haga un GET con `search=ITEM-2` y muestre la fila devuelta por la API.

## Status

DONE
