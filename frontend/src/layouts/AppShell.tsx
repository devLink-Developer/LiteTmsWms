import { NavLink, Outlet } from "react-router-dom";
import { useEffect, useRef, useState } from "react";

import { fetchWorkspaceContext } from "../api/workspace";
import { navigationEntries, navigationLinks } from "../shared/data/modules";
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
  const { warehouseRef, branchRef, role, authorizedWarehouses, setContext } = useWorkspaceStore();
  const [contextError, setContextError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const sidebarTimerRef = useRef<number | null>(null);

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
    }, 3000);
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
          setContextError(error instanceof Error ? error.message : "No se pudo cargar contexto operativo.");
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
          <div className="text-[13px] font-semibold">Lite TMS/WMS</div>
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
      </aside>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex min-h-14 shrink-0 items-center justify-between gap-3 border-b border-borderSoft bg-surface px-4">
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
