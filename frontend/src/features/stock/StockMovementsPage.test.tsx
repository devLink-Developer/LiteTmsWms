import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StockMovementsPage } from "./StockMovementsPage";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  };
}

const ledgerRows = [
  {
    id: "dispatch-in",
    movement_type: "dispatch",
    direction: "increase",
    warehouse_ref: "PR03DP",
    location_ref: "PR03DP-TRN-GEN",
    lot_ref: "",
    item_ref: "100100",
    stock_state: "delivered",
    quantity: "10",
    uom: "UN",
    document_type: "delivery_document",
    document_ref: "DOC-DISPATCH",
    created_by: "eespinoza@familiabercomat.com",
    posted_at: "2026-06-02T18:01:03.000Z",
  },
  {
    id: "dispatch-out",
    movement_type: "dispatch",
    direction: "decrease",
    warehouse_ref: "PR03DP",
    location_ref: "PR03DP-PRE-GEN",
    lot_ref: "",
    item_ref: "100100",
    stock_state: "packed",
    quantity: "10",
    uom: "UN",
    document_type: "delivery_document",
    document_ref: "DOC-DISPATCH",
    created_by: "eespinoza@familiabercomat.com",
    posted_at: "2026-06-02T18:01:02.000Z",
  },
  {
    id: "reservation-in",
    movement_type: "reservation_hold",
    direction: "increase",
    warehouse_ref: "PR03DP",
    location_ref: "PR03DP-RSV-GEN",
    lot_ref: "",
    item_ref: "100100",
    stock_state: "reserved",
    quantity: "10",
    uom: "UN",
    document_type: "inventory_reservation",
    document_ref: "RSV-100100",
    created_by: "warehouse.bot",
    posted_at: "2026-06-02T13:57:18.000Z",
  },
  {
    id: "reservation-out",
    movement_type: "reservation_hold",
    direction: "decrease",
    warehouse_ref: "PR03DP",
    location_ref: "PR03DP-DSP-GEN",
    lot_ref: "",
    item_ref: "100100",
    stock_state: "packed",
    quantity: "10",
    uom: "UN",
    document_type: "inventory_reservation",
    document_ref: "RSV-100100",
    created_by: "warehouse.bot",
    posted_at: "2026-06-02T13:57:17.000Z",
  },
  {
    id: "adjustment-in",
    movement_type: "adjustment",
    direction: "increase",
    warehouse_ref: "PR03DP",
    location_ref: "PR03DP-DSP-GEN",
    lot_ref: "",
    item_ref: "100100",
    stock_state: "packed",
    quantity: "1000",
    uom: "UN",
    document_type: "inventory_manual_adjustment",
    document_ref: "AJU-100100",
    reason: "alta inicial",
    created_by: "tester",
    posted_at: "2026-06-02T13:04:46.000Z",
  },
];

describe("StockMovementsPage", () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      warehouseRef: "PR03DP",
      branchRef: "S001",
      role: "Operador",
      permissions: ["stock:view"],
      authorizedWarehouses: ["PR03DP"],
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (
          url.includes("/api/v1/inventory/ledger/") &&
          url.includes("item=100100") &&
          url.includes("date_from=2026-06-02T08%3A00") &&
          url.includes("date_to=2026-06-02T18%3A30")
        ) {
          return jsonResponse({ results: ledgerRows });
        }
        return jsonResponse({ results: [] });
      }),
    );
  });

  it("queries ledger with WMS filters and groups paired ledger impacts", async () => {
    render(<StockMovementsPage />);

    expect(screen.getByRole("heading", { name: "Movimientos de Stock" })).toBeInTheDocument();
    expect(screen.getByText("0 movimientos")).toBeInTheDocument();
    expect(screen.getByLabelText("ID articulo")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Expandir filtros" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Busqueda rapida")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("ID articulo"), { target: { value: "100100" } });
    fireEvent.change(screen.getByLabelText("Desde"), { target: { value: "2026-06-02T08:00" } });
    fireEvent.change(screen.getByLabelText("Hasta"), { target: { value: "2026-06-02T18:30" } });

    await waitFor(() => expect(screen.getByText("3 movimientos")).toBeInTheDocument());
    expect(screen.getByText("5 impactos de ledger")).toBeInTheDocument();

    const calls = vi.mocked(fetch).mock.calls.map(([input]) => String(input));
    const filteredCall = calls.find((url) => url.includes("item=100100") && url.includes("date_from=2026-06-02T08%3A00"));
    expect(filteredCall).toBeTruthy();
    expect(filteredCall).toContain("date_to=2026-06-02T18%3A30");
    expect(filteredCall).not.toContain("search=100100");
    expect(filteredCall).not.toContain("planned_date");
    expect(filteredCall).not.toContain("status=");

    const table = screen.getAllByRole("table")[0];
    expect(within(table).getByText("PR03DP-PRE-GEN / Preparado -> PR03DP-TRN-GEN / Entregada")).toBeInTheDocument();
    expect(within(table).getByText("PR03DP-DSP-GEN / Preparado -> PR03DP-RSV-GEN / Reservada")).toBeInTheDocument();
    expect(within(table).getByText("eespinoza")).toBeInTheDocument();
    expect(within(table).queryByText("eespinoza@familiabercomat.com")).not.toBeInTheDocument();
    expect(within(table).getByText("warehouse.bot")).toBeInTheDocument();
    expect(within(table).getByText("tester")).toBeInTheDocument();
    expect(within(table).getByText("Documento de entrega")).toBeInTheDocument();
    expect(within(table).getByText("Reserva de inventario")).toBeInTheDocument();
    expect(within(table).getByText("Ajuste manual de inventario")).toBeInTheDocument();
    expect(within(table).queryByText("delivery_document")).not.toBeInTheDocument();
    expect(within(table).queryByText("inventory_reservation")).not.toBeInTheDocument();
    expect(within(table).getAllByText("2 impactos")).toHaveLength(2);

    fireEvent.click(within(table).getByText("Documento de entrega"));
    const detail = screen.getByLabelText("Impactos ledger del movimiento");
    expect(within(detail).getByText("dispatch-in")).toBeInTheDocument();
    expect(within(detail).getByText("dispatch-out")).toBeInTheDocument();
    expect(within(detail).getByText("+10 UN")).toBeInTheDocument();
    expect(within(detail).getByText("-10 UN")).toBeInTheDocument();
    expect(within(detail).getAllByText("eespinoza").length).toBeGreaterThan(0);
  });
});
