import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InventoryExchangePage } from "./InventoryExchangePage";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 200 && status < 300 ? "OK" : "Error",
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  };
}

describe("InventoryExchangePage", () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      warehouseRef: "W001",
      branchRef: "S001",
      role: "Operador",
      permissions: ["stock:transform"],
      authorizedWarehouses: ["W001"],
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/v1/inventory/exchanges/") && init?.method === "POST") {
          const headers = init.headers as Record<string, string>;
          const body = JSON.parse(String(init.body));
          expect(headers["Idempotency-Key"]).toBeTruthy();
          expect(body).toMatchObject({
            warehouse_ref: "W001",
            reason: "Canje bolsa 25kg",
            input: {
              item_ref: "CEM-25KG",
              quantity: "1",
              uom: "UN",
              location_ref: "W001-DSP-GEN",
              lot_ref: "LOTE-1",
            },
            outputs: [
              {
                item_ref: "CEM-1KG",
                quantity: "25",
                uom: "UN",
                input_conversion_factor: "0.04",
                location_ref: "W001-DSP-GEN",
              },
            ],
          });
          return jsonResponse(
            {
              result: {
                id: "exchange-1",
                transformation_type: "exchange",
                status: "posted",
                warehouse_ref: "W001",
                reason: "Canje bolsa 25kg",
                conversion_group_id: "EXC-1",
                lines: [],
              },
            },
            201,
          );
        }
        if (url.includes("/api/v1/inventory/advanced-stock/")) {
          return jsonResponse({
            allowed_warehouses: ["W001"],
            results: [
              {
                id: "stock-1",
                warehouse_ref: "W001",
                location_ref: "W001-DSP-GEN",
                warehouse_location_ref: "W001-DSP-GEN",
                item_ref: "CEM-25KG",
                item_name: "Cemento 25kg",
                lot_ref: "LOTE-1",
                uom: "UN",
                quantities: { prepared: "1", available: "0", total: "1" },
              },
            ],
          });
        }
        if (url.includes("/api/v1/inventory/exchanges/")) {
          return jsonResponse({ results: [] });
        }
        return jsonResponse({ results: [] });
      }),
    );
  });

  it("posts a conserved lot-to-balance exchange with multiple stock references", async () => {
    render(<InventoryExchangePage />);

    expect(screen.getByRole("heading", { name: "Canje lote a saldo" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("CEM-25KG")).toBeInTheDocument());
    fireEvent.click(screen.getByText("CEM-25KG"));

    fireEvent.change(screen.getByLabelText("Cantidad"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Motivo"), { target: { value: "Canje bolsa 25kg" } });
    fireEvent.change(screen.getByLabelText("Articulo destino linea 1"), { target: { value: "CEM-1KG" } });
    fireEvent.change(screen.getByLabelText("Cantidad destino linea 1"), { target: { value: "25" } });
    fireEvent.change(screen.getByLabelText("Unidad destino linea 1"), { target: { value: "UN" } });
    fireEvent.change(screen.getByLabelText("Factor linea 1"), { target: { value: "0.04" } });
    fireEvent.change(screen.getByLabelText("Ubicacion destino linea 1"), { target: { value: "W001-DSP-GEN" } });

    expect(screen.getAllByText("conserva").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Confirmar canje" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/inventory/exchanges/"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(await screen.findByText("Canje EXC-1 posteado.")).toBeInTheDocument();
  });

  it("blocks non-conserved exchange before posting", async () => {
    render(<InventoryExchangePage />);

    await waitFor(() => expect(screen.getByText("CEM-25KG")).toBeInTheDocument());
    fireEvent.click(screen.getByText("CEM-25KG"));
    fireEvent.change(screen.getByLabelText("Cantidad"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Articulo destino linea 1"), { target: { value: "CEM-1KG" } });
    fireEvent.change(screen.getByLabelText("Cantidad destino linea 1"), { target: { value: "24" } });
    fireEvent.change(screen.getByLabelText("Factor linea 1"), { target: { value: "0.04" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar canje" }));

    expect(await screen.findByText("El canje no conserva cantidad segun los factores.")).toBeInTheDocument();
  });
});
