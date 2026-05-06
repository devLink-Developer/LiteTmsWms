import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardPage } from "./DashboardPage";

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 200 && status < 300 ? "OK" : "Error",
    headers: {
      get: (name: string) => (name.toLowerCase() === "content-type" ? "application/json" : ""),
    },
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  };
}

function renderDashboard() {
  render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );
}

const dashboardPayload = {
  generated_at: "2026-05-04T12:00:00Z",
  scope: {
    warehouse_ref: "WH-A",
    mode: "active_warehouse",
    window: "operational_live",
    authorized_warehouses: ["WH-A"],
  },
  kpis: [
    { key: "open_orders", label: "Pedidos abiertos", value: 106, tone: "warning", detail: "10 listos despacho / 8 proximos 7 dias" },
    { key: "active_deliveries", label: "Entregas activas", value: 4, tone: "success", detail: "0 vencidas / 0 con atencion" },
    { key: "open_tasks", label: "Tareas preparacion", value: 2, tone: "info", detail: "assigned + preparing" },
    { key: "pending_route", label: "Reparto por rutear", value: 1, tone: "warning", detail: "3 reparto en scope" },
    { key: "stock_buckets", label: "Stock positivo", value: 1, tone: "success", detail: "5 UN" },
    { key: "module_coverage", label: "Modulos con datos", value: "5/12", tone: "warning", detail: "ceros visibles, sin datos inventados" },
  ],
  charts: {
    fulfillment_status: [
      { key: "pending", label: "Pendiente", count: 105 },
      { key: "allocated", label: "Reservada", count: 1 },
    ],
    delivery_pipeline: [
      { key: "prepared", label: "Preparada", count: 3 },
      { key: "in_route", label: "En ruta", count: 1 },
    ],
    stock_by_state: [
      { key: "packed", label: "Preparado", buckets: 1, quantity_by_uom: [{ uom: "UN", quantity: "5" }] },
      { key: "scrapped", label: "Merma", buckets: 0, quantity_by_uom: [] },
    ],
    ledger_by_day: [
      {
        date: "2026-04-28",
        increase_count: 0,
        decrease_count: 0,
        increase_quantity_by_uom: [],
        decrease_quantity_by_uom: [],
      },
      {
        date: "2026-05-04",
        increase_count: 2,
        decrease_count: 1,
        increase_quantity_by_uom: [{ uom: "UN", quantity: "4" }],
        decrease_quantity_by_uom: [{ uom: "UN", quantity: "2" }],
      },
    ],
    route_load: [
      {
        route_number: "HR-1",
        status: "in_transit",
        planned_date: "2026-05-04",
        stops: 12,
        planned_weight_kg: "1200.5",
        planned_volume_m3: "9.5",
      },
    ],
    module_coverage: [
      { key: "orders", label: "Pedidos", count: 106 },
      { key: "receipts", label: "Ingresos OC", count: 0 },
      { key: "transfers", label: "Transferencias", count: 0 },
      { key: "shipping", label: "Envios", count: 0 },
      { key: "write_offs", label: "Roturas y perdidas", count: 0 },
    ],
  },
  alerts: [
    {
      key: "overdue_orders",
      label: "Pedidos vencidos",
      value: 2,
      tone: "warning",
      detail: "Pedidos abiertos con fecha solicitada anterior a hoy.",
    },
  ],
  modules: [
    { key: "orders", label: "Pedidos", path: "/pedidos", count: 106, active: 106, issues: 2, tone: "warning" },
    { key: "receipts", label: "Ingresos OC", path: "/ingresos/oc", count: 0, active: 0, issues: 0, tone: "success" },
    { key: "transfers", label: "Transferencias", path: "/ingresos/tr-depositos", count: 0, active: 0, issues: 0, tone: "success" },
    { key: "shipping", label: "Envios", path: "/envios", count: 0, active: 0, issues: 0, tone: "success" },
    { key: "stock", label: "Stock", path: "/stock/almacenes", count: 1, active: 1, issues: 0, tone: "success" },
  ],
};

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/v1/logistics/dashboard/")) {
          return jsonResponse(dashboardPayload);
        }
        return jsonResponse({ error: { message: "endpoint inesperado" } }, 404);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders real dashboard metrics and zero-volume modules from the aggregate endpoint", async () => {
    renderDashboard();

    expect(screen.getByText("Cargando...")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("WH-A")).toBeInTheDocument());

    expect(screen.getByRole("heading", { name: "Dashboard operativo" })).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain("/api/v1/logistics/dashboard/");
    expect(screen.getByText("Pedidos abiertos")).toBeInTheDocument();
    expect(screen.getByText("Pedidos por estado")).toBeInTheDocument();
    expect(screen.getByText("Entregas por estado")).toBeInTheDocument();
    expect(screen.getByText("Stock por estado")).toBeInTheDocument();
    expect(screen.getByText("Ledger 7 dias")).toBeInTheDocument();
    expect(screen.getByText("HR-1")).toBeInTheDocument();
    expect(screen.getByText("Pedidos vencidos")).toBeInTheDocument();

    const transferRow = screen.getByRole("row", { name: /Transferencias/i });
    expect(within(transferRow).getAllByText("0").length).toBeGreaterThan(0);
    const receiptsRow = screen.getByRole("row", { name: /Ingresos OC/i });
    expect(within(receiptsRow).getAllByText("0").length).toBeGreaterThan(0);
  });

  it("shows the API error state when the aggregate endpoint fails", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ error: { message: "API caida" } }, 503) as Response);

    renderDashboard();

    await waitFor(() => expect(screen.getByText("Dashboard no cargado.")).toBeInTheDocument());
    expect(screen.getAllByText("API caida").length).toBeGreaterThan(0);
  });
});
