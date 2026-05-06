import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { placeholderPageByKey } from "../../shared/data/modules";
import { PlaceholderPage } from "./PlaceholderPage";

describe("PlaceholderPage", () => {
  it("renders placeholder modules without explanatory text", () => {
    render(<PlaceholderPage config={placeholderPageByKey("lot-to-balance")} />);

    expect(screen.getByRole("heading", { name: "Canje lote a saldo" })).toBeInTheDocument();
    expect(screen.getByText("Operaciones")).toBeInTheDocument();
    expect(screen.getByText("Estado operativo")).toBeInTheDocument();
    expect(screen.queryByText("read-only")).not.toBeInTheDocument();
    expect(screen.queryByText("sin API")).not.toBeInTheDocument();
    expect(screen.queryByText("Pendiente de API de canje")).not.toBeInTheDocument();
  });
});
