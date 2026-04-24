import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { operationModuleByKey } from "../../shared/data/modules";
import { OperationalPage } from "./OperationalPage";

describe("OperationalPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          results: [
            {
              id: "ledger-1",
              purchase_order_ref: "OC-000184",
              status: "received",
              warehouse_ref: "PS003MT",
              item_ref: "ITM-1",
              lines_count: 1,
            },
          ],
        }),
      })),
    );
  });

  it("renders dense read-only operational table", async () => {
    const view = render(<OperationalPage module={operationModuleByKey("receipts")} />);

    expect(view.getByRole("heading", { name: "Ingresos por OC" })).toBeInTheDocument();
    expect(view.queryByRole("button", { name: /registrar/i })).not.toBeInTheDocument();
    expect(view.getByText("solo lectura")).toBeInTheDocument();
    expect(view.getByRole("table")).toBeInTheDocument();
    await waitFor(() => expect(view.getByText("OC-000184")).toBeInTheDocument());
  });
});
