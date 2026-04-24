import { create } from "zustand";

type WorkspaceState = {
  warehouseRef: string;
  branchRef: string;
  role: string;
  permissions: string[];
  authorizedWarehouses: string[];
  setWarehouseRef: (warehouseRef: string) => void;
  setContext: (context: {
    warehouseRef: string;
    branchRef: string;
    role: string;
    permissions: string[];
    authorizedWarehouses: string[];
  }) => void;
};

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  warehouseRef: "",
  branchRef: "Cargando contexto",
  role: "Cargando",
  permissions: [],
  authorizedWarehouses: [],
  setWarehouseRef: (warehouseRef) => set({ warehouseRef }),
  setContext: (context) => set(context),
}));
