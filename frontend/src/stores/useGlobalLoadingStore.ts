import { create } from "zustand";

type LoadingOperation = {
  label: string;
  startedAt: number;
};

type GlobalLoadingState = {
  operations: Record<string, LoadingOperation>;
  start: (label?: string) => string;
  finish: (id: string) => void;
  clear: () => void;
};

const DEFAULT_LABEL = "Procesando...";
let sequence = 0;
let suppressionDepth = 0;

export const useGlobalLoadingStore = create<GlobalLoadingState>((set) => ({
  operations: {},
  start: (label = DEFAULT_LABEL) => {
    sequence += 1;
    const id = `global-loading-${Date.now()}-${sequence}`;
    set((state) => ({
      operations: {
        ...state.operations,
        [id]: {
          label,
          startedAt: Date.now(),
        },
      },
    }));
    return id;
  },
  finish: (id) => {
    set((state) => {
      if (!state.operations[id]) return state;
      const operations = { ...state.operations };
      delete operations[id];
      return { operations };
    });
  },
  clear: () => set({ operations: {} }),
}));

export function beginGlobalLoading(label?: string) {
  const id = useGlobalLoadingStore.getState().start(label);
  return () => useGlobalLoadingStore.getState().finish(id);
}

export async function withGlobalLoading<T>(task: Promise<T>, label?: string): Promise<T> {
  const finish = beginGlobalLoading(label);
  try {
    return await task;
  } finally {
    finish();
  }
}

export function isGlobalLoadingSuppressed() {
  return suppressionDepth > 0;
}

export async function withoutGlobalLoading<T>(task: () => T | Promise<T>): Promise<T> {
  suppressionDepth += 1;
  try {
    return await task();
  } finally {
    suppressionDepth = Math.max(0, suppressionDepth - 1);
  }
}
