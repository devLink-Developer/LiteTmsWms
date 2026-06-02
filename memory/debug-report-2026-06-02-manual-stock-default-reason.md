# Debug Report: Manual Stock Default Reason

Date: 2026-06-02

## Symptom

En `Alta y baja de articulos`, luego de hacer una alta manual, el historial mostraba la direccion como `ALTA` pero el motivo como `Baja manual`.

## Root Cause

La pantalla conservaba `form.reason` al alternar entre los modos Alta y Baja. Al volver desde Baja hacia Alta, la logica usaba `current.reason || "Alta manual"`, por lo que un valor previo `Baja manual` no se reemplazaba. El POST salia con `direction=increase` y `reason=Baja manual`.

## Fix

- El formulario inicial de Alta ahora usa `Alta manual`.
- El motivo por defecto se recalcula por modo cuando el valor actual es uno de los defaults (`Alta manual` o `Baja manual`).
- Un motivo custom escrito por el operador se conserva al cambiar de modo.

## Evidence

Test focalizado:

- `npm test -- --run ManualStockAdjustmentPage`
- Resultado: 1 archivo aprobado, 5 tests aprobados.

## Regression Test

`frontend/src/features/operations/ManualStockAdjustmentPage.test.tsx`

- Reproduce el flujo Baja -> Alta -> Confirmar alta.
- Verifica que el payload quede con `direction=increase` y `reason=Alta manual`.

## Related

Misma pantalla que los reportes previos de busqueda y filtrado de posiciones para alta/baja manual.

## Status

DONE
