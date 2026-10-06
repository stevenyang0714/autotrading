import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedValuation } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { ValuationView } from "./ValuationView";

function card(metric: string): HTMLElement {
  const found = screen.getByRole("list", { name: "Valuation" }).querySelector<HTMLElement>(
    `[data-valuation="${metric}"]`,
  );
  if (!found) throw new Error(`no ${metric} card`);
  return found;
}

describe("ValuationView with recorded API responses", () => {
  it("shows market cap, EV and the six multiples priced at the close", () => {
    render(<ValuationView result={{ status: "ok", data: recordedValuation.aapl }} />);
    expect(within(screen.getByRole("list", { name: "Valuation" })).getAllByRole("listitem", { hidden: true }).length).toBeGreaterThanOrEqual(8);
    expect(screen.getByText(/Priced at the 2026-10-05 close/)).toBeTruthy();
    expect(card("market_cap").textContent).toMatch(/\$\d\.\d{3}T/);
    expect(card("pe_ratio_ttm").textContent).toMatch(/\d+\.\d{2}x/);
    expect(card("fcf_yield").textContent).toMatch(/\d+\.\d{2}%/);
  });

  it("lists each multiple's inputs with dates and filings", () => {
    render(<ValuationView result={{ status: "ok", data: recordedValuation.aapl }} />);
    const pe = card("pe_ratio_ttm");
    expect(pe.textContent).toContain("Inputs");
    expect(pe.textContent).toContain("fiscal year +");
    expect(within(pe).getAllByRole("link", { hidden: true }).length).toBeGreaterThan(0);
  });

  it("shows no value from a stale close, with the reason", () => {
    const { container } = render(
      <ValuationView result={{ status: "ok", data: recordedValuation.stale }} />,
    );
    expect(container.querySelector("[data-price-status]")?.getAttribute("data-price-status")).toBe("stale");
    expect(screen.getByText(/older than five days/)).toBeTruthy(); // said once, on the price line
    expect(card("market_cap").textContent).toContain("Data unavailable");
    expect(card("pe_ratio_ttm").textContent).not.toMatch(/\d+\.\d{2}x/);
  });

  it.each(Object.entries(recordedValuation))("%s renders no unexplained number", (_name, data) => {
    const { container } = render(<ValuationView result={{ status: "ok", data }} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("shows Data unavailable when the API is unreachable", () => {
    render(<ValuationView result={{ status: "unavailable" }} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
  });
});
