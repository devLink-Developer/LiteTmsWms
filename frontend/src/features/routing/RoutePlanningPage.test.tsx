import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RoutePlanningPage } from "./RoutePlanningPage";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";

vi.mock("leaflet", () => ({
  default: {
    divIcon: vi.fn(() => ({})),
  },
}));

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children: ReactNode }) => <div aria-label="Mapa de reparto">{children}</div>,
  TileLayer: () => null,
  Marker: ({ children, eventHandlers }: { children?: ReactNode; eventHandlers?: { click?: () => void } }) => (
    <button
      type="button"
      data-testid={eventHandlers?.click ? "clickable-route-marker" : "route-marker"}
      onClick={(event) => {
        event.stopPropagation();
        eventHandlers?.click?.();
      }}
    >
      {children}
    </button>
  ),
  Polyline: ({ positions }: { positions: Array<[number, number]> }) => (
    <div data-testid="route-line" data-points={positions.length} data-first={`${positions[0]?.[0]},${positions[0]?.[1]}`} />
  ),
  Tooltip: ({ children }: { children: ReactNode }) => <span data-testid="route-tooltip">{children}</span>,
  useMap: () => ({ fitBounds: vi.fn() }),
}));

function renderWithQuery() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RoutePlanningPage />
    </QueryClientProvider>,
  );
}

describe("RoutePlanningPage", () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      warehouseRef: "W001",
      branchRef: "BR-1",
      role: "Planner",
      permissions: [],
      authorizedWarehouses: ["W001"],
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (init?.method === "PATCH" && url.includes("/api/v1/routesheets/route-1/stops")) {
          return {
            ok: true,
            json: async () => ({
              result: {
                id: "route-1",
                route_number: "HR-000000001",
                status: "draft",
                branch_ref: "W001",
                warehouse_ref: "W001",
                vehicle_id: "vehicle-1",
                vehicle: "VH-1",
                driver_ref: "driver-1",
                planned_date: "2026-04-27",
                planned_weight_kg: "0",
                planned_volume_m3: "0",
                loaded_weight_kg: "0",
                loaded_volume_m3: "0",
                total_distance_km: "0",
                total_time_minutes: 0,
                routing_provider: "manual",
                reviewed_at: new Date().toISOString(),
                route_geometry: { type: "LineString", coordinates: [] },
                preview_payload: { routing_status: "fallback_no_ors_key", excluded: [] },
                stops: [],
              },
            }),
          };
        }
        if (url.includes("/api/v1/logistics/master-data/warehouses/")) {
          return {
            ok: true,
            json: async () => ({
              results: [{ warehouse_code: "W001", warehouse_name: "Deposito reparto", is_shipping_allowed: true }],
            }),
          };
        }
        if (url.includes("/api/v1/vehicles/")) {
          return {
            ok: true,
            json: async () => ({
              results: [{ id: "vehicle-1", code: "VH-1", plate: "AA100AA", status: "available", max_weight_kg: "100", max_volume_m3: "10" }],
            }),
          };
        }
        if (url.includes("/api/v1/routesheets/route-1/")) {
          return {
            ok: true,
            json: async () => ({
              result: {
                id: "route-1",
                route_number: "HR-000000001",
                status: "draft",
                branch_ref: "W001",
                warehouse_ref: "W001",
                vehicle_id: "vehicle-1",
                vehicle: "VH-1",
                driver_ref: "driver-1",
                planned_date: "2026-04-27",
                planned_weight_kg: "9.000",
                planned_volume_m3: "0.300",
                loaded_weight_kg: "0",
                loaded_volume_m3: "0",
                total_distance_km: "12.500",
                total_time_minutes: 28,
                routing_provider: "manual",
                reviewed_at: null,
                route_geometry: { type: "LineString", coordinates: [[-58.38, -34.6], [-58.385, -34.605], [-58.39, -34.61]] },
                preview_payload: { routing_status: "fallback_no_ors_key", excluded: [] },
                stops: [
                  {
                    id: "stop-1",
                    sequence: 1,
                    status: "planned",
                    stop_type: "delivery",
                    source_type: "delivery_order",
                    source_ref: "delivery-1",
                    source_label: "DEL-1",
                    delivery_number: "DEL-1",
                    sales_order_number: "SO-1",
                    delivery_mode: "Reparto programado",
                    customer_ref: "CUST-1",
                    customer_name: "Cliente Uno",
                    address_snapshot: { formatted: "Calle 1, Posadas, Misiones", street: "Calle", street_number: "1", city: "Posadas" },
                    lat: "-34.60",
                    lng: "-58.38",
                    planned_weight_kg: "9",
                    planned_volume_m3: "0.3",
                    outcome_status: "",
                    outcome_reason: "",
                    lines: [],
                  },
                ],
              },
            }),
          };
        }
        if (url.includes("/api/v1/routesheets/?")) {
          return {
            ok: true,
            json: async () => ({ results: [] }),
          };
        }
        if (url.includes("/api/v1/routing/optimize")) {
          return {
            ok: true,
            json: async () => ({
              result: {
                id: "route-1",
                route_number: "HR-000000001",
                status: "draft",
                branch_ref: "W001",
                warehouse_ref: "W001",
                vehicle_id: "vehicle-1",
                vehicle: "VH-1",
                driver_ref: "driver-1",
                planned_date: "2026-04-27",
                planned_weight_kg: "9.000",
                planned_volume_m3: "0.300",
                loaded_weight_kg: "0",
                loaded_volume_m3: "0",
                total_distance_km: "12.500",
                total_time_minutes: 28,
                routing_provider: "manual",
                reviewed_at: null,
                route_geometry: { type: "LineString", coordinates: [[-58.38, -34.6], [-58.385, -34.605], [-58.39, -34.61]] },
                preview_payload: { routing_status: "fallback_no_ors_key", excluded: [] },
                stops: [
                  {
                    id: "stop-1",
                    sequence: 1,
                    status: "planned",
                    stop_type: "delivery",
                    source_type: "delivery_order",
                    source_ref: "delivery-1",
                    source_label: "DEL-1",
                    delivery_number: "DEL-1",
                    sales_order_number: "SO-1",
                    delivery_mode: "Reparto programado",
                    customer_ref: "CUST-1",
                    customer_name: "Cliente Uno",
                    address_snapshot: { formatted: "Calle 1, Posadas, Misiones", street: "Calle", street_number: "1", city: "Posadas" },
                    lat: "-34.60",
                    lng: "-58.38",
                    planned_weight_kg: "9",
                    planned_volume_m3: "0.3",
                    outcome_status: "",
                    outcome_reason: "",
                    lines: [],
                  },
                  {
                    id: "stop-2",
                    sequence: 2,
                    status: "planned",
                    stop_type: "delivery",
                    source_type: "delivery_order",
                    source_ref: "delivery-2",
                    source_label: "DEL-2",
                    delivery_number: "DEL-2",
                    sales_order_number: "SO-2",
                    delivery_mode: "Reparto programado",
                    customer_ref: "CUST-2",
                    customer_name: "Cliente Dos",
                    address_snapshot: { formatted: "Avenida 2, Posadas, Misiones", street: "Avenida", street_number: "2", city: "Posadas" },
                    lat: "-34.61",
                    lng: "-58.39",
                    planned_weight_kg: "4",
                    planned_volume_m3: "0.1",
                    outcome_status: "",
                    outcome_reason: "",
                    lines: [],
                  },
                ],
              },
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({
            results: [
              {
                id: "delivery-1",
                delivery_number: "DEL-1",
                status: "prepared",
                delivery_mode: "Reparto programado",
                planned_date: "2026-04-27",
                warehouse_ref: "W001",
                customer_ref: "CUST-1",
                sales_order_number: "SO-1",
                address_snapshot: { street: "Calle 1" },
                lat: "-34.60",
                lng: "-58.38",
                planned_weight_kg: "9",
                planned_volume_m3: "0.3",
              },
            ],
          }),
        };
      }),
    );
  });

  it("renders delivery markers and creates an editable route preview", async () => {
    renderWithQuery();

    await waitFor(() => expect(screen.getAllByText("DEL-1").length).toBeGreaterThan(0));
    expect(screen.getAllByTestId("route-marker").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /Optimizar/i }));

    await waitFor(() => expect(screen.getByText(/HR-000000001/)).toBeInTheDocument());
    expect(screen.getByText("Ruteo manual: sin clave ORS")).toBeInTheDocument();
    expect(screen.getAllByText("Cliente Uno").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Calle 1, Posadas, Misiones").length).toBeGreaterThan(0);
    expect(screen.queryAllByTestId("route-tooltip")).toHaveLength(0);
    expect(screen.getByTestId("route-line")).toHaveAttribute("data-points", "3");
  });

  it("removes a stop from a draft route", async () => {
    renderWithQuery();

    await waitFor(() => expect(screen.getAllByText("DEL-1").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: /Optimizar/i }));
    await waitFor(() => expect(screen.getByText(/HR-000000001/)).toBeInTheDocument());

    const removeButton = screen.getByRole("button", { name: /Quitar/i });
    await waitFor(() => expect(removeButton).not.toBeDisabled());
    fireEvent.click(removeButton);

    await waitFor(() => expect(screen.getByText("Parada quitada.")).toBeInTheDocument());
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/routesheets/route-1/stops"),
      expect.objectContaining({
        method: "PATCH",
        body: expect.stringContaining("remove_stop_ids"),
      }),
    );
  });
});
