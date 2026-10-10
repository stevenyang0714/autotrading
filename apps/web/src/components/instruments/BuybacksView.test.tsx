import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedBuybacks } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { BuybacksView, formatAnnounced } from "./BuybacksView";

function block(name: string): HTMLElement {
  const found = document.querySelector<HTMLElement>(`[data-block="${name}"]`);
  if (!found) throw new Error(`no ${name} block`);
  return found;
}

describe("BuybacksView with recorded API responses", () => {
  it("keeps authorization, actual repurchase and net share reduction apart", () => {
    render(<BuybacksView result={{ status: "ok", data: recordedBuybacks.aapl }} />);
    expect(block("authorization")).toBeTruthy();
    expect(within(block("repurchase")).getByRole("table", { name: "Actual repurchase" })).toBeTruthy();
    expect(within(block("net-share-reduction")).getByRole("table", { name: "Net share reduction" })).toBeTruthy();
    const repurchase = block("repurchase").querySelector('tr[data-row="share_repurchases"]');
    expect(repurchase?.querySelectorAll("td")[1].textContent).toContain("$90.711B");
    const reduction = block("net-share-reduction").querySelector('tr[data-row="net_share_reduction"]');
    expect(reduction?.querySelectorAll("td")[1].textContent).toContain("343.526M shares");
  });

  it("shows each announcement in the issuer's words with its filing", () => {
    render(<BuybacksView result={{ status: "ok", data: recordedBuybacks.aapl }} />);
    const events = within(screen.getByRole("list", { name: "Announcements" })).getAllByRole("listitem", { hidden: true });
    const latest = events[0];
    expect(latest.getAttribute("data-event-kind")).toBe("increase");
    expect(latest.textContent).toContain("Authorization increase $100 billion");
    expect(latest.textContent).toContain("2026-04-30");
    expect(latest.querySelector("q[data-quoted]")?.textContent).toMatch(/authorized .*\$100 billion/);
    expect(within(latest).getAllByRole("link").some((a) => a.textContent?.includes("0000320193-26-000011"))).toBe(true);
    expect(within(screen.getByRole("list", { name: "As tagged in filings" })).getAllByRole("link").length).toBeGreaterThan(0);
  });

  it("shows a yearly plan and an untagged authorization (ExxonMobil)", () => {
    render(<BuybacksView result={{ status: "ok", data: recordedBuybacks.xom }} />);
    expect(screen.getByRole("list", { name: "Announcements" }).textContent).toContain("Buyback plan $20 billion");
    expect(screen.getByRole("list", { name: "As tagged in filings" }).textContent).toContain(
      "not tagged in the 10-Q or 10-K",
    );
  });

  it.each(Object.entries(recordedBuybacks))("%s renders no unexplained number", (_name, data) => {
    const { container } = render(<BuybacksView result={{ status: "ok", data }} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("formats announced amounts as issuers write them", () => {
    expect([formatAnnounced("110000000000"), formatAnnounced("14700000000"), formatAnnounced("500000000")]).toEqual([
      "$110 billion",
      "$14.7 billion",
      "$500 million",
    ]);
  });

  it("shows Data unavailable when the API is unreachable", () => {
    render(<BuybacksView result={{ status: "unavailable" }} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
  });
});
