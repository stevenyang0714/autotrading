import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedMarketsOverview, recordedOverview, recordedSources } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { OverviewView } from "./OverviewView";

function block(container: HTMLElement, id: string): HTMLElement {
  const element = container.querySelector<HTMLElement>(`[data-block="${id}"]`);
  if (!element) throw new Error(`block ${id} missing`);
  return element;
}

describe("OverviewView (recorded FRED data)", () => {
  it("shows six blocks, each with a chart and a cited insight", () => {
    const { container } = render(<OverviewView data={recordedOverview.now} sources={recordedSources} />);
    for (const id of ["inflation", "labor", "growth", "policy", "curve", "risk"]) {
      const element = block(container, id);
      expect(element.querySelector("svg[role=img]")).not.toBeNull();
      expect(element.textContent).toContain("Based on");
    }
    expect(block(container, "labor").textContent).toContain("Aug 2026 revised -60K from its first release");
  });

  it("shows the labor block as known before the August revision", () => {
    const { container } = render(
      <OverviewView data={recordedOverview.beforeRevision} sources={recordedSources} knownOn="2026-09-30" />,
    );
    expect(block(container, "labor").textContent).toContain("in Aug 2026");
    expect(container.querySelector("#known_on")).toHaveProperty("value", "2026-09-30");
  });

  it("shows how fresh the data is, with the next scheduled refresh", () => {
    render(<OverviewView data={recordedOverview.now} sources={recordedSources} />);
    const freshness = screen.getByRole("list", { name: "Data freshness" });
    expect(within(freshness).getAllByText("Fresh").length).toBeGreaterThan(0);
    expect(freshness.querySelector('[data-term-id="next_refresh"]')).not.toBeNull();
  });

  it("adds Chinese names to key labels and tooltips", () => {
    render(<OverviewView data={recordedOverview.now} sources={recordedSources} />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("總覽");
    fireEvent.mouseEnter(screen.getAllByText("非農就業人數")[0]);
    expect(screen.getByRole("tooltip").textContent).toContain("非農就業人數");
  });

  it("shows the markets block: ETF prices with feed status, SPY's year and an insight", () => {
    const { container } = render(<OverviewView data={recordedMarketsOverview} sources={recordedSources} />);
    const markets = block(container, "markets");
    const tiles = within(markets).getByRole("list", { name: "Market prices" });
    expect(tiles.querySelectorAll("li")).toHaveLength(8);
    const spy = tiles.querySelector('[data-symbol="SPY"]');
    expect(spy?.textContent).toContain("$774.74");
    expect(spy?.textContent).toContain("+0.66%");
    expect(spy?.querySelector("[data-feed-status]")).not.toBeNull();
    expect(markets.querySelector("svg[role=img]")).not.toBeNull();
    expect(markets.textContent).toContain("0.4% below its 52-week high");
    expect(markets.querySelector("[data-market-open]")).not.toBeNull();
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it.each(Object.entries(recordedOverview))("%s renders no unexplained number", (_name, data) => {
    const { container } = render(<OverviewView data={data} sources={recordedSources} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
