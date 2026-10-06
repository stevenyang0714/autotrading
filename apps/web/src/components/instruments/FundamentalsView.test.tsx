import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedFundamentals } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { FundamentalsView } from "./FundamentalsView";

function cellText(container: HTMLElement, table: string, metric: string, column: number) {
  const region = within(screen.getByRole("table", { name: table }));
  const row = region.getAllByRole("row").find((r) => r.querySelector(`th [data-term-id="${metric}"]`));
  return row?.querySelectorAll("td")[column]?.textContent ?? "";
}

describe("FundamentalsView with recorded API responses", () => {
  it("shows Apple's FY2025 revenue with its 10-K", () => {
    const { container } = render(<FundamentalsView data={recordedFundamentals.aapl} />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Apple Inc.");
    const revenue = cellText(container, "Annual results", "revenue", 0);
    expect(revenue).toContain("$416.161B");
    expect(revenue).toContain("10-K 0000320193-25-000079");
    const annual = screen.getByRole("table", { name: "Annual results" });
    const link = within(annual).getAllByRole("link", { name: "10-K 0000320193-25-000079" })[0];
    expect(link.getAttribute("href")).toBe(
      "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/0000320193-25-000079-index.htm",
    );
  });

  it("shows the original FY2008 net income before the 10-K/A and the restatement after", () => {
    const { container, unmount } = render(
      <FundamentalsView data={recordedFundamentals.aaplBefore10KA} knownOn="2010-01-25" />,
    );
    const before = cellText(container, "Annual results", "net_income", 1);
    expect(before).toContain("$4.834B");
    expect(before).not.toContain("Restated");
    unmount();

    const after = render(
      <FundamentalsView data={recordedFundamentals.aaplAfter10KA} knownOn="2010-01-27" />,
    );
    const restated = cellText(after.container, "Annual results", "net_income", 1);
    expect(restated).toContain("$6.119B");
    expect(restated).toContain("Restated");
    expect(restated).toContain("was $4.834B");
    expect(restated).toContain("10-K 0001193125-09-214859");
    expect(after.container.querySelector("#known_on")).toHaveProperty("value", "2010-01-27");
  });

  it("labels XOM history reported by the predecessor issuer", () => {
    const { container } = render(<FundamentalsView data={recordedFundamentals.xom} />);
    expect(screen.getByRole("list", { name: "Predecessor issuers" }).textContent).toContain(
      "Exxon Mobil Corp",
    );
    expect(cellText(container, "Annual results", "revenue", 0)).toContain("by Exxon Mobil Corp");
    expect(cellText(container, "Balance sheet", "cash", 0)).not.toContain("by Exxon Mobil Corp");
  });

  it("derives free cash flow and names its inputs (ADR-021)", () => {
    const { container } = render(<FundamentalsView data={recordedFundamentals.aapl} />);
    const fcf = cellText(container, "Annual results", "free_cash_flow", 0);
    expect(fcf).toContain("$98.767B");
    expect(fcf).toContain("operating cash flow − capex");
    expect(fcf).toContain("Operating Cash Flow $111.482B");
  });

  it("shows Apple's FY2017 EPS as reported and split-adjusted", () => {
    const { container } = render(<FundamentalsView data={recordedFundamentals.aapl} />);
    const table = screen.getByRole("table", { name: "Per-share history" });
    const column = Array.from(table.querySelectorAll("thead th")).findIndex((th) =>
      th.textContent?.includes("2017-09-30"),
    );
    const eps = cellText(container, "Per-share history", "eps_diluted", column - 1);
    expect(eps).toContain("$9.21");
    expect(eps).toContain("$2.3025 split-adjusted (÷4)");
  });

  it("shows quarters with trailing twelve months", () => {
    render(<FundamentalsView data={recordedFundamentals.aapl} />);
    const quarterly = screen.getByRole("table", { name: "Quarterly" });
    expect(quarterly.querySelectorAll("thead th")).toHaveLength(10); // metric, 8 quarters, TTM
    const revenue = within(quarterly)
      .getAllByRole("row")
      .find((r) => r.querySelector(`th [data-term-id="revenue"]`));
    expect(revenue?.querySelector("[data-ttm]")?.textContent).toMatch(/\$\d+\.\d{3}B/);
  });

  it("says which debt components were counted as zero", () => {
    const { container } = render(<FundamentalsView data={recordedFundamentals.meta} />);
    expect(cellText(container, "Balance sheet", "total_debt", 0)).toContain(
      "Not reported, counted as zero",
    );
    expect(screen.getByRole("list", { name: "Latest reported values" }).textContent).toContain(
      "shares",
    );
    expect(cellText(container, "Balance sheet", "shares_outstanding", 0)).toContain(
      "sum of share classes",
    );
  });

  it.each(Object.entries(recordedFundamentals))("%s renders no unexplained number", (_name, data) => {
    const { container } = render(<FundamentalsView data={data} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("tells the user when a date was not a calendar date", () => {
    render(<FundamentalsView data={recordedFundamentals.aapl} knownOn="2026-02-30" invalidKnownOn />);
    expect(screen.getByRole("status").textContent).toContain("Not a calendar date");
  });
});
