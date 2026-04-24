import { Navigate, createBrowserRouter, type RouteObject } from "react-router-dom";

import { DashboardPage } from "../features/dashboard/DashboardPage";
import { DeliveryExpeditionPage } from "../features/deliveries/DeliveryExpeditionPage";
import { OperationalPage } from "../features/operations/OperationalPage";
import { PlaceholderPage } from "../features/operations/PlaceholderPage";
import { PreparationTasksPage } from "../features/tasks/PreparationTasksPage";
import { AppShell } from "../layouts/AppShell";
import { placeholderPages, routedOperationModules } from "../shared/data/modules";

const legacyRedirects: RouteObject[] = [
  { path: "entregas", element: <Navigate to="/pedidos/entrega" replace /> },
  { path: "entregas/expedicion", element: <Navigate to="/pedidos/entrega" replace /> },
  { path: "tareas", element: <Navigate to="/pedidos/tareas" replace /> },
  { path: "recepciones", element: <Navigate to="/ingresos/oc" replace /> },
  { path: "transferencias", element: <Navigate to="/ingresos/tr-depositos" replace /> },
  { path: "stock", element: <Navigate to="/stock/almacenes" replace /> },
  { path: "despacho-tienda", element: <Navigate to="/pedidos/entrega" replace /> },
];

export const appRoutes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/pedidos/entrega" replace /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "pedidos/entrega", element: <DeliveryExpeditionPage /> },
      { path: "pedidos/tareas", element: <PreparationTasksPage /> },
      ...legacyRedirects,
      ...routedOperationModules.map((module) => ({
        path: module.path.replace(/^\//, ""),
        element: <OperationalPage module={module} />,
      })),
      ...placeholderPages.map((config) => ({
        path: config.path.replace(/^\//, ""),
        element: <PlaceholderPage config={config} />,
      })),
    ],
  },
];

export const router = createBrowserRouter(appRoutes);
