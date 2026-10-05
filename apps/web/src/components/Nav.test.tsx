import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DASHBOARDS } from "@/lib/dashboards";

import { Nav } from "./Nav";

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboards/earnings" }));

function dashboardLinks() {
  return within(screen.getByRole("list")).getAllByRole("link");
}

describe("Nav", () => {
  it("links to all fifteen dashboards", () => {
    render(<Nav />);
    const links = dashboardLinks();
    expect(links).toHaveLength(15);
    expect(links.map((link) => link.getAttribute("href"))).toEqual(
      DASHBOARDS.map((dashboard) => `/dashboards/${dashboard.slug}`),
    );
  });

  it("marks the current dashboard", () => {
    render(<Nav />);
    const current = dashboardLinks().filter((link) => link.getAttribute("aria-current") === "page");
    expect(current.map((link) => link.textContent)).toEqual(["Earnings"]);
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
