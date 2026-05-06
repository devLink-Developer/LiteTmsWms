import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Gauge, Plus, Save, Search, Truck, UserRound } from "lucide-react";

import {
  fetchCapacityProfiles,
  fetchDrivers,
  fetchFleetVehicles,
  saveCapacityProfile,
  saveDriver,
  saveVehicle,
  type CapacityProfile,
  type CapacityProfilePayload,
  type DriverPayload,
  type DriverRecord,
  type VehiclePayload,
  type VehicleRecord,
} from "../../api/fleet";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { notify, useToastError } from "../../shared/components/toast";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";
import type { StatusTone } from "../../types/operations";

type FleetTab = "vehicles" | "drivers" | "profiles";

type FleetAdminPageProps = {
  initialTab?: FleetTab;
};

const vehicleStatuses = [
  ["available", "Disponible"],
  ["reserved", "Reservado"],
  ["in_route", "En ruta"],
  ["maintenance", "Mantenimiento"],
  ["out_of_service", "Fuera de servicio"],
  ["retired", "Baja"],
] as const;

const driverStatuses = [
  ["available", "Disponible"],
  ["assigned", "Asignado"],
  ["in_route", "En ruta"],
  ["suspended", "Suspendido"],
  ["inactive", "Inactivo"],
] as const;

const statusTone: Record<string, StatusTone> = {
  available: "success",
  reserved: "warning",
  assigned: "info",
  in_route: "info",
  maintenance: "warning",
  out_of_service: "danger",
  retired: "neutral",
  suspended: "danger",
  inactive: "neutral",
};

function emptyVehicle(branchRef = ""): VehiclePayload {
  return {
    code: "",
    plate: "",
    description: "",
    status: "available",
    capacity_profile_id: "",
    branch_ref: branchRef,
    active: true,
  };
}

function vehiclePayload(row: VehicleRecord): VehiclePayload {
  return {
    code: row.code,
    plate: row.plate,
    description: row.description,
    status: row.status,
    capacity_profile_id: row.capacity_profile_id,
    branch_ref: row.branch_ref,
    active: row.active,
  };
}

function emptyDriver(branchRef = "", warehouseRef = ""): DriverPayload {
  return {
    code: "",
    full_name: "",
    document_number: "",
    phone: "",
    email: "",
    license_number: "",
    license_category: "",
    license_expires_at: "",
    status: "available",
    branch_ref: branchRef,
    warehouse_ref: warehouseRef,
    active: true,
    notes: "",
  };
}

function driverPayload(row: DriverRecord): DriverPayload {
  return {
    code: row.code,
    full_name: row.full_name,
    document_number: row.document_number,
    phone: row.phone,
    email: row.email,
    license_number: row.license_number,
    license_category: row.license_category,
    license_expires_at: row.license_expires_at ?? "",
    status: row.status,
    branch_ref: row.branch_ref,
    warehouse_ref: row.warehouse_ref,
    active: row.active,
    notes: row.notes,
  };
}

function emptyProfile(): CapacityProfilePayload {
  return {
    name: "",
    max_weight_kg: "",
    max_volume_m3: "",
    notes: "",
  };
}

function profilePayload(row: CapacityProfile): CapacityProfilePayload {
  return {
    name: row.name,
    max_weight_kg: row.max_weight_kg,
    max_volume_m3: row.max_volume_m3,
    notes: row.notes,
  };
}

function formatNumber(value: string | number | null | undefined, maximumFractionDigits = 3) {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric)) return "0";
  return numeric.toLocaleString("es-AR", { maximumFractionDigits });
}

function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
      {label}
      {children}
    </label>
  );
}

const inputClass =
  "h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20";

export function FleetAdminPage({ initialTab = "vehicles" }: FleetAdminPageProps) {
  const queryClient = useQueryClient();
  const { branchRef, warehouseRef } = useWorkspaceStore();
  const [tab, setTab] = useState<FleetTab>(initialTab);
  const [query, setQuery] = useState("");
  const [vehicleId, setVehicleId] = useState("");
  const [driverId, setDriverId] = useState("");
  const [profileId, setProfileId] = useState("");
  const [vehicleForm, setVehicleForm] = useState<VehiclePayload>(() => emptyVehicle(branchRef));
  const [driverForm, setDriverForm] = useState<DriverPayload>(() => emptyDriver(branchRef, warehouseRef));
  const [profileForm, setProfileForm] = useState<CapacityProfilePayload>(() => emptyProfile());

  useEffect(() => setTab(initialTab), [initialTab]);

  const vehiclesQuery = useQuery({ queryKey: ["fleet-vehicles"], queryFn: fetchFleetVehicles });
  const driversQuery = useQuery({ queryKey: ["fleet-drivers"], queryFn: fetchDrivers });
  const profilesQuery = useQuery({ queryKey: ["fleet-profiles"], queryFn: fetchCapacityProfiles });

  const vehicles = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (vehiclesQuery.data ?? []).filter((row) =>
      [row.code, row.plate, row.description, row.branch_ref, row.capacity_profile_name].some((value) =>
        value.toLowerCase().includes(needle),
      ),
    );
  }, [query, vehiclesQuery.data]);

  const drivers = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (driversQuery.data ?? []).filter((row) =>
      [row.code, row.full_name, row.document_number, row.license_number, row.branch_ref, row.warehouse_ref].some((value) =>
        value.toLowerCase().includes(needle),
      ),
    );
  }, [driversQuery.data, query]);

  const profiles = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (profilesQuery.data ?? []).filter((row) => [row.name, row.notes].some((value) => value.toLowerCase().includes(needle)));
  }, [profilesQuery.data, query]);

  const saveVehicleMutation = useMutation({
    mutationFn: () => saveVehicle(vehicleForm, vehicleId || undefined),
    onSuccess: (row) => {
      setVehicleId(row.id);
      setVehicleForm(vehiclePayload(row));
      notify({ message: `${row.code} guardado.`, tone: "success" });
      void queryClient.invalidateQueries({ queryKey: ["fleet-vehicles"] });
      void queryClient.invalidateQueries({ queryKey: ["vehicles"] });
    },
  });

  const saveDriverMutation = useMutation({
    mutationFn: () => saveDriver(driverForm, driverId || undefined),
    onSuccess: (row) => {
      setDriverId(row.id);
      setDriverForm(driverPayload(row));
      notify({ message: `${row.code} guardado.`, tone: "success" });
      void queryClient.invalidateQueries({ queryKey: ["fleet-drivers"] });
      void queryClient.invalidateQueries({ queryKey: ["drivers"] });
    },
  });

  const saveProfileMutation = useMutation({
    mutationFn: () => saveCapacityProfile(profileForm, profileId || undefined),
    onSuccess: (row) => {
      setProfileId(row.id);
      setProfileForm(profilePayload(row));
      notify({ message: `${row.name} guardado.`, tone: "success" });
      void queryClient.invalidateQueries({ queryKey: ["fleet-profiles"] });
      void queryClient.invalidateQueries({ queryKey: ["vehicles"] });
    },
  });

  const error =
    vehiclesQuery.error ||
    driversQuery.error ||
    profilesQuery.error ||
    saveVehicleMutation.error ||
    saveDriverMutation.error ||
    saveProfileMutation.error;
  useToastError(error);
  const busy = saveVehicleMutation.isPending || saveDriverMutation.isPending || saveProfileMutation.isPending;

  function resetVehicle() {
    setVehicleId("");
    setVehicleForm(emptyVehicle(branchRef));
  }

  function resetDriver() {
    setDriverId("");
    setDriverForm(emptyDriver(branchRef, warehouseRef));
  }

  function resetProfile() {
    setProfileId("");
    setProfileForm(emptyProfile());
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-3">
      <header className="flex shrink-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[20px] font-semibold text-night">ABM de flota</h1>
        </div>
        <div className="inline-flex min-h-10 overflow-hidden rounded border border-borderSoft bg-white p-1 text-[12px] font-semibold shadow-panel">
          {[
            ["vehicles", "Vehiculos", Truck],
            ["drivers", "Choferes", UserRound],
            ["profiles", "Capacidad", Gauge],
          ].map(([key, label, Icon]) => {
            const active = tab === key;
            return (
              <button
                key={key as string}
                type="button"
                onClick={() => setTab(key as FleetTab)}
                className={`inline-flex min-w-28 items-center justify-center gap-2 rounded px-3 transition focus:outline-none focus:ring-2 focus:ring-primary/30 ${
                  active ? "bg-primary text-white" : "text-night hover:bg-softStart"
                }`}
              >
                <Icon size={15} />
                {label as string}
              </button>
            );
          })}
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-borderSoft bg-white p-3">
          <label className="relative min-w-64 flex-1">
            <Search className="pointer-events-none absolute left-2 top-2.5 text-secondaryText" size={15} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-9 w-full rounded border border-borderSoft bg-white pl-8 pr-2 text-[12px] text-night outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
              placeholder="Buscar por codigo, patente, nombre o deposito"
            />
          </label>
          <button
            type="button"
            onClick={tab === "vehicles" ? resetVehicle : tab === "drivers" ? resetDriver : resetProfile}
            className="inline-flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/30"
          >
            <Plus size={15} />
            Nuevo
          </button>
        </div>

        {tab === "vehicles" && (
          <section className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,1.25fr)_420px]">
            <div className="min-h-0 overflow-auto">
              <table className="w-full min-w-[760px] border-collapse text-left text-[12px]">
                <thead className="sticky top-0 z-10 bg-white text-[11px] uppercase text-secondaryText">
                  <tr>
                    <th className="border-b border-borderSoft px-3 py-2">Vehiculo</th>
                    <th className="border-b border-borderSoft px-3 py-2">Estado</th>
                    <th className="border-b border-borderSoft px-3 py-2">Base</th>
                    <th className="border-b border-borderSoft px-3 py-2">Capacidad</th>
                    <th className="border-b border-borderSoft px-3 py-2">Activo</th>
                  </tr>
                </thead>
                <tbody>
                  {vehicles.map((row) => (
                    <tr
                      key={row.id}
                      onClick={() => {
                        setVehicleId(row.id);
                        setVehicleForm(vehiclePayload(row));
                      }}
                      className={`cursor-pointer border-b border-borderSoft transition hover:bg-softStart ${
                        vehicleId === row.id ? "bg-blue-50" : "bg-surface"
                      }`}
                    >
                      <td className="px-3 py-2">
                        <div className="font-mono font-semibold text-night">{row.code}</div>
                        <div className="text-[11px] text-secondaryText">{row.plate} / {row.description || "Sin descripcion"}</div>
                      </td>
                      <td className="px-3 py-2"><StatusBadge label={row.status} tone={statusTone[row.status] ?? "neutral"} /></td>
                      <td className="px-3 py-2 font-mono text-night">{row.branch_ref || "-"}</td>
                      <td className="px-3 py-2 font-mono text-night">
                        {formatNumber(row.max_weight_kg)} kg / {formatNumber(row.max_volume_m3)} m3
                      </td>
                      <td className="px-3 py-2">{row.active ? "Si" : "No"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <form
              className="grid content-start gap-3 border-t border-borderSoft bg-white p-3 lg:border-l lg:border-t-0"
              onSubmit={(event) => {
                event.preventDefault();
                saveVehicleMutation.mutate();
              }}
            >
              <div>
                <h2 className="text-[13px] font-semibold text-night">{vehicleId ? "Editar vehiculo" : "Nuevo vehiculo"}</h2>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Codigo">
                  <input className={inputClass} value={vehicleForm.code} onChange={(event) => setVehicleForm({ ...vehicleForm, code: event.target.value })} />
                </Field>
                <Field label="Patente">
                  <input className={inputClass} value={vehicleForm.plate} onChange={(event) => setVehicleForm({ ...vehicleForm, plate: event.target.value })} />
                </Field>
              </div>
              <Field label="Descripcion">
                <input className={inputClass} value={vehicleForm.description} onChange={(event) => setVehicleForm({ ...vehicleForm, description: event.target.value })} />
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Estado">
                  <select className={inputClass} value={vehicleForm.status} onChange={(event) => setVehicleForm({ ...vehicleForm, status: event.target.value })}>
                    {vehicleStatuses.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </Field>
                <Field label="Sucursal">
                  <input className={inputClass} value={vehicleForm.branch_ref} onChange={(event) => setVehicleForm({ ...vehicleForm, branch_ref: event.target.value })} />
                </Field>
              </div>
              <Field label="Perfil de capacidad">
                <select
                  className={inputClass}
                  value={vehicleForm.capacity_profile_id}
                  onChange={(event) => setVehicleForm({ ...vehicleForm, capacity_profile_id: event.target.value })}
                >
                  <option value="">Sin perfil</option>
                  {(profilesQuery.data ?? []).map((profile) => (
                    <option key={profile.id} value={profile.id}>
                      {profile.name} / {formatNumber(profile.max_weight_kg)} kg / {formatNumber(profile.max_volume_m3)} m3
                    </option>
                  ))}
                </select>
              </Field>
              <label className="inline-flex min-h-9 items-center gap-2 text-[12px] font-semibold text-night">
                <input
                  type="checkbox"
                  checked={vehicleForm.active}
                  onChange={(event) => setVehicleForm({ ...vehicleForm, active: event.target.checked })}
                />
                Activo para operacion
              </label>
              <button type="submit" disabled={busy} className="inline-flex min-h-10 items-center justify-center gap-2 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover disabled:bg-softStart disabled:text-secondaryText">
                <Save size={15} />
                Guardar vehiculo
              </button>
            </form>
          </section>
        )}

        {tab === "drivers" && (
          <section className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,1.25fr)_420px]">
            <div className="min-h-0 overflow-auto">
              <table className="w-full min-w-[820px] border-collapse text-left text-[12px]">
                <thead className="sticky top-0 z-10 bg-white text-[11px] uppercase text-secondaryText">
                  <tr>
                    <th className="border-b border-borderSoft px-3 py-2">Chofer</th>
                    <th className="border-b border-borderSoft px-3 py-2">Estado</th>
                    <th className="border-b border-borderSoft px-3 py-2">Licencia</th>
                    <th className="border-b border-borderSoft px-3 py-2">Deposito</th>
                    <th className="border-b border-borderSoft px-3 py-2">Activo</th>
                  </tr>
                </thead>
                <tbody>
                  {drivers.map((row) => (
                    <tr
                      key={row.id}
                      onClick={() => {
                        setDriverId(row.id);
                        setDriverForm(driverPayload(row));
                      }}
                      className={`cursor-pointer border-b border-borderSoft transition hover:bg-softStart ${
                        driverId === row.id ? "bg-blue-50" : "bg-surface"
                      }`}
                    >
                      <td className="px-3 py-2">
                        <div className="font-mono font-semibold text-night">{row.code}</div>
                        <div className="text-[11px] text-secondaryText">{row.full_name} / DNI {row.document_number || "-"}</div>
                      </td>
                      <td className="px-3 py-2"><StatusBadge label={row.status} tone={statusTone[row.status] ?? "neutral"} /></td>
                      <td className="px-3 py-2 font-mono text-night">{row.license_number || "-"} / {row.license_category || "-"}</td>
                      <td className="px-3 py-2 font-mono text-night">{row.warehouse_ref || row.branch_ref || "-"}</td>
                      <td className="px-3 py-2">{row.active ? "Si" : "No"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <form
              className="grid content-start gap-3 border-t border-borderSoft bg-white p-3 lg:border-l lg:border-t-0"
              onSubmit={(event) => {
                event.preventDefault();
                saveDriverMutation.mutate();
              }}
            >
              <div>
                <h2 className="text-[13px] font-semibold text-night">{driverId ? "Editar chofer" : "Nuevo chofer"}</h2>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Codigo">
                  <input className={inputClass} value={driverForm.code} onChange={(event) => setDriverForm({ ...driverForm, code: event.target.value })} />
                </Field>
                <Field label="Estado">
                  <select className={inputClass} value={driverForm.status} onChange={(event) => setDriverForm({ ...driverForm, status: event.target.value })}>
                    {driverStatuses.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </Field>
              </div>
              <Field label="Nombre completo">
                <input className={inputClass} value={driverForm.full_name} onChange={(event) => setDriverForm({ ...driverForm, full_name: event.target.value })} />
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Documento">
                  <input className={inputClass} value={driverForm.document_number} onChange={(event) => setDriverForm({ ...driverForm, document_number: event.target.value })} />
                </Field>
                <Field label="Telefono">
                  <input className={inputClass} value={driverForm.phone} onChange={(event) => setDriverForm({ ...driverForm, phone: event.target.value })} />
                </Field>
              </div>
              <Field label="Email">
                <input className={inputClass} type="email" value={driverForm.email} onChange={(event) => setDriverForm({ ...driverForm, email: event.target.value })} />
              </Field>
              <div className="grid grid-cols-3 gap-2">
                <Field label="Licencia">
                  <input className={inputClass} value={driverForm.license_number} onChange={(event) => setDriverForm({ ...driverForm, license_number: event.target.value })} />
                </Field>
                <Field label="Categoria">
                  <input className={inputClass} value={driverForm.license_category} onChange={(event) => setDriverForm({ ...driverForm, license_category: event.target.value })} />
                </Field>
                <Field label="Vence">
                  <input className={inputClass} type="date" value={driverForm.license_expires_at} onChange={(event) => setDriverForm({ ...driverForm, license_expires_at: event.target.value })} />
                </Field>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Sucursal">
                  <input className={inputClass} value={driverForm.branch_ref} onChange={(event) => setDriverForm({ ...driverForm, branch_ref: event.target.value })} />
                </Field>
                <Field label="Deposito">
                  <input className={inputClass} value={driverForm.warehouse_ref} onChange={(event) => setDriverForm({ ...driverForm, warehouse_ref: event.target.value })} />
                </Field>
              </div>
              <Field label="Notas">
                <textarea
                  value={driverForm.notes}
                  onChange={(event) => setDriverForm({ ...driverForm, notes: event.target.value })}
                  className="min-h-20 rounded border border-borderSoft bg-white px-2 py-2 text-[12px] text-night outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
                />
              </Field>
              <label className="inline-flex min-h-9 items-center gap-2 text-[12px] font-semibold text-night">
                <input
                  type="checkbox"
                  checked={driverForm.active}
                  onChange={(event) => setDriverForm({ ...driverForm, active: event.target.checked })}
                />
                Activo para operacion
              </label>
              <button type="submit" disabled={busy} className="inline-flex min-h-10 items-center justify-center gap-2 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover disabled:bg-softStart disabled:text-secondaryText">
                <Save size={15} />
                Guardar chofer
              </button>
            </form>
          </section>
        )}

        {tab === "profiles" && (
          <section className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,1fr)_420px]">
            <div className="min-h-0 overflow-auto">
              <table className="w-full min-w-[620px] border-collapse text-left text-[12px]">
                <thead className="sticky top-0 z-10 bg-white text-[11px] uppercase text-secondaryText">
                  <tr>
                    <th className="border-b border-borderSoft px-3 py-2">Perfil</th>
                    <th className="border-b border-borderSoft px-3 py-2">Peso max.</th>
                    <th className="border-b border-borderSoft px-3 py-2">Volumen max.</th>
                    <th className="border-b border-borderSoft px-3 py-2">Notas</th>
                  </tr>
                </thead>
                <tbody>
                  {profiles.map((row) => (
                    <tr
                      key={row.id}
                      onClick={() => {
                        setProfileId(row.id);
                        setProfileForm(profilePayload(row));
                      }}
                      className={`cursor-pointer border-b border-borderSoft transition hover:bg-softStart ${
                        profileId === row.id ? "bg-blue-50" : "bg-surface"
                      }`}
                    >
                      <td className="px-3 py-2 font-semibold text-night">{row.name}</td>
                      <td className="px-3 py-2 font-mono text-night">{formatNumber(row.max_weight_kg)} kg</td>
                      <td className="px-3 py-2 font-mono text-night">{formatNumber(row.max_volume_m3)} m3</td>
                      <td className="px-3 py-2 text-secondaryText">{row.notes || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <form
              className="grid content-start gap-3 border-t border-borderSoft bg-white p-3 lg:border-l lg:border-t-0"
              onSubmit={(event) => {
                event.preventDefault();
                saveProfileMutation.mutate();
              }}
            >
              <div>
                <h2 className="text-[13px] font-semibold text-night">{profileId ? "Editar perfil" : "Nuevo perfil"}</h2>
              </div>
              <Field label="Nombre">
                <input className={inputClass} value={profileForm.name} onChange={(event) => setProfileForm({ ...profileForm, name: event.target.value })} />
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Peso maximo kg">
                  <input className={inputClass} type="number" min="0" step="0.001" value={profileForm.max_weight_kg} onChange={(event) => setProfileForm({ ...profileForm, max_weight_kg: event.target.value })} />
                </Field>
                <Field label="Volumen maximo m3">
                  <input className={inputClass} type="number" min="0" step="0.001" value={profileForm.max_volume_m3} onChange={(event) => setProfileForm({ ...profileForm, max_volume_m3: event.target.value })} />
                </Field>
              </div>
              <Field label="Notas">
                <textarea
                  value={profileForm.notes}
                  onChange={(event) => setProfileForm({ ...profileForm, notes: event.target.value })}
                  className="min-h-24 rounded border border-borderSoft bg-white px-2 py-2 text-[12px] text-night outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
                />
              </Field>
              <button type="submit" disabled={busy} className="inline-flex min-h-10 items-center justify-center gap-2 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover disabled:bg-softStart disabled:text-secondaryText">
                <Save size={15} />
                Guardar perfil
              </button>
            </form>
          </section>
        )}
      </div>
    </div>
  );
}
