import { create } from "zustand";

import { fetchSessionBootstrap, login as loginRequest, logout as logoutRequest } from "../api/session";
import type { LoginPayload, LoginResponse, SessionBootstrap } from "../types/session";
import { notify } from "../shared/components/toast";

type BootstrapStatus = "idle" | "loading" | "ready" | "error";

type SessionState = {
  bootstrap: SessionBootstrap | null;
  status: BootstrapStatus;
  error: string | null;
  hydrate: (force?: boolean) => Promise<SessionBootstrap>;
  login: (payload: LoginPayload) => Promise<LoginResponse>;
  logout: () => Promise<void>;
  clearError: () => void;
};

export const useSessionStore = create<SessionState>((set, get) => ({
  bootstrap: null,
  status: "idle",
  error: null,
  async hydrate(force = false) {
    const current = get().bootstrap;
    if (!force && current && get().status === "ready") {
      return current;
    }

    set({ status: "loading", error: null });
    try {
      const data = await fetchSessionBootstrap();
      set({ bootstrap: data, status: "ready", error: null });
      return data;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Sesion no cargada.";
      set({ status: "error", error: message });
      notify({ message, tone: "error" });
      throw error;
    }
  },
  async login(payload) {
    set({ status: "loading", error: null });
    try {
      const response = await loginRequest(payload);
      set({ bootstrap: response.session, status: "ready", error: null });
      return response;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Inicio fallido.";
      set({ status: "error", error: message });
      notify({ message, tone: "error" });
      throw error;
    }
  },
  async logout() {
    try {
      await logoutRequest();
    } finally {
      set({ bootstrap: null, status: "ready", error: null });
    }
  },
  clearError() {
    set({ error: null });
  },
}));
