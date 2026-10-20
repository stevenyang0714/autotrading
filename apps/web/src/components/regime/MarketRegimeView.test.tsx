import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedRegime, recordedRegimeEarlier } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { MarketRegimeView } from "./MarketRegimeView";

describe("MarketRegimeView with recorded API responses", () => {
  it("shows the stress state with every flag judged", () => {
    render(<MarketRegimeView data={recordedRegime} />);
    const banner = document.querySelector("[data-stress]");
    expect(banner?.getAttribute("data-stress")).toBe("normal");
    expect(banner?.textContent).toContain("NORMAL");
    expect(banner?.textContent).toContain("0 of 9 available flags on");
    expect(banner?.textContent).toContain("Growth x inflation: Disinflationary slowdown");
    const flags = screen.getByRole("list", { name: "Stress flags" }).querySelectorAll("[data-flag]");
    expect(flags).toHaveLength(9);
    expect([...flags].every((f) => f.getAttribute("data-status") === "off")).toBe(true);
  });

  it("shows each dimension with its readings and the vintages behind them", () => {
    render(<MarketRegimeView data={recordedRegime} />);
    const dimensions = screen.getByRole("list", { name: "Dimensions" });
    const states = [...dimensions.querySelectorAll("[data-dimension]")].map(
      (d) => `${d.getAttribute("data-dimension")}:${d.getAttribute("data-state")}`,
    );
    expect(states).toEqual([
      "growth:slowing",
      "inflation:above_target",
      "policy:neutral",
      "credit:calm",
      "volatility:normal",
    ]);
    const inflation = dimensions.querySelector('[data-dimension="inflation"]');
    expect(inflation?.textContent).toContain("above target, falling");
    expect(inflation?.querySelector('[data-reading="core_pce_yoy"]')?.textContent).toContain("Core PCE, year on year: 3.01 percent");
    expect(inflation?.textContent).toMatch(/PCEPILFE \d{4}-\d{2}-\d{2}: [\d.]+ \(vintage \d{4}-\d{2}-\d{2}\)/);
    const policy = dimensions.querySelector('[data-reading="nfci"]');
    expect(policy?.textContent).toContain("Chicago Fed NFCI: -0.548 index");
  });

  it("draws the monthly history and an earlier date shows only what was known then", () => {
    render(<MarketRegimeView data={recordedRegime} />);
    const stress = document.querySelector('tr[data-row="stress"]');
    const cells = stress?.querySelectorAll("[data-state]");
    expect(cells).toHaveLength(2); // August and October
    // The end of August in New York is 1 September in UTC: still August's cell.
    expect(cells?.[0].getAttribute("title")).toMatch(/^2026-08-31: /);
    render(<MarketRegimeView data={recordedRegimeEarlier} knownOn="2026-09-15" />);
    expect(recordedRegimeEarlier.history).toHaveLength(1);
  });

  it.each([
    ["now", recordedRegime],
    ["earlier", recordedRegimeEarlier],
  ] as const)("%s renders no unexplained number", (_name, data) => {
    const { container } = render(<MarketRegimeView data={data} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
