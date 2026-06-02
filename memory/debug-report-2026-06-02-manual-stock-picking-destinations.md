# Debug Report: Manual Stock Picking Destinations

Date: 2026-06-02

## Symptom

En `Alta y baja de articulos`, Alta mostraba `PR03DP-DSP-GEN` como posicion destino junto con `PR03DP-PRE-GEN`.

## Root Cause

El filtro de destinos usaba `purpose === "available" || is_dispatchable || is_pickable`. En la configuracion WMS, `DSP-GEN` tambien esta marcado `is_pickable=True`, pero su `purpose=available`; no es la posicion de picking/preparacion esperada para alta manual.

## Fix

Alta ahora lista solo ubicaciones activas con `purpose` `preparation` o `picking`.

## Evidence

Consulta real de `PR03DP`:

- `PR03DP-DSP-GEN`: `purpose=available`, `is_pickable=True`
- `PR03DP-PRE-GEN`: `purpose=preparation`, `is_pickable=True`
- `PR03DP-BAJ-ROT`: `purpose=breakage`
- `PR03DP-BAJ-PER`: `purpose=loss`

`npm test -- --run ManualStockAdjustmentPage` paso con 4 tests.

## Status

DONE
