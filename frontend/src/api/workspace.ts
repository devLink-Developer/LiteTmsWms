import { apiHeaders, requestJson, trackedFetch } from "./client";

export type WorkspaceContext = {
  warehouse_ref: string;
  branch_ref: string;
  role: string;
  permissions: string[];
  authorized_warehouses?: string[];
};

export async function fetchWorkspaceContext() {
  const response = await trackedFetch("/api/v1/logistics/context/", {
    credentials: "include",
    headers: apiHeaders(),
  });
  if (!response.ok) {
    throw new Error(`API /api/v1/logistics/context/ respondio ${response.status}`);
  }
  return response.json() as Promise<WorkspaceContext>;
}

export async function setActiveWarehouse(warehouseRef: string) {
  return requestJson<WorkspaceContext>("/api/v1/logistics/context/active-warehouse/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ warehouse_ref: warehouseRef }),
  });
}
