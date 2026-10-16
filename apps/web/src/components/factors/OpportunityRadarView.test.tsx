import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedCandidates, recordedFactors } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { OpportunityRadarView } from "./OpportunityRadarView";

describe("OpportunityRadarView with the recorded factor table", () => {
  it("lists every universe instrument with its trend and risk, each linking to its factors", () => {
    render(<OpportunityRadarView data={recordedFactors} />);
    const trend = screen.getByRole("table", { name: "Trend and risk" });
    const rows = trend.querySelectorAll("tbody tr[data-ticker]");
    expect(rows).toHaveLength(18);
    const nvda = trend.querySelector('tr[data-ticker="NVDA"]');
    expect(nvda?.querySelector('[data-column="momentum_12_1"]')?.textContent).toContain("+21.09%");
    expect(nvda?.querySelector("a")?.getAttribute("href")).toBe("/instruments/NVDA#factors");
    const spy = trend.querySelector('tr[data-ticker="SPY"]');
    expect(spy?.querySelector('[data-column="beta_252d"]')?.textContent).toContain("n/m");
  });

  it("shows each company's value and quality as percentiles of its own history", () => {
    render(<OpportunityRadarView data={recordedFactors} />);
    const table = screen.getByRole("table", { name: "Value and quality" });
    expect(table.querySelectorAll("tbody tr[data-ticker]")).toHaveLength(10); // equities only
    const roic = table.querySelector('tr[data-ticker="AAPL"] [data-column="roic"]');
    expect(roic?.textContent).toContain("100th");
    expect(roic?.textContent).toContain("90.32%");
  });

  it("sorts a trend column high to low with unavailable values last", () => {
    render(<OpportunityRadarView data={recordedFactors} sort="momentum_6_1" dir="desc" />);
    const tickers = [
      ...screen.getByRole("table", { name: "Trend and risk" }).querySelectorAll("tbody tr[data-ticker]"),
    ].map((row) => row.getAttribute("data-ticker"));
    const values = tickers.map((ticker) => {
      const found = recordedFactors.rows
        .find((row) => row.ticker === ticker)
        ?.values.find((v) => v.measure_id === "momentum_6_1")?.value;
      return found === null || found === undefined ? null : Number(found);
    });
    const present = values.filter((v): v is number => v !== null);
    expect(present).toEqual([...present].sort((a, b) => b - a));
    expect(values.slice(present.length).every((v) => v === null)).toBe(true);
  });

  it("states it is time-series only and renders no unexplained number", () => {
    const { container } = render(<OpportunityRadarView data={recordedFactors} knownOn="2026-10-06" />);
    expect(screen.getAllByRole("note")[0].textContent).toContain("never ranked against the other instruments");
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("puts the candidates above the tables when given (M2.4)", () => {
    const { container } = render(<OpportunityRadarView data={recordedFactors} candidates={recordedCandidates} />);
    const block = container.querySelector('[data-block="candidates"]');
    expect(block?.querySelector('li[data-candidate="SPY"][data-strategy="S3"]')).toBeTruthy();
    expect(block?.compareDocumentPosition(container.querySelector('[data-block="trend"]') as Node)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(unexplainedNumbers(container)).toEqual([]);
    const { container: none } = render(<OpportunityRadarView data={recordedFactors} />);
    expect(none.querySelector('[data-block="candidates"]')).toBeNull();
  });
});
