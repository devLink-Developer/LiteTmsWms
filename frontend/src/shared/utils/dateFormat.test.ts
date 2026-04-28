import { describe, expect, it } from "vitest";

import { formatAppDate, formatAppDateTime } from "./dateFormat";

describe("dateFormat", () => {
  it("formats dates as dd/mm/yyyy", () => {
    expect(formatAppDate("2026-04-28")).toBe("28/04/2026");
    expect(formatAppDateTime("2026-04-28")).toBe("28/04/2026");
  });

  it("formats date time values with a dd/mm/yyyy date prefix", () => {
    expect(formatAppDateTime("2026-04-28T13:45:00")).toBe("28/04/2026 13:45");
  });
});
