import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import { clearToasts } from "../shared/components/toast";
import { useGlobalLoadingStore } from "../stores/useGlobalLoadingStore";

afterEach(() => {
  clearToasts();
  useGlobalLoadingStore.getState().clear();
  cleanup();
});
