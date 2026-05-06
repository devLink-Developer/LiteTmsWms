import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { appRoutes } from "./router";
import { useSessionStore } from "../stores/useSessionStore";
import type { SessionBootstrap } from "../types/session";

const authenticatedSession: SessionBootstrap = {
  authenticated: true,
  csrfToken: "csrf",
  appName: "Lite Logistic",
  user: {
    username: "operator@example.com",
    email: "operator@example.com",
    displayName: "Operador",
    alias: "operator",
  },
  workspace: {
    warehouse_ref: "PS003MT",
    branch_ref: "Sucursal Norte",
    role: "operador",
    permissions: [],
    authorized_warehouses: ["PS003MT"],
  },
};

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    json: async () => payload,
  };
}

function renderRoute(path: string) {
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("app router", () => {
  beforeEach(() => {
    useSessionStore.setState({ bootstrap: authenticatedSession, status: "ready", error: null });
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

  it("redirects unauthenticated users to login", async () => {
    useSessionStore.setState({
      bootstrap: { authenticated: false, csrfToken: "csrf", appName: "Lite Logistic", user: null, workspace: null },
      status: "ready",
      error: null,
    });
    const router = renderRoute("/pedidos/entrega");

    await waitFor(() => expect(router.state.location.pathname).toBe("/login/"));
    expect(await screen.findByRole("heading", { name: "Ingresar" })).toBeInTheDocument();
  });

  it.each([
    ["/entregas", "/pedidos/entrega", "Expedicion de entregas"],
    ["/entregas/expedicion", "/pedidos/entrega", "Expedicion de entregas"],
    ["/tareas", "/pedidos/tareas", "Tareas de preparacion"],
    ["/pedidos/reparto", "/reparto/confirmacion", "Confirmacion de reparto"],
    ["/ruteo", "/reparto/ruteo", "Planificacion de reparto"],
    ["/hojas-ruta", "/reparto/hojas-ruta", "Hojas de ruta"],
    ["/vehiculos", "/maestros/vehiculos", "ABM de flota"],
    ["/choferes", "/maestros/choferes", "ABM de flota"],
    ["/almacenes", "/maestros/almacenes", "Maestro de almacenes"],
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
    ["/reparto/confirmacion", "Confirmacion de reparto"],
    ["/reparto/preparacion", "Preparacion de reparto"],
    ["/reparto/chofer", "Ejecucion chofer"],
    ["/reparto/hojas-ruta", "Hojas de ruta"],
    ["/maestros/vehiculos", "ABM de flota"],
    ["/maestros/choferes", "ABM de flota"],
    ["/maestros/almacenes", "Maestro de almacenes"],
    ["/ingresos/tr-depositos", "Transferencias entre sucursales"],
    ["/ingresos/devoluciones", "Ingresos por devoluciones"],
    ["/stock/movimientos", "Movimientos de Stock"],
    ["/operaciones/roturas-perdidas", "Roturas y perdidas"],
  ])("renders the operational route %s", async (path, heading) => {
    const router = renderRoute(path);

    await waitFor(() => expect(router.state.location.pathname).toBe(path));
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
  });

  it("renders placeholder routes without API calls beyond shell context", async () => {
    const router = renderRoute("/operaciones/corte-chapas");

    await waitFor(() => expect(router.state.location.pathname).toBe("/operaciones/corte-chapas"));
    expect(await screen.findByRole("heading", { name: "Corte de chapas" })).toBeInTheDocument();
    expect(screen.queryByText("read-only")).not.toBeInTheDocument();
    expect(screen.queryByText("sin API")).not.toBeInTheDocument();
  });
});
