import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedInstruments, recordedPrices } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { InstrumentList } from "./InstrumentList";

describe("InstrumentList", () => {
  it("links every recorded stock to its page", () => {
    const { container } = render(<InstrumentList data={recordedInstruments} />);
    const links = within(screen.getByRole("list", { name: "Instruments" }))
      .getAllByRole("link")
      .filter((link) => link.getAttribute("href")?.startsWith("/instruments/"));
    expect(links.map((link) => link.textContent)).toEqual(["AAPL", "XOM"]);
    expect(container.textContent).toContain("Exxon Mobil Corp");
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("shows each stock's last price with its feed status", () => {
    const { container } = render(<InstrumentList data={recordedInstruments} prices={recordedPrices.latest} />);
    const aapl = screen.getByRole("link", { name: "AAPL" }).closest("li");
    expect(aapl?.textContent).toContain("$333.11");
    expect(aapl?.textContent).toContain("-0.19%");
    expect(aapl?.querySelector('[data-feed-status="end_of_day"]')).not.toBeNull();
    expect(container.querySelector("[data-demo-banner]")).toBeNull();
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("shows only an Unavailable badge without a provider key", () => {
    render(<InstrumentList data={recordedInstruments} prices={recordedPrices.latestNoKey} />);
    const aapl = screen.getByRole("link", { name: "AAPL" }).closest("li");
    expect(aapl?.querySelector('[data-feed-status="unavailable"]')).not.toBeNull();
    expect(aapl?.textContent).not.toContain("$");
  });

  it("shows Data unavailable without numbers when the API is down", () => {
    const { container } = render(<InstrumentList data={null} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
    expect(container.textContent).not.toMatch(/\d/);
  });
});
