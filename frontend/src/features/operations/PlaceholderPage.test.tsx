import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { placeholderPageByKey } from "../../shared/data/modules";
import { PlaceholderPage } from "./PlaceholderPage";

describe("PlaceholderPage", () => {
  it("renders a clear read-only state for modules without API", () => {
    render(<PlaceholderPage config={placeholderPageByKey("lot-to-balance")} />);

    expect(screen.getByRole("heading", { name: "Canje lote a saldo" })).toBeInTheDocument();
    expect(screen.getByText("Operaciones")).toBeInTheDocument();
    expect(screen.getByText("read-only")).toBeInTheDocument();
    expect(screen.getByText("sin API")).toBeInTheDocument();
    expect(screen.getByText("Pendiente de API de canje")).toBeInTheDocument();
  });
});
