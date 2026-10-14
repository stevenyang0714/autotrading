import { describe, expect, it } from "vitest";

import { formatMeasure, isSortKey, ordinal, windowText } from "./factors";

describe("factor formats", () => {
  it("signs returns and relative values, and keeps multiples and beta plain", () => {
    expect(formatMeasure("21.09", "percent", "trend")).toBe("+21.09%");
    expect(formatMeasure("-3.1", "percent", "trend")).toBe("-3.10%");
    expect(formatMeasure("4.6", "percent", "relative")).toBe("+4.60 pts");
    expect(formatMeasure("38.15", "percent", "risk")).toBe("38.15%");
    expect(formatMeasure("38.18", "x", "value")).toBe("38.18x");
    expect(formatMeasure("1.882", "ratio", "risk")).toBe("1.882");
  });

  it("writes percentiles as ordinals", () => {
    expect(["1", "2", "3", "4", "11", "12", "13", "21", "22", "100"].map(ordinal)).toEqual([
      "1st percentile",
      "2nd percentile",
      "3rd percentile",
      "4th percentile",
      "11th percentile",
      "12th percentile",
      "13th percentile",
      "21st percentile",
      "22nd percentile",
      "100th percentile",
    ]);
  });

  it("accepts only known sort keys and writes windows", () => {
    expect(isSortKey("momentum_12_1")).toBe(true);
    expect(isSortKey("roic")).toBe(true);
    expect(isSortKey("drop table")).toBe(false);
    expect(windowText({ start: "2025-10-02", end: "2026-09-03" })).toBe("2025-10-02 to 2026-09-03");
    expect(windowText({ start: null, end: "2026-10-05" })).toBe("2026-10-05");
  });
});
