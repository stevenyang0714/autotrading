import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedEarnings } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { EarningsView } from "./EarningsView";

const RELEASE = "0000320193-26-000011";

function event(accession: string): HTMLElement {
  const found = document.querySelector<HTMLElement>(`[data-event="${accession}"]`);
  if (!found) throw new Error(`no event ${accession}`);
  return found;
}

describe("EarningsView with recorded API responses", () => {
  it("times each release by its acceptance and shows the quarter's actuals", () => {
    render(<EarningsView result={{ status: "ok", data: recordedEarnings.aapl }} />);
    const apple = event(RELEASE);
    expect(apple.textContent).toContain("2026-05-01 04:30 SGT · 04-30 16:30 ET");
    expect(apple.textContent).toContain("after the close");
    const table = within(apple).getByRole("table", { name: "Quarter actuals" });
    const revenue = table.querySelector('tr[data-row="revenue"]');
    expect(revenue?.textContent).toContain("$111.184B");
    expect(revenue?.querySelector('[data-change="change_yoy"]')?.textContent).toBe("+16.60%");
    expect(table.querySelector('tr[data-row="gross_margin"] [data-change="change_yoy"]')?.textContent).toBe(
      "+2.22 pts",
    );
    expect(apple.textContent).toContain("10-Q 0000320193-26-000013");
  });

  it("shows the reaction against SPY and the absent consensus", () => {
    render(<EarningsView result={{ status: "ok", data: recordedEarnings.aapl }} />);
    const reaction = within(event(RELEASE)).getByRole("table", { name: "Reaction" });
    expect(reaction.querySelector('[data-window="day 0"]')?.textContent).toContain("+2.96 pts");
    expect(reaction.querySelector('[data-window="day 0"]')?.textContent).toContain("2026-05-01");
    expect(event(RELEASE).querySelector("[data-consensus]")?.textContent).toContain(
      "Consensus estimate: Data unavailable",
    );
    expect(event(RELEASE).querySelector("[data-guidance]")?.getAttribute("data-guidance")).toBe("none");
  });

  it("on the evening of the release: no actuals and no reaction yet", () => {
    render(<EarningsView result={{ status: "ok", data: recordedEarnings.aaplEvening }} />);
    const apple = event(RELEASE);
    expect(apple.textContent).toContain("No actuals yet: 10-Q for the period to 2026-03-28 not yet public");
    expect(apple.querySelector('[data-window="day 0"]')?.textContent).toContain("no end-of-day close yet");
  });

  it("quotes guidance in the issuer's words with its exhibit", () => {
    render(<EarningsView result={{ status: "ok", data: recordedEarnings.meta }} />);
    const meta = event("0001326801-24-000010");
    const list = within(meta).getByRole("list", { name: "Guidance", hidden: true });
    expect(list.textContent).toContain("Revenue $34.500B to $37.000B");
    expect(list.querySelector("q[data-quoted]")?.textContent).toContain("first quarter 2024 total revenue");
    expect(screen.getAllByRole("link", { hidden: true }).some((a) => a.textContent === "EX-99.1")).toBe(true);
  });

  it.each(Object.entries(recordedEarnings))("%s renders no unexplained number", (_name, data) => {
    const { container } = render(<EarningsView result={{ status: "ok", data }} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
