import { create } from "zustand";

type DomainState = {
  filters: Record<string, string>;
  selectedIds: string[];
  activeRecordId: string | null;
  drawerOpen: boolean;
  loading: boolean;
  error: string | null;
  setFilter: (key: string, value: string) => void;
  resetFilters: () => void;
  selectRecord: (id: string | null) => void;
  toggleSelection: (id: string) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
};

function createDomainStore() {
  return create<DomainState>((set) => ({
    filters: {
      estado: "",
      warehouse: "",
      busqueda: "",
      fecha: "",
    },
    selectedIds: [],
    activeRecordId: null,
    drawerOpen: false,
    loading: false,
    error: null,
    setFilter: (key, value) =>
      set((state) => ({ filters: { ...state.filters, [key]: value } })),
    resetFilters: () => set({ filters: { estado: "", warehouse: "", busqueda: "", fecha: "" } }),
    selectRecord: (id) => set({ activeRecordId: id, drawerOpen: Boolean(id) }),
    toggleSelection: (id) =>
      set((state) => ({
        selectedIds: state.selectedIds.includes(id)
          ? state.selectedIds.filter((selectedId) => selectedId !== id)
          : [...state.selectedIds, id],
      })),
    setLoading: (loading) => set({ loading }),
    setError: (error) => set({ error }),
  }));
}

export const useReceiptsStore = createDomainStore();
export const useTransfersStore = createDomainStore();
export const useOrdersStore = createDomainStore();
export const useDeliveriesStore = createDomainStore();
export const useDistributionStore = createDomainStore();
export const useRoutesStore = createDomainStore();
export const useVehiclesStore = createDomainStore();
export const useInventoryStore = createDomainStore();
export const useStockMovementsStore = createDomainStore();
export const useAuditsStore = createDomainStore();
export const useDispatchStore = createDomainStore();
export const useShippingStore = createDomainStore();
export const useReturnsStore = createDomainStore();

export function storeForModule(moduleKey: string) {
  const stores: Record<string, typeof useReceiptsStore> = {
    receipts: useReceiptsStore,
    transfers: useTransfersStore,
    orders: useOrdersStore,
    deliveries: useDeliveriesStore,
    distribution: useDistributionStore,
    routes: useRoutesStore,
    vehicles: useVehiclesStore,
    stock: useInventoryStore,
    "stock-movements": useStockMovementsStore,
    audits: useAuditsStore,
    dispatch: useDispatchStore,
    shipping: useShippingStore,
    returns: useReturnsStore,
  };
  return stores[moduleKey] ?? useReceiptsStore;
}
