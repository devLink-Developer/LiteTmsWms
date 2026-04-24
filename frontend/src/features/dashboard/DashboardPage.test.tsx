import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardPage } from "./DashboardPage";

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    json: async () => payload,
  };
}

function httpError(status: number) {
  return {
    ok: false,
    status,
    json: async () => ({}),
  };
}

function renderDashboard() {
  render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );
}

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);

        if (url.includes("/api/v1/logistics/overview/")) {
          return jsonResponse({ principles: ["Ledger inventario como fuente operativa."] });
        }
        if (url.includes("/api/v1/fulfillment/deliveries/?delivery_mode=Reparto")) {
          return jsonResponse({
            results: [
              {
                id: "distribution-1",
                delivery_number: "REP-1",
                status: "created",
                delivery_mode: "Reparto",
                warehouse_ref: "PS03DP",
                planned_date: "2026-04-24",
              },
              {
                id: "distribution-2",
                delivery_number: "REP-2",
                status: "in_route",
                delivery_mode: "Reparto",
                warehouse_ref: "PS03DP",
                planned_date: "2026-04-24",
              },
            ],
          });
        }
        if (url.includes("/api/v1/fulfillment/deliveries/")) {
          return jsonResponse({
            results: [
              {
                id: "delivery-1",
                delivery_number: "ENT-1",
                status: "prepared",
                delivery_mode: "Retiro",
                warehouse_ref: "PS03DP",
                planned_date: "2026-04-24",
              },
            ],
          });
        }
        if (url.includes("/api/v1/fulfillment/preparation-tasks/")) {
          return jsonResponse({
            results: [
              {
                id: "task-1",
                status: "assigned",
                assigned_employee_ref: "prep-1",
                assigned_at: "2026-04-24T09:00:00Z",
                warehouse_ref: "PS03DP",
                delivery: {
                  id: "delivery-1",
                  delivery_number: "ENT-1",
                  status: "preparing",
                  delivery_mode: "Reparto",
                  planned_date: "2026-04-24",
                },
                order: {
                  id: "order-1",
                  fulfillment_number: "FUL-1",
                  sales_order_number: "VENT8-1",
                  customer_ref: "CLI-1",
                },
                lines: [{ id: "line-1", item_ref: "SKU-1", planned_qty: "4", uom: "un" }],
                total_qty: "4",
              },
            ],
          });
        }
        if (url.includes("/api/v1/fulfillment/")) {
          return jsonResponse({
            results: [
              {
                id: "order-1",
                fulfillment_number: "FUL-1",
                status: "pending",
                sales_order_number: "VENT8-1",
                customer_ref: "CLI-1",
                warehouse_ref: "PS03DP",
                requested_date: "2026-04-24",
                lines_count: 2,
                deliveries_count: 1,
              },
              {
                id: "order-2",
                fulfillment_number: "FUL-2",
                status: "ready_for_dispatch",
                sales_order_number: "VENT8-2",
                customer_ref: "CLI-2",
                warehouse_ref: "PS03DP",
                requested_date: "2026-04-24",
                lines_count: 1,
                deliveries_count: 1,
              },
            ],
          });
        }
        if (url.includes("/api/v1/inventory/receipts/")) {
          return jsonResponse({
            results: [
              {
                id: "receipt-1",
                purchase_order_ref: "OC-900",
                supplier_ref: "SUP-1",
                status: "with_incident",
                warehouse_ref: "PS03DP",
                lines_count: 3,
              },
            ],
          });
        }
        if (url.includes("/api/v1/transfers/")) {
          return httpError(503);
        }
        if (url.includes("/api/v1/shipping/?status=returned")) {
          return jsonResponse({
            results: [
              {
                id: "return-1",
                shipment_number: "RET-1",
                status: "returned",
                delivery_ref: "ENT-0",
                route_ref: "HR-0",
              },
            ],
          });
        }
        if (url.includes("/api/v1/routes/")) {
          return jsonResponse({
            results: [
              {
                id: "route-1",
                route_number: "HR-1",
                status: "planned",
                planned_date: "2026-04-24",
                warehouse_ref: "PS03DP",
                vehicle: "CAM-1",
                planned_weight_kg: "1200.500",
                planned_volume_m3: "9.500",
              },
            ],
          });
        }
        if (url.includes("/api/v1/inventory/balances/")) {
          return jsonResponse({
            results: [
              {
                id: "stock-1",
                warehouse_ref: "PS03DP",
                item_ref: "SKU-1",
                stock_state: "on_hand",
                quantity: "10.000000",
                uom: "un",
              },
              {
                id: "stock-2",
                warehouse_ref: "PS03DP",
                item_ref: "SKU-2",
                stock_state: "reserved",
                quantity: "4.000000",
                uom: "un",
              },
            ],
          });
        }
        if (url.includes("/api/v1/inventory/ledger/")) {
          return jsonResponse({
            results: [
              {
                id: "ledger-1",
                movement_type: "inbound_receipt",
                direction: "increase",
                warehouse_ref: "PS03DP",
                item_ref: "SKU-1",
                stock_state: "on_hand",
                quantity: "10.000000",
                uom: "un",
                document_type: "receipt",
                document_ref: "OC-900",
                posted_at: "2026-04-24T10:00:00Z",
              },
              {
                id: "ledger-2",
                movement_type: "dispatch",
                direction: "decrease",
                warehouse_ref: "PS03DP",
                item_ref: "SKU-2",
                stock_state: "reserved",
                quantity: "3.000000",
                uom: "un",
                document_type: "delivery",
                document_ref: "ENT-1",
                posted_at: "2026-04-24T11:00:00Z",
              },
            ],
          });
        }

        return jsonResponse({ results: [] });
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders operational KPIs while tolerating a module error", async () => {
    renderDashboard();

    expect(screen.getByRole("heading", { name: "Dashboard operativo" })).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText(/Carga parcial: 1 modulo con error/)).toBeInTheDocument());

    expect(screen.getByText("Pedidos abiertos")).toBeInTheDocument();
    expect(screen.getByText("Tareas preparacion")).toBeInTheDocument();
    expect(screen.getByText("Reparto para ruteo")).toBeInTheDocument();
    expect(screen.getByText("Stock disponible")).toBeInTheDocument();
    expect(screen.getByText("OC-900")).toBeInTheDocument();
    expect(screen.getByText("Ledger inventario como fuente operativa.")).toBeInTheDocument();

    const transferRow = screen.getByRole("row", { name: /Ingresos por TR entre depositos/i });
    expect(within(transferRow).getByText("Error")).toBeInTheDocument();
    expect(within(transferRow).getByText("API /api/v1/transfers/ respondio 503")).toBeInTheDocument();
  });
});
