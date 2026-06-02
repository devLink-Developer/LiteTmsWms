# Debug Report: Manual Stock Article And Position Search

Date: 2026-06-02

## Symptom

En `Alta y baja de articulos`, la busqueda no encontraba articulos ni sus posiciones. El usuario lo vio tanto en Alta como en Baja.

## Root Cause

La pantalla mezclaba dos busquedas distintas:

- Alta solo listaba posiciones destino y no tenia busqueda real de articulos.
- Baja buscaba posiciones de stock disponible, pero el stock fue reseteado a cero; por regla funcional no hay posiciones origen para baja si no existe stock `packed > 0`.

Ademas, el endpoint existente de maestro `/api/v1/logistics/master-data/materials/` puede tardar demasiado para una busqueda por tecla, por lo que no era adecuado para esta pantalla operativa.

## Fix

- Se agrego `/api/v1/inventory/materials/`, endpoint liviano que consulta `MaterialMasterSnapshot`.
- En Alta, la UI ahora tiene dos busquedas separadas: `Buscar articulo` y `Buscar posicion`.
- En Alta, la tabla muestra dos listas seleccionables: articulos y posiciones destino.
- En Baja, se mantiene la busqueda server-side de posiciones origen con stock disponible.
- El mensaje de Baja aclara que solo muestra posiciones con stock disponible.

## Evidence

- `GET /api/v1/inventory/materials/?q=100100&limit=5` devuelve `100100`.
- `npm test -- --run ManualStockAdjustmentPage` paso con 4 tests.
- `python manage.py test tests.test_inventory_services --keepdb` paso con 12 tests.

## Regression Test

`frontend/src/features/operations/ManualStockAdjustmentPage.test.tsx` valida que:

- Alta busca articulos en `/api/v1/inventory/materials/?q=100100`.
- Seleccionar un articulo llena `Articulo` y `UOM`.
- Baja recarga origenes desde API al cambiar el criterio de busqueda.

## Status

DONE
