import { AlertTriangle, Calculator, CheckCircle2, FilterX, RefreshCw, Ruler, Scissors, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  executeSheetCutting,
  fetchSheetCuttingOptions,
  validateSheetCuttingStock,
  type SheetCuttingExecution,
  type SheetCuttingLengthOption,
  type SheetCuttingOptions,
  type SheetCuttingStockValidation,
} from "../../api/logistics";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { notify } from "../../shared/components/toast";
import { useWorkspaceStore } from "../../stores/useWorkspaceStore";

const emptyOptions: SheetCuttingOptions = {
  unit: "cm",
  categories: [],
  materials: [],
  length_options: [],
};

function asNumber(value: string | number | undefined) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function asPositiveInteger(value: string | number | undefined) {
  const parsed = Math.trunc(asNumber(value));
  return parsed > 0 ? parsed : 0;
}

function formatNumber(value: string | number | undefined) {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 }).format(asNumber(value));
}

function formatMeters(value: string | number | undefined) {
  return `${formatNumber(value)} m`;
}

function formatCm(value: string | number | undefined) {
  return `${formatNumber(value)} cm`;
}

function lengthKey(length: string | number) {
  return String(length);
}

function branchAsStore(branchRef: string) {
  const value = branchRef.trim();
  if (!value || value === "sin-sucursal" || value.toLowerCase().includes("cargando")) return "";
  return value;
}

export function SheetCuttingPage() {
  const { branchRef } = useWorkspaceStore();
  const [store, setStore] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [sourceLengthCm, setSourceLengthCm] = useState("");
  const [sourceItemRef, setSourceItemRef] = useState("");
  const [sourceQuantity, setSourceQuantity] = useState("1");
  const [cutQuantities, setCutQuantities] = useState<Record<string, string>>({});
  const [options, setOptions] = useState<SheetCuttingOptions>(emptyOptions);
  const [validation, setValidation] = useState<SheetCuttingStockValidation | null>(null);
  const [validationError, setValidationError] = useState("");
  const [execution, setExecution] = useState<SheetCuttingExecution | null>(null);
  const [loading, setLoading] = useState(false);
  const [validating, setValidating] = useState(false);
  const [executing, setExecuting] = useState(false);

  useEffect(() => {
    const detectedStore = branchAsStore(branchRef);
    if (!store && detectedStore) {
      setStore(detectedStore);
    }
  }, [branchRef, store]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const timer = window.setTimeout(() => {
      fetchSheetCuttingOptions({ store, category, query, limit: 500 })
        .then((payload) => {
          if (cancelled) return;
          setOptions(payload);
          const categoryExists = payload.categories.some((row) => row.category === category);
          if ((!category || !categoryExists) && payload.categories[0]) {
            setCategory(payload.categories[0].category);
          }
        })
        .catch((apiError: unknown) => {
          if (cancelled) return;
          setOptions(emptyOptions);
          const message = apiError instanceof Error ? apiError.message : "Catalogo de chapas no cargado.";
          notify({ message, tone: "error" });
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, query.trim() ? 250 : 0);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [category, query, store]);

  useEffect(() => {
    setCutQuantities({});
    setValidation(null);
    setValidationError("");
    setExecution(null);
  }, [category, sourceLengthCm, sourceQuantity]);

  useEffect(() => {
    if (!options.length_options.length) {
      setSourceLengthCm("");
      return;
    }
    const currentExists = options.length_options.some((row) => String(row.length_cm) === String(sourceLengthCm));
    if (!currentExists) {
      const largest = [...options.length_options].sort((a, b) => b.length_cm - a.length_cm)[0];
      setSourceLengthCm(String(largest.length_cm));
    }
  }, [options.length_options, sourceLengthCm]);

  const selectedSourceLength = asNumber(sourceLengthCm);
  const sourceMaterialOptions = useMemo(() => {
    return options.materials
      .filter((row) => String(row.length_cm) === String(sourceLengthCm))
      .sort((a, b) => String(a.long_name || a.name || a.item_ref).localeCompare(String(b.long_name || b.name || b.item_ref)));
  }, [options.materials, sourceLengthCm]);
  const sourceQty = asPositiveInteger(sourceQuantity) || 1;
  const sourceTotalCm = selectedSourceLength * sourceQty;
  const targetOptions = useMemo(() => {
    return options.length_options
      .filter((row) => row.length_cm < selectedSourceLength)
      .sort((a, b) => b.length_cm - a.length_cm);
  }, [options.length_options, selectedSourceLength]);
  const selectedCuts = useMemo(() => {
    return targetOptions
      .map((row) => ({
        ...row,
        quantity: asPositiveInteger(cutQuantities[lengthKey(row.length_cm)]),
      }))
      .filter((row) => row.quantity > 0);
  }, [cutQuantities, targetOptions]);
  const validationCuts = useMemo(
    () => selectedCuts.map((row) => ({ length_cm: row.length_cm, quantity: row.quantity })),
    [selectedCuts],
  );
  const usedCm = selectedCuts.reduce((total, row) => total + row.length_cm * row.quantity, 0);
  const wasteCm = sourceTotalCm - usedCm;
  const validLocalPlan = selectedCuts.length > 0 && wasteCm >= 0;
  const exactLocalPlan = selectedCuts.length > 0 && wasteCm === 0;
  const composition = selectedCuts.map((row) => `${row.quantity} x ${formatMeters(row.length_m)}`).join(" + ") || "-";
  const hasValidatedStock = Boolean(validation?.valid && validation.stock.has_stock && exactLocalPlan);
  const canExecute = hasValidatedStock && !execution && !executing;

  useEffect(() => {
    if (!sourceMaterialOptions.length) {
      setSourceItemRef("");
      return;
    }
    const currentExists = sourceMaterialOptions.some((row) => row.item_ref === sourceItemRef);
    if (!currentExists) {
      setValidation(null);
      setValidationError("");
      setExecution(null);
      setSourceItemRef(sourceMaterialOptions[0].item_ref);
    }
  }, [sourceItemRef, sourceMaterialOptions]);

  function updateCutQuantity(row: SheetCuttingLengthOption, value: string) {
    if (!/^\d*$/.test(value)) return;
    setValidation(null);
    setValidationError("");
    setExecution(null);
    setCutQuantities((current) => ({ ...current, [lengthKey(row.length_cm)]: value }));
  }

  useEffect(() => {
    let cancelled = false;
    if (!category || !sourceItemRef || !sourceQty) {
      setValidation(null);
      setValidationError("");
      setValidating(false);
      return () => {
        cancelled = true;
      };
    }
    setValidating(true);
    setValidationError("");
    const timer = window.setTimeout(() => {
      validateSheetCuttingStock({
        store,
        category,
        source_item_ref: sourceItemRef,
        source_quantity: sourceQty,
        cuts: validationCuts,
      })
        .then((result) => {
          if (cancelled) return;
          setValidation(result);
          setExecution(null);
        })
        .catch((apiError) => {
          if (cancelled) return;
          setValidation(null);
          setValidationError(apiError instanceof Error ? apiError.message : "Origen no validado.");
        })
        .finally(() => {
          if (!cancelled) setValidating(false);
        });
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [category, sourceItemRef, sourceQty, store, validationCuts]);

  async function executeValidatedPlan() {
    if (!canExecute || !sourceItemRef) return;
    setExecuting(true);
    try {
      const result = await executeSheetCutting({
        store,
        category,
        source_item_ref: sourceItemRef,
        source_quantity: sourceQty,
        cuts: selectedCuts.map((row) => ({ length_cm: row.length_cm, quantity: row.quantity })),
        reason: `Corte de ${formatMeters(selectedSourceLength / 100)} en ${composition}`,
      });
      setExecution(result);
      notify({ message: "Corte ejecutado.", tone: "success" });
    } catch (apiError) {
      notify({ message: apiError instanceof Error ? apiError.message : "Corte no ejecutado.", tone: "error" });
    } finally {
      setExecuting(false);
    }
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-2 overflow-hidden p-2 xl:grid-cols-[280px_minmax(0,1fr)_340px]">
      <aside className="min-h-0 overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
        <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
            <Scissors className="h-4 w-4 text-primaryHover" aria-hidden="true" />
            Categorias
          </div>
          <StatusBadge label={options.unit} tone="info" />
        </div>
        <div className="flex h-full min-h-0 flex-col gap-2 overflow-hidden p-2">
          <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
            Tienda
            <input
              value={store}
              onChange={(event) => setStore(event.target.value.trim())}
              className="h-8 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
              placeholder="PS003MT"
            />
          </label>
          <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
            Buscar
            <span className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-secondaryText" aria-hidden="true" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="h-8 w-full rounded border border-borderSoft bg-white pl-8 pr-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                placeholder="Categoria o articulo"
              />
            </span>
          </label>
          <div className="min-h-0 flex-1 overflow-auto rounded border border-borderSoft">
            {options.categories.map((row) => {
              const selected = row.category === category;
              return (
                <button
                  key={row.category}
                  type="button"
                  onClick={() => setCategory(row.category)}
                  className={`flex w-full items-start justify-between gap-2 border-b border-borderSoft px-2 py-2 text-left text-[12px] transition hover:bg-softStart ${
                    selected ? "bg-blue-50 text-primaryHover outline outline-1 outline-primary/30" : "bg-white text-night"
                  }`}
                >
                  <span className="min-w-0">
                    <span className="block truncate font-semibold">{row.category}</span>
                    <span className="block text-[11px] text-secondaryText">
                      {row.length_count} largos / {formatMeters(row.max_length_m)}
                    </span>
                  </span>
                  <span className="font-mono text-[11px] text-secondaryText">{row.item_count}</span>
                </button>
              );
            })}
            {!options.categories.length ? (
              <div className="px-3 py-8 text-center text-[12px] text-secondaryText">{loading ? "Cargando..." : "Sin categorias."}</div>
            ) : null}
          </div>
        </div>
      </aside>

      <section className="flex min-h-0 min-w-0 flex-col gap-2 overflow-hidden">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <h1 className="text-[18px] font-semibold text-night">Corte de chapas</h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setQuery("");
                setCutQuantities({});
                setValidation(null);
                setExecution(null);
              }}
              className="inline-flex min-h-9 items-center gap-2 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20"
            >
              <FilterX className="h-4 w-4" aria-hidden="true" />
              Limpiar
            </button>
          </div>
        </header>

        <section className="shrink-0 rounded border border-borderSoft bg-softMid p-2 shadow-panel" aria-label="Parametros de origen">
          <div className="grid gap-2 md:grid-cols-[160px_minmax(240px,1fr)_120px_150px]">
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Largo origen
              <select
                value={sourceLengthCm}
                onChange={(event) => setSourceLengthCm(event.target.value)}
                className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
              >
                {[...options.length_options]
                  .sort((a, b) => b.length_cm - a.length_cm)
                  .map((row) => (
                    <option key={row.length_cm} value={row.length_cm}>
                      {formatMeters(row.length_m)} ({formatCm(row.length_cm)})
                    </option>
                ))}
              </select>
            </label>
            <label className="grid min-w-0 gap-1 text-[11px] font-semibold text-secondaryText">
              Articulo origen
              <select
                value={sourceItemRef}
                onChange={(event) => {
                  setSourceItemRef(event.target.value);
                  setValidation(null);
                  setValidationError("");
                  setExecution(null);
                }}
                className="h-9 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
              >
                {sourceMaterialOptions.map((row) => (
                  <option key={row.item_ref} value={row.item_ref}>
                    {row.item_ref} - {row.long_name || row.name || formatMeters(row.length_m)}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-[11px] font-semibold text-secondaryText">
              Chapas origen
              <input
                value={sourceQuantity}
                onChange={(event) => {
                  if (!/^\d*$/.test(event.target.value)) return;
                  setSourceQuantity(event.target.value);
                  setValidation(null);
                  setValidationError("");
                  setExecution(null);
                }}
                inputMode="numeric"
                className="h-9 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
              />
            </label>
            <div className="rounded border border-borderSoft bg-white px-2 py-2 text-[12px]">
              <div className="text-[11px] font-semibold text-secondaryText">Stock validado</div>
              <div className={`mt-1 font-mono font-semibold ${validation?.stock.has_stock ? "text-night" : validation ? "text-red-700" : "text-secondaryText"}`}>
                {validating ? "Validando..." : validation ? formatNumber(validation.stock.available_qty) : "-"}
              </div>
            </div>
          </div>
        </section>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
          <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
            <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
              <Ruler className="h-4 w-4 text-primaryHover" aria-hidden="true" />
              {loading ? "Cargando..." : `${targetOptions.length} largos destino`}
            </div>
            <div className="text-[11px] text-secondaryText">categoria_producto</div>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full min-w-[760px] border-collapse text-left text-[12px]">
              <thead className="sticky top-0 z-10 bg-deep text-white">
                <tr>
                  <th className="w-[130px] px-3 py-2 font-semibold">Largo</th>
                  <th className="px-3 py-2 font-semibold">Articulo ejemplo</th>
                  <th className="w-[110px] px-3 py-2 text-right font-semibold">Catalogo</th>
                  <th className="w-[120px] px-3 py-2 text-right font-semibold">Cantidad</th>
                  <th className="w-[120px] px-3 py-2 text-right font-semibold">Uso</th>
                </tr>
              </thead>
              <tbody>
                {targetOptions.map((row) => {
                  const qty = cutQuantities[lengthKey(row.length_cm)] ?? "";
                  const example = row.examples[0];
                  return (
                    <tr key={row.length_cm} className="border-b border-borderSoft bg-white hover:bg-softStart">
                      <td className="whitespace-nowrap px-3 py-2">
                        <div className="font-mono font-semibold text-night">{formatMeters(row.length_m)}</div>
                        <div className="font-mono text-[11px] text-secondaryText">{formatCm(row.length_cm)}</div>
                      </td>
                      <td className="px-3 py-2">
                        <div className="font-mono font-semibold text-night">{example?.item_ref ?? "-"}</div>
                        <div className="max-w-[380px] truncate text-[11px] text-secondaryText">{example?.long_name || example?.name || "-"}</div>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-secondaryText">{formatNumber(row.item_count)}</td>
                      <td className="px-3 py-2 text-right">
                        <label className="sr-only" htmlFor={`cut-${row.length_cm}`}>
                          Cantidad para {formatMeters(row.length_m)}
                        </label>
                        <input
                          id={`cut-${row.length_cm}`}
                          value={qty}
                          onChange={(event) => updateCutQuantity(row, event.target.value)}
                          inputMode="numeric"
                          className="h-8 w-20 rounded border border-borderSoft bg-white px-2 text-right font-mono text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                          placeholder="0"
                        />
                      </td>
                      <td className="px-3 py-2 text-right font-mono font-semibold text-night">
                        {formatMeters((row.length_cm * asPositiveInteger(qty)) / 100)}
                      </td>
                    </tr>
                  );
                })}
                {!targetOptions.length ? (
                  <tr>
                    <td colSpan={5} className="px-3 py-10 text-center text-[12px] text-secondaryText">
                      {loading ? "Cargando..." : "Sin largos menores al origen."}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <aside className="min-h-0 overflow-hidden rounded border border-borderSoft bg-surface shadow-panel">
        <div className="flex min-h-9 items-center justify-between border-b border-borderSoft px-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-night">
            <Calculator className="h-4 w-4 text-primaryHover" aria-hidden="true" />
            Resultado
          </div>
          <StatusBadge
            label={execution ? "ejecutado" : validation?.valid ? "validado" : validLocalPlan ? "plan" : "pendiente"}
            tone={execution ? "success" : validation?.valid ? "success" : validLocalPlan ? "info" : "neutral"}
          />
        </div>
        <div className="flex h-full min-h-0 flex-col overflow-auto p-3">
          <section className="grid gap-2 border-b border-borderSoft pb-3 text-[12px]">
            <div className="rounded border border-borderSoft bg-softMid px-2 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="text-[11px] font-semibold text-secondaryText">Categoria activa</div>
                <StatusBadge label={category ? "activa" : "sin datos"} tone={category ? "success" : "danger"} />
              </div>
              <div className="mt-1 truncate text-[14px] font-semibold text-night">{category || "-"}</div>
            </div>
            <div className="rounded border border-borderSoft bg-softMid px-2 py-2">
              <div className="text-[11px] font-semibold text-secondaryText">Composicion</div>
              <div className="mt-1 font-mono text-[14px] font-semibold text-night">{composition}</div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded border border-borderSoft bg-white px-2 py-2">
                <div className="text-[11px] font-semibold text-secondaryText">Origen total</div>
                <div className="mt-1 font-mono font-semibold text-night">{formatMeters(sourceTotalCm / 100)}</div>
              </div>
              <div className="rounded border border-borderSoft bg-white px-2 py-2">
                <div className="text-[11px] font-semibold text-secondaryText">Usado total</div>
                <div className="mt-1 font-mono font-semibold text-night">{formatMeters(usedCm / 100)}</div>
              </div>
            </div>
            <div className={`rounded border px-2 py-2 ${wasteCm < 0 ? "border-red-200 bg-red-50" : "border-borderSoft bg-white"}`}>
              <div className="flex items-center justify-between gap-2">
                <div className="text-[11px] font-semibold text-secondaryText">Sobrante</div>
                {wasteCm < 0 ? (
                  <AlertTriangle className="h-4 w-4 text-red-700" aria-hidden="true" />
                ) : (
                  <CheckCircle2 className="h-4 w-4 text-emerald-700" aria-hidden="true" />
                )}
              </div>
              <div className={`mt-1 font-mono text-[18px] font-semibold ${wasteCm < 0 ? "text-red-700" : "text-night"}`}>{formatCm(wasteCm)}</div>
            </div>
          </section>

          <section className="grid gap-2 border-b border-borderSoft py-3 text-[12px]">
            {selectedCuts.map((row) => (
              <div key={row.length_cm} className="rounded border border-borderSoft bg-white px-2 py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono font-semibold text-night">{formatMeters(row.length_m)}</span>
                  <StatusBadge label={`${row.quantity} un`} tone="info" />
                </div>
                <div className="mt-1 font-mono text-[11px] text-secondaryText">{formatMeters((row.length_cm * row.quantity) / 100)} usados</div>
              </div>
            ))}
            {!selectedCuts.length ? <div className="rounded border border-borderSoft bg-softMid px-3 py-2 text-secondaryText">Sin cortes cargados.</div> : null}
          </section>

          <section className="grid gap-2 py-3 text-[12px]">
            <div className="rounded border border-borderSoft bg-softMid px-2 py-2">
              <div className="text-[11px] font-semibold text-secondaryText">Validacion stock</div>
              <div className="mt-1 text-night">{validating ? "Validando origen..." : validationError || validation?.message || "Pendiente"}</div>
              {validation ? (
                <div className="mt-1 font-mono text-[11px] text-secondaryText">
                  {formatNumber(validation.stock.available_qty)} {validation.stock.source_uom} disponibles / requiere {formatNumber(validation.stock.required_qty)}
                </div>
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => void executeValidatedPlan()}
              disabled={!canExecute}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded bg-deep px-3 text-[12px] font-semibold text-white transition hover:bg-primaryHover focus:outline-none focus:ring-2 focus:ring-deep/30 disabled:bg-slate-300"
            >
              {executing ? <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Scissors className="h-4 w-4" aria-hidden="true" />}
              Ejecutar corte
            </button>
            <div className="rounded border border-borderSoft bg-softMid px-2 py-2">
              <div className="text-[11px] font-semibold text-secondaryText">Ejecucion</div>
              <div className="mt-1 text-night">{execution ? `Transformacion ${execution.id}` : "Pendiente"}</div>
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}
