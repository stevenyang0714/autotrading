import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedJournal, recordedSignals } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { StrategyLabView } from "./StrategyLabView";

describe("StrategyLabView with recorded API responses", () => {
  it("lists a NO TRADE and a paper TRADE alike, with the return against SPY", () => {
    render(<StrategyLabView journal={recordedJournal} signals={recordedSignals} />);
    const table = screen.getByRole("table", { name: "Journal entries" });
    const noTrade = table.querySelector('tr[data-decision="no_trade"]');
    const trade = table.querySelector('tr[data-decision="trade"]');
    expect(noTrade?.textContent).toContain("NO TRADE: Priced in");
    expect(noTrade?.textContent).toContain("version 2");
    expect(trade?.textContent).toContain("paper TRADE buy 10");
    expect(trade?.textContent).toContain("exited");
    expect(trade?.querySelector('[data-column="performance"]')?.textContent).toContain(
      "-0.06% vs SPY +1.83% (-1.89 pts)",
    );
    expect(trade?.querySelector('[data-column="performance"]')?.textContent).toContain("-$1.90");
    // A NO TRADE shows the move after it, without money.
    expect(noTrade?.querySelector('[data-column="performance"]')?.textContent).not.toContain("$");
  });

  it("says it is paper only and shows the current signals", () => {
    render(<StrategyLabView journal={recordedJournal} signals={recordedSignals} />);
    expect(document.querySelector("[data-paper-only]")?.textContent).toContain("no order can be sent");
    const signal = within(screen.getByRole("list", { name: "Current signals" }))
      .getByText("AAPL")
      .closest("li");
    expect(signal?.textContent).toContain("ACTIVE · long");
    expect(signal?.textContent).toContain("rules 0.2.0");
    expect(signal?.textContent).toContain("paper only");
    expect(signal?.querySelector('a[href^="/journal/new?ticker=AAPL&signal="]')).not.toBeNull();
  });

  it("renders no unexplained number", () => {
    const { container } = render(<StrategyLabView journal={recordedJournal} signals={recordedSignals} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
