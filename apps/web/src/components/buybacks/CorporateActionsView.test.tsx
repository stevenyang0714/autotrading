import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedBuybackStates } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { CorporateActionsView } from "./CorporateActionsView";

function row(ticker: string): HTMLElement {
  const found = document.querySelector<HTMLElement>(`tr[data-ticker="${ticker}"]`);
  if (!found) throw new Error(`no ${ticker} row`);
  return found;
}

describe("CorporateActionsView with recorded API responses", () => {
  it("reviews every company's state against the rule's thresholds", () => {
    render(<CorporateActionsView data={recordedBuybackStates} sources={null} />);
    const table = screen.getByRole("table", { name: "Threshold review" });
    expect(within(table).getAllByRole("row")).toHaveLength(5);
    expect(
      ["AAPL", "META", "NVDA", "XOM"].map((t) => row(t).querySelector("[data-state]")?.textContent),
    ).toEqual(["ACTIVE", "No state", "WATCH", "ACTIVE"]);
    expect(document.querySelector('th[data-column="active.quarter_repurchase"]')?.textContent).toContain(
      "≥ 0.5%; mega cap: any",
    );
    expect(document.querySelector("[data-mega-cap]")?.textContent).toContain("$500 billion or more");
    expect(document.querySelector('th[data-column="high_conviction.fcf_funding"]')?.textContent).toContain("≤ 1.2x");
    const quarter = row("META").querySelector('[data-condition="active.quarter_repurchase"]');
    expect(quarter?.getAttribute("data-status")).toBe("fail");
    expect(quarter?.getAttribute("title")).toBe("no repurchases in the quarter ended 2026-06-30");
    expect(row("XOM").querySelector('[data-condition="high_conviction.net_debt"]')?.textContent).toBe("12.61%");
    expect(screen.getByText(/rule v0\.2\.0/).textContent).toContain("approved 2026-10-11");
    expect(within(row("AAPL")).getByRole("link", { name: "AAPL" }).getAttribute("href")).toBe("/instruments/AAPL#buybacks");
  });

  it("shows each company's state history and buyback timeline", () => {
    render(<CorporateActionsView data={recordedBuybackStates} sources={null} knownOn="2026-10-06" />);
    const history = screen.getByRole("list", { name: "AAPL state history" });
    expect([...history.children].map((li) => li.getAttribute("aria-label"))).toEqual([
      "2026-03-31: No state, backfilled",
      "2026-10-06: ACTIVE, backfilled",
    ]);
    const timeline = screen.getByRole("list", { name: "AAPL timeline", hidden: true });
    const entries = [...timeline.children].map((li) => li.textContent);
    expect(entries[0]).toBe("2026-10-06 State ACTIVE (backfilled)");
    expect(entries).toContain("2026-04-30 Authorization increase $100 billion");
    expect(within(row("NVDA")).getByRole("link", { name: "NVDA" }).getAttribute("href")).toBe(
      "/instruments/NVDA?known_on=2026-10-06#buybacks",
    );
  });

  it("renders no unexplained number", () => {
    const { container } = render(<CorporateActionsView data={recordedBuybackStates} sources={null} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
