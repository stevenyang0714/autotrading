import { describe, expect, it } from "vitest";

import { recordedPayems } from "@/test/fixtures";

import { chartRows, chartSince, chartSummary } from "./macroChart";

describe("macro chart data (recorded PAYEMS)", () => {
  it("draws the value and its first release, oldest first", () => {
    const rows = chartRows(recordedPayems.now.observations);
    expect(rows.map((r) => r.day)).toEqual([...rows.map((r) => r.day)].sort());
    const august = rows.find((r) => r.day === "2026-08-01");
    // Revised from its first release of 2026-09-04 (ADR-015, M0.6 revision case).
    expect(august).toMatchObject({ revised: true, first: 159075, firstVintage: "2026-09-04" });
    expect(august!.latest).not.toBe(august!.first);
    const unrevised = rows.filter((r) => !r.revised);
    expect(unrevised.every((r) => r.first === r.latest)).toBe(true);
  });

  it("before the revision, August is not revised", () => {
    const before = chartRows(recordedPayems.beforeRevision.observations);
    expect(before.find((r) => r.day === "2026-08-01")).toMatchObject({ revised: false, latest: 159075 });
  });

  it("sizes the range by frequency", () => {
    const knownAt = "2026-10-06T10:00:00Z";
    expect(chartSince(knownAt, "Monthly")).toBe("2016-10-06");
    expect(chartSince(knownAt, "Daily")).toBe("2024-10-06");
    expect(chartSince(knownAt, "Quarterly")).toBe("2006-10-06");
    expect(chartSince(knownAt, null)).toBe("2016-10-06");
  });

  it("summarises the range", () => {
    const rows = chartRows(recordedPayems.now.observations);
    const summary = chartSummary(rows)!;
    expect(summary.from).toBe(rows[0].day);
    expect(summary.revisedCount).toBe(rows.filter((r) => r.revised).length);
    expect(summary.lastRevised).toBe("2026-08-01");
    expect(chartSummary(chartRows(recordedPayems.beforeRevision.observations))!.lastRevised).toBe(
      "2026-07-01",
    );
    expect(summary.low).toBeLessThanOrEqual(summary.high);
    expect(chartSummary([])).toBeNull();
  });
});
