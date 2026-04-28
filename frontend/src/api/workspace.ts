import { apiHeaders, apiUrl } from "./client";

export type WorkspaceContext = {
  warehouse_ref: string;
  branch_ref: string;
  role: string;
  permissions: string[];
  authorized_warehouses?: string[];
};

export async function fetchWorkspaceContext() {
  const response = await fetch(apiUrl("/api/v1/logistics/context/"), {
    credentials: "include",
    headers: apiHeaders(),
  });
  if (!response.ok) {
    throw new Error(`API /api/v1/logistics/context/ respondio ${response.status}`);
  }
  return response.json() as Promise<WorkspaceContext>;
}
