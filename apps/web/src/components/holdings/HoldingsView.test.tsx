import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedHoldingEntries, recordedHoldings } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { HoldingsView } from "./HoldingsView";

describe("HoldingsView with recorded API responses", () => {
  it("shows the USD total, the rate used and each position in its currency", () => {
    render(<HoldingsView data={recordedHoldings} entries={recordedHoldingEntries} />);
    expect(document.querySelector('[data-tile="holdings_equity"]')?.textContent).toContain("$16,684.67");
    expect(document.querySelector('[data-tile="holdings_change"]')?.textContent).toContain("-$19.95");
    const rate = document.querySelector('[data-tile="fx_rate_used"]')?.textContent;
    expect(rate).toContain("32.10");
    expect(rate).toContain("DEXTAUS for 2026-10-23 · 3 days old");
    const positions = screen.getByRole("table", { name: "Positions" });
    const tsmc = positions.querySelector('[data-symbol="2330"]');
    expect(tsmc?.textContent).toContain("NT$150,000.00");
    expect(tsmc?.textContent).toContain("+NT$5,000.00");
    expect(tsmc?.querySelector("a")?.getAttribute("href")).toBe("/instruments/2330");
    const spy = positions.querySelector('[data-symbol="SPY"]');
    expect(spy?.textContent).toContain("$610.00 (2026-10-23)");
    expect(spy?.querySelector("a")).toBeNull(); // a universe ETF has no instrument page
    const tracked = positions.querySelector('[data-symbol="ZZZZ"]');
    expect(tracked?.textContent).toContain("no close yet: valued at cost");
    expect(tracked?.textContent).toContain("$100.00");
  });

  it("lists cash, the totals per currency and every entry with its status", () => {
    render(<HoldingsView data={recordedHoldings} entries={recordedHoldingEntries} />);
    const cash = screen.getByRole("table", { name: "Cash" });
    expect(within(cash).getAllByRole("row")).toHaveLength(3); // header, Firstrade USD, 元大 TWD
    const totals = screen.getByRole("table", { name: "Totals by currency" });
    expect(totals.querySelector('[data-currency="TWD"]')?.textContent).toContain("NT$200,000.00");
    const entries = screen.getByRole("table", { name: "Entries" });
    expect(entries.querySelectorAll('[data-status="reversed"]')).toHaveLength(1);
    expect(entries.querySelector('[data-kind="reversal"]')?.textContent).toContain("reverses an earlier entry");
    expect(entries.textContent).toContain("10 × $580.00, fee $1.00");
  });

  it("offers the form and reversals only when given (viewing now)", () => {
    const { rerender } = render(<HoldingsView data={recordedHoldings} entries={recordedHoldingEntries} />);
    expect(screen.queryByRole("heading", { name: /Record an entry/ })).toBeNull();
    rerender(
      <HoldingsView
        data={recordedHoldings}
        entries={recordedHoldingEntries}
        form={<p>form</p>}
        reverse={(entry) => <button type="button">{`reverse ${entry.kind}`}</button>}
      />,
    );
    expect(screen.getByRole("heading", { name: /Record an entry/ })).toBeTruthy();
    const counted = recordedHoldingEntries.entries.filter((e) => e.status === "counted").length;
    expect(screen.getAllByRole("button", { name: /^reverse / })).toHaveLength(counted);
  });

  it("explains every number", () => {
    const { container } = render(<HoldingsView data={recordedHoldings} entries={recordedHoldingEntries} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("says so when nothing is recorded or the entries are down", () => {
    const empty = {
      ...recordedHoldings,
      equity_usd: "0.00",
      change_usd: "0.00",
      positions: [],
      cash: [],
      totals: [],
      fx: null,
      entries: 0,
    };
    render(<HoldingsView data={empty} entries={{ entries: [], accounts: [] }} />);
    expect(screen.getByText("No open positions at this time.")).toBeTruthy();
    expect(screen.getByText(/Record a deposit first/)).toBeTruthy();
    expect(document.querySelector('[data-tile="fx_rate_used"]')?.textContent).toContain("none known");
  });
});
