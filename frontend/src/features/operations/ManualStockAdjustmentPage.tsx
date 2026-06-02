import { ArrowDownCircle, ArrowUpCircle, ClipboardList, FilterX, MapPin, PackageSearch, RefreshCw, Search, Send, Warehouse } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  createManualStockAdjustment,
  fetchInventoryMaterials,
  fetchInventoryStockReport,
  fetchManualStockAdjustments,
  type InventoryLedgerEntry,
  type InventoryMaterialOption,
  type InventoryStockReportRow,
} from "../../api/inventory";
import { newIdempotencyKey } from "../../api/client";
import { fetchWarehouseLocations, type WarehouseLocation } from "../../api/logistics";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { notify } from "../../shared/components/toast";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";

type AdjustmentMode = "increase" | "decrease";

type FormState = {
  itemRef: string;
  locationRef: string;
  lotRef: string;
  quantity: string;
  uom: string;
  reason: string;
};

const DEFAULT_REASON_BY_MODE: Record<AdjustmentMode, string> = {
  increase: "Alta manual",
  decrease: "Baja manual",
};

const emptyForm: FormState = {
  itemRef: "",
  locationRef: "",
  lotRef: "",
  quantity: "",
  uom: "UN",
  reason: DEFAULT_REASON_BY_MODE.increase,
};

function asNumber(value: string | number | undefined) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatNumber(value: string | number | undefined) {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 3 }).format(asNumber(value));
}

function trim(value: string) {
  return value.trim();
}

function reasonForMode(currentReason: string, nextMode: AdjustmentMode) {
  const reason = currentReason.trim();
  if (!reason || reason === DEFAULT_REASON_BY_MODE.increase || reason === DEFAULT_REASON_BY_MODE.decrease) {
    return DEFAULT_REASON_BY_MODE[nextMode];
  }
  return currentReason;
}

function rowLocation(row: InventoryStockReportRow) {
  return row.warehouse_location_ref || row.location_ref || "";
}

function rowSourceLocation(row: InventoryStockReportRow) {
  return row.location_ref || "";
}

function packedQty(row: InventoryStockReportRow) {
  return asNumber(row.quantities?.packed);
}

function locationLabel(location: WarehouseLocation) {
  return location.location_name || location.name || location.location_ref;
}

function isDestinationLocation(location: WarehouseLocation) {
  const purpose = String(location.purpose || "").toLowerCase();
  return Boolean(location.active && purpose === "available");
}

function adjustmentQty(row: InventoryLedgerEntry) {
  return `${formatNumber(row.quantity)} ${row.uom}`.trim();
}

function materialName(row: InventoryMaterialOption) {
  return row.long_name || row.name || row.item_ref;
}

function materialUom(row: InventoryMaterialOption) {
  return row.uom_code || row.uom || "UN";
}

export function ManualStockAdjustmentPage() {
  const { warehouseRef, authorizedWarehouses } = useWorkspaceStore();
  const activeWarehouse = warehouseRef || authorizedWarehouses[0] || "";
  const [mode, setMode] = useState<AdjustmentMode>("increase");
  const [form, setForm] = useState<FormState>(emptyForm);
  const [locations, setLocations] = useState<WarehouseLocation[]>([]);
  const [stockRows, setStockRows] = useState<InventoryStockReportRow[]>([]);
  const [materials, setMaterials] = useState<InventoryMaterialOption[]>([]);
  const [adjustments, setAdjustments] = useState<InventoryLedgerEntry[]>([]);
  const [selectedLocationRef, setSelectedLocationRef] = useState("");
  const [selectedStockId, setSelectedStockId] = useState("");
  const [selectedMaterialRef, setSelectedMaterialRef] = useState("");
  const [search, setSearch] = useState("");
  const [locationSearch, setLocationSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [materialLoading, setMaterialLoading] = useState(false);
  const [posting, setPosting] = useState(false);
  const submitKeyRef = useRef(newIdempotencyKey());
  const stockRequestSeqRef = useRef(0);
  const materialRequestSeqRef = useRef(0);

  const destinationLocations = useMemo(() => locations.filter(isDestinationLocation), [locations]);
  const originRows = useMemo(() => stockRows.filter((row) => row.warehouse_ref === activeWarehouse && packedQty(row) > 0), [activeWarehouse, stockRows]);

  const visibleLocations = useMemo(() => {
    const needle = locationSearch.trim().toLowerCase();
    if (!needle) return destinationLocations;
    return destinationLocations.filter((location) =>
      [location.location_ref, locationLabel(location), location.purpose, location.zone_ref, location.aisle]
        .some((value) => (value ?? "").toLowerCase().includes(needle)),
    );
  }, [destinationLocations, locationSearch]);

  const visibleOrigins = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return originRows;
    return originRows.filter((row) =>
      [row.item_ref, row.item_name, rowLocation(row), row.lot_ref, row.uom].some((value) => (value ?? "").toLowerCase().includes(needle)),
    );
  }, [originRows, search]);

  const selectedOrigin = originRows.find((row) => row.id === selectedStockId);
  const matchingOrigin = originRows.find(
    (row) =>
      row.item_ref === trim(form.itemRef) &&
      rowSourceLocation(row) === trim(form.locationRef) &&
      (row.lot_ref || "") === trim(form.lotRef) &&
      row.uom === (trim(form.uom) || "UN"),
  );
  const availableForDecrease = selectedOrigin ? packedQty(selectedOrigin) : matchingOrigin ? packedQty(matchingOrigin) : 0;

  async function loadMaterials(materialSearch = search) {
    if (!materialSearch.trim()) {
      setMaterials([]);
      setSelectedMaterialRef("");
      return;
    }
    const requestSeq = materialRequestSeqRef.current + 1;
    materialRequestSeqRef.current = requestSeq;
    setMaterialLoading(true);
    try {
      const payload = await fetchInventoryMaterials({ query: materialSearch.trim(), limit: 50 });
      if (materialRequestSeqRef.current !== requestSeq) {
        return;
      }
      const nextMaterials = payload.results ?? [];
      setMaterials(nextMaterials);
      setSelectedMaterialRef((current) => (current && nextMaterials.some((row) => row.item_ref === current) ? current : nextMaterials[0]?.item_ref ?? ""));
    } catch (apiError) {
      setMaterials([]);
      setSelectedMaterialRef("");
      notify({ message: apiError instanceof Error ? apiError.message : "Articulos no cargados.", tone: "error" });
    } finally {
      if (materialRequestSeqRef.current === requestSeq) {
        setMaterialLoading(false);
      }
    }
  }

  async function loadStockRows(stockSearch = search) {
    if (!activeWarehouse) {
      setStockRows([]);
      setSelectedStockId("");
      return;
    }
    const requestSeq = stockRequestSeqRef.current + 1;
    stockRequestSeqRef.current = requestSeq;
    const stockPayload = await fetchInventoryStockReport({
      warehouse: activeWarehouse,
      state: "packed",
      search: stockSearch.trim(),
      locationScope: "available",
      limit: 500,
    });
    if (stockRequestSeqRef.current !== requestSeq) {
      return;
    }
    const nextOrigins = (stockPayload.results ?? []).filter((row) => row.warehouse_ref === activeWarehouse && packedQty(row) > 0);
    setStockRows(stockPayload.results ?? []);
    setSelectedStockId((current) => (current && nextOrigins.some((row) => row.id === current) ? current : nextOrigins[0]?.id ?? ""));
  }

  async function loadData(stockSearch = search) {
    if (!activeWarehouse) {
      setLocations([]);
      setStockRows([]);
      setAdjustments([]);
      return;
    }
    setLoading(true);
    try {
      const stockRequestSeq = stockRequestSeqRef.current + 1;
      stockRequestSeqRef.current = stockRequestSeq;
      const [locationPayload, stockPayload, adjustmentPayload] = await Promise.all([
        fetchWarehouseLocations(activeWarehouse),
        fetchInventoryStockReport({
          warehouse: activeWarehouse,
          state: "packed",
          search: stockSearch.trim(),
          locationScope: "available",
          limit: 500,
        }),
        fetchManualStockAdjustments({ warehouse: activeWarehouse, limit: 100 }),
      ]);
      const nextLocations = locationPayload.filter(isDestinationLocation);
      const nextOrigins = (stockPayload.results ?? []).filter((row) => row.warehouse_ref === activeWarehouse && packedQty(row) > 0);
      setLocations(locationPayload);
      setAdjustments(adjustmentPayload.results ?? []);
      if (stockRequestSeqRef.current === stockRequestSeq) {
        setStockRows(stockPayload.results ?? []);
        setSelectedStockId((current) => (current && nextOrigins.some((row) => row.id === current) ? current : nextOrigins[0]?.id ?? ""));
      }
      setSelectedLocationRef((current) => (current && nextLocations.some((location) => location.location_ref === current) ? current : nextLocations[0]?.location_ref ?? ""));
      if (!form.locationRef && nextLocations[0]?.location_ref) {
        setForm((current) => ({ ...current, locationRef: nextLocations[0].location_ref }));
      }
    } catch (apiError) {
      setLocations([]);
      setStockRows([]);
      setAdjustments([]);
      notify({ message: apiError instanceof Error ? apiError.message : "Ajustes no cargados.", tone: "error" });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, [activeWarehouse]);

  useEffect(() => {
    if (!activeWarehouse || mode !== "decrease") {
      return;
    }
    const timer = window.setTimeout(() => {
      void loadStockRows(search);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [activeWarehouse, mode, search]);

  useEffect(() => {
    if (mode !== "increase") {
      return;
    }
    const timer = window.setTimeout(() => {
      void loadMaterials(search);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [mode, search]);

  function updateForm(key: keyof FormState, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function selectDestination(location: WarehouseLocation) {
    setSelectedLocationRef(location.location_ref);
    setForm((current) => ({ ...current, locationRef: location.location_ref }));
  }

  function selectMaterial(row: InventoryMaterialOption) {
    setSelectedMaterialRef(row.item_ref);
    setForm((current) => ({
      ...current,
      itemRef: row.item_ref,
      uom: materialUom(row),
    }));
  }

  function selectOrigin(row: InventoryStockReportRow) {
    setSelectedStockId(row.id);
    setForm((current) => ({
      ...current,
      itemRef: row.item_ref,
      locationRef: rowSourceLocation(row),
      lotRef: row.lot_ref || "",
      uom: row.uom || "UN",
    }));
  }

  function switchMode(nextMode: AdjustmentMode) {
    setMode(nextMode);
    setSearch("");
    setLocationSearch("");
    if (nextMode === "increase") {
      const location = destinationLocations.find((entry) => entry.location_ref === selectedLocationRef) ?? destinationLocations[0];
      setForm((current) => ({ ...current, locationRef: location?.location_ref ?? current.locationRef, reason: reasonForMode(current.reason, nextMode) }));
    } else {
      const origin = selectedOrigin ?? originRows[0];
      if (origin) {
        selectOrigin(origin);
      }
      setForm((current) => ({ ...current, reason: reasonForMode(current.reason, nextMode) }));
    }
  }

  async function submitAdjustment() {
    const quantity = asNumber(form.quantity);
    const itemRef = trim(form.itemRef);
    const locationRef = trim(form.locationRef);
    const reason = trim(form.reason);
    if (!activeWarehouse || !itemRef || !locationRef) {
      notify({ message: "Almacen, articulo y ubicacion son requeridos.", tone: "error" });
      return;
    }
    if (quantity <= 0) {
      notify({ message: "Cantidad invalida.", tone: "error" });
      return;
    }
    if (!reason) {
      notify({ message: "Motivo requerido.", tone: "error" });
      return;
    }
    if (mode === "decrease" && quantity > availableForDecrease) {
      notify({ message: "Stock insuficiente en la posicion origen.", tone: "error" });
      return;
    }
    setPosting(true);
    try {
      const result = await createManualStockAdjustment(
        {
          warehouse_ref: activeWarehouse,
          direction: mode,
          item_ref: itemRef,
          location_ref: locationRef,
          lot_ref: trim(form.lotRef),
          quantity: trim(form.quantity),
          uom: trim(form.uom) || "UN",
          reason,
        },
        submitKeyRef.current,
      );
      notify({ message: `${result.document_ref} posteado.`, tone: "success" });
      submitKeyRef.current = newIdempotencyKey();
      setForm((current) => ({ ...emptyForm, locationRef: mode === "increase" ? current.locationRef : "", reason: DEFAULT_REASON_BY_MODE[mode] }));
      await loadData();
    } catch (apiError) {
      notify({ message: apiError instanceof Error ? apiError.message : "Ajuste no posteado.", tone: "error" });
    } finally {
      setPosting(false);
    }
  }

  const totalAvailable = originRows.reduce((total, row) => total + packedQty(row), 0);

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-2 overflow-hidden p-2 xl:grid-cols-[minmax(0,1fr)_360px]">
      <section className="flex min-h-0 min-w-0 flex-col gap-2 overflow-hidden">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <h1 className="text-[18px] font-semibold text-night">Alta y baja de articulos</h1>
          </div>
          <button
            type="button"
            onClick={() => void loadData()}
            disabled={loading}
            className="inline-flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-softStart"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
            Actualizar
          </button>
        </header>

        <section className="grid shrink-0 grid-cols-2 gap-2 lg:grid-cols-4" aria-label="Indicadores de ajuste manual">
          <div className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase text-secondaryText">Almacen</span>
              <StatusBadge label="activo" tone={activeWarehouse ? "success" : "danger"} />
            </div>
            <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{activeWarehouse || "-"}</div>
          </div>
          <div className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase text-secondaryText">Destinos alta</span>
              <StatusBadge label="ubicaciones" tone="info" />
            </div>
            <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{destinationLocations.length}</div>
          </div>
          <div className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase text-secondaryText">Origenes baja</span>
              <StatusBadge label="packed" tone={originRows.length ? "success" : "neutral"} />
            </div>
            <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{originRows.length}</div>
          </div>
          <div className="rounded border border-borderSoft bg-surface px-3 py-2 shadow-panel">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase text-secondaryText">Disponible baja</span>
              <StatusBadge label="cantidad" tone={totalAvailable ? "success" : "neutral"} />
            </div>
            <div className="mt-1 font-mono text-[20px] font-semibold leading-6 text-night">{formatNumber(totalAvailable)}</div>
          </div>
        </section>

        <section className="shrink-0 rounded border border-borderSoft bg-softMid p-2 shadow-panel" aria-label="Filtros de ajuste manual">
          <div className={`grid gap-2 ${mode === "increase" ? "md:grid-cols-[auto_minmax(220px,1fr)_minmax(220px,1fr)_auto]" : "md:grid-cols-[auto_minmax(260px,1fr)_auto]"}`}>
            <div className="inline-grid h-8 grid-cols-2 rounded border border-borderSoft bg-white p-0.5">
              <button
                type="button"
                onClick={() => switchMode("increase")}
                className={`inline-flex items-center justify-center gap-2 rounded px-3 text-[12px] font-semibold ${mode === "increase" ? "bg-primary text-white" : "text-night hover:bg-softStart"}`}
              >
                <ArrowUpCircle className="h-4 w-4" aria-hidden="true" />
                Alta
              </button>
              <button
                type="button"
                onClick={() => switchMode("decrease")}
                className={`inline-flex items-center justify-center gap-2 rounded px-3 text-[12px] font-semibold ${mode === "decrease" ? "bg-primary text-white" : "text-night hover:bg-softStart"}`}
              >
                <ArrowDownCircle className="h-4 w-4" aria-hidden="true" />
                Baja
              </button>
            </div>
            {mode === "increase" ? (
              <>
                <label className="grid min-w-0 gap-1 text-[11px] font-semibold text-secondaryText">
                  Buscar articulo
                  <span className="relative">
                    <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-secondaryText" aria-hidden="true" />
                    <input
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      className="h-8 w-full rounded border border-borderSoft bg-white pl-8 pr-2 text-[12px] font-medium text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                      placeholder="Codigo, nombre o categoria"
                    />
                  </span>
                </label>
                <label className="grid min-w-0 gap-1 text-[11px] font-semibold text-secondaryText">
                  Buscar posicion
                  <span className="relative">
                    <MapPin className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-secondaryText" aria-hidden="true" />
                    <input
                      value={locationSearch}
                      onChange={(event) => setLocationSearch(event.target.value)}
                      className="h-8 w-full rounded border border-borderSoft bg-white pl-8 pr-2 text-[12px] font-medium text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                      placeholder="Ubicacion destino"
                    />
                  </span>
                </label>
              </>
            ) : (
              <label className="grid min-w-0 gap-1 text-[11px] font-semibold text-secondaryText">
                Buscar
                <span className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-secondaryText" aria-hidden="true" />
                  <input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    className="h-8 w-full rounded border border-borderSoft bg-white pl-8 pr-2 text-[12px] font-medium text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                    placeholder="Articulo, ubicacion o lote"
                  />
                </span>
              </label>
            )}
            <button
              type="button"
              onClick={() => {
                setSearch("");
                setLocationSearch("");
              }}
              className="inline-flex min-h-8 items-end justify-center gap-2 self-end rounded border border-borderSoft bg-white px-3 pb-1.5 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20"
            >
              <FilterX className="h-4 w-4" aria-hidden="true" />
              Limpiar
            </button>
          </div>
        </section>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
            <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
              {mode === "increase" ? <MapPin className="h-4 w-4 text-primaryHover" aria-hidden="true" /> : <PackageSearch className="h-4 w-4 text-primaryHover" aria-hidden="true" />}
              {loading || materialLoading
                ? "Cargando..."
                : mode === "increase"
                  ? `${materials.length} articulos / ${visibleLocations.length} posiciones destino`
                  : `${visibleOrigins.length} posiciones origen`}
            </div>
            <div className="text-[11px] text-secondaryText">{mode === "increase" ? "DESTINO" : "ORIGEN PACKED"}</div>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {mode === "increase" ? (
              <div className="grid min-h-full min-w-[980px] grid-cols-[minmax(0,1fr)_minmax(360px,0.85fr)]">
                <section className="min-h-0 overflow-auto border-r border-borderSoft">
                  <div className="sticky top-0 z-10 flex min-h-9 items-center justify-between bg-deep px-3 text-white">
                    <span className="text-[12px] font-semibold">Articulos</span>
                    <span className="text-[11px] text-white/70">{search.trim() ? `${materials.length} encontrados` : "buscar por codigo"}</span>
                  </div>
                  <table className="w-full min-w-[540px] border-collapse text-left text-[12px]">
                    <thead className="sticky top-9 z-10 bg-softMid text-secondaryText">
                      <tr>
                        <th className="w-[130px] px-3 py-2 font-semibold">Articulo</th>
                        <th className="px-3 py-2 font-semibold">Descripcion</th>
                        <th className="w-[80px] px-3 py-2 font-semibold">UOM</th>
                      </tr>
                    </thead>
                    <tbody>
                      {materials.map((material) => {
                        const selected = material.item_ref === selectedMaterialRef || material.item_ref === form.itemRef;
                        return (
                          <tr
                            key={material.item_ref}
                            onClick={() => selectMaterial(material)}
                            className={`cursor-pointer border-b border-borderSoft hover:bg-softStart ${selected ? "bg-blue-50 outline outline-1 outline-primary/30" : "bg-white"}`}
                          >
                            <td className="whitespace-nowrap px-3 py-2 font-mono font-semibold text-night">{material.item_ref}</td>
                            <td className="px-3 py-2">
                              <div className="font-medium text-night">{materialName(material)}</div>
                              <div className="text-[11px] text-secondaryText">{material.category || material.coverage_group || "-"}</div>
                            </td>
                            <td className="px-3 py-2 font-mono text-secondaryText">{materialUom(material)}</td>
                          </tr>
                        );
                      })}
                      {!materials.length ? (
                        <tr>
                          <td colSpan={3} className="px-3 py-10 text-center text-[12px] text-secondaryText">
                            {materialLoading ? "Cargando..." : search.trim() ? "Sin articulos para ese criterio." : "Ingrese un criterio para buscar articulos."}
                          </td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </section>
                <section className="min-h-0 overflow-auto">
                  <div className="sticky top-0 z-10 flex min-h-9 items-center justify-between bg-deep px-3 text-white">
                    <span className="text-[12px] font-semibold">Posiciones destino</span>
                    <span className="text-[11px] text-white/70">{visibleLocations.length} disponibles</span>
                  </div>
                  <table className="w-full min-w-[460px] border-collapse text-left text-[12px]">
                    <thead className="sticky top-9 z-10 bg-softMid text-secondaryText">
                      <tr>
                        <th className="w-[150px] px-3 py-2 font-semibold">Ubicacion</th>
                        <th className="px-3 py-2 font-semibold">Nombre</th>
                        <th className="w-[90px] px-3 py-2 font-semibold">Pick</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleLocations.map((location) => {
                        const selected = location.location_ref === form.locationRef;
                        return (
                          <tr
                            key={location.id || location.location_ref}
                            onClick={() => selectDestination(location)}
                            className={`cursor-pointer border-b border-borderSoft hover:bg-softStart ${selected ? "bg-blue-50 outline outline-1 outline-primary/30" : "bg-white"}`}
                          >
                            <td className="whitespace-nowrap px-3 py-2 font-mono font-semibold text-night">{location.location_ref}</td>
                            <td className="px-3 py-2">
                              <div className="font-medium text-night">{locationLabel(location)}</div>
                              <div className="text-[11px] text-secondaryText">{location.purpose || "-"}</div>
                            </td>
                            <td className="px-3 py-2">
                              <StatusBadge label={location.is_pickable ? "si" : "no"} tone={location.is_pickable ? "success" : "neutral"} />
                            </td>
                          </tr>
                        );
                      })}
                      {!visibleLocations.length ? (
                        <tr>
                          <td colSpan={3} className="px-3 py-10 text-center text-[12px] text-secondaryText">
                            {loading ? "Cargando..." : "Sin posiciones destino."}
                          </td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </section>
              </div>
            ) : (
              <table className="w-full min-w-[820px] border-collapse text-left text-[12px]">
                <thead className="sticky top-0 z-10 bg-deep text-white">
                  <tr>
                    <th className="w-[150px] px-3 py-2 font-semibold">Ubicacion</th>
                    <th className="px-3 py-2 font-semibold">Producto</th>
                    <th className="w-[110px] px-3 py-2 font-semibold">Lote</th>
                    <th className="w-[120px] px-3 py-2 text-right font-semibold">Disponible</th>
                    <th className="w-[70px] px-3 py-2 font-semibold">UOM</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleOrigins.map((row) => {
                    const selected = row.id === selectedStockId;
                    return (
                      <tr
                        key={row.id}
                        onClick={() => selectOrigin(row)}
                        className={`cursor-pointer border-b border-borderSoft hover:bg-softStart ${selected ? "bg-orange-50 outline outline-1 outline-orange-300" : "bg-white"}`}
                      >
                        <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{rowLocation(row) || "-"}</td>
                        <td className="px-3 py-2">
                          <div className="font-mono font-semibold text-night">{row.item_ref}</div>
                          {row.item_name ? <div className="max-w-[340px] truncate text-[11px] text-secondaryText">{row.item_name}</div> : null}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 font-mono text-secondaryText">{row.lot_ref || "-"}</td>
                        <td className="px-3 py-2 text-right font-mono font-semibold text-night">{formatNumber(packedQty(row))}</td>
                        <td className="px-3 py-2 font-mono text-secondaryText">{row.uom}</td>
                      </tr>
                    );
                  })}
                  {!visibleOrigins.length ? (
                    <tr>
                      <td colSpan={5} className="px-3 py-10 text-center text-[12px] text-secondaryText">
                        {loading ? "Cargando..." : "Sin posiciones origen con stock disponible para ese criterio."}
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </section>

      <aside className="min-h-0 overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
        <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
            <ClipboardList className="h-4 w-4 text-primaryHover" aria-hidden="true" />
            Registrar ajuste
          </div>
          <StatusBadge label={mode === "increase" ? "alta" : "baja"} tone={mode === "increase" ? "success" : "danger"} />
        </div>
        <div className="flex h-full min-h-0 flex-col overflow-auto p-3">
          <section className="grid gap-2 border-b border-borderSoft pb-3 text-[12px]">
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded border border-borderSoft bg-softMid px-2 py-2">
                <div className="flex items-center gap-2 text-[11px] font-semibold text-secondaryText">
                  <Warehouse className="h-4 w-4" aria-hidden="true" />
                  Almacen
                </div>
                <div className="mt-1 font-mono font-semibold text-night">{activeWarehouse || "-"}</div>
              </div>
              <div className="rounded border border-borderSoft bg-softMid px-2 py-2">
                <div className="text-[11px] font-semibold text-secondaryText">{mode === "increase" ? "Destino" : "Disponible"}</div>
                <div className="mt-1 font-mono font-semibold text-night">
                  {mode === "increase" ? form.locationRef || "-" : `${formatNumber(availableForDecrease)} ${form.uom || "UN"}`}
                </div>
              </div>
            </div>
          </section>

          <section className="grid gap-3 border-b border-borderSoft py-3">
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Articulo
              <input
                value={form.itemRef}
                onChange={(event) => updateForm("itemRef", event.target.value)}
                className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                placeholder="100100"
              />
            </label>
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Ubicacion
              <input
                value={form.locationRef}
                onChange={(event) => updateForm("locationRef", event.target.value)}
                className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                placeholder={mode === "increase" ? "Destino" : "Origen"}
                list={mode === "increase" ? "manual-adjustment-destinations" : undefined}
              />
              <datalist id="manual-adjustment-destinations">
                {destinationLocations.map((location) => (
                  <option key={location.location_ref} value={location.location_ref}>
                    {locationLabel(location)}
                  </option>
                ))}
              </datalist>
            </label>
            <div className="grid grid-cols-[minmax(0,1fr)_96px] gap-2">
              <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
                Lote
                <input
                  value={form.lotRef}
                  onChange={(event) => updateForm("lotRef", event.target.value)}
                  className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                  placeholder="-"
                />
              </label>
              <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
                UOM
                <input
                  value={form.uom}
                  onChange={(event) => updateForm("uom", event.target.value)}
                  className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                  placeholder="UN"
                />
              </label>
            </div>
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Cantidad
              <input
                value={form.quantity}
                onChange={(event) => updateForm("quantity", event.target.value)}
                inputMode="decimal"
                className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                placeholder="0"
              />
            </label>
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Motivo
              <textarea
                value={form.reason}
                onChange={(event) => updateForm("reason", event.target.value)}
                className="min-h-24 rounded border border-borderSoft bg-white px-2 py-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                placeholder={mode === "increase" ? "Alta manual" : "Baja manual"}
              />
            </label>
            <button
              type="button"
              onClick={() => void submitAdjustment()}
              disabled={posting || !activeWarehouse}
              className={`inline-flex min-h-10 items-center justify-center gap-2 rounded px-3 text-[12px] font-semibold text-white transition focus:outline-none focus:ring-2 disabled:bg-slate-300 ${
                mode === "increase" ? "bg-primary hover:bg-primaryHover focus:ring-primary/30" : "bg-red-600 hover:bg-red-700 focus:ring-red-500/30"
              }`}
            >
              <Send className="h-4 w-4" aria-hidden="true" />
              {posting ? "Posteando..." : mode === "increase" ? "Confirmar alta" : "Confirmar baja"}
            </button>
          </section>

          <section className="min-h-0 py-3">
            <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold text-night">
              <PackageSearch className="h-4 w-4 text-primaryHover" aria-hidden="true" />
              Historial reciente
            </div>
            <div className="grid gap-2">
              {adjustments.slice(0, 8).map((row) => (
                <div key={row.id} className="rounded border border-borderSoft bg-white px-2 py-2 text-[12px]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono font-semibold text-night">{row.document_ref}</span>
                    <StatusBadge label={row.direction === "increase" ? "alta" : "baja"} tone={row.direction === "increase" ? "success" : "danger"} />
                  </div>
                  <div className="mt-1 font-mono text-[11px] text-secondaryText">
                    {row.item_ref} / {row.location_ref || "-"} / {adjustmentQty(row)}
                  </div>
                  {row.reason ? <div className="mt-1 text-secondaryText">{row.reason}</div> : null}
                </div>
              ))}
              {!adjustments.length ? (
                <div className="rounded border border-borderSoft bg-softMid px-3 py-2 text-[12px] text-secondaryText">Sin ajustes registrados.</div>
              ) : null}
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}
