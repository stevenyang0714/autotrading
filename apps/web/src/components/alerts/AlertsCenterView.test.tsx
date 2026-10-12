import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedAlerts, recordedConvergence, recordedOpenAlerts } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { type AlertFilters, AlertsCenterView } from "./AlertsCenterView";

const ALL: AlertFilters = { status: "all", levelMin: 0, includeBackfilled: true };

describe("AlertsCenterView with recorded API responses", () => {
  it("shows each company's level with every check, L4 unavailable", () => {
    render(<AlertsCenterView alerts={recordedAlerts} convergence={recordedConvergence} filters={ALL} />);
    const apple = within(screen.getByRole("list", { name: "Convergence by company" }))
      .getByText("AAPL")
      .closest("li");
    expect(apple?.textContent).toContain("L1 Watch");
    expect(apple?.querySelector('[data-check="2"]')?.textContent).toContain("no valuation support");
    expect(apple?.querySelector('[data-check="4"]')?.getAttribute("data-status")).toBe("unavailable");
    expect(apple?.querySelector('[data-check="4"]')?.textContent).toContain("Phase 2 risk check");
    expect(apple?.textContent).toContain("Buyback state ACTIVE · Market confirmation");
  });

  it("lists alerts with their rule version and evidence", () => {
    render(<AlertsCenterView alerts={recordedAlerts} convergence={recordedConvergence} filters={ALL} />);
    const list = screen.getByRole("list", { name: "Alerts" });
    const level = list.querySelector('[data-kind="level_change"]');
    expect(level?.textContent).toContain("AAPL reached L1 Watch");
    expect(level?.textContent).toContain("alert rules 0.1.0");
    expect(level?.textContent).toContain("backfilled");
    const link = level?.querySelector('a[href="/instruments/AAPL#buybacks"]');
    expect(link?.textContent).toBe("Buyback state ACTIVE");
    expect(list.querySelector('[data-kind="event"]')?.textContent).toContain("L0 Information");
    expect(document.querySelector("[data-in-app]")?.textContent).toContain("IN-APP ONLY");
  });

  it("offers acknowledgement on open alerts and shows it once given", () => {
    const [first, ...rest] = recordedOpenAlerts.entries;
    const acknowledged = {
      ...recordedOpenAlerts,
      entries: [
        { ...first, acknowledgement: { acknowledged_at: "2026-10-07T01:00:00Z", note: "seen, no action" } },
        ...rest,
      ],
    };
    render(
      <AlertsCenterView
        alerts={acknowledged}
        convergence={recordedConvergence}
        filters={{ status: "open", levelMin: 0, includeBackfilled: false }}
        acknowledgeForm={(alert) => <form aria-label={`Acknowledge ${alert.id}`} />}
      />,
    );
    expect(screen.getByText(/Acknowledged .*: seen, no action/)).toBeTruthy();
    expect(screen.queryByRole("form", { name: `Acknowledge ${first.id}` })).toBeNull();
    for (const alert of rest) {
      expect(screen.getByRole("form", { name: `Acknowledge ${alert.id}` })).toBeTruthy();
    }
    expect(document.querySelector("[data-open]")?.textContent).toContain("L0 Information");
  });

  it.each([
    ["all", recordedAlerts],
    ["open", recordedOpenAlerts],
  ] as const)("%s renders no unexplained number", (_name, alerts) => {
    const { container } = render(
      <AlertsCenterView alerts={alerts} convergence={recordedConvergence} filters={ALL} />,
    );
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
