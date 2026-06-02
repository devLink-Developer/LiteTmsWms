import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PurchaseReceiptsPage } from "./PurchaseReceiptsPage";
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

describe("PurchaseReceiptsPage", () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      warehouseRef: "W001",
      branchRef: "S001",
      role: "Operador",
      permissions: ["receipts:create"],
      authorizedWarehouses: ["W001"],
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/v1/inventory/receipts/") && init?.method === "POST") {
          const headers = init.headers as Record<string, string>;
          const body = JSON.parse(String(init.body));
          expect(headers["Idempotency-Key"]).toBeTruthy();
          expect(body).toMatchObject({
            warehouse_ref: "W001",
            purchase_order_ref: "OC-100",
            supplier_ref: "SUP-1",
            target_location_ref: "W001-DSP-GEN",
            lines: [
              {
                item_ref: "ITEM-1",
                expected_qty: "5",
                received_qty: "5",
                uom: "UN",
                location_ref: "W001-DSP-GEN",
                lot_ref: "L1",
              },
            ],
          });
          return jsonResponse(
            {
              result: {
                id: "receipt-1",
                purchase_order_ref: "OC-100",
                supplier_ref: "SUP-1",
                status: "received",
                warehouse_ref: "W001",
                lines_count: 1,
                lines: [{ id: "line-1", item_ref: "ITEM-1", received_qty: "5", expected_qty: "5", uom: "UN", location_ref: "W001-DSP-GEN", lot_ref: "L1" }],
              },
            },
            201,
          );
        }
        if (url.includes("/api/v1/inventory/receipts/")) {
          return jsonResponse({ results: [] });
        }
        return jsonResponse({ results: [] });
      }),
    );
  });

  it("posts a purchase order receipt into packed stock with target location and idempotency key", async () => {
    render(<PurchaseReceiptsPage />);

    expect(screen.getByRole("heading", { name: "Ingresos por OC" })).toBeInTheDocument();
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/inventory/receipts/"), expect.any(Object)));

    fireEvent.change(screen.getByLabelText("OC"), { target: { value: "OC-100" } });
    fireEvent.change(screen.getByLabelText("Proveedor"), { target: { value: "SUP-1" } });
    fireEvent.change(screen.getByLabelText("Ubicacion destino"), { target: { value: "W001-DSP-GEN" } });
    fireEvent.change(screen.getByLabelText("Articulo linea 1"), { target: { value: "ITEM-1" } });
    fireEvent.change(screen.getByLabelText("Cantidad esperada linea 1"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Cantidad recibida linea 1"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Unidad linea 1"), { target: { value: "UN" } });
    fireEvent.change(screen.getByLabelText("Lote linea 1"), { target: { value: "L1" } });
    fireEvent.change(screen.getByLabelText("Motivo"), { target: { value: "Recepcion test" } });

    fireEvent.click(screen.getByRole("button", { name: "Confirmar recepcion" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/inventory/receipts/"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(await screen.findByText("OC OC-100 recibida.")).toBeInTheDocument();
  });

  it("validates missing line quantity before posting", async () => {
    render(<PurchaseReceiptsPage />);

    fireEvent.change(screen.getByLabelText("OC"), { target: { value: "OC-101" } });
    fireEvent.change(screen.getByLabelText("Articulo linea 1"), { target: { value: "ITEM-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar recepcion" }));

    expect(await screen.findByText("Cada renglon requiere articulo y cantidad recibida positiva.")).toBeInTheDocument();
  });
});
