import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RepartoConfirmationPage } from "./RepartoConfirmationPage";
import { formatAppDate } from "../../shared/utils/dateFormat";

function renderWithQuery(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

function futureDateInputValue(days = 7) {
  const date = new Date();
  date.setDate(date.getDate() + days);
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return localDate.toISOString().slice(0, 10);
}

describe("RepartoConfirmationPage", () => {
  let plannedDate: string;

  beforeEach(() => {
    plannedDate = futureDateInputValue();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (method === "POST" && url.includes("/api/v1/fulfillment/fulfillment-1/stock-check")) {
          return {
            ok: true,
            json: async () => ({
              result: {
                reference_type: "fulfillment_order",
                reference_id: "fulfillment-1",
                reference_number: "FUL-100",
                status: "ok",
                can_confirm: true,
                issues: [],
                lines: [
                  {
                    line_id: "line-1",
                    item_ref: "ITEM-1",
                    warehouse_ref: "PS003MT",
                    planned_qty: "3",
                    available_qty: "3",
                    uom: "UN",
                  },
                ],
              },
            }),
          };
        }
        if (method === "POST" && url.includes("/api/v1/fulfillment/fulfillment-1/split")) {
          return {
            ok: true,
            json: async () => ({
              result: {
                id: "delivery-1",
                delivery_number: "ENT-100",
                status: "created",
                delivery_mode: "Repart Prg",
                planned_date: plannedDate,
                fulfillment_id: "fulfillment-1",
                sales_order_number: "VENT8-100",
                documents: [],
                lines: [],
              },
            }),
          };
        }
        if (method === "POST" && url.includes("/validate-stock")) {
          return {
            ok: true,
            json: async () => ({
              result: {
                id: "delivery-1",
                delivery_number: "ENT-100",
                status: "confirmed",
                delivery_mode: "Repart Prg",
                planned_date: plannedDate,
                fulfillment_id: "fulfillment-1",
                sales_order_number: "VENT8-100",
                documents: [],
                lines: [],
              },
            }),
          };
        }
        expect(url).toContain("/api/v1/fulfillment/reparto-confirmation/");
        return {
          ok: true,
          json: async () => ({
            results: [
              {
                id: "fulfillment:fulfillment-1",
                source_type: "fulfillment",
                delivery_id: null,
                delivery_number: "sin entrega",
                status: "pending",
                delivery_mode: "Repart Prg",
                warehouse_ref: "PS003MT",
                planned_date: plannedDate,
                fulfillment_id: "fulfillment-1",
                fulfillment_number: "FUL-100",
                sales_order_number: "VENT8-100",
                transaction_number: "TX-100",
                customer_ref: "CLI-1",
                documents_count: 0,
                lines_count: 1,
                total_qty: "3",
                total_weight_kg: "45",
                total_volume_m3: "0.06",
                address_snapshot: { street: "Uruguay", street_number: "3947", city: "Posadas" },
                lines: [
                  {
                    fulfillment_line_id: "line-1",
                    item_ref: "ITEM-1",
                    warehouse_ref: "PS003MT",
                    split_qty: "3",
                    uom: "UN",
                  },
                ],
              },
            ],
          }),
        };
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("filters reparto deliveries by delivery date and confirms a pending delivery", async () => {
    renderWithQuery(<RepartoConfirmationPage />);

    fireEvent.change(screen.getByLabelText("Fecha entrega"), { target: { value: plannedDate } });

    await waitFor(() => expect(screen.getByText("VENT8-100")).toBeInTheDocument());
    expect(screen.queryByLabelText("Deposito")).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Deposito" })).not.toBeInTheDocument();
    expect(screen.getByText(formatAppDate(plannedDate))).toBeInTheDocument();
    expect(screen.queryByText("100")).not.toBeInTheDocument();
    expect(screen.getByText("sin entrega generada")).toBeInTheDocument();
    expect(screen.getByText("CLI-1")).toBeInTheDocument();

    const row = screen.getByRole("row", { name: /VENT8-100/i });
    expect(within(row).getByRole("button", { name: "Crear y confirmar" })).toBeDisabled();
    fireEvent.click(within(row).getByRole("button", { name: "Validar Stock" }));
    await waitFor(() => expect(screen.getByText("1 pedido con stock.")).toBeInTheDocument());
    expect(within(row).getByRole("button", { name: "Crear y confirmar" })).not.toBeDisabled();
    fireEvent.click(within(row).getByRole("button", { name: "Crear y confirmar" }));

    await waitFor(() => expect(screen.getByText("1 entrega confirmada.")).toBeInTheDocument());
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/fulfillment/fulfillment-1/stock-check"), expect.any(Object));
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/fulfillment/fulfillment-1/split"), expect.any(Object));
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/fulfillment/deliveries/delivery-1/validate-stock"), expect.any(Object));
  });

  it("selects all pending rows from the toolbar", async () => {
    renderWithQuery(<RepartoConfirmationPage />);

    fireEvent.change(screen.getByLabelText("Fecha entrega"), { target: { value: plannedDate } });

    await waitFor(() => expect(screen.getByText("VENT8-100")).toBeInTheDocument());
    const validateSelected = screen.getByRole("button", { name: "Validar Stock seleccionadas" });
    expect(validateSelected).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Seleccionar todas" }));

    expect(screen.getByRole("checkbox", { name: /VENT8-100/i })).toBeChecked();
    expect(validateSelected).not.toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Limpiar" }));

    expect(screen.getByRole("checkbox", { name: /VENT8-100/i })).not.toBeChecked();
    expect(validateSelected).toBeDisabled();
  });
});
