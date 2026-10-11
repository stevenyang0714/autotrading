import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedJournalCard, recordedReplay } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { JournalCardView } from "./JournalCardView";

describe("JournalCardView with recorded API responses", () => {
  it("shows each evidence item as known when the card was written", () => {
    render(<JournalCardView data={recordedJournalCard} replay={recordedReplay} />);
    const evidence = screen.getByRole("list", { name: "Evidence" });
    expect(evidence.querySelectorAll("li")).toHaveLength(5);
    expect(evidence.querySelector('[data-evidence="financial_fact"]')?.textContent).toContain("$416.161B");
    expect(evidence.querySelector('[data-evidence="price_close"]')?.textContent).toContain("$333.08");
    expect(evidence.querySelector('[data-evidence="buyback_state"]')?.textContent).toContain("ACTIVE");
    expect(evidence.textContent).toContain("Why: revenue scale");
    expect(screen.getByRole("list", { name: "Catalysts" }).textContent).toContain(
      "Fiscal Q4 results (expected 2026-10-30)",
    );
  });

  it("shows the entry, its exit and the closed paper return", () => {
    render(<JournalCardView data={recordedJournalCard} replay={recordedReplay} />);
    const decisions = within(screen.getByRole("list", { name: "Decisions" })).getAllByRole("listitem");
    expect(decisions[0].textContent).toContain("paper TRADE buy 10");
    expect(decisions[0].textContent).toContain("Close then $333.08 (2026-09-14)");
    expect(decisions[0].querySelector("[data-performance]")?.getAttribute("data-performance")).toBe("closed");
    expect(decisions[0].textContent).toContain("-0.06% vs SPY +1.83% (-1.89 pts) · -$1.90");
    expect(decisions[1].textContent).toContain("paper exit sell 10");
    expect(decisions[1].textContent).toContain("Exit at $332.89 (2026-10-05)");
  });

  it("shows the replay: every item identical", () => {
    render(<JournalCardView data={recordedJournalCard} replay={recordedReplay} />);
    expect(document.querySelector("[data-replay]")?.getAttribute("data-replay")).toBe("identical");
    const items = screen.getByRole("list", { name: "Replay items" }).querySelectorAll("li");
    expect([...items].map((li) => li.getAttribute("data-status"))).toEqual(Array(8).fill("identical")); // 5 evidence, valuation, entry and exit closes;
  });

  it("offers an exit only for an open TRADE", () => {
    let offered = 0;
    render(
      <JournalCardView
        data={recordedJournalCard}
        replay={recordedReplay}
        exitForm={() => {
          offered += 1;
          return <form aria-label="Exit" />;
        }}
      />,
    );
    expect(offered).toBe(0); // the recorded TRADE is already exited
  });

  it("renders no unexplained number", () => {
    const { container } = render(<JournalCardView data={recordedJournalCard} replay={recordedReplay} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
