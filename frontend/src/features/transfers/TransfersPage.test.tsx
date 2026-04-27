import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TransfersPage } from "./TransfersPage";

function renderWithQuery() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TransfersPage />
    </QueryClientProvider>,
  );
}

describe("TransfersPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        const method = init?.method ?? "GET";
        if (method === "POST") {
          return {
            ok: true,
            json: async () => ({
              result: {
                id: "transfer-2",
                transfer_number: "TR-000000002",
                status: "requested",
                origin_warehouse_ref: "WH-A",
                destination_warehouse_ref: "WH-B",
                requested_by: "tester",
                approved_by: "",
                reason: "Reposicion",
                lines: [],
              },
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({
            results: [
              {
                id: "transfer-1",
                transfer_number: "TR-000000001",
                status: "requested",
                origin_warehouse_ref: "WH-A",
                destination_warehouse_ref: "WH-B",
                requested_by: "tester",
                approved_by: "",
                reason: "",
                lines_count: 1,
              },
            ],
          }),
        };
      }),
    );
  });

  it("renders transfer workflow tabs and creates a request", async () => {
    renderWithQuery();

    await waitFor(() => expect(screen.getByText("TR-000000001")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Solicitud" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preparacion" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Origen"), { target: { value: "WH-A" } });
    fireEvent.change(screen.getByLabelText("Destino"), { target: { value: "WH-B" } });
    fireEvent.change(screen.getByLabelText("Articulo"), { target: { value: "ITEM-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear solicitud" }));

    await waitFor(() => expect(screen.getByText("TR-000000002 creada.")).toBeInTheDocument());
  });
});
