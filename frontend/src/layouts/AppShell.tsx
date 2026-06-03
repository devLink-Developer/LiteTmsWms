import { LogOut } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useEffect, useRef, useState } from "react";

import { fetchWorkspaceContext, setActiveWarehouse } from "../api/workspace";
import { notify } from "../shared/components/toast";
import { navigationEntries, navigationLinks } from "../shared/data/modules";
import { useLiveStatusEvents } from "../shared/hooks/useLiveStatusEvents";
import { useSessionStore } from "../stores/useSessionStore";
import { useWorkspaceStore } from "../stores/useWorkspaceStore";
import type { NavigationLink } from "../types/operations";

function desktopLinkClass(isActive: boolean) {
  return `block rounded px-3 py-2 transition ${isActive ? "bg-primary text-white" : "text-white/78 hover:bg-white/10"}`;
}

function mobileLinkClass(isActive: boolean) {
  return `shrink-0 rounded px-3 py-2 font-semibold transition ${
    isActive ? "bg-primary text-white" : "text-secondaryText hover:bg-softStart"
  }`;
}

function DesktopNavLink({ link }: { link: NavigationLink }) {
  return (
    <NavLink key={link.key} to={link.path} end={link.end} className={({ isActive }) => desktopLinkClass(isActive)}>
      {link.label}
    </NavLink>
  );
}

export function AppShell() {
  const { warehouseRef, role, authorizedWarehouses, setContext } = useWorkspaceStore();
  const logout = useSessionStore((state) => state.logout);
  const navigate = useNavigate();
  const [contextError, setContextError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [switchingWarehouse, setSwitchingWarehouse] = useState(false);
  const sidebarTimerRef = useRef<number | null>(null);
  const warehouseLabel =
    authorizedWarehouses.length === 1
      ? authorizedWarehouses[0]
      : authorizedWarehouses.length
        ? `${authorizedWarehouses.length} depositos`
      : warehouseRef || "sin warehouse";

  useLiveStatusEvents({ enabled: Boolean(warehouseRef) });

  function clearSidebarTimer() {
    if (sidebarTimerRef.current !== null) {
      window.clearTimeout(sidebarTimerRef.current);
      sidebarTimerRef.current = null;
    }
  }

  function showSidebar() {
    clearSidebarTimer();
    setSidebarOpen(true);
  }

  function scheduleSidebarHide() {
    clearSidebarTimer();
    sidebarTimerRef.current = window.setTimeout(() => {
      setSidebarOpen(false);
      sidebarTimerRef.current = null;
    }, 1000);
  }

  async function handleLogout() {
    setIsLoggingOut(true);
    try {
      await logout();
      navigate("/login/", { replace: true });
    } finally {
      setIsLoggingOut(false);
    }
  }

  async function handleWarehouseChange(nextWarehouseRef: string) {
    if (!nextWarehouseRef || nextWarehouseRef === warehouseRef) {
      return;
    }
    setSwitchingWarehouse(true);
    try {
      const context = await setActiveWarehouse(nextWarehouseRef);
      setContext({
        warehouseRef: context.warehouse_ref,
        branchRef: context.branch_ref,
        role: context.role,
        permissions: context.permissions,
        authorizedWarehouses: context.authorized_warehouses ?? [],
      });
      setContextError(null);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Almacen no cambiado.";
      setContextError(message);
      notify({ message, tone: "error" });
    } finally {
      setSwitchingWarehouse(false);
    }
  }

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
          const message = error instanceof Error ? error.message : "Contexto no cargado.";
          setContextError(message);
          notify({ message, tone: "error" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [setContext]);

  useEffect(() => () => clearSidebarTimer(), []);

  return (
    <div className="flex h-dvh min-h-0 overflow-hidden bg-gradient-to-b from-softStart via-softMid to-softEnd text-night">
      <aside
        className={`hidden h-full min-h-0 shrink-0 flex-col overflow-hidden border-r border-borderSoft bg-deep text-white transition-[width] duration-200 lg:flex ${
          sidebarOpen ? "w-60" : "w-3"
        }`}
        onMouseEnter={showSidebar}
        onMouseLeave={scheduleSidebarHide}
        aria-label="Menu principal"
      >
        <div className={`min-w-60 shrink-0 border-b border-white/10 px-4 py-4 transition-opacity duration-150 ${sidebarOpen ? "opacity-100" : "opacity-0"}`}>
          <div className="text-[13px] font-semibold">Lite Logistic</div>
          <div className="mt-1 text-[11px] text-white/70">Consola operativa</div>
        </div>
        <nav className={`min-w-60 min-h-0 flex-1 space-y-1 overflow-y-auto px-2 py-3 text-[12px] transition-opacity duration-150 ${sidebarOpen ? "opacity-100" : "pointer-events-none opacity-0"}`} aria-label="Modulos">
          {navigationEntries.map((entry) =>
            "items" in entry ? (
              <div key={entry.key} className="pt-2 first:pt-0">
                <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-white/45">
                  {entry.label}
                </div>
                <div className="space-y-1">
                  {entry.items.map((link) => (
                    <DesktopNavLink key={link.key} link={link} />
                  ))}
                </div>
              </div>
            ) : (
              <DesktopNavLink key={entry.key} link={entry} />
            ),
          )}
        </nav>
        <div className={`min-w-60 shrink-0 border-t border-white/10 p-3 transition-opacity duration-150 ${sidebarOpen ? "opacity-100" : "pointer-events-none opacity-0"}`}>
          <button
            aria-label="Cerrar sesion"
            className="flex h-11 w-full items-center justify-center gap-2 rounded border border-white/15 bg-white/8 px-3 text-[12px] font-semibold text-white transition hover:border-white/35 hover:bg-white/12 focus:outline-none focus:ring-2 focus:ring-white/25 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={isLoggingOut}
            onClick={() => void handleLogout()}
            type="button"
          >
            <LogOut aria-hidden="true" size={16} strokeWidth={2} />
            <span>Cerrar sesion</span>
          </button>
        </div>
      </aside>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex min-h-14 shrink-0 items-center justify-between gap-3 border-b border-borderSoft bg-surface px-4">
          <div className="min-w-0">
            <div className="text-[13px] font-semibold text-night">
              {contextError ? "Contexto no disponible" : `Contexto operativo ${warehouseRef || "sin warehouse"}`}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {authorizedWarehouses.length > 1 ? (
              <label className="hidden items-center gap-2 rounded border border-borderSoft bg-white px-2 py-1 text-[11px] font-semibold text-secondaryText md:flex">
                Almacen
                <select
                  value={warehouseRef}
                  disabled={switchingWarehouse}
                  onChange={(event) => void handleWarehouseChange(event.target.value)}
                  className="h-7 rounded border border-borderSoft bg-white px-2 font-mono text-[12px] font-semibold text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                  aria-label="Almacen activo"
                >
                  {authorizedWarehouses.map((warehouse) => (
                    <option key={warehouse} value={warehouse}>
                      {warehouse}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <div className="hidden rounded border border-borderSoft bg-white px-3 py-1 font-mono text-[12px] font-semibold text-night md:block">
                {warehouseLabel}
              </div>
            )}
            <div className="hidden rounded border border-borderSoft bg-white px-3 py-1 text-[12px] font-semibold text-night sm:block">{role}</div>
            <button
              aria-label="Cerrar sesion"
              className="flex h-11 min-w-11 items-center justify-center gap-2 rounded border border-borderSoft bg-white px-3 text-secondaryText transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={isLoggingOut}
              onClick={() => void handleLogout()}
              title="Cerrar sesion"
              type="button"
            >
              <LogOut aria-hidden="true" size={16} strokeWidth={2} />
              <span className="text-[12px] font-semibold">Salir</span>
            </button>
          </div>
        </header>
        <nav className="flex shrink-0 gap-1 overflow-x-auto border-b border-borderSoft bg-white px-3 py-2 text-[12px] lg:hidden" aria-label="Modulos">
          {navigationLinks.map((link) => (
            <NavLink
              key={link.key}
              to={link.path}
              end={link.end}
              className={({ isActive }) => mobileLinkClass(isActive)}
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
        <main className="min-h-0 flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
