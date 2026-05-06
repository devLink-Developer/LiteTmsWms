import { useEffect } from "react";
import { RouterProvider } from "react-router-dom";

import { router } from "./router";
import { GlobalLoadingOverlay } from "../shared/components/GlobalLoadingOverlay";
import { LoadingScreen } from "../shared/components/LoadingScreen";
import { ToastViewport } from "../shared/components/toast";
import { useSessionStore } from "../stores/useSessionStore";

export function App() {
  const bootstrap = useSessionStore((state) => state.bootstrap);
  const error = useSessionStore((state) => state.error);
  const hydrate = useSessionStore((state) => state.hydrate);
  const status = useSessionStore((state) => state.status);

  useEffect(() => {
    void hydrate().catch(() => undefined);
  }, [hydrate]);

  if (!bootstrap && (status === "idle" || status === "loading")) {
    return <LoadingScreen label="Preparando Lite Logistic..." />;
  }

  if (!bootstrap && status === "error" && error) {
    return (
      <>
        <main className="flex min-h-[100svh] items-center bg-[#f3f6f9] px-4 py-6 text-[#1f2937] sm:px-6 sm:py-8">
          <section className="mx-auto w-full max-w-2xl rounded-lg border border-[#cfdbe7] bg-white p-6 shadow-[0_30px_72px_rgba(15,42,67,0.16)] sm:p-8">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#0c4f86]">Lite Logistic</p>
            <h1 className="mt-3 text-3xl font-semibold text-[#202938]">Sesion no disponible</h1>
            <button
              className="mt-6 rounded-md bg-[#0c4f86] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#073f6f]"
              onClick={() => void hydrate(true).catch(() => undefined)}
              type="button"
            >
              Recargar
            </button>
          </section>
        </main>
        <GlobalLoadingOverlay />
        <ToastViewport />
      </>
    );
  }

  return (
    <>
      <RouterProvider router={router} />
      <GlobalLoadingOverlay />
      <ToastViewport />
    </>
  );
}
