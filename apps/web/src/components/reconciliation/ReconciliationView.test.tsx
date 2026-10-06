import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedReconciliation } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { ReconciliationDetailView, ReconciliationView } from "./ReconciliationView";

describe("ReconciliationView with recorded API responses", () => {
  it("lists each issuer's latest 10-K and 10-Q with its status", () => {
    render(<ReconciliationView data={recordedReconciliation.list} query={{}} />);
    const table = screen.getByRole("table", { name: "Reconciled filings" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(recordedReconciliation.list.filings.length);
    const apple = rows.find((r) => r.textContent?.includes("0000320193-25-000079"));
    expect(apple?.querySelector("[data-status]")?.textContent).toBe("pass");
    expect(apple?.textContent).toContain("matched");
    expect(apple?.textContent).not.toContain("mismatched"); // zero counts are not listed
    expect(within(table).getAllByRole("link")[0].getAttribute("href")).toMatch(
      /^\/system\/reconciliation\/\d{10}-\d{2}-\d{6}$/,
    );
  });

  it("shows Data unavailable when the API is unreachable", () => {
    const { container } = render(<ReconciliationView data={null} query={{}} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("renders no number outside a glossary-backed metric", () => {
    const { container } = render(<ReconciliationView data={recordedReconciliation.list} query={{}} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});

describe("ReconciliationDetailView", () => {
  it("shows Apple's FY2025 revenue as filed and as stored", () => {
    render(<ReconciliationDetailView data={recordedReconciliation.aapl10K} />);
    const items = screen.getByRole("table", { name: "Reconciliation items" });
    const revenue = within(items)
      .getAllByRole("row")
      .find((r) => r.textContent?.includes("Revenue") && r.textContent.includes("2025-09-27"));
    expect(revenue?.textContent).toContain("416,161,000,000");
    expect(revenue?.querySelector("[data-status]")?.textContent).toBe("match");
  });

  it("renders no number outside a glossary-backed metric", () => {
    const { container } = render(<ReconciliationDetailView data={recordedReconciliation.aapl10K} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
