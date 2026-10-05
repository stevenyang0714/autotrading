import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GLOSSARY } from "@/generated/glossary";
import { DASHBOARDS } from "@/lib/dashboards";

import { Nav } from "./Nav";

const route = vi.hoisted(() => ({ pathname: "/dashboards/earnings" }));
vi.mock("next/navigation", () => ({ usePathname: () => route.pathname }));

function linksIn(group: string) {
  return within(screen.getByRole("list", { name: group })).getAllByRole("link");
}

describe("Nav", () => {
  it("links to all fifteen dashboards", () => {
    render(<Nav />);
    const links = linksIn("Dashboards");
    expect(links).toHaveLength(15);
    expect(links.map((link) => link.getAttribute("href"))).toEqual(
      DASHBOARDS.map((dashboard) => `/dashboards/${dashboard.slug}`),
    );
  });

  it("has a System group with Data Health and Instruments", () => {
    render(<Nav />);
    const links = linksIn("System");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Data Health", "/system/data-health"],
      ["Instruments", "/instruments"],
    ]);
  });

  it("keeps Instruments highlighted on a stock page", () => {
    route.pathname = "/instruments/AAPL";
    try {
      render(<Nav />);
      const current = linksIn("System").filter(
        (link) => link.getAttribute("aria-current") === "page",
      );
      expect(current.map((link) => link.textContent)).toEqual(["Instruments"]);
    } finally {
      route.pathname = "/dashboards/earnings";
    }
  });

  it("marks the current dashboard", () => {
    render(<Nav />);
    const current = linksIn("Dashboards").filter(
      (link) => link.getAttribute("aria-current") === "page",
    );
    expect(current.map((link) => link.textContent)).toEqual(["Earnings"]);
  });

  it("explains each label on hover (errata E13)", () => {
    render(<Nav />);
    const link = screen.getByRole("link", { name: "Congress Trades" });
    expect(link.closest("[data-metric]")?.getAttribute("data-term-id")).toBe(
      "dashboard_congress_trades",
    );
    fireEvent.mouseEnter(link);
    expect(screen.getByRole("tooltip").textContent).toContain(
      GLOSSARY.dashboard_congress_trades.short_definition,
    );
  });

  it("toggles the mobile menu", () => {
    render(<Nav />);
    const button = screen.getByRole("button", { name: "Menu" });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
  });

  it("contains no numbers", () => {
    const { container } = render(<Nav />);
    expect(container.textContent).not.toMatch(/\d/);
  });
});
