import { Navigate, createBrowserRouter, type RouteObject } from "react-router-dom";

import { RequireAuthGuard } from "./RequireAuthGuard";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { LoginPage } from "../features/auth/LoginPage";
import { DeliveryExpeditionPage } from "../features/deliveries/DeliveryExpeditionPage";
import { FleetAdminPage } from "../features/fleet/FleetAdminPage";
import { DriverRouteExecutionPage } from "../features/reparto/DriverRouteExecutionPage";
import { BreakagesLossesPage } from "../features/operations/BreakagesLossesPage";
import { InventoryExchangePage } from "../features/operations/InventoryExchangePage";
import { ManualStockAdjustmentPage } from "../features/operations/ManualStockAdjustmentPage";
import { OperationalPage } from "../features/operations/OperationalPage";
import { PlaceholderPage } from "../features/operations/PlaceholderPage";
import { PurchaseReceiptsPage } from "../features/receipts/PurchaseReceiptsPage";
import { SheetCuttingPage } from "../features/operations/SheetCuttingPage";
import { RepartoConfirmationPage } from "../features/reparto/RepartoConfirmationPage";
import { RepartoPreparationPage } from "../features/reparto/RepartoPreparationPage";
import { RoutePlanningPage } from "../features/routing/RoutePlanningPage";
import { StockBalancesPage } from "../features/stock/StockBalancesPage";
import { StockMovementsPage } from "../features/stock/StockMovementsPage";
import { PreparationTasksPage } from "../features/tasks/PreparationTasksPage";
import { TransfersPage } from "../features/transfers/TransfersPage";
import { WarehouseMasterPage } from "../features/masters/WarehouseMasterPage";
import { AppShell } from "../layouts/AppShell";
import { placeholderPages, routedOperationModules } from "../shared/data/modules";

const legacyRedirects: RouteObject[] = [
  { path: "entregas", element: <Navigate to="/pedidos/entrega" replace /> },
  { path: "entregas/expedicion", element: <Navigate to="/pedidos/entrega" replace /> },
  { path: "tareas", element: <Navigate to="/pedidos/tareas" replace /> },
  { path: "pedidos/reparto", element: <Navigate to="/reparto/confirmacion" replace /> },
  { path: "ruteo", element: <Navigate to="/reparto/ruteo" replace /> },
  { path: "hojas-ruta", element: <Navigate to="/reparto/hojas-ruta" replace /> },
  { path: "vehiculos", element: <Navigate to="/maestros/vehiculos" replace /> },
  { path: "choferes", element: <Navigate to="/maestros/choferes" replace /> },
  { path: "almacenes", element: <Navigate to="/maestros/almacenes" replace /> },
  { path: "recepciones", element: <Navigate to="/ingresos/oc" replace /> },
  { path: "transferencias", element: <Navigate to="/ingresos/tr-depositos" replace /> },
  { path: "stock", element: <Navigate to="/stock/almacenes" replace /> },
  { path: "despacho-tienda", element: <Navigate to="/pedidos/entrega" replace /> },
];

export const appRoutes: RouteObject[] = [
  { path: "/login/", element: <LoginPage /> },
  {
    path: "/",
    element: (
      <RequireAuthGuard>
        <AppShell />
      </RequireAuthGuard>
    ),
    children: [
      { index: true, element: <Navigate to="/pedidos/entrega" replace /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "pedidos/entrega", element: <DeliveryExpeditionPage /> },
      { path: "reparto/confirmacion", element: <RepartoConfirmationPage /> },
      { path: "reparto/preparacion", element: <RepartoPreparationPage /> },
      { path: "reparto/ruteo", element: <RoutePlanningPage /> },
      { path: "reparto/chofer", element: <DriverRouteExecutionPage /> },
      { path: "maestros/vehiculos", element: <FleetAdminPage initialTab="vehicles" /> },
      { path: "maestros/choferes", element: <FleetAdminPage initialTab="drivers" /> },
      { path: "maestros/almacenes", element: <WarehouseMasterPage /> },
      { path: "pedidos/tareas", element: <PreparationTasksPage /> },
      { path: "ingresos/oc", element: <PurchaseReceiptsPage /> },
      { path: "ingresos/tr-depositos", element: <TransfersPage /> },
      { path: "stock/almacenes", element: <StockBalancesPage /> },
      { path: "stock/movimientos", element: <StockMovementsPage /> },
      { path: "operaciones/canje-lote-saldo", element: <InventoryExchangePage /> },
      { path: "operaciones/alta-baja-articulos", element: <ManualStockAdjustmentPage /> },
      { path: "operaciones/corte-chapas", element: <SheetCuttingPage /> },
      { path: "operaciones/roturas-perdidas", element: <BreakagesLossesPage /> },
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
