import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("translates known status codes to Spanish", () => {
    render(<StatusBadge label="ready_for_dispatch" tone="info" />);

    expect(screen.getByText("Lista para despacho")).toBeInTheDocument();
  });

  it("keeps non-status labels unchanged", () => {
    render(<StatusBadge label="PS03DP" tone="success" />);

    expect(screen.getByText("PS03DP")).toBeInTheDocument();
  });
});
