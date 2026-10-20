import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CompanyCandidate } from "@/lib/api";
import { recordedCandidates, recordedConvergence } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { CandidatesView } from "./CandidatesView";

describe("CandidatesView with recorded API responses", () => {
  it("lists the rotation's ETFs with their trend and versions, and says no company is at L3", () => {
    const { container } = render(<CandidatesView data={recordedCandidates} />);
    expect(container.querySelector('[role="note"]')?.textContent).toContain("Long only (no short data, OD-5)");
    expect(container.querySelector("[data-context] [data-stress]")?.textContent).toBe("NORMAL");
    const etfs = screen.getByRole("list", { name: "ETF candidates" });
    const spy = etfs.querySelector('li[data-candidate="SPY"][data-strategy="S3"]');
    expect(spy?.textContent).toContain("100.00%");
    expect(spy?.textContent).toContain("S3 Macro Regime / ETF Rotation");
    expect(spy?.textContent).toContain("rotation rules 0.2.0 · regime rules 0.2.0");
    expect(spy?.querySelector("a")?.getAttribute("href")).toBe("/instruments/SPY#factors");
    expect(container.querySelector('[data-candidates="S1"]')?.textContent).toContain("No company is at L3 or L4");
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("shows a company candidate with its level checks", () => {
    // The integration data has no company at L3 or L4: a recorded company level, as the API
    // would wrap it, shows the layout.
    const company: CompanyCandidate = {
      ticker: recordedConvergence.companies[0].ticker,
      strategy_id: "S1",
      strategy: "Buyback + Value + Quality",
      alert_rule_version: recordedConvergence.rule_version,
      buyback_rule_version: "0.3.0",
      convergence: recordedConvergence.companies[0],
    };
    const { container } = render(
      <CandidatesView data={{ ...recordedCandidates, companies: [company] }} knownOn="2026-10-06" />,
    );
    const item = container.querySelector(`li[data-candidate="${company.ticker}"][data-strategy="S1"]`);
    expect(item?.querySelector("a")?.getAttribute("href")).toBe(
      `/instruments/${company.ticker}?known_on=2026-10-06#buybacks`,
    );
    expect(item?.querySelectorAll("[data-check]")).toHaveLength(3); // L2, L3 and L4
    expect(item?.textContent).toContain(`alert rules ${recordedConvergence.rule_version}`);
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("says when the API is down", () => {
    render(<CandidatesView data={null} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
  });
});
