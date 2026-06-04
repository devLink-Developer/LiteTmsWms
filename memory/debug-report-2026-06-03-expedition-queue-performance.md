# Debug Report: Expedition Queue Performance

Date: 2026-06-03

## Symptom

En `/pedidos/entrega`, la consulta de pedidos tardaba mucho y en ocasiones no respondia.

## Root Cause

La cola de expedicion hacia trabajo sincronico repetido por cada busqueda amplia:

- Para busquedas por cliente/DNI, `refresh_legacy_impacts_for_fulfillments` consultaba impactos legacy pedido por pedido y reprocesaba impactos ya aplicados.
- La resolucion de snapshots de articulos llamaba `pos_freight_product_refs` por linea, repitiendo el mismo calculo/lectura para cada item de la misma tienda.
- La serializacion de entregas consultaba la hoja de ruta por entrega, aunque la cola ya cargaba un contexto masivo de movimientos.
- `RouteStop.source_type/source_ref`, usado para buscar paradas por entrega, no tenia indice compuesto.

## Fix

- `refresh_legacy_impacts_for_fulfillments` ahora consulta impactos legacy en bulk para varias ordenes y salta impactos locales `APPLIED` con la misma version de origen.
- El refresh devuelve cantidad de impactos procesados; `expedition_queue` solo recarga fulfillments si hubo cambios.
- `_resolve_line_item_snapshots` y `_resolve_legacy_line_item_snapshots` reutilizan refs POS de flete por tienda.
- `_build_movement_context` precalcula `route_assignments_by_delivery`; la serializacion de cola no llama `_delivery_route_assignment` por entrega.
- Se agrego indice `routestop_source_ref_idx` sobre `RouteStop(source_type, source_ref)`.

## Evidence

Medicion local con el cliente de mayor volumen (`customer_ref=20000042`, 298 pedidos locales, cola devuelve 100):

- Antes: primera corrida observada 64.021s.
- Perfil antes de optimizar impactos/snapshots: 20.779s, con 13.941s en refresh legacy.
- Despues de bulk + skip de impactos aplicados + cache POS + evitar recarga: 3.551s.

Tests ejecutados:

- `python manage.py test tests.test_fulfillment_delivery_flow --keepdb`
- `python manage.py test tests.test_api_filters --keepdb`
- `python manage.py makemigrations --check --dry-run`
- `python manage.py migrate`

Suite completa:

- `python manage.py test tests --keepdb` encontro 117 tests y falla por entorno: falta `pyarrow` en `.venv`, requerido por tests Parquet/ruteo. No esta relacionado con este cambio.

## Regression Tests

- La busqueda por cliente con multiples pedidos usa refresh bulk en vez de refresh por pedido.
- Impactos legacy ya aplicados con la misma version de origen no se reprocesan.
- Snapshots de lineas reutilizan refs POS de flete por tienda.
- La cola usa contexto precargado para `route_sheet` y no consulta asignacion de ruta por entrega.

## Status

DONE_WITH_CONCERNS: el fix y tests focalizados estan OK; la suite completa requiere instalar `pyarrow` en el entorno local.
