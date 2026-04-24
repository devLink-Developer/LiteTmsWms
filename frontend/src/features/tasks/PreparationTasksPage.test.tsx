import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PreparationTasksPage } from "./PreparationTasksPage";

describe("PreparationTasksPage", () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/mark-prepared")) {
          return {
            ok: true,
            json: async () => ({
              result: {
                id: "delivery-1",
                delivery_number: "ENT-VENT8-1",
                status: "prepared",
                delivery_mode: "Reparto",
                planned_date: "2026-04-24",
                fulfillment_id: "fulfillment-1",
                sales_order_number: "VENT8-100001658",
                documents: [],
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
                id: "task-1",
                status: "assigned",
                assigned_employee_ref: "eespinoza",
                assigned_at: "2026-04-24T10:00:00Z",
                prepared_by: "",
                prepared_at: null,
                notes: "",
                warehouse_ref: "PS03DP",
                store_ref: "PS003MT",
                total_qty: "2.000000",
                delivery: {
                  id: "delivery-1",
                  delivery_number: "ENT-VENT8-1",
                  status: "preparing",
                  delivery_mode: "Reparto",
                  planned_date: "2026-04-24",
                },
                order: {
                  id: "fulfillment-1",
                  fulfillment_number: "FUL-VENT8-100001658",
                  sales_order_number: "VENT8-100001658",
                  transaction_number: "PS003MT-693",
                  customer_ref: "20000042",
                },
                lines: [
                  {
                    id: "line-1",
                    item_ref: "107226",
                    warehouse_ref: "PS03DP",
                    planned_qty: "1.000000",
                    uom: "un",
                    legacy_line_id: "922",
                  },
                ],
              },
            ],
          }),
        };
      }),
    );
  });

  it("renders preparation tasks and marks a task prepared", async () => {
    render(<PreparationTasksPage />);

    await waitFor(() => expect(screen.getAllByText("VENT8-100001658").length).toBeGreaterThan(0));
    expect(screen.getAllByText("ENT-VENT8-1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("eespinoza").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Marcar preparada" }));
    await waitFor(() => expect(screen.getByText("ENT-VENT8-1 marcada como preparada.")).toBeInTheDocument());
  });
});
