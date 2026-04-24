import { render, screen, waitFor } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { appRoutes } from "./router";

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    json: async () => payload,
  };
}

function renderRoute(path: string) {
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

describe("app router", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/v1/logistics/context/")) {
          return jsonResponse({
            warehouse_ref: "PS003MT",
            branch_ref: "Sucursal Norte",
            role: "operador",
            permissions: [],
            authorized_warehouses: ["PS003MT"],
          });
        }
        if (url.includes("/api/v1/logistics/overview/")) {
          return jsonResponse({ principles: [] });
        }
        return jsonResponse({ results: [] });
      }),
    );
  });

  it.each([
    ["/entregas", "/pedidos/entrega", "Expedicion de entregas"],
    ["/entregas/expedicion", "/pedidos/entrega", "Expedicion de entregas"],
    ["/tareas", "/pedidos/tareas", "Tareas de preparacion"],
    ["/recepciones", "/ingresos/oc", "Ingresos por OC"],
    ["/stock", "/stock/almacenes", "Stock por almacen"],
    ["/despacho-tienda", "/pedidos/entrega", "Expedicion de entregas"],
  ])("redirects %s to %s", async (fromPath, toPath, heading) => {
    const router = renderRoute(fromPath);

    await waitFor(() => expect(router.state.location.pathname).toBe(toPath));
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
  });

  it.each([
    ["/pedidos", "Listar pedidos"],
    ["/pedidos/tareas", "Tareas de preparacion"],
    ["/pedidos/reparto", "Reparto"],
    ["/ingresos/tr-depositos", "Ingresos por TR entre depositos"],
    ["/ingresos/devoluciones", "Ingresos por devoluciones"],
    ["/hojas-ruta", "Hojas de ruta"],
    ["/stock/movimientos", "Movimientos de Stock"],
  ])("renders the operational route %s", async (path, heading) => {
    const router = renderRoute(path);

    await waitFor(() => expect(router.state.location.pathname).toBe(path));
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
  });

  it("renders placeholder routes without API calls beyond shell context", async () => {
    const router = renderRoute("/operaciones/corte-chapas");

    await waitFor(() => expect(router.state.location.pathname).toBe("/operaciones/corte-chapas"));
    expect(await screen.findByRole("heading", { name: "Corte de chapas" })).toBeInTheDocument();
    expect(screen.getByText("read-only")).toBeInTheDocument();
    expect(screen.getByText("sin API")).toBeInTheDocument();
  });
});
