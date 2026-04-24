# Solicitud De Schema TMS/WMS

Este archivo documenta las extensiones necesarias para implementar TMS/WMS. No se solicita modificar el modelo legacy salvo indices recomendados. Las nuevas tablas pertenecen al dominio operativo y deben vivir idealmente en un esquema separado `tmswms` o, si la infraestructura no lo permite, con prefijo por app.

## Principios

- No crear foreign keys fisicas hacia tablas legacy.
- Guardar referencias logicas legacy: `TransactionNumber`, `SalesOrderNumber`, `retailLineItemId`, `SalesOrderLineRecId`, `RecId`, `ItemNumber`, `Warehouse`, `StoreId`.
- Crear FKs fisicas solo entre tablas nuevas del dominio TMS/WMS cuando ayuden a preservar integridad interna.
- Usar UUID como PK operativa.
- Incluir `created_at`, `updated_at`, `created_by`, `updated_by`.
- Comandos criticos deben ser idempotentes.
- Movimientos de stock posteados son append-only; correcciones por reversa.

## Indices Legacy Recomendados

No son obligatorios para arrancar, pero reducen costo operativo:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_txn_sales_order_number
  ON transactions_orders_transaction ("SalesOrderNumber");
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_txn_transaction_warehouse
  ON transactions_orders_transaction ("TransactionNumber", "Warehouse");
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_line_sales_order_line
  ON "transactions_orders_retailLineItem" ("SalesOrderNumber", "LineNumber");
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_line_item_number
  ON "transactions_orders_retailLineItem" ("ItemNumber");
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_line_fulfillment_store
  ON "transactions_orders_retailLineItem" ("FulfillmentStoreId");
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_line_shipping_warehouse
  ON "transactions_orders_retailLineItem" ("ShippingWarehouseId");
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_line_status_requested_date
  ON "transactions_orders_retailLineItem" ("OrderStatus", "RequestedShippingDate");
```

## Tablas Nuevas

| Tabla | Por que se necesita | Por que no alcanza lo actual | Claves e indices |
|---|---|---|---|
| `core_audit_trail` | Auditoria funcional de cambios criticos. | Legacy solo tiene campos generales de creacion/modificacion, no payload de cambio ni motivo. | PK `id`; idx `(entity_type, entity_id)`, `(action, created_at)`, `correlation_id`. |
| `core_status_history` | Historial de transiciones de estado. | No hay maquinas de estado logisticas. | PK `id`; idx `(entity_type, entity_id, created_at)`, `(to_status, created_at)`. |
| `core_idempotency_key` | Deduplicar comandos y reintentos. | Flags `LegacySent/LogisticsSent` no son control de comandos. | UQ `key`; idx `(operation_type, reference_type, reference_id)`. |
| `core_domain_event_outbox` | Publicar eventos post-commit hacia integraciones/cache. | No hay outbox ni trazabilidad de reintentos. | PK `id`; idx `(status, created_at)`, `(aggregate_type, aggregate_id)`. |
| `inventory_balance` | Proyeccion materializada por warehouse/item/estado. | `maestros_stock_warehousestockrecord` es snapshot externo y no distingue buckets operativos. | UQ `(warehouse_ref, item_ref, lot_ref, stock_state, uom)`; idx `(warehouse_ref, item_ref)`. |
| `inventory_ledger_entry` | Fuente de verdad transaccional de stock. | No existe historial append-only de movimientos. | UQ `idempotency_key`; idx `(warehouse_ref, item_ref, stock_state)`, `(document_type, document_ref)`, legacy refs. |
| `inventory_reservation` | Reserva operativa por pedido/transferencia. | El snapshot no diferencia disponible/reservado/preparacion. | idx `(status, warehouse_ref)`, `(source_type, source_ref)`, `legacy_sales_order_number`. |
| `inventory_reservation_line` | Detalle de reserva por linea. | Entregas parciales requieren trazabilidad por `retailLineItemId`. | idx `(item_ref, warehouse_ref)`, `legacy_line_id`. |
| `inventory_transformation` | Canjes, conversiones y cortes/fraccionamientos. | Un ajuste no conserva linaje origen-destino. | idx `(transformation_type, status)`, `(conversion_group_id)`. |
| `inventory_transformation_line` | Inputs/outputs/merma de transformacion. | Se necesita reconstruir material padre-hijo. | idx `(role, item_ref)`, `parent_line_ref`. |
| `purchase_order_receipt` | Cabecera de recepcion por OC. | No existe documento operativo de recepcion parcial/diferencia. | idx `(purchase_order_ref)`, `(warehouse_ref, status)`. |
| `purchase_order_receipt_line` | Lineas esperadas/recibidas/diferencias. | La OC o pedido no registra recepcion fisica granular. | idx `(item_ref, warehouse_ref)`, `incident_ref`. |
| `transfer_order` | Solicitud y lifecycle de transferencia. | No existe origen/destino/transito/recepcion parcial. | UQ `transfer_number`; idx `status`, origen/destino. |
| `transfer_order_line` | Cantidades solicitadas, enviadas, recibidas y diferencias. | No hay trazabilidad por linea entre almacenes. | UQ `(transfer_id, line_number)`; idx item/warehouse. |
| `transfer_shipment` | Despacho de origen. | Transferencia no puede inferirse solo de stock. | UQ `shipment_number`; FK interna a transfer. |
| `transfer_receipt` | Recepcion total/parcial en destino. | Diferencias destino requieren documento propio. | UQ `receipt_number`; FK interna a transfer. |
| `fulfillment_order` | Orquestacion desde pedido legacy. | Pedido legacy no debe mutarse ni duplicarse. | UQ `fulfillment_number`; idx `legacy_sales_order_number`, estado. |
| `fulfillment_order_line` | Estado operativo por linea de pedido. | `retailLineItem` no diferencia reservado/preparado/anulable. | idx `legacy_line_id`, item/warehouse. |
| `delivery_order` | Entrega planificada desde fulfillment. | Un pedido puede tener multiples entregas. | UQ `delivery_number`; idx estado/fecha/modo. |
| `delivery_order_line` | Cantidades por entrega. | Split parcial exige trazabilidad por linea. | FK interna a delivery y fulfillment line. |
| `delivery_split` | Registro explicito del split y remanente. | No alcanza con actualizar cantidad entregada acumulada. | idx lineas internas; guardar `remaining_after_split`. |
| `vehicle_capacity_profile` | Peso/volumen maximo reusable. | No hay maestro de vehiculos ni capacidad. | UQ `name`. |
| `vehicle` | Maestro de vehiculos y disponibilidad. | Ruteo necesita recurso asignable. | UQ `code`, `plate`; idx `(status, branch_ref)`. |
| `route_sheet` | Hoja de ruta versionada. | No existe documento de transporte. | UQ `route_number`; idx `(status, planned_date)`, warehouse. |
| `route_stop` | Paradas secuenciadas con estado propio. | La direccion de pedido no conserva ejecucion de parada. | UQ `(route_id, sequence)`; idx estado, cliente, legacy refs. |
| `route_stop_line` | Lineas/cantidades por parada. | Capacidad y trazabilidad deben calcularse por linea. | idx delivery, item/warehouse. |
| `route_assignment` | Asignacion de vehiculo y motivo. | Debe auditarse reasignacion. | FK interna a route/vehicle. |
| `route_optimization_run` | Snapshot de ruteo automatico. | Se requiere versionar propuesta y re-ruteos. | FK route; guardar input/output payload. |
| `warehouse_audit` | Conteos, conteo ciego y aprobacion. | No hay documento de auditoria. | UQ `audit_number`; idx warehouse/status. |
| `warehouse_audit_line` | Diferencias por item. | Ajuste agregado no explica conteo. | idx item/warehouse, requires_approval. |
| `store_dispatch` | Retiro en tienda, terceros y validaciones. | Envio/retiro no vive en pedido legacy. | UQ `dispatch_number`; idx estado/warehouse/cliente. |
| `store_dispatch_line` | Retiro total/parcial por linea. | El pedido no registra validacion de mostrador. | idx item/warehouse, legacy_line_id. |
| `shipment` | Envio y tracking interno. | Modo de entrega legacy no es lifecycle de envio. | UQ `shipment_number`; idx estado/fecha, delivery, route. |
| `shipment_event` | Eventos de envio/intentos/reprogramacion. | No hay timeline de tracking. | idx `(shipment_id, created_at)`, event type. |
| `logistics_incident` | Incidencias transversales. | Diferencias no deben quedar como texto suelto. | UQ `incident_number`; idx domain/status, entity. |

## Pseudo-DDL Base

```sql
CREATE TABLE tmswms.inventory_ledger_entry (
  id uuid PRIMARY KEY,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  created_by varchar(120) NOT NULL DEFAULT '',
  warehouse_ref varchar(80) NOT NULL,
  item_ref varchar(60) NOT NULL,
  stock_state varchar(30) NOT NULL,
  movement_type varchar(40) NOT NULL,
  direction varchar(20) NOT NULL,
  quantity numeric(18,6) NOT NULL CHECK (quantity > 0),
  uom varchar(20) NOT NULL,
  document_type varchar(80) NOT NULL,
  document_ref varchar(80) NOT NULL,
  idempotency_key varchar(120) NOT NULL UNIQUE,
  legacy_transaction_number varchar(60) NOT NULL DEFAULT '',
  legacy_sales_order_number varchar(60) NOT NULL DEFAULT '',
  legacy_line_id varchar(60) NOT NULL DEFAULT '',
  legacy_rec_id varchar(60) NOT NULL DEFAULT '',
  payload jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE tmswms.inventory_balance (
  id uuid PRIMARY KEY,
  warehouse_ref varchar(80) NOT NULL,
  item_ref varchar(60) NOT NULL,
  lot_ref varchar(80) NOT NULL DEFAULT '',
  stock_state varchar(30) NOT NULL,
  uom varchar(20) NOT NULL,
  quantity numeric(18,6) NOT NULL DEFAULT 0,
  version integer NOT NULL DEFAULT 1,
  UNIQUE (warehouse_ref, item_ref, lot_ref, stock_state, uom)
);
```

El resto de tablas sigue el mismo patron definido en los modelos Django iniciales.

## Impacto En Integraciones

- El POS sigue consumiendo parquet/cache; el TMS/WMS publica eventos para regeneracion o reconciliacion.
- `LogisticsSent` puede usarse como ayuda de integracion, nunca como estado de negocio principal.
- Los backfills deben ser idempotentes por clave natural legacy.
- Las migraciones son aditivas y no bloquean lectura del legacy.
