# Estrategia De Testing

## Piramide

1. Unit tests de servicios de dominio.
2. Integration tests Django con base transaccional.
3. Contract tests de API.
4. Frontend tests con Vitest + Testing Library.
5. E2E solo para flujos criticos.

## Backend

Casos iniciales:

- ledger actualiza balance;
- balance negativo se rechaza;
- idempotencia no duplica movimiento;
- reserva no excede disponible;
- preparacion no excede reservado;
- despacho no excede preparado;
- transferencia parcial conserva enviado/recibido/diferencia;
- fraccionamiento conserva linaje;
- ruta no cierra con capacidad excedida;
- auditoria no cierra con diferencias sin aprobacion.

Usar `TestCase` y `TransactionTestCase` para concurrencia. Las mutaciones criticas deben ejecutarse dentro de `transaction.atomic()` y bloquear balance con `select_for_update()`.

## API

Validar:

- `200/201` para lectura/creacion;
- `400` para payload invalido;
- `403` para permisos;
- `409` para transicion invalida;
- `422` para regla de negocio;
- formato homogeneo de error;
- `Idempotency-Key` obligatorio en comandos.

## Frontend

Casos iniciales:

- tabla densa renderiza columnas y acciones;
- filtros por busqueda/estado/warehouse;
- drawer muestra timeline y referencias;
- stores Zustand seleccionan y resetean filtros;
- permisos ocultan/deshabilitan acciones;
- error mantiene layout estable.

## E2E Prioritario

- recepcion parcial con diferencia;
- transferencia origen-transito-destino parcial;
- split de pedido en dos entregas;
- cierre de ruta bloqueado por capacidad;
- auditoria con ajuste aprobado.

## Criterios De Merge

- No se mergea mutacion de stock sin test de idempotencia.
- No se mergea transicion de estado sin test de estado invalido.
- No se mergea nueva pantalla sin prueba de render y accesibilidad basica.
- Todo bug operativo agrega test de regresion antes del fix.
