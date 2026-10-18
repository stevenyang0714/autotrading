import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SignalList } from "@/components/journal/SignalList";
import { CandidatesView } from "@/components/candidates/CandidatesView";
import { recordedMomentum, recordedMomentumCandidates, recordedMomentumCarried, recordedMomentumSignals } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { MomentumView } from "./MomentumView";

describe("MomentumView with recorded API responses", () => {
  it("shows the S4 target in force with every company's momentum and reason", () => {
    const { container } = render(<MomentumView data={recordedMomentum} />);
    expect(container.querySelector("[data-reason]")?.getAttribute("data-reason")).toBe("month_start");
    expect(container.querySelector("[data-target]")?.textContent).toContain("Target: NVDA (100.00% each); cash 0.00%");
    const rows = screen.getByRole("table", { name: "Company readings" }).querySelectorAll("tbody tr");
    expect([...rows].map((r) => r.getAttribute("data-company"))).toEqual([
      "AAPL",
      "MSFT",
      "GOOGL",
      "META",
      "NVDA",
      "JPM",
      "XOM",
      "AZO",
      "ORLY",
      "LOW",
    ]);
    const nvda = container.querySelector('tr[data-company="NVDA"]');
    expect(nvda?.getAttribute("data-selected")).toBe("yes");
    expect(nvda?.textContent).toContain("12-1 mom. +21.09% > 0");
    expect(nvda?.textContent).toContain("100.00%");
    // one year of recorded closes is too short for 12-1 momentum: not selected, with the reason
    const aapl = container.querySelector('tr[data-company="AAPL"]');
    expect(aapl?.getAttribute("data-selected")).toBe("no");
    expect(aapl?.textContent).toContain("12-1 mom. unavailable");
    expect(container.querySelector('tr[data-company="GOOGL"]')?.textContent).toContain("no factor snapshot known at T");
    expect(screen.getByText(/momentum rules 0\.1\.0/)).toBeTruthy();
    expect(screen.getByRole("table", { name: "Recent S4 targets" }).querySelectorAll("tbody tr")).toHaveLength(4);
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("shows a carried target with the date it was set, and says when the API is down", () => {
    const { container, unmount } = render(<MomentumView data={recordedMomentumCarried} />);
    expect(container.querySelector("[data-reason]")?.getAttribute("data-reason")).toBe("carried");
    expect(container.querySelector("[data-target]")?.textContent).toContain("set 2026-10-06");
    expect(unexplainedNumbers(container)).toEqual([]);
    unmount();
    render(<MomentumView data={null} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
  });

  it("lists the S4 signals as their own cards, with a link to write a Thesis Card", () => {
    const { container } = render(<SignalList signals={recordedMomentumSignals.current} />);
    const card = container.querySelector('[data-strategy="S4"][data-signal="NVDA"]');
    expect(card?.textContent).toContain("100.00% · long");
    expect(card?.textContent).toContain("12-1 mom. +21.09%");
    expect(card?.textContent).toContain("paper only");
    expect(card?.querySelector('a[href="/journal/new?ticker=NVDA"]')).not.toBeNull();
    // never shown as a buyback-state card
    expect(screen.getByRole("list", { name: "S4 momentum signals" })).toBeTruthy();
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("shows the S4 companies on the Opportunity Radar beside the S3 ETFs", () => {
    const { container } = render(<CandidatesView data={recordedMomentumCandidates} />);
    const s4 = container.querySelector('[data-candidates="S4"]');
    const nvda = s4?.querySelector('[data-candidate="NVDA"]');
    expect(nvda?.getAttribute("data-strategy")).toBe("S4");
    expect(nvda?.textContent).toContain("momentum rules 0.1.0");
    expect(container.querySelector('[data-candidates="S3"] [data-candidate="SPY"]')).not.toBeNull();
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
