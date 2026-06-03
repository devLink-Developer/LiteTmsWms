import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useWorkspaceStore } from "../../stores/useWorkspaceStore";
import { DeliveryExpeditionPage } from "./DeliveryExpeditionPage";

describe("DeliveryExpeditionPage", () => {
  let deliveryStatus: "confirmed" | "planned" | "preparing" | "prepared";
  let routeLocked: boolean;
  let orderFullyAllocated: boolean;
  let crossWarehouseConflict: boolean;
  let confirmWarehouseConflict: boolean;
  let fullRemittedOrder: boolean;
  let duplicatedStockIssues: boolean;
  let activeLineStockIssue: boolean;
  let activeLinePartialStockIssue: boolean;
  let orderImpacts: boolean;
  let cancellationScenario: "none" | "full" | "partial";
  let lastStockCheckBody: Record<string, unknown>;
  let lastSplitBody: Record<string, unknown>;
  let lastConfirmBody: Record<string, unknown>;

  beforeEach(() => {
    vi.useRealTimers();
    deliveryStatus = "planned";
    routeLocked = false;
    orderFullyAllocated = false;
    crossWarehouseConflict = false;
    confirmWarehouseConflict = false;
    fullRemittedOrder = false;
    duplicatedStockIssues = false;
    activeLineStockIssue = false;
    activeLinePartialStockIssue = false;
    orderImpacts = false;
    cancellationScenario = "none";
    lastStockCheckBody = {};
    lastSplitBody = {};
    lastConfirmBody = {};
    useWorkspaceStore.setState({
      warehouseRef: "PS003MT",
      branchRef: "test",
      role: "tester",
      permissions: [],
      authorizedWarehouses: ["PS003MT"],
    });
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:remito"),
      revokeObjectURL: vi.fn(),
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/stock-check")) {
          lastStockCheckBody = init?.body ? JSON.parse(String(init.body)) : {};
          if (crossWarehouseConflict) {
            return {
              ok: false,
              status: 409,
              json: async () => ({
                error: {
                  code: "cross_warehouse_confirmed_delivery",
                  message: "La entrega ENT-OTRO ya esta confirmada en PS999.",
                  details: {
                    delivery_id: "del-cross",
                    delivery_number: "ENT-OTRO",
                    fulfillment_id: "order-184",
                    sales_order_number: "PED-000184",
                    source_warehouse_ref: "PS999",
                    target_warehouse_ref: "PS003MT",
                    status: "confirmed",
                  },
                  correlation_id: "",
                },
              }),
            };
          }
          if (duplicatedStockIssues) {
            return {
              ok: true,
              status: 200,
              json: async () => ({
                result: {
                  reference_type: "fulfillment_order",
                  reference_id: "order-184",
                  reference_number: "PED-000184",
                  status: "insufficient",
                  can_confirm: false,
                  issues: [
                    {
                      line_id: "184-1",
                      item_ref: "100100",
                      warehouse_ref: "PS003MT",
                      planned_qty: "1",
                      available_qty: "0",
                      uom: "un",
                    },
                    {
                      line_id: "184-2",
                      item_ref: "100101",
                      warehouse_ref: "PS003MT",
                      planned_qty: "1",
                      available_qty: "0",
                      uom: "un",
                    },
                    {
                      line_id: "184-1",
                      item_ref: "100100",
                      warehouse_ref: "PS003MT",
                      planned_qty: "1",
                      available_qty: "0",
                      uom: "un",
                    },
                    {
                      line_id: "184-2",
                      item_ref: "100101",
                      warehouse_ref: "PS003MT",
                      planned_qty: "1",
                      available_qty: "0",
                      uom: "un",
                    },
                  ],
                  lines: [],
                },
              }),
            };
          }
          if (activeLineStockIssue) {
            return {
              ok: true,
              status: 200,
              json: async () => ({
                result: {
                  reference_type: "fulfillment_order",
                  reference_id: "order-184",
                  reference_number: "PED-000184",
                  status: "insufficient",
                  can_confirm: false,
                  issues: [
                    {
                      line_id: "184-1",
                      item_ref: "CER-104",
                      warehouse_ref: "PS003MT",
                      planned_qty: "2.88",
                      available_qty: "0",
                      uom: "m2",
                    },
                  ],
                  lines: [
                    {
                      line_id: "184-1",
                      item_ref: "CER-104",
                      warehouse_ref: "PS003MT",
                      planned_qty: "2.88",
                      available_qty: "0",
                      uom: "m2",
                    },
                  ],
                },
              }),
            };
          }
          if (activeLinePartialStockIssue) {
            const requestedLine = Array.isArray((lastStockCheckBody as { lines?: unknown[] }).lines)
              ? (lastStockCheckBody as { lines: Array<{ delivery_unit_qty?: number }> }).lines[0]
              : null;
            const requestedUnits = Number(requestedLine?.delivery_unit_qty ?? 0);
            if (requestedUnits <= 1) {
              return {
                ok: true,
                status: 200,
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
                        planned_qty: "1.44",
                        available_qty: "1.44",
                        uom: "m2",
                      },
                    ],
                  },
                }),
              };
            }
            return {
              ok: true,
              status: 200,
              json: async () => ({
                result: {
                  reference_type: "fulfillment_order",
                  reference_id: "order-184",
                  reference_number: "PED-000184",
                  status: "insufficient",
                  can_confirm: false,
                  issues: [
                    {
                      line_id: "184-1",
                      item_ref: "CER-104",
                      warehouse_ref: "PS003MT",
                      planned_qty: "2.88",
                      available_qty: "1.44",
                      uom: "m2",
                    },
                  ],
                  lines: [
                    {
                      line_id: "184-1",
                      item_ref: "CER-104",
                      warehouse_ref: "PS003MT",
                      planned_qty: "2.88",
                      available_qty: "1.44",
                      uom: "m2",
                    },
                  ],
                },
              }),
            };
          }
          return {
            ok: true,
            status: 200,
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
        if (url.includes("/reassign-warehouse")) {
          const body = init?.body ? JSON.parse(String(init.body)) : {};
          crossWarehouseConflict = false;
          confirmWarehouseConflict = false;
          deliveryStatus = "confirmed";
          return {
            ok: true,
            status: 200,
            json: async () => ({
              result: {
                id: "del-cross",
                delivery_number: url.includes("del-184-1") ? "ENT-000184-1" : "ENT-OTRO",
                status: "confirmed",
                delivery_mode: "Reparto programado",
                planned_date: "2026-04-24",
                fulfillment_id: "order-184",
                sales_order_number: "PED-000184",
                warehouse_ref: body.target_warehouse_ref ?? "PS003MT",
                documents: [],
                lines: [],
              },
            }),
          };
        }
        if (url.includes("/validate-stock")) {
          lastConfirmBody = init?.body ? JSON.parse(String(init.body)) : {};
          if (confirmWarehouseConflict) {
            return {
              ok: false,
              status: 409,
              json: async () => ({
                error: {
                  code: "cross_warehouse_confirmed_delivery",
                  message: "La entrega ENT-000184-1 ya esta confirmada en PS003MT.",
                  details: {
                    delivery_id: "del-184-1",
                    delivery_number: "ENT-000184-1",
                    fulfillment_id: "order-184",
                    sales_order_number: "PED-000184",
                    source_warehouse_ref: "PS003MT",
                    target_warehouse_ref: "PR03DP",
                    status: "confirmed",
                  },
                  correlation_id: "",
                },
              }),
            };
          }
          deliveryStatus = "confirmed";
          return {
            ok: true,
            status: 200,
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
          lastSplitBody = init?.body ? JSON.parse(String(init.body)) : {};
          return {
            ok: true,
            status: 200,
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
            status: 200,
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
            status: 200,
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
            status: 200,
            blob: async () => new Blob(["pdf"], { type: "application/pdf" }),
          };
        }
        if (url.includes("/remito")) {
          return {
            ok: true,
            status: 200,
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
          status: 200,
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
                sales_order_type: "P",
                source_hash: "hash",
                impacts: orderImpacts
                  ? [
                      {
                        id: "impact-annulment-1",
                        type: "anulacion",
                        impact_type: "annulment",
                        status: "applied",
                        sales_order_number: "ANU-000184",
                        transaction_number: "TX-ANU-184",
                        original_sales_order_number: "PED-000184",
                        warehouse_ref: "PS003MT",
                        impact_date: "2026-04-24T10:00:00Z",
                        lines: [
                          {
                            id: "impact-line-annulment-1",
                            fulfillment_line_id: "184-1",
                            item_ref: "CER-104",
                            warehouse_ref: "PS003MT",
                            quantity: "2.88",
                            applied_qty: "2.88",
                            uom: "m2",
                          },
                        ],
                      },
                      {
                        id: "impact-return-1",
                        type: "devolucion",
                        impact_type: "return",
                        status: "applied",
                        sales_order_number: "DEV-000184",
                        transaction_number: "TX-DEV-184",
                        original_sales_order_number: "PED-000184",
                        warehouse_ref: "PS003MT",
                        impact_date: "2026-04-24T11:00:00Z",
                        lines: [
                          {
                            id: "impact-line-return-1",
                            fulfillment_line_id: "184-1",
                            item_ref: "CER-104",
                            warehouse_ref: "PS003MT",
                            quantity: "1.44",
                            applied_qty: "1.44",
                            uom: "m2",
                          },
                        ],
                      },
                    ]
                  : [],
                movements: [
                  {
                    key: "fulfillment:order-184:created",
                    at: "2026-04-24T08:00:00Z",
                    label: "Pedido ingresado a TMS/WMS",
                    status: "pending",
                    detail: "PED-000184",
                    actor: "sync",
                    source_type: "fulfillment_order",
                    source_ref: "order-184",
                  },
                  {
                    key: "document:doc-184-3:issued",
                    at: "2026-04-24T12:46:00Z",
                    label: "Remito emitido",
                    status: "closed",
                    detail: "R-ENT-000184-3",
                    actor: "operario-1",
                    source_type: "delivery_document",
                    source_ref: "doc-184-3",
                    document_number: "R-ENT-000184-3",
                  },
                  ...(orderImpacts
                    ? [
                        {
                          key: "impact:impact-annulment-1:annulment",
                          at: "2026-04-24T10:00:00Z",
                          label: "Anulacion aplicada",
                          status: "applied",
                          detail: "ANU-000184",
                          actor: "sync",
                          source_type: "fulfillment_order_impact",
                          source_ref: "impact-annulment-1",
                        },
                        {
                          key: "impact:impact-return-1:return",
                          at: "2026-04-24T11:00:00Z",
                          label: "Devolucion recibida",
                          status: "applied",
                          detail: "DEV-000184",
                          actor: "sync",
                          source_type: "fulfillment_order_impact",
                          source_ref: "impact-return-1",
                          returned_qty: "1.44",
                          uom: "m2",
                        },
                        {
                          key: "impact:impact-return-1:return-stock",
                          at: "2026-04-24T11:00:01Z",
                          label: "Stock ingresado",
                          status: "applied",
                          detail: "PS003MT",
                          actor: "sync",
                          source_type: "inventory_ledger_entry",
                          source_ref: "impact-return-1",
                          returned_qty: "1.44",
                          uom: "m2",
                        },
                      ]
                    : []),
                  ...(routeLocked
                    ? [
                        {
                          key: "route-stop:stop-1:assigned",
                          at: "2026-04-24T14:00:00Z",
                          label: "Asignada a hoja de ruta",
                          status: "planned",
                          detail: "Parada 1",
                          actor: "planner",
                          source_type: "route_stop",
                          source_ref: "stop-1",
                          route_number: "HR-000000123",
                        },
                      ]
                    : []),
                ],
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
                    ordered_qty: fullRemittedOrder ? "1.44" : "18",
                    reserved_qty: orderFullyAllocated || fullRemittedOrder || cancellationScenario !== "none" ? "0" : "18",
                    prepared_qty: orderFullyAllocated ? "18" : fullRemittedOrder || cancellationScenario !== "none" ? "0" : "14",
                    delivered_qty: fullRemittedOrder || cancellationScenario !== "none" ? "0" : "6",
                    cancelled_qty: cancellationScenario !== "none" ? "18" : orderImpacts ? "2.88" : "0",
                    returned_qty: orderImpacts ? "1.44" : "0",
                    pending_qty: cancellationScenario !== "none" ? "0" : fullRemittedOrder ? "1.44" : "12",
                    planned_qty: cancellationScenario !== "none" ? "0" : orderFullyAllocated ? "18" : fullRemittedOrder ? "1.44" : "10",
                    stock_available: "14",
                    max_dispatchable_qty: orderFullyAllocated || fullRemittedOrder || cancellationScenario !== "none" ? "0" : "4",
                    uom: "m2",
                    sales_uom: "m2",
                    delivery_uom: "caja",
                    conversion_factor: "1.44",
                    planned_delivery_unit_qty: fullRemittedOrder ? "1" : "6.94",
                    max_dispatchable_delivery_unit_qty: orderFullyAllocated || fullRemittedOrder || cancellationScenario !== "none" ? "0" : "2",
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
                    ordered_qty: fullRemittedOrder ? "0" : "1",
                    reserved_qty: "0",
                    prepared_qty: "0",
                    delivered_qty: "0",
                    cancelled_qty: cancellationScenario === "full" ? "1" : "0",
                    pending_qty: fullRemittedOrder || cancellationScenario === "full" ? "0" : "1",
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
                deliveries:
                  cancellationScenario !== "none"
                    ? []
                    : [
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
                          movements: [
                            {
                              key: "delivery:del-184-1:created",
                              at: "2026-04-24T08:30:00Z",
                              label: "Entrega creada",
                              status: deliveryStatus,
                              detail: "ENT-000184-1",
                              actor: "operario-1",
                              source_type: "delivery_order",
                              source_ref: "del-184-1",
                            },
                          ],
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
                          movements: [],
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
                          movements: [
                            {
                              key: "delivery:del-184-3:delivered",
                              at: "2026-04-24T12:46:00Z",
                              label: "Remito emitido",
                              status: "delivered_complete",
                              detail: "R-ENT-000184-3",
                              actor: "operario-1",
                              source_type: "delivery_order",
                              source_ref: "del-184-3",
                              document_number: "R-ENT-000184-3",
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
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getAllByText("PED-000184").length).toBeGreaterThan(0));
    expect(screen.getAllByText("Ricardo Ortigoza").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Ceramica Calacatta").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ENT-000184-1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ENT-000184-2").length).toBeGreaterThan(0);
    expect(screen.getByText("Resumen de entrega")).toBeInTheDocument();
    expect(screen.getByText("Articulos de la entrega")).toBeInTheDocument();
    expect(screen.queryByText("Un pedido puede tener multiples entregas y remitos.")).not.toBeInTheDocument();
    expect(screen.queryByText("Articulos remitidos")).not.toBeInTheDocument();
    expect(screen.getByText("Almacen retiro")).toBeInTheDocument();
    expect(screen.getByText("Trazabilidad")).toBeInTheDocument();
    expect(screen.queryByText("Movimientos del pedido")).not.toBeInTheDocument();
    expect(screen.getByText("2 movimientos")).toBeInTheDocument();
    expect(screen.queryByText("Pedido ingresado a TMS/WMS")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ver trazabilidad" }));
    expect(screen.getByRole("dialog", { name: "PED-000184" })).toBeInTheDocument();
    expect(screen.getByText("Pedido ingresado a TMS/WMS")).toBeInTheDocument();
    expect(screen.getAllByText("Remito emitido").length).toBeGreaterThan(0);
    expect(screen.getAllByText("PS003MT").length).toBeGreaterThan(0);
    expect(screen.getAllByText("6 caja").length).toBeGreaterThan(0);
    expect(screen.getAllByText("24/04/2026").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Cantidad a entregar SIN-001")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Agregar entrega" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generar remito" })).toBeDisabled();
  });

  it("renders annulment and return impacts inside the original order", async () => {
    orderImpacts = true;
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getAllByText("PED-000184").length).toBeGreaterThan(0));
    expect(screen.getByText("Anulacion")).toBeInTheDocument();
    expect(screen.getByText("Devolucion")).toBeInTheDocument();
    expect(screen.getByText("Stock ingresado")).toBeInTheDocument();
    expect(screen.getByText("Anulado 2,88 m2")).toBeInTheDocument();
    expect(screen.getByText("Devuelto 1,44 m2")).toBeInTheDocument();
    expect(screen.queryByText("Un pedido puede tener multiples entregas y remitos.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Ver trazabilidad" }));
    expect(screen.getByText("Anulacion aplicada")).toBeInTheDocument();
    expect(screen.getByText("Devolucion recibida")).toBeInTheDocument();
    expect(screen.getAllByText("Stock ingresado").length).toBeGreaterThan(0);
  });

  it("shows remito summary without changing the central delivery", async () => {
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getAllByText("ENT-000184-3").length).toBeGreaterThan(0));
    const centralPanel = screen.getByRole("main");
    expect(within(centralPanel).getByText("ENT-000184-1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /ENT-000184-3/ }));

    expect(within(centralPanel).getByText("ENT-000184-1")).toBeInTheDocument();
    expect(within(centralPanel).queryByText("ENT-000184-3")).not.toBeInTheDocument();
    expect(screen.getAllByText("R-ENT-000184-3").length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByText("Autorizado Remito")).toBeInTheDocument());
    expect(screen.getByText("Resumen de remito")).toBeInTheDocument();
    expect(screen.getByText("Articulos del remito")).toBeInTheDocument();
    expect(screen.getAllByText("1 caja").length).toBeGreaterThan(0);
  });

  it("labels a fully remitted order as remito generado instead of parcial", async () => {
    fullRemittedOrder = true;
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getAllByText("remito generado").length).toBeGreaterThan(0));
    expect(screen.queryByText("parcial")).not.toBeInTheDocument();
  });

  it("labels a fully annulled order as anulada instead of pendiente", async () => {
    cancellationScenario = "full";
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getAllByText("anulada").length).toBeGreaterThan(0));
    expect(screen.queryByText("pendiente")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Agregar entrega" })).toBeDisabled();
  });

  it("keeps a partially annulled order pending when another line remains open", async () => {
    cancellationScenario = "partial";
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getAllByText("pendiente").length).toBeGreaterThan(0));
    expect(screen.queryByText("anulada")).not.toBeInTheDocument();
  });

  it("labels a confirmed split delivery as parcial confirmada with the remaining balance", async () => {
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getAllByText("parcial confirmada").length).toBeGreaterThan(0));
    expect(screen.getAllByText("Queda 6 caja").length).toBeGreaterThan(0);
    expect(screen.getAllByText("6 caja").length).toBeGreaterThan(0);
  });

  it("moves a delivery through preparation before enabling remito", async () => {
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

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

  it("requires stock validation before reassigning a reserved delivery from another warehouse", async () => {
    deliveryStatus = "confirmed";
    confirmWarehouseConflict = true;
    useWorkspaceStore.setState({ warehouseRef: "PR03DP", authorizedWarehouses: ["PR03DP"] });
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getByText("Confirmado en PS003MT")).toBeInTheDocument());
    expect(screen.queryByText(/El pedido viene de/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Validar Stock" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Confirmar entrega" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Enviar a preparar" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Validar Stock" }));

    await waitFor(() => expect(screen.getByText("Stock validado.")).toBeInTheDocument());
    expect(lastStockCheckBody).toMatchObject({ allow_past_reparto_date: true, target_warehouse_ref: "PR03DP" });
    expect(screen.getByRole("button", { name: "Confirmar entrega" })).not.toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Confirmar entrega" }));

    await waitFor(() => expect(screen.getByRole("dialog", { name: "Entrega confirmada en otro deposito" })).toBeInTheDocument());
    expect(lastConfirmBody).toMatchObject({ allow_past_reparto_date: true, target_warehouse_ref: "PR03DP" });

    fireEvent.click(screen.getByRole("button", { name: "Confirmar en PR03DP" }));

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Entrega confirmada en otro deposito" })).not.toBeInTheDocument());
    expect(screen.getByText(/ENT-000184-1 reasignada a PR03DP./)).toBeInTheDocument();
  });

  it("blocks remito generation for deliveries already assigned to a route sheet", async () => {
    deliveryStatus = "prepared";
    routeLocked = true;
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getAllByText("HR-000000123").length).toBeGreaterThan(0));
    expect(screen.getByRole("button", { name: "Generar remito" })).toBeDisabled();
    expect(screen.getByText(/En hoja de ruta/)).toBeInTheDocument();
  });

  it("blocks adding another delivery when the order is fully allocated", async () => {
    orderFullyAllocated = true;
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getByText("Pedido completo en entregas/HR")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Agregar entrega" })).toBeDisabled();
    expect(screen.getAllByText("18 m2").length).toBeGreaterThan(0);
  });

  it("confirms a new local delivery before preparation", async () => {
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Agregar entrega" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Agregar entrega" }));
    const qtyInput = screen.getByLabelText("Cantidad a entregar CER-104") as HTMLInputElement;
    const blockedInput = screen.getByLabelText("Cantidad a entregar SIN-001") as HTMLInputElement;
    expect(qtyInput.value).toBe("0");
    expect(blockedInput).toBeDisabled();
    expect(screen.getByRole("columnheader", { name: "Pendiente" })).toBeInTheDocument();
    const blockedRowCells = within(screen.getByText("SIN-001").closest("tr") as HTMLElement).getAllByRole("cell");
    expect(blockedRowCells[5]).toHaveTextContent("1 Un");
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
    await waitFor(() => expect(screen.getByText("Stock validado.")).toBeInTheDocument());
    expect(lastStockCheckBody).toMatchObject({ allow_past_reparto_date: true, target_warehouse_ref: "PS003MT" });
    expect(screen.getByRole("button", { name: "Confirmar entrega" })).not.toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Confirmar entrega" }));
    await waitFor(() => expect(screen.getByText(/ENT-000184-1 confirmada; stock reservado./)).toBeInTheDocument());
    expect(lastSplitBody).toMatchObject({ allow_past_reparto_date: true, target_warehouse_ref: "PS003MT" });
    expect(lastConfirmBody).toMatchObject({ allow_past_reparto_date: true, target_warehouse_ref: "PS003MT" });
  });

  it("shows insufficient stock issues as a deduplicated readable list", async () => {
    duplicatedStockIssues = true;
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Agregar entrega" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Agregar entrega" }));
    fireEvent.click(screen.getByRole("button", { name: "Entregar todo" }));
    fireEvent.click(screen.getByRole("button", { name: "Validar Stock" }));

    await waitFor(() => expect(screen.getByText(/Stock insuficiente en 2 articulos\./)).toBeInTheDocument());
    const alertText = screen.getByRole("alert").textContent ?? "";
    expect(alertText).toContain("100100: solicitado 1 un; disponible 0 un");
    expect(alertText).toContain("100101: solicitado 1 un; disponible 0 un");
    expect(alertText.match(/100100/g) ?? []).toHaveLength(1);
    expect(alertText.match(/100101/g) ?? []).toHaveLength(1);
    expect(alertText).not.toContain(" / ");
    expect(screen.getByRole("button", { name: "Confirmar entrega" })).toBeDisabled();
  });

  it("marks validated stock rows in green after validation", async () => {
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Agregar entrega" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Agregar entrega" }));
    fireEvent.click(screen.getByRole("button", { name: "Entregar todo" }));
    fireEvent.click(screen.getByRole("button", { name: "Validar Stock" }));

    await waitFor(() => expect(screen.getByText("Stock validado.")).toBeInTheDocument());
    const validatedRow = screen.getByLabelText("Cantidad a entregar CER-104").closest("tr");
    expect(validatedRow).toHaveClass("bg-emerald-50");
    expect(within(validatedRow as HTMLElement).getByText("stock ok")).toBeInTheDocument();
  });

  it("marks insufficient stock rows in red after validation", async () => {
    activeLineStockIssue = true;
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Agregar entrega" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Agregar entrega" }));
    fireEvent.click(screen.getByRole("button", { name: "Entregar todo" }));
    fireEvent.click(screen.getByRole("button", { name: "Validar Stock" }));

    await waitFor(() => expect(screen.getByText(/Stock insuficiente en 1 articulo\./)).toBeInTheDocument());
    const invalidRow = screen.getByLabelText("Cantidad a entregar CER-104").closest("tr");
    expect(invalidRow).toHaveClass("bg-rose-50");
    expect(within(invalidRow as HTMLElement).getByText("sin stock")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirmar entrega" })).toBeDisabled();
  });

  it("confirms available stock as a partial draft delivery", async () => {
    activeLinePartialStockIssue = true;
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Agregar entrega" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Agregar entrega" }));
    fireEvent.click(screen.getByRole("button", { name: "Entregar todo" }));
    fireEvent.click(screen.getByRole("button", { name: "Validar Stock" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Confirmar Disponibles" })).not.toBeDisabled());
    const partialRow = screen.getByLabelText("Cantidad a entregar CER-104").closest("tr");
    expect(partialRow).toHaveClass("bg-amber-50");
    expect(within(partialRow as HTMLElement).getByText("parcial")).toBeInTheDocument();
    expect(within(partialRow as HTMLElement).getByText("Entregar disponible")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Confirmar Disponibles" }));
    const dialog = screen.getByRole("dialog", { name: "Confirmar disponibles" });
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText(/falta 1 caja/)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Confirmar Disponibles" }));

    await waitFor(() => expect(screen.getByText(/ENT-000184-1 confirmada parcialmente; stock reservado./)).toBeInTheDocument());
    expect(lastSplitBody).toMatchObject({
      lines: [{ fulfillment_line_id: "184-1", delivery_unit_qty: 1 }],
    });
  });

  it("shows a modal and reassigns a confirmed delivery from another warehouse", async () => {
    crossWarehouseConflict = true;
    useWorkspaceStore.setState({ warehouseRef: "PS003MT", authorizedWarehouses: ["PS003MT"] });
    render(<DeliveryExpeditionPage />);

    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "PED-000184" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Agregar entrega" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Agregar entrega" }));
    fireEvent.click(screen.getByRole("button", { name: "Entregar todo" }));
    fireEvent.click(screen.getByRole("button", { name: "Validar Stock" }));

    await waitFor(() => expect(screen.getByRole("dialog", { name: "Entrega confirmada en otro deposito" })).toBeInTheDocument());
    expect(screen.getAllByText("ENT-OTRO").length).toBeGreaterThan(0);
    expect(screen.getByText("PS999")).toBeInTheDocument();
    expect(screen.getAllByText("PS003MT").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Confirmar en PS003MT" }));

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Entrega confirmada en otro deposito" })).not.toBeInTheDocument());
    expect(screen.getByText(/ENT-OTRO reasignada a PS003MT./)).toBeInTheDocument();
  });

  it("searches pending orders by customer DNI", async () => {
    render(<DeliveryExpeditionPage />);

    fireEvent.click(screen.getByRole("button", { name: "DNI cliente" }));
    fireEvent.change(screen.getByLabelText("Busqueda"), { target: { value: "30111222" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar pedido" }));

    await waitFor(() => expect(screen.getAllByText("PED-000184").length).toBeGreaterThan(0));
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("target_warehouse_ref=PS003MT"), expect.any(Object));
  });
});
