import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { FeedStatus } from "@/lib/api";

import { DemoBanner } from "./DemoBanner";
import { FEED_STATUS, PriceBadge } from "./PriceBadge";

describe("PriceBadge", () => {
  it.each(Object.keys(FEED_STATUS) as FeedStatus[])("%s is explained by the feed_status term", (status) => {
    const { container } = render(<PriceBadge status={status} />);
    const badge = container.querySelector(`[data-feed-status="${status}"]`);
    expect(badge?.textContent).toBe(FEED_STATUS[status][0]);
    expect(badge?.closest('[data-term-id="feed_status"]')).not.toBeNull();
  });

  it("never calls a single-venue price simply live", () => {
    render(<PriceBadge status="live_single_venue" />);
    expect(screen.getByText("Live · IEX only")).toBeTruthy();
  });
});

describe("DemoBanner", () => {
  it.each<FeedStatus>(["fixture", "demo"])("shows DEMO DATA when a %s price is visible", (status) => {
    render(<DemoBanner statuses={["end_of_day", status]} />);
    expect(screen.getByRole("note", { name: "Demo data" }).textContent).toContain("DEMO DATA");
  });

  it("stays hidden for real prices", () => {
    const { container } = render(
      <DemoBanner statuses={["live_single_venue", "end_of_day", "stale", "unavailable", null]} />,
    );
    expect(container.innerHTML).toBe("");
  });
});
