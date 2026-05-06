import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StockBalancesPage } from "./StockBalancesPage";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => payload,
  };
}

describe("StockBalancesPage", () => {
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
        if (url.includes("/api/v1/logistics/master-data/warehouses/")) {
          return jsonResponse({
            results: [
              { warehouse_code: "WH-A", warehouse_name: "Deposito A", is_shipping_allowed: true },
              { warehouse_code: "WH-C", warehouse_name: "Deposito C", is_shipping_allowed: true },
            ],
          });
        }
        if (url.includes("/api/v1/inventory/advanced-stock/")) {
          return jsonResponse({
            allowed_warehouses: ["WH-A", "WH-C"],
            results: [
              {
                warehouse_ref: "WH-A",
                location_ref: "A-01-01",
                warehouse_location_ref: "A-01-01",
                location_name: "Rack A",
                purpose: "available",
                zone_ref: "Z01",
                aisle: "A01",
                floor: "F01",
                level: "N01",
                position: "P001",
                is_dispatchable: true,
                lot_ref: "A-01-01",
                item_ref: "103374",
                item_name: "Porcelanato gris",
                category_ref: "CER",
                category: "CER",
                uom: "m2",
                quantities: {
                  available: "12.5",
                  reserved: "2",
                  in_preparation: "1",
                  prepared: "0",
                  in_transit: "0",
                  damaged_waste: "0",
                  total: "15.5",
                },
              },
              {
                warehouse_ref: "WH-C",
                location_ref: "C-03-02",
                warehouse_location_ref: "C-03-02",
                location_name: "Rack C",
                purpose: "available",
                zone_ref: "Z03",
                aisle: "A02",
                floor: "F01",
                level: "N02",
                position: "P003",
                is_dispatchable: true,
                lot_ref: "L-1",
                item_ref: "200000",
                item_name: "Bacha blanca",
                category_ref: "SAN",
                category: "SAN",
                uom: "un",
                quantities: {
                  available: "0",
                  reserved: "0",
                  in_preparation: "0",
                  prepared: "5",
                  in_transit: "0",
                  damaged_waste: "1",
                  total: "6",
                },
              },
            ],
          });
        }
        return jsonResponse({
          allowed_warehouses: ["WH-A", "WH-C"],
          results: [
            {
              id: "bal-1",
              warehouse_ref: "WH-A",
              warehouse_location_ref: "A-01-01",
              item_ref: "103374",
              item_name: "Porcelanato gris",
              supplier_ref: "SUP-1",
              category_ref: "CER",
              lot_ref: "",
              pallet_ref: "PAL-7",
              quality_status: "OK",
              stock_state: "on_hand",
              quantity: "12.5",
              uom: "m2",
              version: 3,
            },
            {
              id: "bal-2",
              warehouse_ref: "WH-C",
              warehouse_location_ref: "C-02-01",
              item_ref: "103374",
              item_name: "Porcelanato gris",
              supplier_ref: "SUP-1",
              category_ref: "CER",
              lot_ref: "",
              pallet_ref: "PAL-8",
              quality_status: "OK",
              stock_state: "reserved",
              quantity: "2",
              uom: "m2",
              version: 1,
            },
            {
              id: "bal-3",
              warehouse_ref: "WH-C",
              warehouse_location_ref: "C-03-02",
              item_ref: "200000",
              item_name: "Bacha blanca",
              supplier_ref: "SUP-2",
              category_ref: "SAN",
              lot_ref: "L-1",
              pallet_ref: "PAL-9",
              quality_status: "OBS",
              stock_state: "packed",
              quantity: "5",
              uom: "un",
              version: 2,
            },
          ],
        });
      }),
    );
  });

  it("renders scoped stock balances with filters and detail", async () => {
    render(<StockBalancesPage />);

    expect(screen.getByRole("heading", { name: "Stock por almacen" })).toBeInTheDocument();
    expect(screen.getByText("0 buckets")).toBeInTheDocument();
    expect(screen.getByText("Sin filtros.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Actualizar" })).toBeDisabled();

    await waitFor(() => expect(screen.getByRole("option", { name: "WH-A / Deposito A" })).toBeInTheDocument());
    const fetchCalls = vi.mocked(fetch).mock.calls.map(([input]) => String(input));
    expect(fetchCalls.some((url) => url.includes("/api/v1/inventory/advanced-stock/"))).toBe(false);

    fireEvent.change(screen.getByLabelText("Almacen"), { target: { value: "WH-A" } });
    await waitFor(() => expect(screen.getByText("1 buckets")).toBeInTheDocument());

    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/inventory/advanced-stock/"), expect.any(Object));
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("location_scope=available"), expect.any(Object));
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("state=packed%2Con_hand"), expect.any(Object));
    expect(screen.getByText("scope operativo")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "WH-C / Deposito C" })).toBeInTheDocument();
    expect(screen.getAllByText("A-01-01").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Rack A").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Z01").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Porcelanato gris").length).toBeGreaterThan(0);
    expect(screen.queryByText("Bacha blanca")).not.toBeInTheDocument();
    expect(screen.getAllByText("12,5 m2").length).toBeGreaterThan(0);
    expect(screen.getByText("Detalle compacto")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Limpiar" }));
    await waitFor(() => expect(screen.getByText("0 buckets")).toBeInTheDocument());
    expect(screen.getByText("Sin filtros.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Busqueda rapida"), { target: { value: "200000" } });
    await waitFor(() => expect(screen.getByText("1 buckets")).toBeInTheDocument());
    const table = screen.getAllByRole("table")[0];
    expect(within(table).getByText("200000")).toBeInTheDocument();
    expect(within(table).queryByText("103374")).not.toBeInTheDocument();
  });
});
