import { describe, expect, it } from "vitest";

import { DASHBOARDS, plannedLabel } from "./dashboards";

// 02 §21, in order. Changing this list is a spec change, not a refactor.
const CANONICAL_LABELS = [
  "Global Monitor",
  "Market Regime",
  "Opportunity Radar",
  "Fundamental Research",
  "Corporate Actions",
  "Event Transmission",
  "Earnings",
  "X / Expert Watch",
  "Policy Monitor",
  "Congress Trades",
  "Options & Vol",
  "Portfolio Risk",
  "Alerts Center",
  "Strategy Lab",
  "Execution",
];

describe("dashboard registry", () => {
  it("lists the fifteen canonical dashboards in spec order", () => {
    expect(DASHBOARDS.map((dashboard) => dashboard.label)).toEqual(CANONICAL_LABELS);
  });

  it("has unique ids and slugs", () => {
    expect(new Set(DASHBOARDS.map((d) => d.id)).size).toBe(DASHBOARDS.length);
    expect(new Set(DASHBOARDS.map((d) => d.slug)).size).toBe(DASHBOARDS.length);
  });

  it("assigns every dashboard to a phase after the foundation phase", () => {
    for (const dashboard of DASHBOARDS) {
      expect(dashboard.plannedPhase).toBeGreaterThanOrEqual(1);
      expect(dashboard.plannedPhase).toBeLessThanOrEqual(6);
    }
  });

  it("keeps labels and purposes free of numbers", () => {
    for (const dashboard of DASHBOARDS) {
      expect(dashboard.label).not.toMatch(/\d/);
      expect(dashboard.purpose).not.toMatch(/\d/);
    }
  });

  it("formats the planned label", () => {
    expect(plannedLabel(3)).toBe("Planned — Phase 3");
  });
});
