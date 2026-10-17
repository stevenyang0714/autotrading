import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedBacktests } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { BacktestsView } from "./BacktestsView";

describe("BacktestsView with recorded API responses", () => {
  it("shows each strategy's method, samples, folds, costs and trades, never a return", () => {
    const { container } = render(<BacktestsView data={recordedBacktests} />);
    const cards = screen.getByRole("list", { name: "Backtest runs" }).querySelectorAll("li[data-backtest]");
    expect([...cards].map((c) => c.getAttribute("data-backtest"))).toEqual(["S1", "S3", "S4"]);
    const s3 = container.querySelector('[data-backtest="S3"]');
    expect(s3?.textContent).toContain("rotation rules 0.1.0 · backtest rules 0.1.0");
    expect(s3?.textContent).toContain("filled at the next session close");
    expect(s3?.textContent).toContain("equities 7 bps, ETFs 3 bps");
    expect(s3?.querySelector("[data-samples]")?.textContent).toContain("out-of-sample after 2026-10-16: no session yet");
    expect(s3?.querySelector("[data-withheld]")?.textContent).toContain("CAGR");
    expect(s3?.querySelector("[data-withheld]")?.textContent).toContain("Data unavailable");
    expect(s3?.querySelector('tr[data-fold="2026"]')?.getAttribute("data-sample")).toBe("in_sample");
    expect(s3?.querySelector('[data-scenario="double"]')?.textContent).toContain("Costs ×2");
    expect(s3?.querySelector("[data-latest-target]")?.textContent).toContain("SPY 100.00%");
    expect(s3?.querySelector('tr[data-trade="SPY"]')?.textContent).toContain("3 bps");
    expect(container.textContent).not.toMatch(/Sharpe [0-9]|CAGR [0-9]/);
    expect(container.querySelector("[data-overlap]")?.textContent).toContain("never held companies at the same time");
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("says when nothing was run by the date, and when the API is down", () => {
    const { container, unmount } = render(<BacktestsView data={{ ...recordedBacktests, runs: [], overlap: null }} />);
    expect(container.textContent).toContain("No backtest was run by this date");
    expect(unexplainedNumbers(container)).toEqual([]);
    unmount();
    render(<BacktestsView data={null} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
  });
});
