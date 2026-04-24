import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeliveryExpeditionPage } from "./DeliveryExpeditionPage";

describe("DeliveryExpeditionPage", () => {
  let deliveryStatus: "confirmed" | "planned" | "preparing" | "prepared";

  beforeEach(() => {
    vi.useRealTimers();
    deliveryStatus = "planned";
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:remito"),
      revokeObjectURL: vi.fn(),
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/validate-stock")) {
          deliveryStatus = "confirmed";
          return {
            ok: true,
            json: async () => ({
              result: {
                id: "del-184-1",
                delivery_number: "ENT-000184-1",
                status: deliveryStatus,
                delivery_mode: "Reparto programado",
                planned_date: "2026-04-24",
                fulfillment_id: "order-184",
                sales_order_number: "PED-000184",
                documents: [],
                lines: [],
              },
            }),
          };
        }
        if (url.includes("/split")) {
          return {
            ok: true,
            json: async () => ({
              result: {
                id: "del-184-1",
                delivery_number: "ENT-000184-1",
                status: "created",
                delivery_mode: "Reparto programado",
                planned_date: "2026-04-24",
                fulfillment_id: "order-184",
                sales_order_number: "PED-000184",
                documents: [],
                lines: [{ id: "dl-1", fulfillment_line_id: "184-1", item_ref: "CER-104", planned_qty: "4", uom: "CJ" }],
              },
            }),
          };
        }
        if (url.includes("/send-to-prepare")) {
          deliveryStatus = "preparing";
          return {
            ok: true,
            json: async () => ({
              result: {
                id: "del-184-1",
                delivery_number: "ENT-000184-1",
                status: deliveryStatus,
                delivery_mode: "Reparto programado",
                planned_date: "2026-04-24",
                fulfillment_id: "order-184",
                sales_order_number: "PED-000184",
                documents: [],
                lines: [],
                preparation_task: {
                  id: "prep-1",
                  delivery_id: "del-184-1",
                  status: "assigned",
                  assigned_employee_ref: "operario-1",
                  assigned_at: "2026-04-24T09:00:00Z",
                  prepared_by: "",
                  prepared_at: null,
                  notes: "",
                },
              },
            }),
          };
        }
        if (url.includes("/mark-prepared")) {
          deliveryStatus = "prepared";
          return {
            ok: true,
            json: async () => ({
              result: {
                id: "del-184-1",
                delivery_number: "ENT-000184-1",
                status: deliveryStatus,
                delivery_mode: "Reparto programado",
                planned_date: "2026-04-24",
                fulfillment_id: "order-184",
                sales_order_number: "PED-000184",
                documents: [],
                lines: [],
              },
            }),
          };
        }
        if (url.includes("/remito.pdf")) {
          return {
            ok: true,
            blob: async () => new Blob(["pdf"], { type: "application/pdf" }),
          };
        }
        if (url.includes("/remito")) {
          return {
            ok: true,
            json: async () => ({
              result: {
                id: "doc-1",
                document_number: "R-ENT-000184-1",
                document_type: "remito",
                status: "issued",
                issued_at: "2026-04-24T09:00:00Z",
                delivery_id: "del-184-1",
                sales_order_number: "PED-000184",
              },
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({
            results: [
              {
                id: "order-184",
                created_at: "2026-04-24T08:00:00Z",
                updated_at: "2026-04-24T08:00:00Z",
                fulfillment_number: "PED-000184",
                status: "partial",
                sales_order_number: "PED-000184",
                transaction_number: "TX-009872",
                customer_ref: "CLI-10924",
                customer_dni: "30111222",
                delivery_mode: "Reparto programado",
                requested_date: "2026-04-24",
                warehouse_ref: "PS003MT",
                source_hash: "hash",
                lines: [
                  {
                    id: "184-1",
                    legacy_line_id: "1",
                    item_ref: "CER-104",
                    warehouse_ref: "PS003MT",
                    ordered_qty: "18",
                    reserved_qty: "18",
                    prepared_qty: "14",
                    delivered_qty: "6",
                    cancelled_qty: "0",
                    pending_qty: "12",
                    planned_qty: "10",
                    stock_available: "14",
                    max_dispatchable_qty: "4",
                    uom: "CJ",
                  },
                ],
                deliveries: [
                  {
                    id: "del-184-1",
                    delivery_number: "ENT-000184-1",
                    status: deliveryStatus,
                    delivery_mode: "Reparto programado",
                    planned_date: "2026-04-24",
                    documents: [],
                    lines: [{ id: "dl-1", fulfillment_line_id: "184-1", item_ref: "CER-104", planned_qty: "6", uom: "CJ" }],
                  },
                  {
                    id: "del-184-2",
                    delivery_number: "ENT-000184-2",
                    status: "planned",
                    delivery_mode: "Reparto programado",
                    planned_date: "2026-04-25",
                    documents: [],
                    lines: [{ id: "dl-2", fulfillment_line_id: "184-1", item_ref: "CER-104", planned_qty: "4", uom: "CJ" }],
                  },
                ],
              },
            ],
          }),
        };
      }),
    );
  });

  it("renders expedition workflow for split deliveries", async () => {
    render(<DeliveryExpeditionPage />);

    expect(screen.getByRole("heading", { name: "Expedicion de entregas" })).toBeInTheDocument();
    expect(screen.queryByText("PED-000184")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pendientes" }));

    await waitFor(() => expect(screen.getAllByText("PED-000184").length).toBeGreaterThan(0));
    expect(screen.getAllByText("ENT-000184-1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ENT-000184-2").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Agregar entrega" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generar remito" })).toBeDisabled();
  });

  it("moves a delivery through preparation before enabling remito", async () => {
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pendientes" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Confirmar entrega" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "Enviar a preparar" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Marcar preparada" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Generar remito" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Enviar a preparar" }));
    await waitFor(() => expect(screen.getByText(/ENT-000184-1 enviada a preparar./)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Marcar preparada" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Generar remito" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Marcar preparada" }));
    await waitFor(() => expect(screen.getByText(/ENT-000184-1 marcada como preparada./)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Generar remito" })).not.toBeDisabled();
  });

  it("confirms a new local delivery before preparation", async () => {
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pendientes" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Agregar entrega" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Agregar entrega" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirmar entrega" })).not.toBeDisabled());
    expect(screen.getByRole("button", { name: "Enviar a preparar" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Confirmar entrega" }));
    await waitFor(() => expect(screen.getByText(/ENT-000184-1 confirmada; stock reservado./)).toBeInTheDocument());
  });

  it("searches pending orders by customer DNI", async () => {
    render(<DeliveryExpeditionPage />);

    fireEvent.click(screen.getByRole("button", { name: "DNI cliente" }));
    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "30111222" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pendientes" }));

    await waitFor(() => expect(screen.getAllByText("PED-000184").length).toBeGreaterThan(0));
  });
});
