import type { NavigationEntry, NavigationLink, OperationModule, PlaceholderPageConfig } from "../../types/operations";

export const operationModules: OperationModule[] = [
  {
    key: "orders",
    label: "Listar pedidos",
    path: "/pedidos",
    description: "Fulfillment con remanente, reserva, preparacion y split de entrega.",
    apiPath: "/api/v1/fulfillment/",
    columns: ["Pedido", "Estado", "Warehouse", "Cliente", "Prioridad", "Lineas", "SLA"],
    permissions: ["orders:view", "orders:edit", "orders:split"],
    readOnly: true,
  },
  {
    key: "deliveries",
    label: "Entrega",
    path: "/pedidos/entrega",
    description: "Entregas multiples por pedido, cambios de modo y cantidades despachadas.",
    apiPath: "/api/v1/fulfillment/deliveries/",
    primaryAction: "Crear entrega",
    columns: ["Entrega", "Estado", "Warehouse", "Cliente", "Prioridad", "Cantidad", "SLA"],
    permissions: ["deliveries:view", "deliveries:edit", "deliveries:close"],
  },
  {
    key: "distribution",
    label: "Confirmacion de reparto",
    path: "/reparto/confirmacion",
    description: "Entregas con metodo de envio Reparto, listas para evaluacion de ruteo.",
    apiPath: "/api/v1/fulfillment/deliveries/?delivery_mode=Reparto",
    columns: ["Entrega", "Estado", "Warehouse", "Modo", "Prioridad", "Cantidad", "SLA"],
    permissions: ["deliveries:view", "routes:view"],
    readOnly: true,
  },
  {
    key: "receipts",
    label: "Ingresos por OC",
    path: "/ingresos/oc",
    description: "Ingreso total o parcial por orden de compra con diferencias e incidencias.",
    apiPath: "/api/v1/inventory/receipts/",
    columns: ["OC", "Estado", "Warehouse", "Responsable", "Prioridad", "Cantidad", "SLA"],
    permissions: ["receipts:view", "receipts:create", "receipts:close"],
    readOnly: true,
  },
  {
    key: "transfers",
    label: "Ingresos por TR entre depositos",
    path: "/ingresos/tr-depositos",
    description: "Origen, transito, recepcion parcial, diferencias y cierre entre almacenes.",
    apiPath: "/api/v1/transfers/",
    columns: ["Transferencia", "Estado", "Origen", "Destino", "Prioridad", "Cantidad", "SLA"],
    permissions: ["transfers:view", "transfers:create", "transfers:approve"],
    readOnly: true,
  },
  {
    key: "returns",
    label: "Ingresos por devoluciones",
    path: "/ingresos/devoluciones",
    description: "Devoluciones automaticas recibidas desde tracking, solo visualizacion sin impacto manual de stock.",
    apiPath: "/api/v1/shipping/?status=returned",
    columns: ["Envio", "Estado", "Warehouse", "Entrega", "Prioridad", "Bultos", "SLA"],
    permissions: ["shipping:view", "returns:view"],
    readOnly: true,
  },
  {
    key: "routes",
    label: "Hojas de ruta",
    path: "/reparto/hojas-ruta",
    description: "Planificacion manual y automatica con peso, volumen y secuencia.",
    apiPath: "/api/v1/routes/",
    columns: ["Ruta", "Estado", "Warehouse", "Vehiculo", "Prioridad", "Paradas", "SLA"],
    permissions: ["routes:view", "routes:create", "routes:close"],
    readOnly: true,
  },
  {
    key: "stock",
    label: "Stock por almacen",
    path: "/stock/almacenes",
    description: "Balances derivados, ledger, reservas, transito, ajustes y fraccionamientos.",
    apiPath: "/api/v1/inventory/balances/",
    columns: ["Item", "Estado", "Warehouse", "Origen", "Prioridad", "Cantidad", "SLA"],
    permissions: ["stock:view", "stock:adjust", "stock:transform"],
    readOnly: true,
  },
  {
    key: "stock-movements",
    label: "Movimientos de Stock",
    path: "/stock/movimientos",
    description: "Ledger de ingresos, egresos, ajustes y movimientos trazados por deposito.",
    apiPath: "/api/v1/inventory/ledger/",
    columns: ["Movimiento", "Estado", "Warehouse", "Origen", "Prioridad", "Cantidad", "Fecha"],
    permissions: ["stock:view", "stock:ledger"],
    readOnly: true,
  },
  {
    key: "tasks",
    label: "Tareas de preparacion",
    path: "/pedidos/tareas",
    description: "Preparacion de entregas reservadas con asignacion por deposito y responsable.",
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
    description: "Envio a preparacion, tareas abiertas y marcado de preparado para entregas por reparto.",
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
    description: "Alta, baja y modificacion de vehiculos con capacidad, disponibilidad y restricciones de uso.",
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
    description: "Conteos, diferencias, aprobaciones y ajustes trazados.",
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
    description: "Retiro parcial, tercero autorizado, validacion y comprobante operativo.",
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
    description: "Seguimiento interno, intentos, reprogramacion, entrega y devolucion.",
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
  "receipts",
  "transfers",
  "returns",
  "routes",
  "stock",
  "stock-movements",
  "audits",
  "shipping",
].map(operationModuleByKey);

export const placeholderPages: PlaceholderPageConfig[] = [
  {
    key: "sheet-cutting",
    label: "Corte de chapas",
    path: "/operaciones/corte-chapas",
    groupLabel: "Operaciones",
    description: "Operacion de corte pendiente de API de transformacion de stock.",
    checkpoints: ["Vista read-only", "Sin consumo de lote", "Pendiente de API de corte"],
  },
  {
    key: "lot-to-balance",
    label: "Canje lote a saldo",
    path: "/operaciones/canje-lote-saldo",
    groupLabel: "Operaciones",
    description: "Canje de lote a saldo pendiente de API de transformacion.",
    checkpoints: ["Vista read-only", "Sin conversion activa", "Pendiente de API de canje"],
  },
  {
    key: "breakages-losses",
    label: "Roturas y perdidas",
    path: "/operaciones/roturas-perdidas",
    groupLabel: "Operaciones",
    description: "Registro de roturas y perdidas pendiente de API de ajustes.",
    checkpoints: ["Vista read-only", "Sin ajuste contable", "Pendiente de API de roturas"],
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
  { key: "stock", label: "Stock", path: operationModuleByKey("stock").path },
  { key: "stock-movements", label: "Movimientos de Stock", path: operationModuleByKey("stock-movements").path },
  {
    key: "operations",
    label: "Operaciones",
    items: [
      { key: "sheet-cutting", label: "Corte de chapas", path: placeholderPageByKey("sheet-cutting").path },
      { key: "lot-to-balance", label: "Canje lote a saldo", path: placeholderPageByKey("lot-to-balance").path },
      { key: "breakages-losses", label: "Roturas y perdidas", path: placeholderPageByKey("breakages-losses").path },
    ],
  },
  {
    key: "masters",
    label: "Maestros",
    items: [
      { key: "master-vehicles", label: "Vehiculo", path: "/maestros/vehiculos" },
      { key: "master-drivers", label: "Choferes", path: "/maestros/choferes" },
    ],
  },
];

export const navigationLinks: NavigationLink[] = navigationEntries.flatMap((entry) =>
  "items" in entry ? entry.items : [entry],
);
