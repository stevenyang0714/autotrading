import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedResearch } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { ResearchRecordView } from "./ResearchRecordView";

function row(metric: string): HTMLElement {
  const found = document.querySelector<HTMLElement>(`tr[data-row="${metric}"]`);
  if (!found) throw new Error(`no ${metric} row`);
  return found;
}

describe("ResearchRecordView with recorded API responses", () => {
  it("shows TTM and five fiscal years in three sections", () => {
    render(<ResearchRecordView result={{ status: "ok", data: recordedResearch.aapl }} />);
    const table = screen.getByRole("table", { name: "Research Record" });
    const headers = [...table.querySelectorAll("thead th[data-period]")].map((th) => th.textContent);
    expect(headers[0]).toBe("TTM to 2026-06-27");
    expect(headers.slice(1)).toHaveLength(5);
    expect(headers[1]).toBe("FY ending 2025-09-27");
    expect([...table.querySelectorAll("tbody[data-section]")].map((t) => t.getAttribute("data-section"))).toEqual([
      "economics",
      "quality",
      "capital_allocation",
    ]);
  });

  it("opens each value's inputs with the filings behind them", () => {
    render(<ResearchRecordView result={{ status: "ok", data: recordedResearch.aapl }} />);
    const roic = row("roic");
    const fy2025 = roic.querySelectorAll("td")[1];
    expect(fy2025.textContent).toContain("83.14%");
    const inputs = within(fy2025).getByText("inputs").closest("details") as HTMLElement;
    expect(inputs.textContent).toContain("operating income x (1 - tax rate 15.61%)");
    expect(within(inputs).getAllByRole("link", { hidden: true }).some((a) => a.textContent === "10-K 0000320193-25-000079")).toBe(true);
    expect(row("cash_returned").querySelectorAll("td")[1].textContent).toContain("$106.132B");
  });

  it("says once why a whole row is missing, and per cell otherwise", () => {
    render(<ResearchRecordView result={{ status: "ok", data: recordedResearch.xom }} />);
    const roic = row("roic");
    expect(roic.querySelectorAll("td")).toHaveLength(1);
    expect(roic.textContent).toContain("Data unavailable: not reported: operating income");
    expect(row("net_margin").querySelectorAll("td").length).toBeGreaterThan(1);
  });

  it.each(Object.entries(recordedResearch))("%s renders no unexplained number", (_name, data) => {
    const { container } = render(<ResearchRecordView result={{ status: "ok", data }} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("shows Data unavailable when the API is unreachable", () => {
    render(<ResearchRecordView result={{ status: "unavailable" }} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
  });
});
