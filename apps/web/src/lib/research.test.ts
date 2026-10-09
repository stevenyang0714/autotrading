import { describe, expect, it } from "vitest";

import type { ResearchSummaryRow } from "@/lib/api";
import { cell, formatCell, isSortKey, sortRows } from "@/lib/research";
import { recordedResearchDashboard } from "@/test/fixtures";

function row(ticker: string, roic: string | null, reason: "unavailable" | "not_meaningful" | null = null): ResearchSummaryRow {
  const base = recordedResearchDashboard.current.rows[0];
  return {
    ...base,
    ticker,
    values: [{ metric_id: "roic", unit: "percent", value: roic, reason: roic === null ? (reason ?? "unavailable") : null, detail: null }],
  };
}

describe("research dashboard sorting", () => {
  it("sorts by a column, keeps rows without a value last and breaks ties by ticker", () => {
    const rows = [row("XOM", null), row("AAPL", "83.14"), row("NVDA", "98.48"), row("JPM", null, "not_meaningful"), row("MSFT", "83.14")];
    expect(sortRows(rows, "roic", "desc").map((r) => r.ticker)).toEqual(["NVDA", "AAPL", "MSFT", "JPM", "XOM"]);
    expect(sortRows(rows, "roic", "asc").map((r) => r.ticker)).toEqual(["AAPL", "MSFT", "NVDA", "JPM", "XOM"]);
    expect(sortRows(rows, "ticker", "asc").map((r) => r.ticker)).toEqual(["AAPL", "JPM", "MSFT", "NVDA", "XOM"]);
  });

  it("accepts only known columns", () => {
    expect([isSortKey("roic"), isSortKey("ticker"), isSortKey("price; drop"), isSortKey(undefined)]).toEqual([true, true, false, false]);
  });

  it("reads the DCF columns from the fair value and says why they are missing", () => {
    const xom = recordedResearchDashboard.current.rows.find((r) => r.ticker === "XOM");
    if (!xom) throw new Error("no XOM row");
    const base = cell(xom, "base_per_share");
    expect(base.value).toBeNull();
    expect(base.detail).toContain("stock-based compensation");
    expect(formatCell("124.94", "USD/shares")).toBe("$124.94");
    expect(formatCell("0.4321", "x")).toBe("0.43x");
    expect(formatCell("-2.6", "percent")).toBe("-2.60%");
  });
});
