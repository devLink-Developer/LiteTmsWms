import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SheetCuttingPage } from "./SheetCuttingPage";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 200 && status < 300 ? "OK" : "Error",
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  };
}

const optionsPayload = {
  unit: "cm",
  source_files: ["materiales_TEST.parquet"],
  categories: [
    {
      category: "Chapa Test",
      item_count: 3,
      store_count: 1,
      min_length_cm: 100,
      max_length_cm: 1300,
      min_length_m: 1,
      max_length_m: 13,
      length_count: 3,
    },
  ],
  materials: [
    {
      item_ref: "CH-100",
      category: "Chapa Test",
      name: "Chapa Test x 1m",
      long_name: "Chapa Test x 1.00m",
      uom: "un",
      uom_code: "ST",
      length_cm: 100,
      length_m: 1,
    },
    {
      item_ref: "CH-600",
      category: "Chapa Test",
      name: "Chapa Test x 6m",
      long_name: "Chapa Test x 6.00m",
      uom: "un",
      uom_code: "ST",
      length_cm: 600,
      length_m: 6,
    },
    {
      item_ref: "CH-1300",
      category: "Chapa Test",
      name: "Chapa Test x 13m",
      long_name: "Chapa Test x 13.00m",
      uom: "un",
      uom_code: "ST",
      length_cm: 1300,
      length_m: 13,
    },
  ],
  length_options: [
    {
      length_cm: 100,
      length_m: 1,
      item_count: 1,
      available_for_delivery: 8,
      examples: [{ item_ref: "CH-100", long_name: "Chapa Test x 1.00m" }],
    },
    {
      length_cm: 600,
      length_m: 6,
      item_count: 1,
      available_for_delivery: 2,
      examples: [{ item_ref: "CH-600", long_name: "Chapa Test x 6.00m" }],
    },
    {
      length_cm: 1300,
      length_m: 13,
      item_count: 1,
      available_for_delivery: 4,
      examples: [{ item_ref: "CH-1300", long_name: "Chapa Test x 13.00m" }],
    },
  ],
};

function validationBodies() {
  return vi
    .mocked(fetch)
    .mock.calls.filter(([url, init]) => String(url).includes("/api/v1/inventory/sheet-cutting/validate/") && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init?.body)));
}

describe("SheetCuttingPage", () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      warehouseRef: "W001",
      branchRef: "TEST",
      role: "Operador",
      permissions: ["stock:view"],
      authorizedWarehouses: ["W001"],
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/v1/inventory/sheet-cutting/validate/") && init?.method === "POST") {
          const body = JSON.parse(String(init.body));
          expect(body.store).toBe("TEST");
          expect(body.category).toBe("Chapa Test");
          expect(body.source_item_ref).toBe("CH-1300");
          const usedCm = body.cuts.reduce((total: number, cut: { length_cm: number; quantity: number }) => total + cut.length_cm * cut.quantity, 0);
          const wasteCm = 1300 - usedCm;
          const hasCuts = body.cuts.length > 0;
          const exactFit = hasCuts && wasteCm === 0;
          return jsonResponse({
            result: {
              valid: exactFit,
              message: exactFit
                ? "Corte validado con stock disponible."
                : hasCuts
                  ? "El sobrante debe ser 0 cm para ejecutar el corte."
                  : "Origen validado con stock disponible.",
              stock: {
                warehouse_ref: "W001",
                source_item_ref: "CH-1300",
                source_uom: "UN",
                stock_state: "packed",
                required_qty: "1",
                available_qty: "1",
                has_stock: true,
              },
              plan: {
                unit: "cm",
                valid: exactFit,
                category: "Chapa Test",
                source: { item_ref: "CH-1300", length_cm: 1300, length_m: 13, quantity: 1, total_cm: 1300, total_m: 13 },
                outputs: body.cuts.map((cut: { length_cm: number; quantity: number }) => ({
                  item_ref: cut.length_cm === 600 ? "CH-600" : "CH-100",
                  length_cm: cut.length_cm,
                  length_m: cut.length_cm / 100,
                  quantity: cut.quantity,
                  used_cm: cut.length_cm * cut.quantity,
                  used_m: (cut.length_cm * cut.quantity) / 100,
                })),
                used_cm: usedCm,
                used_m: usedCm / 100,
                waste_cm: wasteCm,
                waste_m: wasteCm / 100,
                message: exactFit ? "Corte valido." : "El corte excede el largo origen o no tiene salidas.",
              },
            },
          });
        }
        if (url.includes("/api/v1/inventory/sheet-cutting/execute/") && init?.method === "POST") {
          const body = JSON.parse(String(init.body));
          expect(body.source_item_ref).toBe("CH-1300");
          return jsonResponse(
            {
              result: {
                id: "tr-1",
                status: "posted",
                warehouse_ref: "W001",
                transformation_type: "split",
                reason: "Corte test",
                posted_at: "2026-05-05T20:00:00Z",
                source: { item_ref: "CH-1300", length_cm: 1300, length_m: 13, quantity: 1, total_cm: 1300, total_m: 13 },
                outputs: [],
                used_cm: 1300,
                used_m: 13,
                waste_cm: 0,
                waste_m: 0,
                stock: {
                  warehouse_ref: "W001",
                  source_item_ref: "CH-1300",
                  source_uom: "UN",
                  stock_state: "packed",
                  required_qty: "1",
                  available_qty: "1",
                  has_stock: true,
                },
              },
            },
            201,
          );
        }
        return jsonResponse(optionsPayload);
      }),
    );
  });

  it("validates packed stock and executes a 13m sheet as two 6m cuts plus one 1m cut", async () => {
    render(<SheetCuttingPage />);

    expect(screen.getByRole("heading", { name: "Corte de chapas" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("Chapa Test").length).toBeGreaterThan(0));

    await waitFor(() => expect(validationBodies().some((body) => body.cuts.length === 0)).toBe(true));
    expect(await screen.findByText("Origen validado con stock disponible.")).toBeInTheDocument();

    fireEvent.change(await screen.findByLabelText("Cantidad para 6 m"), { target: { value: "2" } });
    fireEvent.change(await screen.findByLabelText("Cantidad para 1 m"), { target: { value: "1" } });

    expect(screen.getByText("2 x 6 m + 1 x 1 m")).toBeInTheDocument();
    expect(screen.getAllByText("0 cm").length).toBeGreaterThan(0);

    await waitFor(() => expect(validationBodies().some((body) => body.cuts.length === 2)).toBe(true));
    expect((await screen.findAllByText("Corte validado con stock disponible.")).length).toBeGreaterThan(0);

    fireEvent.click(screen.getAllByRole("button", { name: "Ejecutar corte" })[0]);

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/inventory/sheet-cutting/execute/"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(await screen.findByText("Transformacion tr-1")).toBeInTheDocument();
  });

  it("keeps execution disabled while the plan has leftover length", async () => {
    render(<SheetCuttingPage />);

    await waitFor(() => expect(screen.getAllByText("Chapa Test").length).toBeGreaterThan(0));
    fireEvent.change(await screen.findByLabelText("Cantidad para 6 m"), { target: { value: "2" } });

    expect(screen.getByText("2 x 6 m")).toBeInTheDocument();
    expect(screen.getAllByText("100 cm").length).toBeGreaterThan(0);
    await waitFor(() => expect(validationBodies().some((body) => body.cuts.length === 1)).toBe(true));
    expect(await screen.findByText("El sobrante debe ser 0 cm para ejecutar el corte.")).toBeInTheDocument();

    for (const button of screen.getAllByRole("button", { name: "Ejecutar corte" })) {
      expect(button).toBeDisabled();
    }
  });
});
