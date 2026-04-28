import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeliveryExpeditionPage } from "./DeliveryExpeditionPage";

describe("DeliveryExpeditionPage", () => {
  let deliveryStatus: "confirmed" | "planned" | "preparing" | "prepared";
  let routeLocked: boolean;
  let orderFullyAllocated: boolean;

  beforeEach(() => {
    vi.useRealTimers();
    deliveryStatus = "planned";
    routeLocked = false;
    orderFullyAllocated = false;
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:remito"),
      revokeObjectURL: vi.fn(),
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/stock-check")) {
          return {
            ok: true,
            json: async () => ({
              result: {
                reference_type: "fulfillment_order",
                reference_id: "order-184",
                reference_number: "PED-000184",
                status: "ok",
                can_confirm: true,
                issues: [],
                lines: [
                  {
                    line_id: "184-1",
                    item_ref: "CER-104",
                    warehouse_ref: "PS003MT",
                    planned_qty: "2.88",
                    available_qty: "4",
                    uom: "m2",
                  },
                ],
              },
            }),
          };
        }
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
                    item_name: "Ceramica Calacatta",
                    item_long_name: "Ceramica Calacatta 60x60 caja 1,44",
                    category: "Ceramicos",
                    coverage_group: "STK",
                    warehouse_ref: "PS003MT",
                    ordered_qty: "18",
                    reserved_qty: orderFullyAllocated ? "0" : "18",
                    prepared_qty: orderFullyAllocated ? "18" : "14",
                    delivered_qty: "6",
                    cancelled_qty: "0",
                    pending_qty: "12",
                    planned_qty: orderFullyAllocated ? "18" : "10",
                    stock_available: "14",
                    max_dispatchable_qty: orderFullyAllocated ? "0" : "4",
                    uom: "m2",
                    sales_uom: "m2",
                    delivery_uom: "caja",
                    conversion_factor: "1.44",
                    planned_delivery_unit_qty: "6.94",
                    max_dispatchable_delivery_unit_qty: orderFullyAllocated ? "0" : "2",
                    unit_weight_kg: "15",
                    unit_volume_m3: "0.02",
                    planned_weight_kg: "150",
                    planned_volume_m3: "0.2",
                  },
                  {
                    id: "184-2",
                    legacy_line_id: "2",
                    item_ref: "SIN-001",
                    item_name: "Articulo sin disponible",
                    item_long_name: "Articulo sin disponible",
                    category: "Sin stock",
                    coverage_group: "STK",
                    warehouse_ref: "PS003MT",
                    ordered_qty: "1",
                    reserved_qty: "0",
                    prepared_qty: "0",
                    delivered_qty: "0",
                    cancelled_qty: "0",
                    pending_qty: "1",
                    planned_qty: "0",
                    stock_available: "0",
                    max_dispatchable_qty: "0",
                    uom: "Un",
                    sales_uom: "Un",
                    delivery_uom: "Un",
                    conversion_factor: "1",
                    planned_delivery_unit_qty: "0",
                    max_dispatchable_delivery_unit_qty: "0",
                    unit_weight_kg: "1",
                    unit_volume_m3: "0.001",
                    planned_weight_kg: "0",
                    planned_volume_m3: "0",
                  },
                ],
                deliveries: [
                  {
                    id: "del-184-1",
                    delivery_number: "ENT-000184-1",
                    status: deliveryStatus,
                    delivery_mode: "Reparto programado",
                    planned_date: "2026-04-24",
                    warehouse_ref: "PS003MT",
                    route_sheet: routeLocked
                      ? {
                          id: "route-1",
                          route_number: "HR-000000123",
                          status: "draft",
                          stop_id: "stop-1",
                          stop_status: "planned",
                        }
                      : null,
                    documents: [],
                    lines: [
                      {
                        id: "dl-1",
                        fulfillment_line_id: "184-1",
                        item_ref: "CER-104",
                        planned_qty: "8.64",
                        delivery_unit_qty: "6",
                        delivery_uom: "caja",
                        conversion_factor: "1.44",
                        uom: "m2",
                        warehouse_ref: "PS003MT",
                      },
                    ],
                  },
                  {
                    id: "del-184-2",
                    delivery_number: "ENT-000184-2",
                    status: "planned",
                    delivery_mode: "Reparto programado",
                    planned_date: "2026-04-25",
                    warehouse_ref: "PS003MT",
                    documents: [],
                    lines: [
                      {
                        id: "dl-2",
                        fulfillment_line_id: "184-1",
                        item_ref: "CER-104",
                        planned_qty: "5.76",
                        delivery_unit_qty: "4",
                        delivery_uom: "caja",
                        conversion_factor: "1.44",
                        uom: "m2",
                        warehouse_ref: "PS003MT",
                      },
                    ],
                  },
                  {
                    id: "del-184-3",
                    delivery_number: "ENT-000184-3",
                    status: "delivered_complete",
                    delivery_mode: "Reparto programado",
                    planned_date: "2026-04-24",
                    warehouse_ref: "PS003MT",
                    address_snapshot: {
                      receiver: "Autorizado Remito",
                      reference: "Retiro remito",
                    },
                    documents: [
                      {
                        id: "doc-184-3",
                        document_number: "R-ENT-000184-3",
                        document_type: "remito",
                        status: "issued",
                        issued_at: "2026-04-24T12:46:00Z",
                      },
                    ],
                    lines: [
                      {
                        id: "dl-3",
                        fulfillment_line_id: "184-1",
                        item_ref: "CER-104",
                        planned_qty: "1.44",
                        delivery_unit_qty: "1",
                        delivery_uom: "caja",
                        conversion_factor: "1.44",
                        uom: "m2",
                        warehouse_ref: "PS003MT",
                      },
                    ],
                  },
                ],
                customer: {
                  customer_ref: "CLI-10924",
                  name: "Ricardo Ortigoza",
                  document_type: "DNI",
                  document_number: "30111222",
                  phone: "3764000000",
                  email: "cliente@example.com",
                  address_text: "Uruguay 3947, Posadas",
                },
                pickup_authorization: {
                  name: "Ricardo Ortigoza",
                  reference: "Retiro con DNI",
                },
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
    expect(screen.getAllByText("Ricardo Ortigoza").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Ceramica Calacatta").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ENT-000184-1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ENT-000184-2").length).toBeGreaterThan(0);
    expect(screen.getByText("Articulos remitidos")).toBeInTheDocument();
    expect(screen.getByText("Almacen retiro")).toBeInTheDocument();
    expect(screen.getAllByText("PS003MT").length).toBeGreaterThan(0);
    expect(screen.getByText("6 caja")).toBeInTheDocument();
    expect(screen.getAllByText("24/04/2026").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Cantidad a entregar SIN-001")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Agregar entrega" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generar remito" })).toBeDisabled();
  });

  it("shows remito summary without changing the central delivery", async () => {
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pendientes" }));

    await waitFor(() => expect(screen.getAllByText("ENT-000184-3").length).toBeGreaterThan(0));
    const centralPanel = screen.getByRole("main");
    expect(within(centralPanel).getByText("ENT-000184-1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /ENT-000184-3/ }));

    expect(within(centralPanel).getByText("ENT-000184-1")).toBeInTheDocument();
    expect(within(centralPanel).queryByText("ENT-000184-3")).not.toBeInTheDocument();
    expect(screen.getAllByText("R-ENT-000184-3").length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByText("Autorizado Remito")).toBeInTheDocument());
    expect(screen.getByText("1 caja")).toBeInTheDocument();
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

  it("blocks remito generation for deliveries already assigned to a route sheet", async () => {
    deliveryStatus = "prepared";
    routeLocked = true;
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pendientes" }));

    await waitFor(() => expect(screen.getAllByText("HR-000000123").length).toBeGreaterThan(0));
    expect(screen.getByRole("button", { name: "Generar remito" })).toBeDisabled();
    expect(screen.getByText(/En hoja de ruta/)).toBeInTheDocument();
  });

  it("blocks adding another delivery when the order is fully allocated", async () => {
    orderFullyAllocated = true;
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pendientes" }));

    await waitFor(() => expect(screen.getByText("Pedido completo en entregas/HR")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Agregar entrega" })).toBeDisabled();
    expect(screen.getAllByText("18 m2").length).toBeGreaterThan(0);
  });

  it("confirms a new local delivery before preparation", async () => {
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pendientes" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Agregar entrega" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Agregar entrega" }));
    const qtyInput = screen.getByLabelText("Cantidad a entregar CER-104") as HTMLInputElement;
    const blockedInput = screen.getByLabelText("Cantidad a entregar SIN-001") as HTMLInputElement;
    expect(qtyInput.value).toBe("0");
    expect(blockedInput).toBeDisabled();
    expect(screen.getByRole("button", { name: "Confirmar entrega" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Entregar todo" })).not.toBeDisabled();

    fireEvent.change(qtyInput, { target: { value: "99" } });
    expect(qtyInput.value).toBe("2");

    fireEvent.click(screen.getByRole("button", { name: "Entregar todo" }));
    expect(qtyInput.value).toBe("2");
    expect(screen.getAllByText(/43,2 kg/).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByRole("button", { name: "Validar Stock" })).not.toBeDisabled());
    expect(screen.getByRole("button", { name: "Confirmar entrega" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Enviar a preparar" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Validar Stock" }));
    await waitFor(() => expect(screen.getByText(/Stock validado. Puede confirmar/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Confirmar entrega" })).not.toBeDisabled();

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
