import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BreakagesLossesPage } from "./BreakagesLossesPage";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 200 && status < 300 ? "OK" : "Error",
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => payload,
  };
}

describe("BreakagesLossesPage", () => {
  let stockRows: unknown[];
  let expectedSourceLocation: string;

  beforeEach(() => {
    stockRows = [
      {
        warehouse_ref: "W001",
        warehouse_location_ref: "W001-DSP-GEN",
        location_ref: "W001-DSP-GEN",
        lot_ref: "",
        item_ref: "ITEM-1",
        item_name: "Porcelanato gris",
        uom: "UN",
        quantities: { available: "0", prepared: "5", damaged_waste: "0", total: "5" },
      },
    ];
    expectedSourceLocation = "W001-DSP-GEN";
    useWorkspaceStore.setState({
      warehouseRef: "W001",
      branchRef: "S001",
      role: "Operador",
      permissions: ["stock:view"],
      authorizedWarehouses: ["W001"],
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/v1/inventory/advanced-stock/")) {
          return jsonResponse({
            allowed_warehouses: ["W001"],
            results: stockRows,
          });
        }
        if (url.includes("/api/v1/inventory/write-offs/") && init?.method === "POST") {
          const body = JSON.parse(String(init.body));
          expect(body.source_stock_state).toBe("packed");
          expect(body.reason_code).toBe("breakage");
          expect(body.source_location_ref).toBe(expectedSourceLocation);
          expect(body.lines[0]).toMatchObject({ item_ref: "ITEM-1", quantity: "2", uom: "UN" });
          return jsonResponse({
            result: {
              id: "wo-1",
              write_off_number: "WO-1",
              status: "posted",
              warehouse_ref: "W001",
              source_location_ref: "W001-DSP-GEN",
              target_location_ref: "W001-BAJ-ROT",
              reason_code: "breakage",
              reason: "Rotura test",
              lines: [{ id: "line-1", item_ref: "ITEM-1", quantity: "2", posted_qty: "2", uom: "UN" }],
            },
          }, 201);
        }
        if (url.includes("/api/v1/inventory/write-offs/")) {
          return jsonResponse({ results: [], allowed_warehouses: ["W001"] });
        }
        return jsonResponse({ results: [] });
      }),
    );
  });

  it("does not send legacy lot fallback as source location", async () => {
    stockRows = [
      {
        warehouse_ref: "W001",
        warehouse_location_ref: "LOT-LEGACY",
        location_ref: "",
        lot_ref: "LOT-LEGACY",
        item_ref: "ITEM-1",
        item_name: "Porcelanato gris",
        uom: "UN",
        quantities: { available: "0", prepared: "3", damaged_waste: "0", total: "3" },
      },
    ];
    expectedSourceLocation = "";
    render(<BreakagesLossesPage />);

    await waitFor(() => expect(screen.getAllByText("LOT-LEGACY").length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText("Cantidad"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Motivo"), { target: { value: "Rotura test" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar baja" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/inventory/write-offs/"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("validates quantity and posts a breakage write-off", async () => {
    render(<BreakagesLossesPage />);

    expect(screen.getByRole("heading", { name: "Roturas y perdidas" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("1 buckets disponibles")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Cantidad"), { target: { value: "8" } });
    fireEvent.change(screen.getByLabelText("Motivo"), { target: { value: "Rotura test" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar baja" }));
    expect(await screen.findByText("Stock insuficiente.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Cantidad"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar baja" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/inventory/write-offs/"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
