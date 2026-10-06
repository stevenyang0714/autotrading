import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedPrices } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { InstrumentPricePanel } from "./InstrumentPricePanel";

describe("InstrumentPricePanel (recorded Alpaca data)", () => {
  it("shows the IEX quote with its feed status, the year chart and the 52-week high", () => {
    const { container } = render(<InstrumentPricePanel result={{ status: "ok", data: recordedPrices.aapl }} />);
    const panel = screen.getByRole("region", { name: "Price" });
    expect(panel.textContent).toContain("$333.11");
    expect(panel.textContent).toContain("-0.19%");
    expect(panel.textContent).toContain("bid $316.31");
    expect(panel.textContent).toContain("ask $349.69");
    expect(panel.textContent).toContain("volume 1,105,512 (IEX)");
    expect(panel.textContent).toContain("2.3% below $341.07");
    expect(panel.querySelector('[data-feed-status="end_of_day"]')).not.toBeNull();
    expect(panel.querySelector('svg[role="img"]')).not.toBeNull();
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("shows a past date's last public close on that day's split basis", () => {
    const { container } = render(
      <InstrumentPricePanel result={{ status: "ok", data: recordedPrices.nvdaBeforeSplit }} />,
    );
    // NVDA midday 2024-06-07: the 06-06 close, before the 10-for-1 split.
    expect(container.textContent).toContain("$1,209.98");
    expect(container.textContent).toContain("close of 2024-06-06");
    expect(container.textContent).not.toContain("US market");
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("shows no number without a provider key", () => {
    const { container } = render(
      <InstrumentPricePanel result={{ status: "ok", data: recordedPrices.aaplNoKey }} />,
    );
    expect(container.querySelector('[data-feed-status="unavailable"]')).not.toBeNull();
    // Only the market session (next open) carries digits; no price, change or volume.
    container.querySelector("[data-market-open]")?.remove();
    expect(container.textContent).not.toMatch(/\d|\$/);
  });

  it("shows no number when the API is down", () => {
    const { container } = render(<InstrumentPricePanel result={{ status: "unavailable" }} />);
    expect(container.textContent).toContain("Price data unavailable");
    expect(container.textContent).not.toMatch(/\d/);
  });
});
