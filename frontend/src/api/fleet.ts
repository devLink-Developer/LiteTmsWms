import { apiGet, apiHeaders, apiPost, trackedFetch } from "./client";

export type CapacityProfile = {
  id: string;
  name: string;
  max_weight_kg: string;
  max_volume_m3: string;
  notes: string;
};

export type VehicleRecord = {
  id: string;
  code: string;
  plate: string;
  description: string;
  status: string;
  capacity_profile_id: string;
  capacity_profile_name: string;
  max_weight_kg: string;
  max_volume_m3: string;
  branch_ref: string;
  active: boolean;
};

export type DriverRecord = {
  id: string;
  code: string;
  full_name: string;
  document_number: string;
  phone: string;
  email: string;
  license_number: string;
  license_category: string;
  license_expires_at: string | null;
  status: string;
  branch_ref: string;
  warehouse_ref: string;
  active: boolean;
  notes: string;
};

export type VehiclePayload = {
  code: string;
  plate: string;
  description: string;
  status: string;
  capacity_profile_id: string;
  branch_ref: string;
  active: boolean;
};

export type DriverPayload = {
  code: string;
  full_name: string;
  document_number: string;
  phone: string;
  email: string;
  license_number: string;
  license_category: string;
  license_expires_at: string;
  status: string;
  branch_ref: string;
  warehouse_ref: string;
  active: boolean;
  notes: string;
};

export type CapacityProfilePayload = {
  name: string;
  max_weight_kg: string;
  max_volume_m3: string;
  notes: string;
};

type CommandResult<T> = {
  result: T;
  error?: { message: string };
};

async function apiPatch<T>(path: string, body: unknown) {
  const response = await trackedFetch(path, {
    method: "PATCH",
    credentials: "include",
    headers: apiHeaders({
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`,
    }),
    body: JSON.stringify(body),
  });
  const payload = (await response.json().catch(() => ({}))) as CommandResult<T>;
  if (!response.ok) throw new Error(payload.error?.message ?? `API ${path} respondio ${response.status}`);
  return payload.result;
}

export async function fetchCapacityProfiles() {
  const response = await apiGet<CapacityProfile>("/api/v1/vehicles/profiles/");
  if (response.error) throw new Error(response.error.message);
  return response.results ?? [];
}

export async function saveCapacityProfile(payload: CapacityProfilePayload, profileId?: string) {
  if (profileId) return apiPatch<CapacityProfile>(`/api/v1/vehicles/profiles/${profileId}/`, payload);
  const response = await apiPost<CommandResult<CapacityProfile>>("/api/v1/vehicles/profiles/", payload);
  return response.result;
}

export async function fetchFleetVehicles() {
  const response = await apiGet<VehicleRecord>("/api/v1/vehicles/?include_inactive=1");
  if (response.error) throw new Error(response.error.message);
  return response.results ?? [];
}

export async function saveVehicle(payload: VehiclePayload, vehicleId?: string) {
  if (vehicleId) return apiPatch<VehicleRecord>(`/api/v1/vehicles/${vehicleId}/`, payload);
  const response = await apiPost<CommandResult<VehicleRecord>>("/api/v1/vehicles/", payload);
  return response.result;
}

export async function fetchDrivers() {
  const response = await apiGet<DriverRecord>("/api/v1/vehicles/drivers/?include_inactive=1");
  if (response.error) throw new Error(response.error.message);
  return response.results ?? [];
}

export async function saveDriver(payload: DriverPayload, driverId?: string) {
  if (driverId) return apiPatch<DriverRecord>(`/api/v1/vehicles/drivers/${driverId}/`, payload);
  const response = await apiPost<CommandResult<DriverRecord>>("/api/v1/vehicles/drivers/", payload);
  return response.result;
}
