import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  recordedAlerts,
  recordedConvergence,
  recordedDeliveredAlerts,
  recordedOpenAlerts,
  recordedRegimeAlerts,
} from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { type AlertFilters, AlertsCenterView } from "./AlertsCenterView";

const ALL: AlertFilters = { status: "all", levelMin: 0, includeBackfilled: true };

describe("AlertsCenterView with recorded API responses", () => {
  it("shows each company's level with every check, L4 reading the standard risk check", () => {
    render(<AlertsCenterView alerts={recordedAlerts} convergence={recordedConvergence} filters={ALL} />);
    const apple = within(screen.getByRole("list", { name: "Convergence by company" }))
      .getByText("AAPL")
      .closest("li");
    expect(apple?.textContent).toContain("L1 Watch");
    expect(apple?.querySelector('[data-check="2"]')?.textContent).toContain("no valuation support");
    expect(apple?.querySelector('[data-check="4"]')?.getAttribute("data-status")).toBe("fail");
    expect(apple?.querySelector('[data-check="4"]')?.textContent).toContain("needs L3 first (standard risk check passes)");
    expect(apple?.textContent).toContain("Buyback state ACTIVE · Market confirmation");
  });

  it("lists alerts with their rule version and evidence", () => {
    render(<AlertsCenterView alerts={recordedAlerts} convergence={recordedConvergence} filters={ALL} />);
    const list = screen.getByRole("list", { name: "Alerts" });
    const level = list.querySelector('[data-kind="level_change"]');
    expect(level?.textContent).toContain("AAPL reached L1 Watch");
    expect(level?.textContent).toContain("alert rules 0.6.0");
    expect(level?.textContent).toContain("backfilled");
    const link = level?.querySelector('a[href="/instruments/AAPL#buybacks"]');
    expect(link?.textContent).toBe("Buyback state ACTIVE");
    expect(list.querySelector('[data-kind="event"]')?.textContent).toContain("L0 Information");
    expect(document.querySelector("[data-in-app]")?.textContent).toContain("IN-APP ONLY");
    expect(document.querySelector("[data-in-app]")?.textContent).toContain("standard paper position");
    expect(document.querySelector("[data-delivery]")?.getAttribute("data-delivery")).toBe("off");
    expect(document.querySelector("[data-delivery]")?.textContent).toContain("Telegram not set up");
    expect(list.querySelector("[data-delivered]")).toBeNull();
  });

  it("says when Telegram is on and when each alert was pushed (M3.0b)", () => {
    const { container } = render(
      <AlertsCenterView alerts={recordedDeliveredAlerts} convergence={recordedConvergence} filters={ALL} />,
    );
    expect(document.querySelector("[data-in-app]")?.textContent).toContain("TELEGRAM ON");
    expect(document.querySelector("[data-delivery]")?.textContent).toContain("delivery rules 0.2.0");
    const pushed = [...container.querySelectorAll("[data-alert]")].filter((a) => a.querySelector("[data-delivered]"));
    expect(pushed.length).toBe(recordedDeliveredAlerts.entries.filter((e) => e.delivered_at).length);
    expect(pushed[0]?.textContent).toContain("sent to Telegram");
    expect(container.textContent).not.toContain("987654321");
    expect(unexplainedNumbers(container)).toEqual([]);
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

  it("shows a market-wide stress alert with its state and a link to the regime then", () => {
    render(<AlertsCenterView alerts={recordedRegimeAlerts} convergence={recordedConvergence} filters={ALL} />);
    const market = screen.getByRole("list", { name: "Alerts" }).querySelector('[data-kind="regime"]');
    expect(market?.textContent).toContain("Market stress eased to NORMAL (was ELEVATED)");
    expect(market?.textContent).toContain("NORMAL");
    // Assessed 2026-10-06 18:00 UTC = 10-07 02:00 SGT: As known on 10-07 is the first day that includes it.
    expect(market?.querySelector('a[href="/dashboards/market-regime?known_on=2026-10-07"]')).not.toBeNull();
  });

  it.each([
    ["regime", recordedRegimeAlerts],
    ["all", recordedAlerts],
    ["open", recordedOpenAlerts],
  ] as const)("%s renders no unexplained number", (_name, alerts) => {
    const { container } = render(
      <AlertsCenterView alerts={alerts} convergence={recordedConvergence} filters={ALL} />,
    );
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
