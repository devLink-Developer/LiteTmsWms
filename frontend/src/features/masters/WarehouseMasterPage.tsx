import { Building2, CheckCircle2, FilterX, MapPinned, Plus, RefreshCw, Save, Search, Warehouse } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  fetchWarehouseLocations,
  fetchWarehouseMasters,
  generateWarehouseLocations,
  saveWarehouseMaster,
  type WarehouseLocation,
  type WarehousePayload,
  type WarehouseRecord,
} from "../../api/logistics";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { notify } from "../../shared/components/toast";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";
import type { StatusTone } from "../../types/operations";

type WarehouseFilters = {
  search: string;
};

type WarehouseForm = WarehousePayload & {
  layoutZones: string;
  layoutAisles: string;
  layoutFloors: string;
  layoutLevels: string;
  layoutPositions: string;
};

const emptyFilters: WarehouseFilters = { search: "" };

function emptyForm(): WarehouseForm {
  return {
    warehouse_ref: "",
    name: "",
    warehouse_type: "shipping",
    branch_ref: "",
    store_ref: "",
    store_name: "",
    is_pickup_allowed: false,
    is_shipping_allowed: true,
    active: true,
    layoutZones: "",
    layoutAisles: "",
    layoutFloors: "1",
    layoutLevels: "",
    layoutPositions: "",
  };
}

function formFromWarehouse(row: WarehouseRecord): WarehouseForm {
  return {
    warehouse_ref: row.warehouse_ref || row.warehouse_code,
    name: row.name || row.warehouse_name || "",
    warehouse_type: row.warehouse_type || "shipping",
    branch_ref: row.branch_ref || "",
    store_ref: row.store_ref || row.store_code || "",
    store_name: row.store_name || "",
    is_pickup_allowed: !!row.is_pickup_allowed,
    is_shipping_allowed: row.is_shipping_allowed !== false,
    active: row.active !== false,
    layoutZones: "",
    layoutAisles: "",
    layoutFloors: "1",
    layoutLevels: "",
    layoutPositions: "",
  };
}

function payloadFromForm(form: WarehouseForm): WarehousePayload {
  const layout =
    form.layoutZones && form.layoutAisles && form.layoutLevels && form.layoutPositions
      ? {
          zones: form.layoutZones,
          aisles: form.layoutAisles,
          floors: form.layoutFloors || "1",
          levels: form.layoutLevels,
          positions: form.layoutPositions,
        }
      : undefined;
  return {
    warehouse_ref: form.warehouse_ref.trim().toUpperCase(),
    name: form.name.trim(),
    warehouse_type: (form.warehouse_type ?? "").trim(),
    branch_ref: (form.branch_ref ?? "").trim(),
    store_ref: (form.store_ref ?? "").trim(),
    store_name: (form.store_name ?? "").trim(),
    is_pickup_allowed: !!form.is_pickup_allowed,
    is_shipping_allowed: !!form.is_shipping_allowed,
    active: !!form.active,
    layout,
  };
}

function compact(value: string | undefined, fallback = "-") {
  return value?.trim() || fallback;
}

function authorizationTone(code: string, authorizedWarehouses: string[]): StatusTone {
  if (!authorizedWarehouses.length) return "neutral";
  return authorizedWarehouses.includes(code) ? "success" : "warning";
}

function buildKpis(rows: WarehouseRecord[], locations: WarehouseLocation[], authorizedWarehouses: string[]) {
  return [
    { label: "Almacenes", value: String(rows.length), hint: "locales", tone: rows.length ? "info" : "neutral" as StatusTone },
    { label: "Activos", value: String(rows.filter((row) => row.active !== false).length), hint: "operativos", tone: "success" as StatusTone },
    { label: "Ubicaciones", value: String(locations.length), hint: "seleccionado", tone: locations.length ? "info" : "neutral" as StatusTone },
    {
      label: "Scope",
      value: String(rows.filter((row) => authorizedWarehouses.includes(row.warehouse_ref)).length),
      hint: authorizedWarehouses.length ? "autorizados" : "sin permisos",
      tone: authorizedWarehouses.length ? "success" : "neutral" as StatusTone,
    },
  ];
}

export function WarehouseMasterPage() {
  const { warehouseRef, authorizedWarehouses } = useWorkspaceStore();
  const [filters, setFilters] = useState<WarehouseFilters>(emptyFilters);
  const [warehouses, setWarehouses] = useState<WarehouseRecord[]>([]);
  const [locations, setLocations] = useState<WarehouseLocation[]>([]);
  const [selectedRef, setSelectedRef] = useState("");
  const [form, setForm] = useState<WarehouseForm>(() => emptyForm());
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  async function loadWarehouses() {
    setLoading(true);
    try {
      const rows = await fetchWarehouseMasters({ query: filters.search, active: "", limit: 500 });
      setWarehouses(rows);
      const nextRef = selectedRef && rows.some((row) => row.warehouse_ref === selectedRef) ? selectedRef : rows[0]?.warehouse_ref ?? "";
      setSelectedRef(nextRef);
      if (nextRef) {
        const selected = rows.find((row) => row.warehouse_ref === nextRef);
        if (selected) setForm(formFromWarehouse(selected));
        setLocations(await fetchWarehouseLocations(nextRef));
      } else {
        setLocations([]);
      }
    } catch (apiError) {
      setWarehouses([]);
      setLocations([]);
      setSelectedRef("");
      notify({ message: apiError instanceof Error ? apiError.message : "Almacenes no cargados.", tone: "error" });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadWarehouses();
  }, [filters.search]);

  async function selectWarehouse(row: WarehouseRecord) {
    setSelectedRef(row.warehouse_ref);
    setForm(formFromWarehouse(row));
    try {
      setLocations(await fetchWarehouseLocations(row.warehouse_ref));
    } catch {
      setLocations([]);
    }
  }

  function updateForm<K extends keyof WarehouseForm>(key: K, value: WarehouseForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function newWarehouse() {
    setSelectedRef("");
    setForm(emptyForm());
    setLocations([]);
  }

  async function saveWarehouse() {
    const payload = payloadFromForm(form);
    if (!payload.warehouse_ref || !payload.name) {
      notify({ message: "Codigo y nombre son obligatorios.", tone: "error" });
      return;
    }
    setSaving(true);
    try {
      const saved = await saveWarehouseMaster(payload, selectedRef || undefined);
      setSelectedRef(saved.warehouse_ref);
      setForm(formFromWarehouse(saved));
      setLocations(await fetchWarehouseLocations(saved.warehouse_ref));
      notify({ message: `${saved.warehouse_ref} guardado.`, tone: "success" });
      await loadWarehouses();
    } catch (apiError) {
      notify({ message: apiError instanceof Error ? apiError.message : "Almacen no guardado.", tone: "error" });
    } finally {
      setSaving(false);
    }
  }

  async function generateLocations() {
    if (!selectedRef) return;
    setSaving(true);
    try {
      const generated = await generateWarehouseLocations(selectedRef, payloadFromForm(form).layout);
      setLocations(generated);
      notify({ message: `${generated.length} ubicaciones disponibles.`, tone: "success" });
    } catch (apiError) {
      notify({ message: apiError instanceof Error ? apiError.message : "Ubicaciones no generadas.", tone: "error" });
    } finally {
      setSaving(false);
    }
  }

  const selectedWarehouse = warehouses.find((row) => row.warehouse_ref === selectedRef);
  const kpis = useMemo(() => buildKpis(warehouses, locations, authorizedWarehouses), [authorizedWarehouses, locations, warehouses]);

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-2 overflow-hidden p-2 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section className="flex min-h-0 min-w-0 flex-col gap-2 overflow-hidden">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <h1 className="text-[18px] font-semibold text-night">Maestro de almacenes</h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={newWarehouse}
              className="inline-flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20"
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              Nuevo
            </button>
            <button
              type="button"
              onClick={() => void loadWarehouses()}
              disabled={loading}
              className="inline-flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
              Actualizar
            </button>
          </div>
        </header>

        <section className="grid shrink-0 grid-cols-2 gap-2 lg:grid-cols-4" aria-label="Indicadores de almacenes">
          {kpis.map((item) => (
            <div key={item.label} className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold uppercase text-secondaryText">{item.label}</span>
                <StatusBadge label={item.hint} tone={item.tone} />
              </div>
              <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{item.value}</div>
            </div>
          ))}
        </section>

        <section className="shrink-0 rounded border border-borderSoft bg-softMid p-2 shadow-panel" aria-label="Filtros de almacenes">
          <div className="grid gap-2 md:grid-cols-[minmax(260px,1fr)_auto_auto]">
            <label className="grid min-w-0 gap-1 text-[11px] font-semibold text-secondaryText">
              Buscar almacen
              <span className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-secondaryText" aria-hidden="true" />
                <input
                  value={filters.search}
                  onChange={(event) => setFilters({ search: event.target.value })}
                  className="h-8 w-full rounded border border-borderSoft bg-white pl-8 pr-2 text-[12px] font-medium text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                  placeholder="Codigo, nombre o sucursal"
                />
              </span>
            </label>
            <button
              type="button"
              onClick={() => setFilters(emptyFilters)}
              disabled={!filters.search}
              className="inline-flex min-h-8 items-end justify-center gap-2 self-end rounded border border-borderSoft bg-white px-3 pb-1.5 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
            >
              <FilterX className="h-4 w-4" aria-hidden="true" />
              Limpiar
            </button>
            <div className="self-end text-right text-[11px] font-semibold text-secondaryText">{filters.search ? "1 filtro activo" : "Sin filtros"}</div>
          </div>
        </section>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
            <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
              <Warehouse className="h-4 w-4 text-primaryHover" aria-hidden="true" />
              {loading ? "Cargando..." : `${warehouses.length} almacenes`}
            </div>
            <div className="text-[11px] text-secondaryText">Maestro local TMS/WMS</div>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full min-w-[900px] border-collapse text-left text-[12px]">
              <thead className="sticky top-0 z-10 bg-deep text-white">
                <tr>
                  <th className="w-[145px] px-3 py-2 font-semibold">Almacen</th>
                  <th className="px-3 py-2 font-semibold">Nombre</th>
                  <th className="w-[120px] px-3 py-2 font-semibold">Tipo</th>
                  <th className="w-[145px] px-3 py-2 font-semibold">Sucursal</th>
                  <th className="w-[120px] px-3 py-2 font-semibold">Estado</th>
                  <th className="w-[130px] px-3 py-2 font-semibold">Scope</th>
                </tr>
              </thead>
              <tbody>
                {warehouses.map((warehouse) => {
                  const selected = selectedWarehouse?.warehouse_ref === warehouse.warehouse_ref;
                  return (
                    <tr
                      key={warehouse.warehouse_ref}
                      onClick={() => void selectWarehouse(warehouse)}
                      className={`cursor-pointer border-b border-borderSoft hover:bg-softStart ${selected ? "bg-blue-50 outline outline-1 outline-primary/30" : "bg-white"}`}
                    >
                      <td className="whitespace-nowrap px-3 py-2 font-mono font-semibold text-night">{warehouse.warehouse_ref}</td>
                      <td className="px-3 py-2 text-night">{compact(warehouse.name || warehouse.warehouse_name)}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-secondaryText">{compact(warehouse.warehouse_type)}</td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-secondaryText">{compact(warehouse.store_ref || warehouse.store_code)}</td>
                      <td className="px-3 py-2">
                        <StatusBadge label={warehouse.active ? "activo" : "inactivo"} tone={warehouse.active ? "success" : "neutral"} />
                      </td>
                      <td className="px-3 py-2">
                        <StatusBadge
                          label={authorizedWarehouses.includes(warehouse.warehouse_ref) ? "autorizado" : "maestro"}
                          tone={authorizationTone(warehouse.warehouse_ref, authorizedWarehouses)}
                        />
                      </td>
                    </tr>
                  );
                })}
                {!warehouses.length && (
                  <tr>
                    <td colSpan={6} className="px-3 py-10 text-center text-[12px] text-secondaryText">
                      {loading ? "Cargando..." : "Sin almacenes."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <aside className="min-h-0 overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
        <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
            <Building2 className="h-4 w-4 text-primaryHover" aria-hidden="true" />
            {selectedRef ? "Editar almacen" : "Alta almacen"}
          </div>
          <StatusBadge label={form.warehouse_ref === warehouseRef ? "activo" : "local"} tone={form.warehouse_ref === warehouseRef ? "success" : "neutral"} />
        </div>
        <div className="grid max-h-full gap-3 overflow-auto p-3 text-[12px]">
          <section className="grid gap-2 border-b border-borderSoft pb-3">
            <div className="grid grid-cols-2 gap-2">
              <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
                Codigo
                <input
                  value={form.warehouse_ref}
                  disabled={!!selectedRef}
                  onChange={(event) => updateForm("warehouse_ref", event.target.value.toUpperCase())}
                  className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
                />
              </label>
              <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
                Tipo
                <input
                  value={form.warehouse_type}
                  onChange={(event) => updateForm("warehouse_type", event.target.value)}
                  className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                />
              </label>
            </div>
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Nombre
              <input
                value={form.name}
                onChange={(event) => updateForm("name", event.target.value)}
                className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
              />
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
                Sucursal
                <input
                  value={form.store_ref}
                  onChange={(event) => updateForm("store_ref", event.target.value)}
                  className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                />
              </label>
              <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
                Rama
                <input
                  value={form.branch_ref}
                  onChange={(event) => updateForm("branch_ref", event.target.value)}
                  className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                />
              </label>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <label className="flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-2 text-[12px] font-semibold text-night">
                <input type="checkbox" checked={!!form.active} onChange={(event) => updateForm("active", event.target.checked)} />
                Activo
              </label>
              <label className="flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-2 text-[12px] font-semibold text-night">
                <input type="checkbox" checked={!!form.is_pickup_allowed} onChange={(event) => updateForm("is_pickup_allowed", event.target.checked)} />
                Retiro
              </label>
              <label className="flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-2 text-[12px] font-semibold text-night">
                <input type="checkbox" checked={!!form.is_shipping_allowed} onChange={(event) => updateForm("is_shipping_allowed", event.target.checked)} />
                Envio
              </label>
            </div>
          </section>

          <section className="grid gap-2 border-b border-borderSoft pb-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
                <MapPinned className="h-4 w-4 text-primaryHover" aria-hidden="true" />
                Layout disponible
              </div>
              <StatusBadge label="opcional" tone="neutral" />
            </div>
            <div className="grid grid-cols-5 gap-1">
              {[
                ["layoutZones", "Zonas"],
                ["layoutAisles", "Pas."],
                ["layoutFloors", "Pisos"],
                ["layoutLevels", "Niv."],
                ["layoutPositions", "Pos."],
              ].map(([key, label]) => (
                <label key={key} className="grid gap-1 text-[10px] font-semibold text-secondaryText">
                  {label}
                  <input
                    value={String(form[key as keyof WarehouseForm] ?? "")}
                    onChange={(event) => updateForm(key as keyof WarehouseForm, event.target.value as never)}
                    inputMode="numeric"
                    className="h-8 rounded border border-borderSoft bg-white px-1 text-center font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                  />
                </label>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => void saveWarehouse()}
                disabled={saving}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded bg-primary px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:bg-slate-300"
              >
                <Save className="h-4 w-4" aria-hidden="true" />
                {saving ? "Guardando..." : "Guardar"}
              </button>
              <button
                type="button"
                onClick={() => void generateLocations()}
                disabled={saving || !selectedRef}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
              >
                <Plus className="h-4 w-4" aria-hidden="true" />
                Ubicaciones
              </button>
            </div>
          </section>

          <section className="grid gap-2">
            <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
              <CheckCircle2 className="h-4 w-4 text-primaryHover" aria-hidden="true" />
              Ubicaciones generadas
            </div>
            <div className="max-h-64 overflow-auto rounded border border-borderSoft">
              <table className="w-full border-collapse text-left text-[12px]">
                <thead className="bg-softMid text-secondaryText">
                  <tr>
                    <th className="px-2 py-2 font-semibold">Codigo</th>
                    <th className="px-2 py-2 font-semibold">Uso</th>
                  </tr>
                </thead>
                <tbody>
                  {locations.map((location) => (
                    <tr key={location.location_ref} className="border-t border-borderSoft bg-white">
                      <td className="px-2 py-2 font-mono text-night">{location.location_ref}</td>
                      <td className="px-2 py-2">
                        <StatusBadge label={location.purpose} tone={location.allows_scrap ? "danger" : location.is_dispatchable ? "success" : "neutral"} />
                      </td>
                    </tr>
                  ))}
                  {!locations.length ? (
                    <tr>
                      <td colSpan={2} className="px-2 py-8 text-center text-secondaryText">
                        Sin ubicaciones.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}
