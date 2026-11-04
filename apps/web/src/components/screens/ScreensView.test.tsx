import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedTaiwanScreens, recordedTaiwanScreensHistory } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { ScreensView } from "./ScreensView";

describe("ScreensView with recorded API responses", () => {
  it("shows the session's coverage, each screen's definition and watch list, the history and the sources", () => {
    const { container } = render(
      <ScreensView data={recordedTaiwanScreens} history={recordedTaiwanScreensHistory} invalidKnownOn={false} />,
    );
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Taiwan Screens");
    expect(document.querySelector("[data-run]")?.textContent).toContain("coverage 1,077 of 1,083 (99.5%)");
    expect(document.querySelector("[data-run]")?.textContent).toContain("screen rules 0.1.0");
    // a later session whose files have not come is named, with why
    expect(document.querySelector("[data-pending]")?.textContent).toContain("2026-11-03 not judged");
    expect(screen.queryByRole("note", { name: "Demo data" })).toBeNull();
    expect(document.querySelector('[data-block="movers"]')?.textContent).toContain("No mover this session.");

    const swing = document.querySelector('[data-screen="tw_swing_trend"]');
    expect(swing?.textContent).toContain("收盤價高於 20 日均線");
    expect(swing?.textContent).toContain("連續 2 日收盤低於 20 日均線");
    const row = swing?.querySelector('tr[data-code="2881"]');
    expect(row?.getAttribute("data-state")).toBe("on_watch");
    expect(row?.textContent).toContain("富邦金");
    expect(row?.textContent).toContain("金融保險業");
    expect(row?.textContent).toContain("since 2026-10-01, 15 sessions");
    expect(row?.querySelectorAll('[data-status="pass"]').length).toBeGreaterThan(0);
    expect(row?.querySelector('[data-status="not_applicable"]')).toBeTruthy(); // one company in industry 17
    expect(row?.textContent).toContain("twse");
    expect(document.querySelector('[data-screen="tw_range_breakout"]')?.textContent).toContain(
      "Nothing on the watch list.",
    );

    const history = document.querySelector('[data-block="history"]');
    expect(history?.textContent).toContain("15 sessions");
    expect(history?.querySelector('[data-history="tw_range_breakout"]')?.textContent).toContain(
      "none on 100.0% of sessions",
    );
    expect(history?.textContent).not.toMatch(/return [0-9]/);
    const attribution = document.querySelector('[data-block="attribution"]')?.textContent;
    expect(attribution).toContain("政府資料開放授權條款");
    expect(attribution).toContain("資料來源：FinMind");
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("says when no session is judged yet", () => {
    render(
      <ScreensView
        data={{ ...recordedTaiwanScreens, run: null, rules: null, pending: null }}
        history={null}
        invalidKnownOn={false}
      />,
    );
    expect(screen.getByText(/No judged session yet/)).toBeTruthy();
    expect(screen.getByText(/the history check could not be loaded/)).toBeTruthy();
  });
});
