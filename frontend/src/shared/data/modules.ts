import type { NavigationEntry, NavigationLink, OperationModule, PlaceholderPageConfig } from "../../types/operations";

export const operationModules: OperationModule[] = [
  {
    key: "orders",
    label: "Listar pedidos",
    path: "/pedidos",
    description: "",
    apiPath: "/api/v1/fulfillment/",
    columns: ["Pedido", "Estado", "Warehouse", "Cliente", "Prioridad", "Lineas", "SLA"],
    permissions: ["orders:view", "orders:edit", "orders:split"],
    readOnly: true,
  },
  {
    key: "deliveries",
    label: "Entrega",
    path: "/pedidos/entrega",
    description: "",
    apiPath: "/api/v1/fulfillment/deliveries/",
    primaryAction: "Crear entrega",
    columns: ["Entrega", "Estado", "Warehouse", "Cliente", "Prioridad", "Cantidad", "SLA"],
    permissions: ["deliveries:view", "deliveries:edit", "deliveries:close"],
  },
  {
    key: "distribution",
    label: "Confirmacion de reparto",
    path: "/reparto/confirmacion",
    description: "",
    apiPath: "/api/v1/fulfillment/deliveries/?delivery_mode=Reparto",
    columns: ["Entrega", "Estado", "Warehouse", "Modo", "Prioridad", "Cantidad", "SLA"],
    permissions: ["deliveries:view", "routes:view"],
    readOnly: true,
  },
  {
    key: "receipts",
    label: "Ingresos por OC",
    path: "/ingresos/oc",
    description: "",
    apiPath: "/api/v1/inventory/receipts/",
    columns: ["OC", "Estado", "Warehouse", "Responsable", "Prioridad", "Cantidad", "SLA"],
    permissions: ["receipts:view", "receipts:create", "receipts:close"],
    readOnly: true,
  },
  {
    key: "transfers",
    label: "Ingresos por TR entre depositos",
    path: "/ingresos/tr-depositos",
    description: "",
    apiPath: "/api/v1/transfers/",
    columns: ["Transferencia", "Estado", "Origen", "Destino", "Prioridad", "Cantidad", "SLA"],
    permissions: ["transfers:view", "transfers:create", "transfers:approve"],
    readOnly: true,
  },
  {
    key: "returns",
    label: "Ingresos por devoluciones",
    path: "/ingresos/devoluciones",
    description: "",
    apiPath: "/api/v1/shipping/?status=returned",
    columns: ["Envio", "Estado", "Warehouse", "Entrega", "Prioridad", "Bultos", "SLA"],
    permissions: ["shipping:view", "returns:view"],
    readOnly: true,
  },
  {
    key: "routes",
    label: "Hojas de ruta",
    path: "/reparto/hojas-ruta",
    description: "",
    apiPath: "/api/v1/routes/",
    columns: ["Ruta", "Estado", "Warehouse", "Vehiculo", "Prioridad", "Paradas", "SLA"],
    permissions: ["routes:view", "routes:create", "routes:close"],
    readOnly: true,
  },
  {
    key: "stock",
    label: "Stock por almacen",
    path: "/stock/almacenes",
    description: "",
    apiPath: "/api/v1/inventory/balances/",
    columns: ["Item", "Estado", "Warehouse", "Origen", "Prioridad", "Cantidad", "SLA"],
    permissions: ["stock:view", "stock:adjust", "stock:transform"],
    readOnly: true,
  },
  {
    key: "stock-movements",
    label: "Movimientos de Stock",
    path: "/stock/movimientos",
    description: "",
    apiPath: "/api/v1/inventory/ledger/",
    columns: ["Movimiento", "Estado", "Warehouse", "Origen", "Prioridad", "Cantidad", "Fecha"],
    permissions: ["stock:view", "stock:ledger"],
    readOnly: true,
  },
  {
    key: "tasks",
    label: "Tareas de preparacion",
    path: "/pedidos/tareas",
    description: "",
    apiPath: "/api/v1/fulfillment/preparation-tasks/",
    primaryAction: "Actualizar tareas",
    columns: ["Tarea", "Estado", "Deposito", "Preparador", "Pedido", "Cantidad", "Asignada"],
    permissions: ["tasks:view", "tasks:prepare"],
    showInDashboard: false,
  },
  {
    key: "reparto-preparation",
    label: "Preparacion de reparto",
    path: "/reparto/preparacion",
    description: "",
    apiPath: "/api/v1/fulfillment/preparation-tasks/",
    primaryAction: "Enviar a preparar",
    columns: ["Entrega", "Estado", "Deposito", "Preparador", "Pedido", "Cantidad", "Asignada"],
    permissions: ["deliveries:view", "tasks:prepare"],
    hiddenFromNavigation: true,
    showInDashboard: false,
  },
  {
    key: "vehicles",
    label: "Vehiculo",
    path: "/maestros/vehiculos",
    description: "",
    apiPath: "/api/v1/vehicles/",
    primaryAction: "Alta vehiculo",
    columns: ["Vehiculo", "Estado", "Base", "Perfil", "Prioridad", "Capacidad", "SLA"],
    permissions: ["vehicles:view", "vehicles:create", "vehicles:edit"],
    hiddenFromNavigation: true,
    showInDashboard: false,
  },
  {
    key: "audits",
    label: "Auditorias",
    path: "/auditorias",
    description: "",
    apiPath: "/api/v1/audits/",
    primaryAction: "Iniciar conteo",
    columns: ["Auditoria", "Estado", "Warehouse", "Responsable", "Prioridad", "Items", "SLA"],
    permissions: ["audits:view", "audits:approve", "audits:close"],
    hiddenFromNavigation: true,
    readOnly: true,
    showInDashboard: false,
  },
  {
    key: "dispatch",
    label: "Despacho tienda",
    path: "/despacho-tienda",
    description: "",
    apiPath: "/api/v1/dispatch/",
    primaryAction: "Validar retiro",
    columns: ["Retiro", "Estado", "Tienda", "Cliente", "Prioridad", "Cantidad", "SLA"],
    permissions: ["dispatch:view", "dispatch:edit", "dispatch:close"],
    hiddenFromNavigation: true,
    readOnly: true,
    showInDashboard: false,
  },
  {
    key: "shipping",
    label: "Envios",
    path: "/envios",
    description: "",
    apiPath: "/api/v1/shipping/",
    primaryAction: "Crear envio",
    columns: ["Envio", "Estado", "Warehouse", "Cliente", "Prioridad", "Bultos", "SLA"],
    permissions: ["shipping:view", "shipping:edit", "shipping:close"],
    hiddenFromNavigation: true,
    readOnly: true,
    showInDashboard: false,
  },
];

export function operationModuleByKey(key: string) {
  const module = operationModules.find((entry) => entry.key === key);
  if (!module) {
    throw new Error(`Modulo operativo no registrado: ${key}`);
  }
  return module;
}

export const dashboardOperationModules = [
  "orders",
  "deliveries",
  "tasks",
  "distribution",
  "receipts",
  "transfers",
  "returns",
  "routes",
  "stock",
  "stock-movements",
].map(operationModuleByKey);

export const routedOperationModules = [
  "orders",
  "transfers",
  "returns",
  "routes",
  "audits",
  "shipping",
].map(operationModuleByKey);

export const placeholderPages: PlaceholderPageConfig[] = [
  {
    key: "breakages-losses",
    label: "Roturas y perdidas",
    path: "/operaciones/roturas-perdidas",
    groupLabel: "Operaciones",
    description: "",
    checkpoints: [],
  },
];

export function placeholderPageByKey(key: string) {
  const page = placeholderPages.find((entry) => entry.key === key);
  if (!page) {
    throw new Error(`Placeholder operativo no registrado: ${key}`);
  }
  return page;
}

export const navigationEntries: NavigationEntry[] = [
  { key: "dashboard", label: "Dashboard", path: "/dashboard", end: true },
  {
    key: "orders",
    label: "Pedidos",
    items: [
      { key: "orders-list", label: "Listar pedidos", path: operationModuleByKey("orders").path, end: true },
      { key: "orders-delivery", label: "Entrega", path: operationModuleByKey("deliveries").path },
      { key: "orders-tasks", label: "Tareas de preparacion", path: operationModuleByKey("tasks").path },
    ],
  },
  {
    key: "reparto",
    label: "Reparto",
    items: [
      { key: "reparto-confirmation", label: "Confirmacion de reparto", path: operationModuleByKey("distribution").path },
      { key: "reparto-preparation", label: "Preparacion de reparto", path: operationModuleByKey("reparto-preparation").path },
      { key: "reparto-routing", label: "Ruteo", path: "/reparto/ruteo" },
      { key: "reparto-driver-execution", label: "Ejecucion chofer", path: "/reparto/chofer" },
      { key: "reparto-route-sheets", label: "Hojas de ruta", path: operationModuleByKey("routes").path },
    ],
  },
  {
    key: "income",
    label: "Ingresos",
    items: [
      { key: "income-purchase-order", label: "Ingresos por OC", path: operationModuleByKey("receipts").path },
      { key: "income-transfers", label: "Ingresos por TR entre depositos", path: operationModuleByKey("transfers").path },
      { key: "income-returns", label: "Ingresos por devoluciones", path: operationModuleByKey("returns").path },
    ],
  },
  {
    key: "stock",
    label: "Stock",
    items: [
      { key: "stock-balances", label: "Stock por almacen", path: operationModuleByKey("stock").path },
      { key: "stock-movements", label: "Movimientos de Stock", path: operationModuleByKey("stock-movements").path },
    ],
  },
  {
    key: "operations",
    label: "Operaciones",
    items: [
      { key: "sheet-cutting", label: "Corte de chapas", path: "/operaciones/corte-chapas" },
      { key: "lot-to-balance", label: "Canje lote a saldo", path: "/operaciones/canje-lote-saldo" },
      { key: "manual-stock-adjustment", label: "Alta y baja de articulos", path: "/operaciones/alta-baja-articulos" },
      { key: "breakages-losses", label: "Roturas y perdidas", path: placeholderPageByKey("breakages-losses").path },
    ],
  },
  {
    key: "masters",
    label: "Maestros",
    items: [
      { key: "master-warehouses", label: "Almacenes", path: "/maestros/almacenes" },
      { key: "master-vehicles", label: "Vehiculo", path: "/maestros/vehiculos" },
      { key: "master-drivers", label: "Choferes", path: "/maestros/choferes" },
    ],
  },
];

export const navigationLinks: NavigationLink[] = navigationEntries.flatMap((entry) =>
  "items" in entry ? entry.items : [entry],
);
