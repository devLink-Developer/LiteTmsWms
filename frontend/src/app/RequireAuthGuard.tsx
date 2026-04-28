import type { PropsWithChildren } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useSessionStore } from "../stores/useSessionStore";
import { LoadingScreen } from "../shared/components/LoadingScreen";

export function RequireAuthGuard({ children }: PropsWithChildren) {
  const bootstrap = useSessionStore((state) => state.bootstrap);
  const status = useSessionStore((state) => state.status);
  const location = useLocation();

  if (!bootstrap && (status === "idle" || status === "loading")) {
    return <LoadingScreen label="Validando sesion..." />;
  }

  if (!bootstrap?.authenticated) {
    return <Navigate replace state={{ from: location }} to="/login/" />;
  }

  return children;
}

