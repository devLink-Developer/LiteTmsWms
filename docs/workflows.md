# Workflows Operativos

## Recepcion De Compra

1. Crear recepcion esperada desde OC.
2. Iniciar conteo fisico.
3. Registrar cantidades recibidas por linea.
4. Generar ledger `inbound_receipt`.
5. Si hay diferencia, abrir incidencia.
6. Cerrar parcial o total.

Estados: `draft -> expected -> receiving -> partial_received|received|with_incident -> closed`.

## Stock

1. Toda entrada/salida se postea en `inventory_ledger_entry`.
2. `inventory_balance` se actualiza como proyeccion.
3. Reservas mueven disponibilidad desde `on_hand` hacia `reserved`.
4. Picking/preparacion consume `reserved`.
5. Despacho mueve a `packed/dispatched/in_transit` segun documento.
6. Correcciones se hacen por reversa o ajuste aprobado.

## Transferencias

1. Solicitar transferencia.
2. Aprobar si la politica lo exige.
3. Reservar y pickear en origen.
4. Despachar origen y mover a transito.
5. Recibir total o parcial en destino.
6. Registrar diferencias/incidencias.
7. Cerrar cuando lo recibido y lo observado quede conciliado.

Estados: `requested -> approved -> picking -> dispatched -> in_transit -> partial_received|received|discrepant -> closed`.

## Fulfillment Y Entregas Parciales

1. Leer pedido legacy.
2. Crear `FulfillmentOrder`.
3. Reservar stock por linea.
4. Crear una o varias `DeliveryOrder`.
5. Cada `DeliverySplit` registra cantidad y remanente.
6. Cambios de modo de entrega quedan auditados.
7. Cierre recalcula pendiente, entregado, preparado, reservado y anulable.

## Hojas De Ruta

1. Seleccionar entregas listas.
2. Agrupar por warehouse, zona y fecha.
3. Calcular peso/volumen por linea.
4. Asignar vehiculo.
5. Validar capacidad.
6. Secuenciar paradas.
7. Ejecutar ruta.
8. Cerrar total o con incidencias.

Ruteo v1 no resuelve VRP avanzado ni trafico real; deja persistida una sugerencia editable.

## Auditoria De Almacen

1. Crear auditoria.
2. Ejecutar conteo o conteo ciego.
3. Consolidar diferencias.
4. Solicitar aprobacion.
5. Postear ajuste.
6. Cerrar.

No se cierra con diferencias no aprobadas.

## Despacho En Tienda

1. Solicitar retiro.
2. Validar identidad o tercero autorizado.
3. Preparar mercaderia.
4. Retirar total/parcial.
5. Emitir comprobante operativo.
6. Registrar incidencia si aplica.

## Envios

1. Preparar envio.
2. Asociar entrega/ruta.
3. Registrar despacho.
4. Registrar intento de entrega.
5. Reprogramar, entregar o devolver.
6. Cerrar con timeline completo.

## Fraccionamiento / Corte

1. Crear transformacion `split`.
2. Registrar input de material origen.
3. Registrar outputs y merma si existe.
4. Validar conservacion de cantidad/unidad/factor.
5. Postear movimientos de ledger.
6. Mantener linaje padre-hijo.
