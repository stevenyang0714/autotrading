import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { recordedAssumptions, recordedFairValue } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { AssumptionsForm, type SaveAction } from "./AssumptionsForm";
import { FairValueView } from "./FairValueView";

function scenario(name: string): HTMLElement {
  const found = screen.getByRole("list", { name: "Scenarios" }).querySelector<HTMLElement>(
    `[data-scenario="${name}"]`,
  );
  if (!found) throw new Error(`no ${name} scenario`);
  return found;
}

function comparison(name: string): HTMLElement {
  const found = document.querySelector<HTMLElement>(`[data-comparison="${name}"]`);
  if (!found) throw new Error(`no ${name} comparison`);
  return found;
}

function dollars(element: HTMLElement): number {
  const match = /\$([\d,]+\.\d{2})/.exec(element.textContent ?? "");
  if (!match) throw new Error(`no dollar value in ${element.textContent}`);
  return Number(match[1].replace(/,/g, ""));
}

describe("FairValueView with recorded API responses", () => {
  it("labels the block as model output and names the assumptions and discount rate", () => {
    render(<FairValueView result={{ status: "ok", data: recordedFairValue.aapl }} assumptions={recordedAssumptions} ticker="AAPL" />);
    expect(document.querySelector("[data-model-output]")?.textContent).toContain("Model output, not fact");
    expect(document.querySelector("[data-model-output]")?.textContent).toContain("模型結果，不是事實");
    const used = document.querySelector("[data-assumptions]");
    expect(used?.getAttribute("data-assumptions")).toBe("default");
    expect(used?.textContent).toContain("not reviewed");
    expect(within(screen.getByLabelText("Assumption parameters")).getByText("bear 0% · base 5% · bull 10%")).toBeTruthy();
    const rate = document.querySelector("[data-discount-rate]")?.textContent ?? "";
    expect(rate).toMatch(/Discount rate.*\d+(\.\d+)?% = 10-year Treasury \d+(\.\d+)?% \(2026-10-0\d\) \+ equity risk premium 5%/);
    expect(rate).toContain("terminal growth 2.5%");
  });

  it("shows the bear, base and bull range against the price, and the reverse DCF", () => {
    render(<FairValueView result={{ status: "ok", data: recordedFairValue.aapl }} assumptions={recordedAssumptions} ticker="AAPL" />);
    const [bear, base, bull] = ["bear", "base", "bull"].map((name) => dollars(scenario(name)));
    expect(bear).toBeLessThan(base);
    expect(base).toBeLessThan(bull);
    expect(scenario("base").textContent).toContain("Base: 5% a year, years 1-5");
    expect(comparison("price").textContent).toMatch(/\$\d+\.\d{2}.*2026-10-05 close/);
    expect(comparison("implied_upside").textContent).toMatch(/-?\d+\.\d{2}%/);
    expect(comparison("margin_of_safety").textContent).toMatch(/-?\d+\.\d{2}%/);
    expect(comparison("reverse_dcf_growth").textContent).toMatch(/\d+\.\d{2}% a year, years 1-5/);
  });

  it("lists the DCF inputs with their filings, the relative table and the data dates", () => {
    render(<FairValueView result={{ status: "ok", data: recordedFairValue.aapl }} assumptions={recordedAssumptions} ticker="AAPL" />);
    const inputs = screen.getByText("DCF inputs").closest("details");
    expect(inputs?.textContent).toContain("operating cash flow - capex - SBC, last four quarters");
    expect(within(inputs as HTMLElement).getAllByRole("link", { hidden: true }).length).toBeGreaterThan(0);
    const rows = screen.getByRole("table", { name: "Relative valuation" }).querySelectorAll("[data-relative]");
    expect([...rows].map((row) => row.getAttribute("data-relative"))).toEqual([
      "pe_ratio_ttm",
      "ev_to_ebitda",
      "ev_to_sales",
      "price_to_book",
      "fcf_yield",
      "earnings_yield",
    ]);
    expect(rows[0].textContent).toMatch(/\d+\.\d{2}x.*\d+\.\d{2}x/);
    const dates = document.querySelector("[data-model-dates]")?.textContent ?? "";
    expect(dates).toMatch(/Model date .*latest filing 10-[QK] \d{10}-\d{2}-\d{6}, close 2026-10-05, 10-year Treasury 2026-10-0\d/);
  });

  it("switches versions: v1 is named with its reason and only the base growth differs", () => {
    render(<FairValueView result={{ status: "ok", data: recordedFairValue.aaplV1 }} assumptions={recordedAssumptions} ticker="AAPL" knownOn="2026-10-06" />);
    expect(document.querySelector("[data-assumptions]")?.getAttribute("data-assumptions")).toBe("v1");
    expect(screen.getByText(/services mix supports faster growth/)).toBeTruthy();
    const picker = screen.getByLabelText("Version") as HTMLSelectElement;
    expect(picker.value).toBe("1");
    expect([...picker.options].map((option) => option.value)).toEqual(["1", "default"]);
    const form = picker.closest("form");
    expect(form?.getAttribute("action")).toBe("/instruments/AAPL");
    expect((form?.querySelector('input[name="known_on"]') as HTMLInputElement).value).toBe("2026-10-06");
    expect(dollars(scenario("bear"))).toBe(Number(recordedFairValue.aapl.dcf.scenarios[0].per_share));
    expect(dollars(scenario("base"))).toBeGreaterThan(Number(recordedFairValue.aapl.dcf.scenarios[1].per_share));
  });

  it("keeps the DCF but shows no price comparison from a stale close", () => {
    render(<FairValueView result={{ status: "ok", data: recordedFairValue.stale }} assumptions={recordedAssumptions} ticker="AAPL" />);
    expect(screen.getByRole("list", { name: "Price comparison" }).getAttribute("data-comparison-price")).toBe("stale");
    expect(screen.getByRole("list", { name: "Scenarios" })).toBeTruthy();
    expect(comparison("price").textContent).toContain("older than five days");
    for (const name of ["implied_upside", "margin_of_safety", "reverse_dcf_growth"]) {
      expect(comparison(name).textContent).toContain("Data unavailable");
      expect(comparison(name).textContent).not.toMatch(/\d+\.\d{2}%/);
    }
  });

  it("explains a missing DCF (ExxonMobil reports no separate SBC line)", () => {
    render(<FairValueView result={{ status: "ok", data: recordedFairValue.xom }} assumptions={null} ticker="XOM" />);
    expect(document.querySelector("[data-dcf-status]")?.getAttribute("data-dcf-status")).toBe("unavailable");
    expect(screen.getByText(/stock-based compensation \(an assumption set can leave SBC out\)/)).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Scenarios" })).toBeNull();
    expect(screen.queryByLabelText("Version")).toBeNull(); // no list: no picker, no form
  });

  it.each(Object.entries(recordedFairValue))("%s renders no unexplained number", (_name, data) => {
    const { container } = render(
      <FairValueView result={{ status: "ok", data }} assumptions={recordedAssumptions} ticker="AAPL" action={vi.fn()} />,
    );
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("says when a version does not exist, and when the API is unreachable", () => {
    const { unmount } = render(
      <FairValueView result={{ status: "not_found", detail: "no assumption version 9" }} assumptions={recordedAssumptions} ticker="AAPL" />,
    );
    expect(screen.getByRole("alert").textContent).toContain("no assumption version 9");
    expect(screen.getByRole("link", { name: "Show the latest version" }).getAttribute("href")).toBe("/instruments/AAPL#fair-value");
    unmount();
    render(<FairValueView result={{ status: "unavailable" }} assumptions={null} ticker="AAPL" />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
  });
});

describe("AssumptionsForm", () => {
  const parameters = recordedFairValue.aapl.assumptions.parameters;

  it("starts from the version on screen, within the API's limits", () => {
    render(<AssumptionsForm ticker="AAPL" parameters={parameters} limits={recordedAssumptions.limits} action={vi.fn()} />);
    const premium = screen.getByLabelText(/Equity risk premium/) as HTMLInputElement;
    expect([premium.value, premium.min, premium.max]).toEqual(["5", "2", "10"]);
    expect((screen.getByLabelText(/Base growth/) as HTMLInputElement).value).toBe("5");
    expect((screen.getByLabelText(/Subtract stock-based compensation/) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText(/Reason/) as HTMLInputElement).required).toBe(true);
  });

  it("sends the form to the action and shows the API's reasons when it refuses", async () => {
    const action = vi.fn<SaveAction>(async () => ({
      errors: ["growth must be ordered: bear <= base <= bull"],
    }));
    render(
      <AssumptionsForm ticker="AAPL" knownOn="2026-10-06" parameters={parameters} limits={recordedAssumptions.limits} action={action} />,
    );
    fireEvent.change(screen.getByLabelText(/Bear growth/), { target: { value: "12" } });
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "Test" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save as a new version" }));
    });
    expect(action).toHaveBeenCalledTimes(1);
    const sent = action.mock.calls[0][1];
    expect(Object.fromEntries(sent.entries())).toMatchObject({
      ticker: "AAPL",
      known_on: "2026-10-06",
      growth_bear: "12",
      growth_base: "5",
      subtract_sbc: "on",
      reason: "Test",
    });
    expect((await screen.findByRole("alert")).textContent).toContain("bear <= base <= bull");
  });
});
