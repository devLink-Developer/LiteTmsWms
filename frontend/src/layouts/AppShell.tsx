import { NavLink, Outlet } from "react-router-dom";
import { useEffect, useState } from "react";

import { fetchWorkspaceContext } from "../api/workspace";
import { operationModules } from "../shared/data/modules";
import { useWorkspaceStore } from "../stores/useWorkspaceStore";

export function AppShell() {
  const { warehouseRef, branchRef, role, authorizedWarehouses, setContext } = useWorkspaceStore();
  const [contextError, setContextError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchWorkspaceContext()
      .then((context) => {
        if (cancelled) {
          return;
        }
        setContext({
          warehouseRef: context.warehouse_ref,
          branchRef: context.branch_ref,
          role: context.role,
          permissions: context.permissions,
          authorizedWarehouses: context.authorized_warehouses ?? [],
        });
        setContextError(null);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setContextError(error instanceof Error ? error.message : "No se pudo cargar contexto operativo.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [setContext]);

  return (
    <div className="flex min-h-dvh bg-gradient-to-b from-softStart via-softMid to-softEnd text-night">
      <aside className="hidden w-60 shrink-0 border-r border-borderSoft bg-deep text-white lg:block">
        <div className="border-b border-white/10 px-4 py-4">
          <div className="text-[13px] font-semibold">Lite TMS/WMS</div>
          <div className="mt-1 text-[11px] text-white/70">Consola operativa</div>
        </div>
        <nav className="space-y-1 px-2 py-3 text-[12px]" aria-label="Modulos">
          <NavLink
            to="/dashboard"
            className={({ isActive }) =>
              `block rounded px-3 py-2 font-semibold transition ${isActive ? "bg-primary text-white" : "text-white/78 hover:bg-white/10"}`
            }
          >
            Dashboard
          </NavLink>
          {operationModules.map((module) => (
            <NavLink
              key={module.key}
              to={module.path}
              className={({ isActive }) =>
                `block rounded px-3 py-2 transition ${isActive ? "bg-primary text-white" : "text-white/78 hover:bg-white/10"}`
              }
            >
              {module.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex min-h-14 items-center justify-between gap-3 border-b border-borderSoft bg-surface px-4">
          <div className="min-w-0">
            <div className="text-[11px] font-semibold uppercase text-secondaryText">{branchRef}</div>
            <div className="text-[13px] font-semibold text-night">
              {contextError ? "Contexto no disponible" : `Contexto operativo ${warehouseRef || "sin warehouse"}`}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="hidden rounded border border-borderSoft bg-white px-3 py-1 font-mono text-[12px] font-semibold text-night md:block">
              {authorizedWarehouses.length ? `${authorizedWarehouses.length} depositos` : warehouseRef || "sin warehouse"}
            </div>
            <div className="rounded border border-borderSoft bg-white px-3 py-1 text-[12px] font-semibold text-night">{role}</div>
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
