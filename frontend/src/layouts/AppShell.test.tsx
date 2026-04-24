import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useWorkspaceStore } from "../stores/useWorkspaceStore";
import { AppShell } from "./AppShell";

function contextResponse() {
  return {
    ok: true,
    json: async () => ({
      warehouse_ref: "PS003MT",
      branch_ref: "Sucursal Norte",
      role: "operador",
      permissions: [],
      authorized_warehouses: ["PS003MT", "PS03DP"],
    }),
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
    vi.stubGlobal("fetch", vi.fn(async () => contextResponse()));
  });

  it("renders the grouped operations menu without Despacho tienda", async () => {
    render(
      <MemoryRouter initialEntries={["/pedidos/reparto"]}>
        <AppShell />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("Contexto operativo PS003MT")).toBeInTheDocument());

    const desktopNav = screen.getAllByRole("navigation", { name: "Modulos" })[0];
    expect(within(desktopNav).getByText("Pedidos")).toBeInTheDocument();
    expect(within(desktopNav).getByRole("link", { name: "Listar pedidos" })).toHaveAttribute("href", "/pedidos");
    expect(within(desktopNav).getByRole("link", { name: "Entrega" })).toHaveAttribute("href", "/pedidos/entrega");
    expect(within(desktopNav).getByRole("link", { name: "Tareas de preparacion" })).toHaveAttribute(
      "href",
      "/pedidos/tareas",
    );
    expect(within(desktopNav).getByRole("link", { name: "Reparto" })).toHaveAttribute("href", "/pedidos/reparto");
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
    expect(within(desktopNav).getByText("Operaciones")).toBeInTheDocument();
    expect(screen.queryByText("Despacho tienda")).not.toBeInTheDocument();
  });
});
