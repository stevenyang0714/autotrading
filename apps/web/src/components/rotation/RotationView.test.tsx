import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedRotation, recordedRotationEarlier } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { RotationView } from "./RotationView";

describe("RotationView with recorded API responses", () => {
  it("shows the target in force with every ETF's trend, beta and gate", () => {
    const { container } = render(<RotationView data={recordedRotation} />);
    expect(container.querySelector("[data-reason]")?.getAttribute("data-reason")).toBe("month_start");
    expect(container.querySelector("[data-stress]")?.textContent).toBe("NORMAL");
    expect(container.querySelector("[data-target]")?.textContent).toContain("Target: SPY (100.00% each); cash 0.00%");
    const rows = screen.getByRole("table", { name: "ETF readings" }).querySelectorAll("tbody tr");
    expect([...rows].map((r) => r.getAttribute("data-etf"))).toEqual([
      "SPY",
      "QQQ",
      "IWM",
      "XLK",
      "XLE",
      "TLT",
      "IEF",
      "GLD",
    ]);
    const spy = container.querySelector('tr[data-etf="SPY"]');
    expect(spy?.getAttribute("data-eligible")).toBe("yes");
    expect(spy?.textContent).toContain("12-1 mom.");
    expect(spy?.textContent).toContain("100.00%");
    // one year of recorded closes is too short for 12-1 momentum: not selected, with the reason
    const qqq = container.querySelector('tr[data-etf="QQQ"]');
    expect(qqq?.getAttribute("data-eligible")).toBe("no");
    expect(qqq?.textContent).toContain("12-1 mom. unavailable");
    expect(qqq?.textContent).toContain("trend not up: 12-1 mom.");
    expect(screen.getByText(/rotation rules 0\.2\.0/)).toBeTruthy();
    expect(screen.getByRole("table", { name: "Recent targets" }).querySelectorAll("tbody tr")).toHaveLength(4);
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("says when nothing was assessed by the date, and when the API is down", () => {
    const { container, unmount } = render(<RotationView data={recordedRotationEarlier} />);
    expect(container.textContent).toContain("No rotation assessment by this date");
    expect(unexplainedNumbers(container)).toEqual([]);
    unmount();
    render(<RotationView data={null} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
  });
});
