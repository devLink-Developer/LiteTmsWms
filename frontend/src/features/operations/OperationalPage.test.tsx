import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { operationModules } from "../../shared/data/modules";
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
              document_ref: "REC-000184",
              movement_type: "receipt",
              warehouse_ref: "PS003MT",
              item_ref: "ITM-1",
              quantity: "18",
              uom: "UN",
              posted_at: "2026-04-24T08:42:00Z",
            },
          ],
        }),
      })),
    );
  });

  it("renders dense operational table and primary action", async () => {
    const view = render(<OperationalPage module={operationModules[0]} />);

    expect(view.getByRole("heading", { name: "Recepciones" })).toBeInTheDocument();
    expect(view.getByRole("button", { name: "Registrar recepcion" })).toBeInTheDocument();
    expect(view.getByRole("table")).toBeInTheDocument();
    await waitFor(() => expect(view.getByText("REC-000184")).toBeInTheDocument());
  });
});
