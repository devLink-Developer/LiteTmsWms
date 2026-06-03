import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSessionStore } from "../stores/useSessionStore";
import { useWorkspaceStore } from "../stores/useWorkspaceStore";
import { AppShell } from "./AppShell";

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 200 && status < 300 ? "OK" : "Error",
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => payload,
  };
}

function contextPayload() {
  return {
    warehouse_ref: "PS003MT",
    branch_ref: "Sucursal Norte",
    role: "operador",
    permissions: [],
    authorized_warehouses: ["PS003MT"],
  };
}

describe("AppShell", () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      warehouseRef: "",
      branchRef: "Cargando contexto",
      role: "Cargando",
      permissions: [],
      authorizedWarehouses: [],
    });
    useSessionStore.setState({ bootstrap: null, status: "ready", error: null });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/auth/api/logout/")) {
          return jsonResponse({ success: true, redirectTo: "/login/" });
        }
        return jsonResponse(contextPayload());
      }),
    );
  });

  function renderShell() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/reparto/confirmacion"]}>
          <AppShell />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("starts with the desktop sidebar collapsed and opens on hover", async () => {
    renderShell();

    await waitFor(() => expect(screen.getByText("Contexto operativo PS003MT")).toBeInTheDocument());
    const sidebar = screen.getByLabelText("Menu principal");
    expect(sidebar).toHaveClass("w-3");

    fireEvent.mouseEnter(sidebar);

    expect(sidebar).toHaveClass("w-60");
  });

  it("renders the grouped operations menu without Despacho tienda", async () => {
    renderShell();

    await waitFor(() => expect(screen.getByText("Contexto operativo PS003MT")).toBeInTheDocument());
    expect(screen.getByText("PS003MT")).toBeInTheDocument();

    const desktopNav = screen.getAllByRole("navigation", { name: "Modulos" })[0];
    expect(within(desktopNav).getByText("Pedidos")).toBeInTheDocument();
    expect(within(desktopNav).getByRole("link", { name: "Listar pedidos" })).toHaveAttribute("href", "/pedidos");
    expect(within(desktopNav).getByRole("link", { name: "Entrega" })).toHaveAttribute("href", "/pedidos/entrega");
    expect(within(desktopNav).getByRole("link", { name: "Tareas de preparacion" })).toHaveAttribute("href", "/pedidos/tareas");
    expect(within(desktopNav).getByText("Reparto")).toBeInTheDocument();
    expect(within(desktopNav).getByRole("link", { name: "Confirmacion de reparto" })).toHaveAttribute(
      "href",
      "/reparto/confirmacion",
    );
    expect(within(desktopNav).getByRole("link", { name: "Preparacion de reparto" })).toHaveAttribute(
      "href",
      "/reparto/preparacion",
    );
    expect(within(desktopNav).getByRole("link", { name: "Ruteo" })).toHaveAttribute("href", "/reparto/ruteo");
    expect(within(desktopNav).getByRole("link", { name: "Ejecucion chofer" })).toHaveAttribute(
      "href",
      "/reparto/chofer",
    );
    expect(within(desktopNav).getByRole("link", { name: "Hojas de ruta" })).toHaveAttribute(
      "href",
      "/reparto/hojas-ruta",
    );
    expect(within(desktopNav).getByText("Ingresos")).toBeInTheDocument();
    expect(within(desktopNav).getByRole("link", { name: "Ingresos por OC" })).toHaveAttribute("href", "/ingresos/oc");
    expect(within(desktopNav).getByRole("link", { name: "Ingresos por TR entre depositos" })).toHaveAttribute(
      "href",
      "/ingresos/tr-depositos",
    );
    expect(within(desktopNav).getByRole("link", { name: "Ingresos por devoluciones" })).toHaveAttribute(
      "href",
      "/ingresos/devoluciones",
    );
    expect(within(desktopNav).getByText("Stock")).toBeInTheDocument();
    expect(within(desktopNav).getByRole("link", { name: "Stock por almacen" })).toHaveAttribute(
      "href",
      "/stock/almacenes",
    );
    expect(within(desktopNav).getByRole("link", { name: "Movimientos de Stock" })).toHaveAttribute(
      "href",
      "/stock/movimientos",
    );
    expect(within(desktopNav).getByText("Operaciones")).toBeInTheDocument();
    expect(within(desktopNav).getByRole("link", { name: "Corte de chapas" })).toBeInTheDocument();
    expect(within(desktopNav).getByText("Maestros")).toBeInTheDocument();
    expect(within(desktopNav).getByRole("link", { name: "Almacenes" })).toHaveAttribute(
      "href",
      "/maestros/almacenes",
    );
    expect(within(desktopNav).getByRole("link", { name: "Vehiculo" })).toHaveAttribute(
      "href",
      "/maestros/vehiculos",
    );
    expect(within(desktopNav).getByRole("link", { name: "Choferes" })).toHaveAttribute("href", "/maestros/choferes");
    expect(screen.queryByText("Despacho tienda")).not.toBeInTheDocument();
  });

  it("renders a logout button in the top bar", async () => {
    renderShell();

    await waitFor(() => expect(screen.getByText("Contexto operativo PS003MT")).toBeInTheDocument());
    const logoutButtons = screen.getAllByRole("button", { name: "Cerrar sesion" });
    expect(logoutButtons.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Cerrar sesion")).toBeInTheDocument();
    fireEvent.click(logoutButtons[0]);

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/auth/api/logout/"), expect.objectContaining({ method: "POST" })),
    );
  });
});
