import { Navigate, createBrowserRouter } from "react-router-dom";

import { DashboardPage } from "../features/dashboard/DashboardPage";
import { DeliveryExpeditionPage } from "../features/deliveries/DeliveryExpeditionPage";
import { OperationalPage } from "../features/operations/OperationalPage";
import { PreparationTasksPage } from "../features/tasks/PreparationTasksPage";
import { AppShell } from "../layouts/AppShell";
import { operationModules } from "../shared/data/modules";

const genericOperationModules = operationModules.filter((module) => !["deliveries", "tasks"].includes(module.key));

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/entregas/expedicion" replace /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "tareas", element: <PreparationTasksPage /> },
      { path: "entregas", element: <Navigate to="/entregas/expedicion" replace /> },
      { path: "entregas/expedicion", element: <DeliveryExpeditionPage /> },
      ...genericOperationModules.map((module) => ({
        path: module.path.replace(/^\//, ""),
        element: <OperationalPage module={module} />,
      })),
    ],
  },
]);
