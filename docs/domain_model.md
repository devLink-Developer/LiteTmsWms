# Modelo De Dominio

## Bounded Contexts

- `core`: auditoria, historial de estados, idempotencia y outbox.
- `integrations.legacy`: modelos unmanaged y adaptadores de lectura a Litecore.
- `inventory`: ledger, balances, reservas, recepciones, ajustes y transformaciones.
- `transfers`: transferencia entre almacenes con origen, transito, destino e incidencias.
- `fulfillment`: vinculacion de pedido legacy, preparacion, split y entregas.
- `routes`: hojas de ruta, paradas, secuencia y ruteo automatico v1.
- `vehicles`: vehiculos, capacidad y disponibilidad.
- `audits`: conteos, diferencias, aprobacion y ajustes.
- `dispatch`: retiro/despacho en tienda.
- `shipping`: envios, intentos, reprogramacion y cierre.
- `logistics`: incidencias y orquestacion transversal.

## Fuente De Verdad

- Pedido, cliente y articulo: legacy Litecore.
- Stock operativo: `inventory_ledger_entry`.
- Lectura rapida de stock: `inventory_balance`.
- Cache POS/parquet: proyeccion runtime.
- Estado logistico: entidades nuevas TMS/WMS.

## Estados

| Entidad | Estados |
|---|---|
| Recepcion | `draft`, `expected`, `receiving`, `partial_received`, `received`, `with_incident`, `closed`, `cancelled` |
| Reserva | `open`, `partially_allocated`, `allocated`, `released`, `consumed`, `expired`, `cancelled` |
| Transferencia | `requested`, `approved`, `picking`, `dispatched`, `in_transit`, `partial_received`, `received`, `discrepant`, `closed`, `cancelled` |
| Fulfillment | `pending`, `allocated`, `preparing`, `ready_for_dispatch`, `partially_delivered`, `delivered`, `rescheduled`, `closed`, `cancelled` |
| Entrega | `created`, `planned`, `assigned`, `loaded`, `in_route`, `attempted`, `delivered_partial`, `delivered_complete`, `returned`, `cancelled` |
| Ruta | `draft`, `planned`, `capacity_checked`, `assigned`, `loading`, `in_transit`, `closed`, `cancelled` |
| Parada | `pending`, `planned`, `allocated`, `loaded`, `en_route`, `arrived`, `delivered`, `failed`, `rescheduled`, `cancelled` |
| Vehiculo | `available`, `reserved`, `in_route`, `maintenance`, `out_of_service`, `retired` |
| Auditoria | `draft`, `counting`, `counted`, `discrepancy_review`, `adjustment_pending_approval`, `approved`, `posted`, `closed`, `cancelled` |
| Despacho tienda | `requested`, `authorized`, `prepared`, `counter_ready`, `partial_pickup`, `picked_up`, `with_incident`, `closed`, `cancelled` |
| Envio | `pending`, `prepared`, `dispatched`, `in_transit`, `attempted`, `rescheduled`, `delivered`, `returned`, `closed`, `cancelled` |
| Transformacion | `draft`, `validated`, `posted`, `reversed` |

## Invariantes

- No reservar mas que lo disponible.
- No preparar mas que lo reservado.
- No despachar mas que lo preparado.
- No recibir mas que lo despachado salvo incidencia documentada.
- No cerrar una entrega parcial sin recalcular remanente.
- No cerrar auditoria con diferencias sin resolucion o ajuste aprobado.
- No cerrar ruta si excede capacidad por peso o volumen salvo override aprobado.
- No editar un movimiento de stock posteado; se corrige con contramovimiento.
- No fraccionar/cortar sin registrar origen, destino, factor, unidad y merma.
- Toda transicion critica registra actor, timestamp, motivo y payload resumido.

## Relacion Operativa

```text
LegacyOrder -> FulfillmentOrder -> DeliveryOrder -> RouteStop -> Shipment
          \                 \             \             \
           \                 \             \             AuditTrail/StatusHistory
            \                 \             InventoryLedgerEntry
             \                 DeliverySplit
              InventoryReservation
```

Las relaciones hacia legacy se resuelven por adaptadores y claves logicas, no por FKs fisicas.
