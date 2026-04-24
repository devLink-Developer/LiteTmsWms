# Contratos API

Base: `/api/v1`.

Las respuestas de error siguen:

```json
{
  "error": {
    "code": "business_rule_violation",
    "message": "La hoja de ruta excede la capacidad del vehiculo.",
    "details": {},
    "correlation_id": "req-..."
  }
}
```

## Reglas Generales

- `GET` usa paginacion server-side, filtros y orden.
- `POST`, `PATCH` y comandos de estado requieren `Idempotency-Key`.
- `409` para conflicto de estado.
- `422` para violacion de regla de negocio.
- `403` para permiso insuficiente.
- Payloads incluyen referencias legacy cuando apliquen.

## Inventario

`GET /inventory/balances?warehouse=&item=&state=`

```json
{
  "results": [
    {
      "id": "uuid",
      "warehouse_ref": "PS003MT",
      "item_ref": "1000123",
      "stock_state": "on_hand",
      "quantity": "12.000000",
      "uom": "UN",
      "version": 4
    }
  ]
}
```

`GET /inventory/ledger?reference_type=&reference_id=`

`POST /inventory/reservations`

```json
{
  "warehouse_ref": "PS003MT",
  "source_type": "sales_order",
  "source_ref": "SO-100",
  "actor": "operador.wms",
  "lines": [
    {
      "item_ref": "1000123",
      "quantity": "2",
      "uom": "UN",
      "legacy_sales_order_number": "SO-100",
      "legacy_line_id": "44321"
    }
  ]
}
```

## Transferencias

- `GET /transfers/`
- `POST /transfers/`
- `POST /transfers/{id}/approve`
- `POST /transfers/{id}/ship`
- `POST /transfers/{id}/receive`
- `POST /transfers/{id}/close`

Reglas:

- `receive` puede ser parcial.
- `received_qty > shipped_qty` requiere incidencia.
- `close` exige diferencias resueltas o documentadas.

## Fulfillment Y Entregas

- `GET /fulfillment/`
- `POST /fulfillment/from-legacy-order`
- `POST /fulfillment/{id}/split`
- `GET /fulfillment/expedition-queue/`
- `GET /fulfillment/deliveries/`
- `POST /fulfillment/deliveries/{id}/validate-stock`
- `POST /fulfillment/deliveries/{id}/remito`
- `GET /fulfillment/deliveries/{id}/remito.pdf`
- `POST /fulfillment/deliveries/{id}/reschedule`
- `POST /fulfillment/deliveries/{id}/complete`

Split:

```json
{
  "legacy_sales_order_number": "SO-100",
  "legacy_line_id": "44321",
  "delivery_mode": "home_delivery",
  "split_qty": "3",
  "reason": "Entrega parcial por disponibilidad"
}
```

Ingesta local desde Litecore:

```json
{
  "sales_order_number": "SO-100"
}
```

Validacion de stock y emision de remito requieren `Idempotency-Key`.

## Rutas Y Vehiculos

- `GET /routes/`
- `POST /routes/preview`
- `POST /routes/`
- `POST /routes/{id}/assign-vehicle`
- `POST /routes/{id}/recalculate`
- `POST /routes/{id}/close`
- `GET /vehicles/`
- `POST /vehicles/`
- `PATCH /vehicles/{id}`

`POST /routes/preview` devuelve propuesta con capacidad, excluidos y secuencia sugerida.

## Auditorias

- `GET /audits/`
- `POST /audits/`
- `POST /audits/{id}/count`
- `POST /audits/{id}/approve-adjustments`
- `POST /audits/{id}/post`
- `POST /audits/{id}/close`

## Despacho Y Envios

- `GET /dispatch/`
- `POST /dispatch/{id}/validate-pickup`
- `POST /dispatch/{id}/partial-pickup`
- `GET /shipping/`
- `POST /shipping/{id}/attempt`
- `POST /shipping/{id}/reschedule`
- `POST /shipping/{id}/deliver`

## Idempotencia

Para comandos:

```http
Idempotency-Key: sales-order-SO-100-split-001
```

Si se repite la misma clave, el backend debe devolver la misma respuesta o una respuesta equivalente sin duplicar movimientos, entregas, auditorias ni eventos.
