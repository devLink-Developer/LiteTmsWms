# Lite TMS/WMS

Microservicio TMS/WMS para operar recepcion, stock transaccional, transferencias, fulfillment, entregas parciales, hojas de ruta, vehiculos, auditorias, despacho en tienda y envios sobre el ecosistema Litecore existente.

La base actual aporta pedidos, lineas, clientes, articulos, precios, atributos logisticos y stock snapshot por warehouse. Este proyecto agrega el dominio operativo que falta sin reestructurar tablas legacy ni asumir foreign keys fisicas inexistentes.

## Stack

- Docker
- Django 6.0.1
- React 19.2.4
- Vite 8.x con `@vitejs/plugin-react`
- TypeScript 5.9.x
- React Router DOM 7.13.2
- Zustand 5.0.12
- Tailwind CSS 3.4.17
- Bootstrap 5.3.3 + Bootstrap Icons solo para UI legado/templates Django
- Vitest 4.1.2 + Testing Library
- Gunicorn + WhiteNoise

## Puertos

La aplicacion publica la SPA en `8021:8021`.

El backend escucha en `8021` dentro del contenedor `backend` y queda accesible desde la SPA via proxy Vite (`/api -> http://backend:8021`). No se publica otro `8021` del backend en el host porque dos procesos no pueden ocupar el mismo puerto del host al mismo tiempo.

## Arquitectura

```text
backend/
  config/
  apps/
    common/
    core/
    integrations/legacy/
    inventory/
    transfers/
    fulfillment/
    routes/
    vehicles/
    audits/
    dispatch/
    shipping/
    logistics/
frontend/
  src/app/
  src/layouts/
  src/shared/
  src/stores/
  src/features/
docs/
```

El backend es un modular monolith Django. Cada app representa un bounded context y expone modelos, servicios de aplicacion y endpoints JSON iniciales. El frontend es una SPA operativa desktop-first con sidebar, filtros persistentes, tablas densas, drawer de detalle y timeline.

## Reutilizacion Del Esquema Actual

Se reutiliza como fuente de lectura:

- `transactions_orders_transaction`: cabecera de pedido, `TransactionNumber`, `SalesOrderNumber`, `CustomerAccount`, `Warehouse`, `StoreId`.
- `transactions_orders_retailLineItem`: lineas de pedido, `retailLineItemId`, `SalesOrderLineRecId`, `ItemNumber`, cantidades, modo de entrega, coordenadas y almacenes.
- `transactions_orders_tender`: pagos asociados para conciliacion.
- `transactions_line_tax`: impuestos canonicos por linea.
- `Maestros_Clientes`, `Maestros_Clientes_Direcciones`, `Maestros_Clientes_Contactos`: cliente, direcciones y contactos.
- `maestros_materiales_sap`, `maestros_articulos_parametros`, `fletes_product_table`, `fletes_invent_item_sales_setup`: atributos, dimensiones, peso, volumen y restricciones logisticas.
- `maestros_stock_warehousestockrecord`: snapshot para seed/reconciliacion, no verdad transaccional.
- parquet runtime: cache operativo POS, no persistencia del TMS/WMS.

## Decisiones Tecnicas

- No se crean FKs fisicas hacia legacy.
- Las relaciones con legacy son logicas: `TransactionNumber`, `SalesOrderNumber`, `retailLineItemId`, `RecId`, `ItemNumber`, `Warehouse`, `StoreId`.
- El stock operativo se resuelve con ledger inmutable + balances derivados.
- Reservas, preparacion, despacho, transito y entrega son estados diferenciados.
- Un pedido legacy puede generar multiples entregas y cada entrega conserva remanente.
- Transferencias modelan salida origen, transito, recepcion parcial/final e incidencias.
- Fraccionamiento/corte es una transformacion de primera clase, no un ajuste.
- Ruteo v1 usa heuristica deterministica por warehouse, zona, fecha, prioridad y capacidad.
- Mutaciones criticas exigen `Idempotency-Key`.
- Todo cambio de estado relevante genera `StatusHistory` y/o `AuditTrail`.

## Ejecucion

Crear `.env` desde `.env.example` y luego:

```powershell
docker compose up --build
```

SPA:

```text
http://localhost:8021
```

Backend healthcheck por proxy:

```text
http://localhost:8021/api/v1/health/
```

Backend local sin Docker:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8021
```

Frontend local:

```powershell
cd frontend
npm install
npm run dev
```

## Prueba Local Contra Litecore

Para probar sin tocar QA, el backend Docker usa el contenedor local `litecore_db` publicado en `localhost:5433` desde el host. Dentro de Docker se conecta por `host.docker.internal:5433`.

Las tablas legacy `public.transactions_orders%` son solo lectura. Todo lo administrado por TMS/WMS se crea en el schema `tmswms`.

```powershell
docker compose up -d --build backend frontend
docker compose exec -T backend python manage.py ensure_tmswms_schema
docker compose exec -T backend python manage.py migrate --noinput
docker compose exec -T backend python manage.py sync_legacy_orders --limit 10
```

Endpoints principales de la prueba:

- `POST /api/v1/fulfillment/from-legacy-order`
- `GET /api/v1/fulfillment/expedition-queue/`
- `POST /api/v1/fulfillment/{id}/split`
- `POST /api/v1/fulfillment/deliveries/{id}/validate-stock`
- `POST /api/v1/fulfillment/deliveries/{id}/remito`
- `GET /api/v1/fulfillment/deliveries/{id}/remito.pdf`

## Estado De La Base

Incluye:

- scaffold Django ejecutable;
- modelos iniciales por dominio;
- adaptadores unmanaged para tablas legacy principales;
- servicios iniciales de inventario con ledger, balance, reservas e idempotencia;
- endpoints JSON base;
- SPA navegable con modulos operativos;
- Docker;
- documentacion tecnica y solicitud de schema.

## Proximos Pasos

1. Revisar `solicitud_schema.md` con DBA/integraciones.
2. Generar migraciones iniciales del dominio nuevo.
3. Completar comandos de estado por dominio.
4. Conectar endpoints reales al frontend.
5. Agregar pruebas de concurrencia e idempotencia para cada comando critico.
6. Definir politica final de publicacion a parquet/cache operativo.
