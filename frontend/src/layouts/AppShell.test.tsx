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
      <MemoryRouter initialEntries={["/reparto/confirmacion"]}>
        <AppShell />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("Contexto operativo PS003MT")).toBeInTheDocument());

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
    expect(within(desktopNav).getByText("Operaciones")).toBeInTheDocument();
    expect(within(desktopNav).getByRole("link", { name: "Corte de chapas" })).toBeInTheDocument();
    expect(within(desktopNav).getByText("Maestros")).toBeInTheDocument();
    expect(within(desktopNav).getByRole("link", { name: "Vehiculo" })).toHaveAttribute(
      "href",
      "/maestros/vehiculos",
    );
    expect(within(desktopNav).getByRole("link", { name: "Choferes" })).toHaveAttribute("href", "/maestros/choferes");
    expect(screen.queryByText("Despacho tienda")).not.toBeInTheDocument();
  });
});
