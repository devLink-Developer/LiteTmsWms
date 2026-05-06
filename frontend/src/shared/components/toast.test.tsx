import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { notify, ToastViewport } from "./toast";

describe("ToastViewport", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("dismisses notifications after 3 seconds", () => {
    render(<ToastViewport />);

    act(() => {
      notify({ message: "Stock validado", tone: "success" });
    });

    expect(screen.getByText("Stock validado")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(2999);
    });
    expect(screen.getByText("Stock validado")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByText("Stock validado")).not.toBeInTheDocument();
  });

  it("renders multiline messages with preserved line breaks", () => {
    render(<ToastViewport />);

    act(() => {
      notify({
        message: "Stock insuficiente en 2 articulos.\n- 100100: solicitado 1 un; disponible 0 un",
        tone: "error",
      });
    });

    expect(screen.getByText(/Stock insuficiente en 2 articulos/)).toHaveClass("whitespace-pre-line");
  });

  it("stays open while the mouse is over the toast", () => {
    render(<ToastViewport />);

    act(() => {
      notify({ message: "Confirmacion pendiente", tone: "warning" });
    });

    const toast = screen.getByRole("status");
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    fireEvent.mouseEnter(toast);

    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(screen.getByText("Confirmacion pendiente")).toBeInTheDocument();

    fireEvent.mouseLeave(toast);
    act(() => {
      vi.advanceTimersByTime(999);
    });
    expect(screen.getByText("Confirmacion pendiente")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByText("Confirmacion pendiente")).not.toBeInTheDocument();
  });
});
