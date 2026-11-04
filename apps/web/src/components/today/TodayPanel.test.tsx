import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  recordedDeliveredAlerts,
  recordedCandidates,
  recordedHoldings,
  recordedMarketsOverview,
  recordedSources,
  recordedTaiwan,
  recordedTaiwanScreens,
} from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { TodayPanel } from "./TodayPanel";

const props = {
  holdings: recordedHoldings,
  alerts: recordedDeliveredAlerts,
  candidates: recordedCandidates,
  screens: recordedTaiwanScreens,
  us: recordedMarketsOverview.market ?? null,
  taiwan: recordedTaiwan,
  sources: recordedSources,
  now: "2026-10-22T00:00:00Z",
};

describe("TodayPanel with recorded API responses", () => {
  it("puts the holdings, this week's pushes, both markets, the radar and data health first", () => {
    const { container } = render(<TodayPanel {...props} />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Today");
    const holdings = document.querySelector('[data-today="holdings"]');
    expect(holdings?.textContent).toContain("$16,684.67");
    expect(holdings?.textContent).toContain("-$19.95 in 24 h");
    expect(screen.getByRole("list", { name: "Largest weights" }).querySelectorAll("li").length).toBeGreaterThan(0);
    const pushed = props.alerts.entries.filter((a) => a.delivered_at).length;
    expect(document.querySelectorAll('[data-today="pushes"] [data-alert]')).toHaveLength(Math.min(pushed, 5));
    const markets = document.querySelector('[data-today="markets"]')?.textContent;
    expect(markets).toContain("US closed");
    expect(markets).toContain("Taiwan");
    expect(document.querySelector('[data-today="radar"]')?.textContent).toContain("flagged by the rules");
    expect(document.querySelector('[data-today="health"]')).toBeTruthy();
    const screens = document.querySelector('[data-today="screens"]')?.textContent;
    expect(screens).toContain("2026-10-22: 0 movers");
    expect(screens).toContain("波段趨勢: 0 new, 1 on watch");
    expect(screens).toContain("2026-11-03 not judged yet");
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("asks for the first entry when nothing is recorded, and says when a source is down", () => {
    render(
      <TodayPanel
        {...props}
        holdings={{ ...recordedHoldings, entries: 0, positions: [] }}
        alerts={null}
        candidates={null}
        sources={null}
      />,
    );
    expect(document.querySelector('[data-today="holdings"]')?.textContent).toContain("Nothing recorded yet");
    expect(document.querySelector('[data-today="pushes"]')?.textContent).toContain("Data unavailable");
    expect(document.querySelector('[data-today="radar"]')?.textContent).toContain("Data unavailable");
  });
});
