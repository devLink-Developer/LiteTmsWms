import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { operationModuleByKey } from "../../shared/data/modules";
import { OperationalPage } from "./OperationalPage";

describe("OperationalPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          results: [
            {
              id: "ledger-1",
              purchase_order_ref: "OC-000184",
              status: "received",
              warehouse_ref: "PS003MT",
              item_ref: "ITM-1",
              lines_count: 1,
            },
          ],
        }),
      })),
    );
  });

  it("renders dense read-only operational table", async () => {
    const view = render(<OperationalPage module={operationModuleByKey("receipts")} />);

    expect(view.getByRole("heading", { name: "Ingresos por OC" })).toBeInTheDocument();
    expect(view.queryByRole("button", { name: /registrar/i })).not.toBeInTheDocument();
    expect(view.queryByText("solo lectura")).not.toBeInTheDocument();
    expect(view.getByRole("table")).toBeInTheDocument();
    await waitFor(() => expect(view.getByText("OC-000184")).toBeInTheDocument());
  });

  it("searches orders through the backend and shows movement timeline", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        calls.push(url);
        return {
          ok: true,
          json: async () => ({
            results: url.includes("q=VENT8-100001719")
              ? [
                  {
                    id: "fulfillment-1719",
                    fulfillment_number: "FUL-VENT8-100001719",
                    status: "ready_for_dispatch",
                    sales_order_number: "VENT8-100001719",
                    transaction_number: "PS003MT-693-12107-000002800",
                    customer_ref: "20000070",
                    warehouse_ref: "PS03DP",
                    delivery_mode: "Repart Prg",
                    requested_date: "2026-04-26",
                    lines: [{ id: "line-1", item_ref: "100402" }],
                    deliveries: [
                      {
                        id: "delivery-1",
                        delivery_number: "E-000000005",
                        status: "in_route",
                        delivery_mode: "Repart Prg",
                        planned_date: "2026-04-27",
                        route_sheet: { route_number: "HR-000000123", status: "in_transit" },
                        totals: { delivery_unit_qty: "4", planned_weight_kg: "120", planned_volume_m3: "0.400" },
                        documents: [],
                      },
                      {
                        id: "delivery-2",
                        delivery_number: "E-000000004",
                        status: "delivered_complete",
                        delivery_mode: "Repart Prg",
                        planned_date: "2026-04-26",
                        documents: [
                          {
                            id: "doc-1",
                            document_number: "R-000000005",
                            document_type: "remito",
                            status: "closed",
                            issued_at: "2026-04-26T12:00:00Z",
                          },
                        ],
                      },
                    ],
                    movements: [
                      {
                        key: "route-stop:1",
                        at: "2026-04-27T12:00:00Z",
                        label: "Ejecucion de reparto",
                        status: "in_route",
                        detail: "Parada 1",
                        actor: "driver",
                        route_number: "HR-000000123",
                      },
                    ],
                  },
                ]
              : [],
          }),
        };
      }),
    );

    render(<OperationalPage module={operationModuleByKey("orders")} />);

    expect(calls).toHaveLength(0);
    const searchInput = screen.getByLabelText("Busqueda");
    fireEvent.change(searchInput, { target: { value: "VENT8-100001719" } });
    expect(calls).toHaveLength(0);
    fireEvent.keyDown(searchInput, { key: "Enter" });

    await waitFor(() => expect(screen.getByText("VENT8-100001719")).toBeInTheDocument());
    expect(calls.some((url) => url.includes("/api/v1/fulfillment/?q=VENT8-100001719"))).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Abrir" }));

    expect(screen.getByText("Entregas pendientes")).toBeInTheDocument();
    expect(screen.getByText("E-000000005")).toBeInTheDocument();
    expect(screen.getByText("en ruta")).toBeInTheDocument();
    expect(screen.getByText("Entregas con remito")).toBeInTheDocument();
    expect(screen.getByText("R-000000005 / Cerrado")).toBeInTheDocument();

    expect(screen.queryByText("Ejecucion de reparto")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ver trazabilidad" }));

    expect(screen.getByText("Ejecucion de reparto")).toBeInTheDocument();
    expect(screen.getByText(/Hoja de ruta HR-000000123/)).toBeInTheDocument();
  });

  it("runs order search from the Buscar button", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        calls.push(String(input));
        return {
          ok: true,
          json: async () => ({
            results: [
              {
                id: "fulfillment-button",
                fulfillment_number: "FUL-VENT8-100002000",
                status: "pending",
                sales_order_number: "VENT8-100002000",
                customer_ref: "20000071",
                warehouse_ref: "PS03DP",
                lines_count: 1,
              },
            ],
          }),
        };
      }),
    );

    render(<OperationalPage module={operationModuleByKey("orders")} />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "VENT8-100002000" } });
    expect(calls).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));

    await waitFor(() => expect(screen.getByText("VENT8-100002000")).toBeInTheDocument());
    expect(calls.some((url) => url.includes("/api/v1/fulfillment/?q=VENT8-100002000"))).toBe(true);
  });
});
