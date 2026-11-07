import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedPolicy, recordedPolicyVersions } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { PolicyView } from "./PolicyView";

describe("PolicyView with recorded API responses", () => {
  it("shows the version in force, each sleeve's drift and the one outside its band", () => {
    render(<PolicyView data={recordedPolicy} versions={recordedPolicyVersions} />);
    expect(document.querySelector("[data-not-advice]")?.textContent).toContain("not advice");
    expect(document.querySelector('[aria-label="Policy in force"]')?.textContent).toContain("Version 2");
    const sleeves = screen.getByRole("table", { name: "Sleeves" });
    const us = sleeves.querySelector('[data-sleeve="US equity"]');
    expect(us?.getAttribute("data-outside")).toBe("true");
    expect(us?.textContent).toContain("40.00%");
    expect(us?.textContent).toContain("± 1.00 pp");
    expect(us?.textContent).toContain("-2.84 pp");
    expect(us?.textContent).toContain("US:VOO 5%");
    expect(sleeves.querySelector('[data-sleeve="Cash"]')?.getAttribute("data-outside")).toBe("false");
    expect(screen.getByRole("table", { name: "Market" }).querySelectorAll("[data-group]")).toHaveLength(3);
    const holdings = screen.getByRole("table", { name: "Holdings by sleeve" });
    expect(holdings.querySelector('[data-holding="US:SPY"]')?.textContent).toContain("above your position cap");
    expect(holdings.querySelector('[data-holding="TWD"]')?.textContent).toContain("NT$54,480.00");
  });

  it("lists the trades to the targets and the cash they move", () => {
    render(<PolicyView data={recordedPolicy} versions={recordedPolicyVersions} />);
    expect(document.querySelector("[data-due]")?.textContent).toContain("Rebalancing is due: 1 sleeve is outside its band");
    const trades = screen.getByRole("table", { name: "Trades to the targets" });
    const voo = trades.querySelector('[data-trade="US:VOO"]');
    expect(voo?.getAttribute("data-side")).toBe("buy");
    expect(voo?.textContent).toContain("$550.00 (2026-10-23)");
    expect(trades.querySelector('[data-trade="US:SPY"]')?.getAttribute("data-side")).toBe("sell");
    const zzzz = trades.querySelector('[data-trade="US:ZZZZ"]');
    expect(zzzz?.textContent).toContain("no close known: the USD amount only");
    expect(zzzz?.textContent).toContain("n/a");
    const twd = screen.getByRole("table", { name: "Cash moved by the trades" }).querySelector('[data-flow="TWD"]');
    expect(twd?.textContent).toContain("-NT$9,000.00");
    expect(twd?.textContent).toContain("NT$45,480.00");
    expect(screen.getByText(/Fees, taxes and board lots are not counted/)).toBeTruthy();
    expect(screen.getByRole("table", { name: "Policy versions" }).querySelectorAll("[data-version]")).toHaveLength(2);
  });

  it("explains every number", () => {
    const { container } = render(<PolicyView data={recordedPolicy} versions={recordedPolicyVersions} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("asks for a first version when there is none, and offers the form only when given", () => {
    const bare = {
      ...recordedPolicy,
      policy: null,
      sleeves: [],
      asset_classes: [],
      markets: [],
      due: false,
      blocked: ["no_policy"],
      trades: [],
      cash_flows: [],
    };
    const { container, rerender } = render(<PolicyView data={bare} versions={{ versions: [] }} />);
    expect(document.querySelector('[data-blocked="no_policy"]')?.textContent).toContain("No policy yet");
    expect(screen.queryByRole("table", { name: "Sleeves" })).toBeNull();
    expect(screen.queryByRole("heading", { name: /Write your policy/ })).toBeNull();
    expect(screen.getByText("No version saved yet.")).toBeTruthy();
    expect(unexplainedNumbers(container)).toEqual([]);
    rerender(<PolicyView data={bare} versions={{ versions: [] }} form={<p>form</p>} />);
    expect(screen.getByRole("heading", { name: /Write your policy/ })).toBeTruthy();
  });

  it("says why no trade is listed while a holding is unassigned", () => {
    const blocked = {
      ...recordedPolicy,
      blocked: ["unassigned"],
      trades: [],
      cash_flows: [],
      holdings: recordedPolicy.holdings.map((h) => (h.key === "US:ZZZZ" ? { ...h, sleeve: null } : h)),
    };
    render(<PolicyView data={blocked} versions={recordedPolicyVersions} />);
    expect(document.querySelector('[data-blocked="unassigned"]')?.textContent).toContain("belong to no sleeve");
    expect(document.querySelector("[data-due]")?.textContent).toContain("but no trade is listed");
    expect(document.querySelector('[data-holding="US:ZZZZ"]')?.textContent).toContain("unassigned");
  });
});
