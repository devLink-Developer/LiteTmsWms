import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { appRoutes } from "../../app/router";
import { ToastViewport } from "../../shared/components/toast";
import { useSessionStore } from "../../stores/useSessionStore";
import type { SessionBootstrap } from "../../types/session";

const unauthenticatedSession: SessionBootstrap = {
  authenticated: false,
  csrfToken: "csrf",
  appName: "Lite Logistic",
  user: null,
  workspace: null,
};

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
    role: "Operador",
    permissions: ["deliveries:view"],
    authorized_warehouses: ["PS003MT"],
  },
};

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 200 && status < 300 ? "OK" : "Error",
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => payload,
  };
}

function renderLogin() {
  const router = createMemoryRouter(appRoutes, { initialEntries: ["/login/"] });
  render(
    <>
      <RouterProvider router={router} />
      <ToastViewport />
    </>,
  );
  return router;
}

describe("LoginPage", () => {
  beforeEach(() => {
    useSessionStore.setState({ bootstrap: unauthenticatedSession, status: "ready", error: null });
    window.localStorage.clear();
  });

  it("renders the Lite Logistic login shell", () => {
    renderLogin();

    expect(screen.getByLabelText("Lite Logistic")).toBeInTheDocument();
    expect(screen.getByText("LL")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ingresar" })).toBeInTheDocument();
    expect(screen.getByLabelText(/Usuario o correo/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Contrasena/)).toBeInTheDocument();
    expect(screen.getByLabelText("Recordar este usuario")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /INGRESAR/ })).toBeInTheDocument();
  });

  it("logs in and navigates to the operational route", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/auth/api/login/")) {
          return jsonResponse({ success: true, redirectTo: "/pedidos/entrega", session: authenticatedSession });
        }
        if (url.includes("/api/v1/logistics/context/")) {
          return jsonResponse(authenticatedSession.workspace);
        }
        return jsonResponse({ results: [] });
      }),
    );
    const router = renderLogin();

    fireEvent.change(screen.getByLabelText(/Usuario o correo/), { target: { value: "OPERADOR" } });
    fireEvent.change(screen.getByLabelText(/Contrasena/), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: /INGRESAR/ }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/pedidos/entrega"));
  });

  it("shows a toast when login fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ success: false, error: "Credenciales incorrectas" }, 401)));
    renderLogin();

    fireEvent.change(screen.getByLabelText(/Usuario o correo/), { target: { value: "operador" } });
    fireEvent.change(screen.getByLabelText(/Contrasena/), { target: { value: "bad" } });
    fireEvent.click(screen.getByRole("button", { name: /INGRESAR/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Credenciales incorrectas");
  });
});
