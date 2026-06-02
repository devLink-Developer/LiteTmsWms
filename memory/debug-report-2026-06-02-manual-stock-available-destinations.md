# Debug Report: Manual Stock Available Destinations

Date: 2026-06-02

## Symptom

La pantalla `Alta y baja de articulos` listaba posiciones de preparacion como destino de alta manual.

## Root Cause

La correccion anterior interpreto `is_pickable/preparation` como destino valido para alta. En este WMS, la alta manual debe ingresar a posiciones DISPONIBLE (`purpose=available`), por ejemplo `PR01DP-DSP-GEN`. Las posiciones `reserved`, `preparation`, `transit`, `breakage` y `loss` son transaccionales o de descarte.

## Fix

- Frontend: Alta manual ahora lista solo ubicaciones activas con `purpose=available`.
- Backend: `adjust_inventory_manually` rechaza altas manuales en ubicaciones cuyo `purpose` no sea `available`.

## Evidence

Consulta real:

- `PR01DP-DSP-GEN`: `purpose=available`
- `PR01DP-PRE-GEN`: `purpose=preparation`

Tests:

- `npm test -- --run ManualStockAdjustmentPage`
- `python manage.py test tests.test_inventory_services --keepdb`

## Status

DONE
