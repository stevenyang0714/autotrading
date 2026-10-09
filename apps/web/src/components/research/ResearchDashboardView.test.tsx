import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedResearchDashboard } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { ResearchDashboardView } from "./ResearchDashboardView";

function tickers(): string[] {
  return [...document.querySelectorAll("tbody tr[data-ticker]")].map((r) => r.getAttribute("data-ticker") ?? "");
}

describe("ResearchDashboardView with recorded API responses", () => {
  it("lists every company with its period, and links each to its Research Record", () => {
    render(<ResearchDashboardView data={recordedResearchDashboard.current} sources={null} />);
    expect(tickers()).toEqual(["AAPL", "META", "XOM"]);
    const apple = document.querySelector<HTMLElement>('tr[data-ticker="AAPL"]');
    if (!apple) throw new Error("no AAPL row");
    expect(within(apple).getByRole("link", { name: "AAPL" }).getAttribute("href")).toBe("/instruments/AAPL#research-record");
    expect(apple.textContent).toContain("TTM to 2026-06-27");
    expect(apple.querySelector('[data-column="roic"]')?.textContent).toMatch(/^\d+\.\d{2}%$/);
    expect(apple.querySelector('[data-column="base_per_share"]')?.textContent).toMatch(/^\$\d+\.\d{2}$/);
  });

  it("labels the DCF columns as model output and explains missing values", () => {
    render(<ResearchDashboardView data={recordedResearchDashboard.current} sources={null} />);
    expect(document.querySelector('[data-group="model"]')?.textContent).toContain("model output, not fact");
    const xom = document.querySelector<HTMLElement>('tr[data-ticker="XOM"]');
    expect(xom?.querySelector('[data-column="roic"]')?.textContent).toBe("n/a");
    const reasons = document.querySelector("[data-missing-reasons]")?.textContent ?? "";
    expect(reasons).toContain("not reported: operating income");
  });

  it("sorts on the server from the URL, with links that keep As known on", () => {
    render(<ResearchDashboardView data={recordedResearchDashboard.current} sources={null} sort="roic" dir="desc" knownOn="2026-10-06" />);
    expect(tickers()).toEqual(["AAPL", "META", "XOM"]);
    const header = screen.getByRole("link", { name: "Sort by ROIC" });
    expect(header.getAttribute("href")).toBe("/dashboards/fundamental-research?known_on=2026-10-06&sort=roic&dir=asc");
    expect(header.closest("th")?.getAttribute("aria-sort")).toBe("descending");
    expect(screen.getByRole("link", { name: "Sort by P/E" }).getAttribute("href")).toContain("sort=pe_ratio_ttm&dir=desc");
  });

  it("shows no upside from a stale close", () => {
    render(<ResearchDashboardView data={recordedResearchDashboard.stale} sources={null} />);
    const apple = document.querySelector<HTMLElement>('tr[data-ticker="AAPL"]');
    expect(apple?.querySelector('[data-column="implied_upside"]')?.textContent).toBe("n/a");
    expect(apple?.querySelector('[data-column="base_per_share"]')?.textContent).toMatch(/^\$\d+\.\d{2}$/);
  });

  it.each(Object.entries(recordedResearchDashboard))("%s renders no unexplained number", (_name, data) => {
    const { container } = render(<ResearchDashboardView data={data} sources={null} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
