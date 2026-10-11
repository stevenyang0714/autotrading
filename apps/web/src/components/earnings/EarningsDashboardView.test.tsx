import { render, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedEarningsDashboard } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { EarningsDashboardView } from "./EarningsDashboardView";

describe("EarningsDashboardView with recorded API responses", () => {
  it("lists each company's latest release with its reaction and no consensus", () => {
    const { container } = render(<EarningsDashboardView data={recordedEarningsDashboard} sources={null} />);
    const latest = within(container).getByRole("table", { name: "Latest releases" });
    const rows = [...latest.querySelectorAll("tbody tr[data-ticker]")].map((r) => r.getAttribute("data-ticker"));
    expect(rows).toEqual(["AAPL", "META", "XOM"]);
    const apple = latest.querySelector<HTMLElement>('tr[data-ticker="AAPL"]');
    expect(within(apple as HTMLElement).getByRole("link", { name: "AAPL" }).getAttribute("href")).toBe("/instruments/AAPL#earnings");
    expect(apple?.textContent).toContain("Data unavailable");
    const recent = within(container).getByRole("table", { name: "Recent releases" });
    expect(recent.querySelector('tr[data-accession="0000320193-26-000011"] [data-column="day0"]')?.textContent).toBe(
      "+2.96 pts",
    );
  });

  it("renders no unexplained number", () => {
    const { container } = render(<EarningsDashboardView data={recordedEarningsDashboard} sources={null} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
