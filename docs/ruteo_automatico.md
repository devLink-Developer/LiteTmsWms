# Ruteo Automatico

Este documento describe la funcionalidad de ruteo automatico implementada en Lite TMS/WMS para replicarla en otra aplicacion. La version actual es una propuesta operativa v1: genera una hoja de ruta editable, secuencia paradas con una heuristica deterministica y usa OpenRouteService cuando esta configurado para obtener distancia, duracion y geometria.

## Objetivo

Permitir que un operador seleccione entregas de reparto pendientes y genere una hoja de ruta preliminar por deposito y fecha, con:

- paradas ordenadas;
- peso y volumen consolidados;
- distancia y tiempo estimados;
- vehiculo y chofer opcionales durante el preview;
- validacion de capacidad antes de confirmar;
- trazabilidad de la propuesta generada;
- edicion manual antes de confirmar.

La funcionalidad no intenta resolver un VRP avanzado. La optimizacion v1 usa vecino mas cercano desde el origen y deja la ruta en estado `draft` para revision humana.

## Alcance Funcional

### Flujo principal

1. El usuario consulta entregas pendientes de reparto por `warehouse_ref` y `planned_date`.
2. El usuario selecciona entregas con coordenadas validas.
3. El sistema genera un preview automatico de hoja de ruta.
4. El sistema persiste la hoja en estado `draft`, con paradas y lineas.
5. El usuario revisa el mapa, puede reordenar paradas, mover coordenadas o quitar paradas.
6. El usuario asigna o confirma vehiculo y chofer.
7. El sistema valida capacidad por peso y volumen.
8. La ruta se confirma como `planned` y las paradas pasan a `allocated`.
9. Las entregas asociadas pasan a estado `assigned`.

### Estados relevantes

Ruta:

- `draft`: preview editable.
- `capacity_checked`: capacidad validada internamente.
- `planned`: ruta confirmada.
- `loading`: ruta en carga.
- `in_transit`: ruta en calle.
- `closed`: ruta cerrada.
- `closed_with_incident`: ruta cerrada con incidencias.
- `cancelled`: ruta anulada o reemplazada por una reoptimizacion.

Parada:

- `planned`: parada creada por el preview.
- `allocated`: parada confirmada en una ruta planificada.
- `loaded`: mercaderia cargada.
- `en_route`: parada en ejecucion.
- `delivered`: entrega exitosa.
- `failed`: entrega fallida.
- `rescheduled`: parada reprogramada.
- `cancelled`: parada anulada.

Entrega ruteable:

- Debe estar en `confirmed` o `prepared`.
- Debe ser una modalidad de reparto/envio.
- Debe tener lineas fisicas entregables.
- Debe tener coordenadas, ya sea en el payload del preview o en el snapshot de direccion.
- No debe estar ya asociada a una ruta activa no cancelada/no cerrada.

## Reglas Funcionales

- El preview requiere `warehouse_ref`.
- `planned_date` es opcional; si no se informa, se usa la fecha local del backend.
- `branch_ref` es opcional; si no se informa, toma el mismo valor que `warehouse_ref`.
- El vehiculo puede informarse en el preview, pero es obligatorio para confirmar.
- La confirmacion requiere revision previa del mapa o payload `reviewed: true`.
- Solo se editan paradas mientras la ruta esta en `draft`.
- Si una entrega no tiene coordenadas, no bloquea todo el preview: se informa en `preview_payload.excluded` con razon `missing_coordinates`.
- Si ninguna entrega queda ruteable, el sistema rechaza el preview.
- La capacidad se calcula por suma de peso y volumen de las paradas.
- Si peso o volumen superan el perfil del vehiculo, la confirmacion falla salvo override explicito.
- Toda mutacion critica requiere `Idempotency-Key`.
- Repetir la misma `Idempotency-Key` con el mismo payload devuelve el mismo resultado sin duplicar hojas, paradas ni auditorias.
- Reusar una `Idempotency-Key` con otro payload se considera error de negocio.
- Al reoptimizar el mismo deposito y fecha, las rutas `draft` existentes se consolidan en la nueva propuesta y se cancelan como reemplazadas.

## Modelo De Datos Minimo

### `route_sheet`

Hoja de ruta versionada.

Campos principales:

- `id`
- `route_number`
- `status`
- `branch_ref`
- `warehouse_ref`
- `vehicle_id`
- `driver_ref`
- `planned_date`
- `planned_weight_kg`
- `planned_volume_m3`
- `loaded_weight_kg`
- `loaded_volume_m3`
- `total_distance_km`
- `total_time_minutes`
- `routing_provider`
- `route_geometry`
- `preview_payload`
- `reviewed_at`
- `reviewed_by`
- `planning_version`
- `generated_by`
- `capacity_override_reason`
- timestamps y actor de creacion/actualizacion

Indices recomendados:

- `(warehouse_ref, planned_date, status)`
- `(status, planned_date)`
- `(driver_ref, planned_date, status)`
- `route_number` unico

### `route_stop`

Parada secuenciada dentro de una hoja de ruta.

Campos principales:

- `id`
- `route_id`
- `sequence`
- `status`
- `stop_type`
- `source_type`
- `source_ref`
- `customer_ref`
- `address_snapshot`
- `latitude`
- `longitude`
- `service_time_minutes`
- `planned_arrival_at`
- `time_window_start`
- `time_window_end`
- `planned_weight_kg`
- `planned_volume_m3`
- `outcome_status`
- `outcome_reason`
- `outcome_payload`
- referencias legacy opcionales

Restricciones e indices:

- unico `(route_id, sequence)`
- indice por `(status, sequence)`
- indice por `customer_ref`
- indice por referencias legacy si aplica

### `route_stop_line`

Lineas/cantidades de cada parada para trazabilidad y capacidad.

Campos principales:

- `id`
- `stop_id`
- `delivery_ref`
- `source_line_ref`
- `item_ref`
- `warehouse_ref`
- `quantity`
- `uom`
- `weight_kg`
- `volume_m3`
- `delivered_qty`
- `returned_qty`
- `difference_qty`
- `capacity_estimated`
- referencias legacy opcionales

Indices recomendados:

- `delivery_ref`
- `(item_ref, warehouse_ref)`

### `route_optimization_run`

Snapshot auditable de cada propuesta automatica.

Campos principales:

- `id`
- `route_id`
- `algorithm`
- `input_payload`
- `output_payload`
- `accepted`
- timestamps y actor

Cuando la ruta se confirma, sus corridas asociadas quedan con `accepted = true`.

### Entidades de soporte

- `vehicle_capacity_profile`: `max_weight_kg`, `max_volume_m3`.
- `vehicle`: codigo, patente, estado, perfil de capacidad, sucursal.
- `idempotency_key`: clave, hash de request, payload de respuesta y estado.
- `audit_trail`: eventos de negocio como `preview_created` y `stops_updated`.
- `status_history`: transiciones relevantes de ruta y parada.

## Datos De Entrada

Cada entrega debe exponer:

- `id`
- `delivery_number`
- `status`
- `delivery_mode`
- `planned_date`
- `warehouse_ref`
- `customer_ref`
- `legacy_sales_order_number`
- `address_snapshot`
- `lines`

Cada linea de entrega debe exponer:

- `id`
- `item_ref`
- `warehouse_ref`
- `planned_qty`
- `uom`
- `planned_weight_kg`
- `planned_volume_m3`
- referencias legacy si existen

El peso y volumen deben recalcularse o refrescarse desde el maestro logistico antes de rutear. En esta aplicacion se llama a `refresh_delivery_capacity_from_master` y luego se toman solo lineas fisicas.

## Origen De La Ruta

El origen se resuelve en este orden:

1. Coordenadas enviadas en el payload: `origin.lat` y `origin.lng`.
2. Configuracion `WAREHOUSE_ORIGINS`.
3. Snapshot de maestro logistico por deposito.
4. Geocodificacion del domicilio del deposito con OpenRouteService, si hay `ORS_API_KEY`.
5. Sin origen, se ordena de forma deterministica por coordenadas y referencia.

Ejemplo de `WAREHOUSE_ORIGINS`:

```json
{
  "W001": {
    "lat": "-34.590001",
    "lng": "-58.370002",
    "formatted": "Deposito W001",
    "source": "settings"
  }
}
```

## Algoritmo De Ruteo V1

1. Validar idempotencia del comando.
2. Resolver `planned_date`, `warehouse_ref`, `branch_ref`, vehiculo y chofer.
3. Resolver origen de la ruta.
4. Buscar rutas `draft` existentes del mismo deposito y fecha.
5. Tomar las entregas del payload y sumar las entregas de las rutas `draft` existentes.
6. Validar que cada entrega sea ruteable:
   - estado `confirmed` o `prepared`;
   - modalidad de reparto/envio;
   - lineas fisicas;
   - coordenadas disponibles.
7. Excluir entregas sin coordenadas y guardarlas en `preview_payload.excluded`.
8. Refrescar peso/volumen por linea desde maestro.
9. Secuenciar paradas con vecino mas cercano:
   - si hay origen, partir desde el origen;
   - tomar siempre la parada no visitada mas cercana por distancia Haversine;
   - repetir hasta agotar paradas;
   - si no hay origen, ordenar por `(latitude, longitude, source_ref)`.
10. Calcular distancia, duracion y geometria:
   - con `ORS_API_KEY`: llamar a OpenRouteService Directions `driving-car/geojson`;
   - sin `ORS_API_KEY` o ante error: usar fallback local.
11. Crear `route_sheet` en `draft`.
12. Crear `route_stop` con secuencia `1..N`.
13. Crear `route_stop_line` por cada linea fisica.
14. Cancelar drafts reemplazados y marcar `preview_payload.superseded_by`.
15. Crear `route_optimization_run`.
16. Crear auditoria `preview_created`.
17. Devolver la hoja serializada.

### Calculo fallback

Cuando no se puede usar OpenRouteService:

- Distancia: suma de distancias Haversine entre origen y paradas.
- Velocidad estimada: 40 km/h.
- Tiempo de servicio: `ROUTING_SERVICE_MINUTES_PER_STOP * cantidad_de_paradas`.
- `routing_provider`: `manual`.
- `routing_status`: `fallback_no_ors_key`, `fallback_ors_unavailable` o `fallback_insufficient_points`.
- `route_geometry`: `LineString` con origen y paradas en formato `[lng, lat]`.

### Proveedor ORS

Con `ORS_API_KEY`:

- Endpoint de direcciones: `/v2/directions/driving-car/geojson`.
- El request envia coordenadas `[[lng, lat], ...]`.
- La respuesta aporta:
  - distancia en metros;
  - duracion en segundos;
  - geometria GeoJSON.
- El sistema agrega tiempo de servicio por parada.
- `routing_provider`: `ors`.
- `routing_status`: `optimized`.

## Configuracion

Variables relevantes:

```env
ROUTING_PROVIDER=ors
ORS_API_KEY=
ORS_BASE_URL=https://api.openrouteservice.org
ROUTING_SERVICE_MINUTES_PER_STOP=10
WAREHOUSE_ORIGINS=
```

Notas:

- La variable `ROUTING_PROVIDER` queda disponible para evolucionar el proveedor, pero la implementacion actual usa ORS cuando existe `ORS_API_KEY` y fallback local cuando no.
- `WAREHOUSE_ORIGINS` debe ser JSON valido.
- Las coordenadas se guardan como decimales de alta precision.
- GeoJSON usa orden `[lng, lat]`; los modelos de parada usan campos separados `latitude` y `longitude`.

## API Recomendada

Base: `/api/v1`.

Headers para comandos:

```http
Content-Type: application/json
Idempotency-Key: route-preview-W001-2026-04-30-001
X-Actor: usuario.operador
```

### Consultar entregas pendientes

```http
GET /api/v1/routing/pending-deliveries/?warehouse_ref=W001&planned_date=2026-04-30
```

Respuesta:

```json
{
  "results": [
    {
      "id": "delivery-uuid",
      "delivery_number": "DEL-001",
      "status": "prepared",
      "delivery_mode": "Reparto programado",
      "planned_date": "2026-04-30",
      "warehouse_ref": "W001",
      "customer_ref": "CUST-001",
      "sales_order_number": "SO-001",
      "address_snapshot": {
        "street": "Calle 123",
        "latitude": "-34.600000",
        "longitude": "-58.380000"
      },
      "lat": "-34.600000",
      "lng": "-58.380000",
      "planned_weight_kg": "12.500",
      "planned_volume_m3": "0.350"
    }
  ]
}
```

### Generar preview automatico

```http
POST /api/v1/routing/optimize
```

Payload:

```json
{
  "warehouse_ref": "W001",
  "branch_ref": "BR-1",
  "planned_date": "2026-04-30",
  "vehicle_id": "vehicle-uuid",
  "driver_ref": "driver-1",
  "origin": {
    "lat": -34.590001,
    "lng": -58.370002
  },
  "deliveries": [
    {
      "delivery_id": "delivery-uuid",
      "lat": "-34.600000",
      "lng": "-58.380000"
    }
  ]
}
```

Respuesta:

```json
{
  "result": {
    "id": "route-uuid",
    "route_number": "HR-000001",
    "status": "draft",
    "warehouse_ref": "W001",
    "vehicle_id": "vehicle-uuid",
    "driver_ref": "driver-1",
    "planned_date": "2026-04-30",
    "planned_weight_kg": "12.500",
    "planned_volume_m3": "0.350",
    "total_distance_km": "4.120",
    "total_time_minutes": 18,
    "routing_provider": "ors",
    "route_geometry": {
      "type": "LineString",
      "coordinates": [
        [-58.370002, -34.590001],
        [-58.380000, -34.600000]
      ]
    },
    "preview_payload": {
      "excluded": [],
      "routing_status": "optimized",
      "input": {}
    },
    "stops": [
      {
        "id": "stop-uuid",
        "sequence": 1,
        "status": "planned",
        "source_type": "delivery_order",
        "source_ref": "delivery-uuid",
        "delivery_number": "DEL-001",
        "customer_ref": "CUST-001",
        "lat": "-34.600000",
        "lng": "-58.380000",
        "planned_weight_kg": "12.500",
        "planned_volume_m3": "0.350",
        "lines": []
      }
    ]
  }
}
```

### Editar orden, coordenadas o quitar paradas

```http
PATCH /api/v1/routesheets/{route_id}/stops
```

Payload:

```json
{
  "stops": [
    {
      "id": "stop-uuid",
      "sequence": 1,
      "lat": "-34.600500",
      "lng": "-58.380500"
    }
  ],
  "remove_stop_ids": []
}
```

Reglas:

- Solo permitido en rutas `draft`.
- Recalcula peso, volumen, distancia, tiempo y geometria.
- Incrementa `planning_version`.
- Marca `reviewed_at` y `reviewed_by`.

### Confirmar ruta

```http
PUT /api/v1/routesheets/{route_id}/confirm
```

Payload:

```json
{
  "vehicle_id": "vehicle-uuid",
  "driver_ref": "driver-1",
  "reviewed": true
}
```

Efectos:

- Valida capacidad del vehiculo.
- Cambia ruta a `planned`.
- Cambia paradas a `allocated`.
- Cambia entregas a `assigned`.
- Marca corridas de optimizacion como aceptadas.

## Respuesta De Errores

Formato:

```json
{
  "error": {
    "code": "business_rule_violation",
    "message": "Solo entregas confirmadas o preparadas pueden rutearse.",
    "details": {},
    "correlation_id": "req-..."
  }
}
```

Codigos usados:

- `400 validation_error`: payload invalido.
- `403 forbidden`: usuario sin permiso para el deposito.
- `404 not_found`: ruta o entrega inexistente.
- `422 business_rule_violation`: regla funcional incumplida.
- `422 capacity_violation`: exceso de capacidad.
- `503 master_data_unavailable`: maestro logistico no disponible.

## Seguridad Y Permisos

La aplicacion filtra operaciones por depositos autorizados:

- El usuario debe tener al menos un deposito autorizado para operar reparto.
- El `warehouse_ref` del payload debe estar dentro de sus depositos.
- Todas las entregas del payload deben pertenecer a depositos autorizados.
- La consulta de hojas y entregas nunca devuelve depositos no autorizados.

En otra aplicacion, este punto debe adaptarse al sistema de permisos propio, pero no conviene omitirlo porque evita rutear entregas de otro deposito por error operativo.

## UI Recomendada

Pantalla operativa de ruteo:

- Filtros: deposito, fecha, estado de ruta.
- Lista de entregas pendientes con peso, volumen, cliente, pedido y coordenadas.
- Selector de vehiculo y chofer.
- Boton `Optimizar`.
- Mapa con:
  - origen;
  - marcadores de paradas;
  - linea de ruta;
  - labels permanentes con secuencia.
- Panel lateral de hoja de ruta:
  - capacidad usada vs capacidad del vehiculo;
  - distancia y tiempo;
  - estado de proveedor;
  - paradas ordenables por drag and drop;
  - accion para quitar parada;
  - acciones de confirmar, iniciar carga, salir y cerrar.

Comportamientos esperados:

- Antes del preview, mostrar entregas seleccionables.
- Despues del preview, bloquear seleccion directa y trabajar sobre la ruta `draft`.
- Permitir arrastrar marcadores solo en `draft`.
- Deshabilitar confirmacion si no hay vehiculo, si no hay paradas o si capacidad excede.
- Mostrar advertencia cuando `routing_status` empiece con `fallback`.

## Checklist Para Implementar En Otra Aplicacion

1. Crear entidades equivalentes a `route_sheet`, `route_stop`, `route_stop_line` y `route_optimization_run`.
2. Asegurar maestro de vehiculos con peso y volumen maximo.
3. Exponer entregas ruteables con estado, modalidad, fecha, deposito, lineas, peso, volumen y coordenadas.
4. Resolver origen por deposito.
5. Implementar idempotencia por comando.
6. Implementar algoritmo de vecino mas cercano.
7. Integrar ORS Directions para distancia/geometria y fallback local.
8. Persistir cada preview como `draft`, no solo devolverlo en memoria.
9. Permitir revision manual antes de confirmar.
10. Validar capacidad al confirmar.
11. Auditar preview, reordenamiento, confirmacion y cancelacion de drafts reemplazados.
12. Agregar permisos por deposito.
13. Cubrir pruebas automatizadas de reglas criticas.

## Casos De Prueba Minimos

- Preview exitoso con una entrega preparada y coordenadas.
- Preview idempotente: repetir misma clave no duplica hoja.
- Reusar misma clave con payload distinto falla.
- Confirmacion sin revision falla.
- Confirmacion con vehiculo y `reviewed: true` cambia ruta a `planned`.
- Entrega en estado no ruteable falla.
- Entrega sin coordenadas queda excluida.
- Preview sin entregas validas falla.
- Reoptimizacion del mismo deposito y fecha cancela draft anterior.
- Quitar parada de draft devuelve la entrega al pool pendiente.
- Reordenar paradas recalcula metricas y sube `planning_version`.
- Capacidad excedida bloquea confirmacion.
- Sin `ORS_API_KEY`, el fallback devuelve distancia, tiempo y `LineString`.
- Con origen configurado, la primera coordenada de la geometria es exactamente el origen.
- Usuario sin permiso para el deposito recibe `403`.

## Fuentes En Este Repositorio

Archivos principales:

- `backend/apps/routes/models.py`: modelos de ruta, parada, lineas, asignacion y corridas de optimizacion.
- `backend/apps/routes/services.py`: reglas de negocio, algoritmo, ORS, fallback, idempotencia y confirmacion.
- `backend/apps/routes/api.py`: endpoints y permisos por deposito.
- `backend/apps/routes/urls.py`: rutas HTTP.
- `frontend/src/api/routing.ts`: contrato usado por la SPA.
- `frontend/src/features/routing/RoutePlanningPage.tsx`: experiencia de usuario de planificacion.
- `backend/tests/test_route_transfer_flow.py`: pruebas de preview, reoptimizacion, origen, confirmacion y ejecucion.

