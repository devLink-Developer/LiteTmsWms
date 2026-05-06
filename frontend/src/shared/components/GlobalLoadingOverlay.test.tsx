import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GlobalLoadingOverlay } from "./GlobalLoadingOverlay";
import { trackedFetch } from "../../api/client";
import { beginGlobalLoading, useGlobalLoadingStore } from "../../stores/useGlobalLoadingStore";

describe("GlobalLoadingOverlay", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useGlobalLoadingStore.getState().clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("shows a blocking wait screen while a global operation is active", () => {
    render(<GlobalLoadingOverlay />);

    let finish: () => void = () => undefined;
    act(() => {
      finish = beginGlobalLoading("Cargando datos...");
    });
    act(() => {
      vi.advanceTimersByTime(179);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByRole("status")).toHaveTextContent("Cargando datos...");

    act(() => {
      finish();
    });
    act(() => {
      vi.advanceTimersByTime(120);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("tracks API requests automatically", async () => {
    let resolveFetch: (response: Response) => void = () => undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            resolveFetch = resolve;
          }),
      ),
    );

    const request = trackedFetch("/api/v1/example/");
    expect(Object.keys(useGlobalLoadingStore.getState().operations)).toHaveLength(1);

    resolveFetch(new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
    await request;

    expect(Object.keys(useGlobalLoadingStore.getState().operations)).toHaveLength(0);
  });

  it("does not show the global wait screen for silent background requests", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));

    await trackedFetch("/api/v1/background-refresh/", undefined, { globalLoading: false });

    expect(Object.keys(useGlobalLoadingStore.getState().operations)).toHaveLength(0);
  });
});
