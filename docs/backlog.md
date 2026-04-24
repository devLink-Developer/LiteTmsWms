# Backlog Tecnico

## Fase 1 - Base Contractual

- Aprobar `solicitud_schema.md`.
- Definir nombres definitivos de tablas/esquema.
- Generar migraciones iniciales.
- Confirmar estrategia de lectura legacy y permisos DB.

## Fase 2 - Integracion Legacy

- Completar adapters para clientes, direcciones, articulos, stock snapshot y parquets.
- Implementar cursores de sincronizacion.
- Agregar outbox/inbox real.
- Crear fixtures legacy.

## Fase 3 - Inventario

- Completar ledger, balances, reservas, picking, despacho y ajustes.
- Agregar concurrencia y pruebas de contencion.
- Implementar fraccionamiento/corte completo.

## Fase 4 - Fulfillment Y Transferencias

- Crear fulfillment desde pedido legacy.
- Implementar split de entregas.
- Implementar transferencia parcial y cierre con diferencias.

## Fase 5 - Transporte

- CRUD vehiculos.
- Planner v1 por capacidad/zona/fecha.
- Cierre de ruta con paradas e incidencias.

## Fase 6 - Auditoria, Despacho Y Envios

- Conteos ciegos.
- Aprobacion de ajustes.
- Retiro por tercero.
- Tracking interno de envios.

## Fase 7 - Frontend Operativo

- Conectar vistas a API real.
- Paginacion server-side.
- Permisos UI.
- Estados loading/empty/error/success.
- Tests de flujos criticos.

## Riesgos

- Calidad de peso/volumen en maestros.
- Ausencia de maestro explicito branch/warehouse en el esquema aportado.
- Alta contencion de stock por warehouse/item.
- Sincronizacion con parquet/cache POS.
- Diferencias entre estado comercial legacy y estado logistico nuevo.
