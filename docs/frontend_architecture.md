# Arquitectura Frontend

## Principio Visual

La SPA es una consola operativa empresarial, desktop-first, densa y estable. La paleta obligatoria se implementa como tokens Tailwind:

- `night`: `#071a2e`
- `primary`: `#1f6bb4`
- `primaryHover`: `#0f4f8c`
- `deep`: `#08253f`
- `softStart`: `#f3f8fd`
- `softMid`: `#eef5fb`
- `softEnd`: `#e4edf7`
- `surface`: `#f5f9fd`
- `borderSoft`: `#d6e2ef`
- `secondaryText`: `#4c6480`

Se usan acentos semanticos para warning/success/danger porque los estados no deben depender solo de azul.

## Estructura

```text
src/
  app/router.tsx
  layouts/AppShell.tsx
  shared/components/
  shared/data/modules.ts
  stores/
  features/dashboard/
  features/operations/
  api/client.ts
  types/
```

## Router

- `/dashboard`
- `/recepciones`
- `/transferencias`
- `/pedidos`
- `/entregas` redirige a `/entregas/expedicion`
- `/entregas/expedicion`
- `/hojas-ruta`
- `/vehiculos`
- `/stock`
- `/auditorias`
- `/despacho-tienda`
- `/envios`

## Layout

- Sidebar fija desktop.
- Topbar compacta con contexto de sucursal/warehouse/rol.
- Area central con tablas densas.
- Drawer derecho para detalle, timeline y referencias cruzadas.

## Stores Zustand

Hay store por dominio:

- `useReceiptsStore`
- `useTransfersStore`
- `useOrdersStore`
- `useDeliveriesStore`
- `useRoutesStore`
- `useVehiclesStore`
- `useInventoryStore`
- `useAuditsStore`
- `useDispatchStore`
- `useShippingStore`

Cada store mantiene:

- filtros persistentes;
- seleccion multiple;
- registro activo;
- estado de drawer;
- loading/error.

## Componentes

- `KpiStrip`
- `FilterBar`
- `DataTable`
- `StatusBadge`
- `DrawerPanel`
- `Timeline`

## UX Operativa

- Filtros frecuentes siempre visibles.
- Acciones por fila y accion primaria por pantalla.
- Estados con badge textual y color.
- Skeleton/error/empty pendientes de conectar contra API real.
- Sin cards decorativas grandes ni landing.
- Tablas preparadas para paginacion server-side y virtualizacion posterior.

## Permisos UI

Patron:

- `module:view`
- `module:create`
- `module:edit`
- `module:approve`
- `module:close`
- `module:cancel`
- `module:adjust`
- `module:export`

La UI oculta acciones no permitidas y deshabilita acciones invalidas por estado con motivo visible.
