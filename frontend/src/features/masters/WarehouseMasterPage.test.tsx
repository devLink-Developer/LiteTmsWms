import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WarehouseMasterPage } from "./WarehouseMasterPage";
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

describe("WarehouseMasterPage", () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      warehouseRef: "W001",
      branchRef: "S001",
      role: "Operador",
      permissions: ["warehouses:manage"],
      authorizedWarehouses: ["W001"],
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/v1/logistics/warehouses/") && init?.method === "POST") {
          const body = JSON.parse(String(init.body));
          expect(body).toMatchObject({ warehouse_ref: "W002", name: "Deposito Nuevo" });
          return jsonResponse({
            result: {
              id: "wh-2",
              warehouse_ref: "W002",
              warehouse_code: "W002",
              name: "Deposito Nuevo",
              warehouse_name: "Deposito Nuevo",
              warehouse_type: "shipping",
              active: true,
            },
          }, 201);
        }
        if (url.includes("/locations/")) {
          return jsonResponse({
            results: [
              { id: "loc-1", warehouse_ref: "W001", location_ref: "W001-DSP-GEN", purpose: "available", location_type: "system", is_dispatchable: true, is_reservable: false, is_pickable: true, allows_scrap: false, system_location: true, generated: true, active: true },
              { id: "loc-2", warehouse_ref: "W001", location_ref: "W001-BAJ-ROT", purpose: "breakage", location_type: "system", is_dispatchable: false, is_reservable: false, is_pickable: false, allows_scrap: true, system_location: true, generated: true, active: true },
            ],
          });
        }
        if (url.includes("/api/v1/logistics/warehouses/")) {
          return jsonResponse({
            results: [
              {
                id: "wh-1",
                warehouse_ref: "W001",
                warehouse_code: "W001",
                name: "Deposito Central",
                warehouse_name: "Deposito Central",
                warehouse_type: "shipping",
                active: true,
              },
            ],
          });
        }
        return jsonResponse({ results: [] });
      }),
    );
  });

  it("renders local warehouses and posts a new warehouse payload", async () => {
    render(<WarehouseMasterPage />);

    expect(screen.getByRole("heading", { name: "Maestro de almacenes" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("1 almacenes")).toBeInTheDocument());
    expect(screen.getByText("W001-DSP-GEN")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Nuevo" }));
    fireEvent.change(screen.getByLabelText("Codigo"), { target: { value: "W002" } });
    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Deposito Nuevo" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/logistics/warehouses/"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
