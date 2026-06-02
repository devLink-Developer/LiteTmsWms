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
  let partialFulfillmentStock: boolean;
  let deliveryRowStock: boolean;
  let lastSplitBody: Record<string, unknown>;
  let lastConfirmAvailableBody: Record<string, unknown>;

  beforeEach(() => {
    plannedDate = futureDateInputValue();
    partialFulfillmentStock = false;
    deliveryRowStock = false;
    lastSplitBody = {};
    lastConfirmAvailableBody = {};
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (method === "POST" && url.includes("/api/v1/fulfillment/fulfillment-1/stock-check")) {
          const body = init?.body ? JSON.parse(String(init.body)) : {};
          if (partialFulfillmentStock) {
            const requestedQty = Number(body.lines?.[0]?.split_qty ?? 0);
            const canConfirm = requestedQty <= 2;
            return {
              ok: true,
              json: async () => ({
                result: {
                  reference_type: "fulfillment_order",
                  reference_id: "fulfillment-1",
                  reference_number: "FUL-100",
                  status: canConfirm ? "ok" : "insufficient",
                  can_confirm: canConfirm,
                  issues: canConfirm
                    ? []
                    : [
                        {
                          line_id: "line-1",
                          item_ref: "ITEM-1",
                          warehouse_ref: "PS003MT",
                          planned_qty: "3",
                          available_qty: "2",
                          uom: "UN",
                        },
                      ],
                  lines: [
                    {
                      line_id: "line-1",
                      item_ref: "ITEM-1",
                      warehouse_ref: "PS003MT",
                      planned_qty: canConfirm ? "2" : "3",
                      available_qty: "2",
                      uom: "UN",
                    },
                  ],
                },
              }),
            };
          }
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
          lastSplitBody = init?.body ? JSON.parse(String(init.body)) : {};
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
        if (method === "POST" && url.includes("/confirm-available")) {
          lastConfirmAvailableBody = init?.body ? JSON.parse(String(init.body)) : {};
          return {
            ok: true,
            json: async () => ({
              result: {
                id: "delivery-existing",
                delivery_number: "ENT-EXIST",
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
        if (method === "POST" && url.includes("/api/v1/fulfillment/deliveries/delivery-existing/stock-check")) {
          return {
            ok: true,
            json: async () => ({
              result: {
                reference_type: "delivery_order",
                reference_id: "delivery-existing",
                reference_number: "ENT-EXIST",
                status: "insufficient",
                can_confirm: false,
                issues: [
                  {
                    line_id: "delivery-line-1",
                    fulfillment_line_id: "line-1",
                    item_ref: "ITEM-1",
                    warehouse_ref: "PS003MT",
                    planned_qty: "3",
                    available_qty: "2",
                    uom: "UN",
                  },
                ],
                lines: [
                  {
                    line_id: "delivery-line-1",
                    fulfillment_line_id: "line-1",
                    item_ref: "ITEM-1",
                    warehouse_ref: "PS003MT",
                    planned_qty: "3",
                    available_qty: "2",
                    uom: "UN",
                  },
                ],
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
              deliveryRowStock
                ? {
                    id: "delivery:delivery-existing",
                    source_type: "delivery",
                    delivery_id: "delivery-existing",
                    delivery_number: "ENT-EXIST",
                    status: "planned",
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
                        delivery_line_id: "delivery-line-1",
                        fulfillment_line_id: "line-1",
                        item_ref: "ITEM-1",
                        warehouse_ref: "PS003MT",
                        split_qty: "3",
                        delivery_unit_qty: "3",
                        uom: "UN",
                        delivery_uom: "UN",
                        conversion_factor: "1",
                      },
                    ],
                  }
                : {
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
                    delivery_unit_qty: "3",
                    uom: "UN",
                    delivery_uom: "UN",
                    conversion_factor: "1",
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

  it("confirms available stock for a pending fulfillment row", async () => {
    partialFulfillmentStock = true;
    renderWithQuery(<RepartoConfirmationPage />);

    fireEvent.change(screen.getByLabelText("Fecha entrega"), { target: { value: plannedDate } });

    await waitFor(() => expect(screen.getByText("VENT8-100")).toBeInTheDocument());
    const row = screen.getByRole("row", { name: /VENT8-100/i });
    fireEvent.click(within(row).getByRole("button", { name: "Validar Stock" }));

    await waitFor(() => expect(within(row).getByText("stock parcial")).toBeInTheDocument());
    expect(within(row).getByRole("button", { name: "Confirmar Disponibles" })).not.toBeDisabled();
    expect(screen.getByText("parcial")).toBeInTheDocument();

    fireEvent.click(within(row).getByRole("button", { name: "Confirmar Disponibles" }));
    expect(screen.getByRole("dialog", { name: "Confirmar disponibles" })).toBeInTheDocument();

    fireEvent.click(within(screen.getByRole("dialog", { name: "Confirmar disponibles" })).getByRole("button", { name: "Confirmar Disponibles" }));

    await waitFor(() => expect(screen.getByText("1 entrega parcial confirmada.")).toBeInTheDocument());
    expect(lastSplitBody).toMatchObject({
      lines: [{ fulfillment_line_id: "line-1", split_qty: 2 }],
    });
  });

  it("confirms available stock for selected rows from the toolbar", async () => {
    partialFulfillmentStock = true;
    renderWithQuery(<RepartoConfirmationPage />);

    fireEvent.change(screen.getByLabelText("Fecha entrega"), { target: { value: plannedDate } });

    await waitFor(() => expect(screen.getByText("VENT8-100")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Seleccionar todas" }));
    fireEvent.click(screen.getByRole("button", { name: "Validar Stock seleccionadas" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Confirmar disponibles seleccionadas" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Confirmar disponibles seleccionadas" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Confirmar disponibles" })).getByRole("button", { name: "Confirmar Disponibles" }));

    await waitFor(() => expect(screen.getByText("1 entrega parcial confirmada.")).toBeInTheDocument());
    expect(lastSplitBody).toMatchObject({
      lines: [{ fulfillment_line_id: "line-1", split_qty: 2 }],
    });
  });

  it("uses confirm-available for an existing planned delivery row", async () => {
    deliveryRowStock = true;
    renderWithQuery(<RepartoConfirmationPage />);

    fireEvent.change(screen.getByLabelText("Fecha entrega"), { target: { value: plannedDate } });

    await waitFor(() => expect(screen.getByText("VENT8-100")).toBeInTheDocument());
    const row = screen.getByRole("row", { name: /VENT8-100/i });
    fireEvent.click(within(row).getByRole("button", { name: "Validar Stock" }));

    await waitFor(() => expect(within(row).getByText("stock parcial")).toBeInTheDocument());
    fireEvent.click(within(row).getByRole("button", { name: "Confirmar Disponibles" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Confirmar disponibles" })).getByRole("button", { name: "Confirmar Disponibles" }));

    await waitFor(() => expect(screen.getByText("1 entrega parcial confirmada.")).toBeInTheDocument());
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/fulfillment/deliveries/delivery-existing/confirm-available"), expect.any(Object));
    expect(lastConfirmAvailableBody).toMatchObject({
      lines: [{ delivery_line_id: "delivery-line-1", planned_qty: 2 }],
    });
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
