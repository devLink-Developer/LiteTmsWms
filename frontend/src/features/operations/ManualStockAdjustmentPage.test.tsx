import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ManualStockAdjustmentPage } from "./ManualStockAdjustmentPage";
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

describe("ManualStockAdjustmentPage", () => {
  let postedBodies: Record<string, unknown>[];

  beforeEach(() => {
    postedBodies = [];
    useWorkspaceStore.setState({
      warehouseRef: "W001",
      branchRef: "S001",
      role: "Operador",
      permissions: ["stock:view", "stock:adjust"],
      authorizedWarehouses: ["W001"],
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/v1/logistics/warehouses/W001/locations/")) {
          return jsonResponse({
            results: [
              {
                id: "loc-1",
                warehouse_ref: "W001",
                location_ref: "W001-DSP-GEN",
                name: "Disponible general",
                location_type: "dock",
                purpose: "available",
                is_dispatchable: true,
                is_reservable: true,
                is_pickable: true,
                allows_scrap: false,
                system_location: true,
                generated: true,
                active: true,
              },
              {
                id: "loc-2",
                warehouse_ref: "W001",
                location_ref: "W001-PRE-GEN",
                name: "En preparacion",
                location_type: "system",
                purpose: "preparation",
                is_dispatchable: false,
                is_reservable: false,
                is_pickable: true,
                allows_scrap: false,
                system_location: true,
                generated: true,
                active: true,
              },
              {
                id: "loc-3",
                warehouse_ref: "W001",
                location_ref: "W001-BAJ-ROT",
                name: "Baja rotura",
                location_type: "system",
                purpose: "breakage",
                is_dispatchable: false,
                is_reservable: false,
                is_pickable: false,
                allows_scrap: true,
                system_location: true,
                generated: true,
                active: true,
              },
            ],
          });
        }
        if (url.includes("/api/v1/inventory/advanced-stock/")) {
          const params = new URL(url, "http://localhost").searchParams;
          const search = params.get("search") ?? "";
          if (search === "ITEM-2") {
            return jsonResponse({
              allowed_warehouses: ["W001"],
              results: [
                {
                  warehouse_ref: "W001",
                  warehouse_location_ref: "W001-DSP-B",
                  location_ref: "W001-DSP-B",
                  lot_ref: "",
                  item_ref: "ITEM-2",
                  item_name: "Articulo buscado",
                  uom: "UN",
                  quantities: { prepared: "4", available: "0", total: "4" },
                },
              ],
            });
          }
          return jsonResponse({
            allowed_warehouses: ["W001"],
            results: [
              {
                warehouse_ref: "W001",
                warehouse_location_ref: "W001-DSP-GEN",
                location_ref: "W001-DSP-GEN",
                lot_ref: "",
                item_ref: "ITEM-1",
                item_name: "Articulo prueba",
                uom: "UN",
                quantities: { prepared: "5", available: "0", total: "5" },
              },
            ],
          });
        }
        if (url.includes("/api/v1/inventory/materials/")) {
          const params = new URL(url, "http://localhost").searchParams;
          const query = params.get("q") ?? "";
          if (query === "100100") {
            return jsonResponse({
              results: [
                {
                  item_ref: "100100",
                  name: "Barra de Acero Tors AN-420 06 mm",
                  long_name: "Barra de Acero Tors AN-420 06 mm",
                  category: "Hierros",
                  uom: "un",
                  uom_code: "ST",
                },
              ],
            });
          }
          return jsonResponse({ results: [] });
        }
        if (url.includes("/api/v1/inventory/manual-adjustments/") && init?.method === "POST") {
          const body = JSON.parse(String(init.body));
          postedBodies.push(body);
          return jsonResponse(
            {
              result: {
                document_ref: "AJU-1",
                warehouse_ref: "W001",
                location_ref: body.location_ref,
                lot_ref: body.lot_ref,
                item_ref: body.item_ref,
                direction: body.direction,
                quantity: body.quantity,
                uom: body.uom,
                stock_state: "packed",
                reason: body.reason,
                ledger_entries: [],
              },
            },
            201,
          );
        }
        if (url.includes("/api/v1/inventory/manual-adjustments/")) {
          return jsonResponse({ results: [], allowed_warehouses: ["W001"] });
        }
        return jsonResponse({ results: [] });
      }),
    );
  });

  it("reloads origin rows from the API when the decrease search changes", async () => {
    render(<ManualStockAdjustmentPage />);

    await waitFor(() => expect(screen.getByText(/1 posiciones destino/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Baja" }));
    await waitFor(() => expect(screen.getByText("ITEM-1")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Buscar"), { target: { value: "ITEM-2" } });

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("search=ITEM-2"),
        expect.objectContaining({ credentials: "include" }),
      ),
    );
    expect(await screen.findByText("ITEM-2")).toBeInTheDocument();
    expect(screen.getByText("Articulo buscado")).toBeInTheDocument();
  });

  it("searches material master rows for increase adjustments", async () => {
    render(<ManualStockAdjustmentPage />);

    await waitFor(() => expect(screen.getByText(/1 posiciones destino/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Buscar articulo"), { target: { value: "100100" } });

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/inventory/materials/?q=100100"),
        expect.objectContaining({ credentials: "include" }),
      ),
    );
    expect(await screen.findByText("100100")).toBeInTheDocument();
    expect(screen.getByText("Barra de Acero Tors AN-420 06 mm")).toBeInTheDocument();

    fireEvent.click(screen.getByText("100100"));
    expect(screen.getByLabelText("Articulo")).toHaveValue("100100");
    expect(screen.getByLabelText("UOM")).toHaveValue("ST");
  });

  it("posts an increase using the selected destination location", async () => {
    render(<ManualStockAdjustmentPage />);

    expect(screen.getByRole("heading", { name: "Alta y baja de articulos" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/1 posiciones destino/)).toBeInTheDocument());
    expect(screen.queryByText("W001-PRE-GEN")).not.toBeInTheDocument();
    expect(screen.queryByText("W001-BAJ-ROT")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByText("W001-DSP-GEN")[0]);
    fireEvent.change(screen.getByLabelText("Articulo"), { target: { value: "ITEM-NEW" } });
    fireEvent.change(screen.getByLabelText("Cantidad"), { target: { value: "9" } });
    fireEvent.change(screen.getByLabelText("Motivo"), { target: { value: "Alta manual inicial" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar alta" }));

    await waitFor(() => expect(postedBodies).toHaveLength(1));
    expect(postedBodies[0]).toMatchObject({
      warehouse_ref: "W001",
      direction: "increase",
      item_ref: "ITEM-NEW",
      location_ref: "W001-DSP-GEN",
      quantity: "9",
      uom: "UN",
      reason: "Alta manual inicial",
    });
  });

  it("uses the increase default reason after switching back from decrease", async () => {
    render(<ManualStockAdjustmentPage />);

    await waitFor(() => expect(screen.getByText(/1 posiciones destino/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Baja" }));
    await waitFor(() => expect(screen.getByLabelText("Motivo")).toHaveValue("Baja manual"));

    fireEvent.click(screen.getByRole("button", { name: "Alta" }));
    await waitFor(() => expect(screen.getByLabelText("Motivo")).toHaveValue("Alta manual"));

    fireEvent.change(screen.getByLabelText("Articulo"), { target: { value: "ITEM-NEW" } });
    fireEvent.change(screen.getByLabelText("Cantidad"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar alta" }));

    await waitFor(() => expect(postedBodies).toHaveLength(1));
    expect(postedBodies[0]).toMatchObject({
      direction: "increase",
      item_ref: "ITEM-NEW",
      location_ref: "W001-DSP-GEN",
      quantity: "2",
      reason: "Alta manual",
    });
  });

  it("posts a decrease from an origin row and blocks quantities above available stock", async () => {
    render(<ManualStockAdjustmentPage />);

    await waitFor(() => expect(screen.getByText(/1 posiciones destino/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Baja" }));
    await waitFor(() => expect(screen.getByText("1 posiciones origen")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Cantidad"), { target: { value: "8" } });
    fireEvent.change(screen.getByLabelText("Motivo"), { target: { value: "Baja manual ajuste" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar baja" }));
    expect(await screen.findByText("Stock insuficiente en la posicion origen.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Cantidad"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar baja" }));

    await waitFor(() => expect(postedBodies).toHaveLength(1));
    expect(postedBodies[0]).toMatchObject({
      warehouse_ref: "W001",
      direction: "decrease",
      item_ref: "ITEM-1",
      location_ref: "W001-DSP-GEN",
      quantity: "3",
      uom: "UN",
      reason: "Baja manual ajuste",
    });
  });
});
