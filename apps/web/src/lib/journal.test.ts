import { describe, expect, it } from "vitest";

import { recordedJournalCard } from "@/test/fixtures";

import { decisionLabel, formatPnl, formatPoints, performanceSummary } from "./journal";

describe("journal formats", () => {
  const [entry, exit] = recordedJournalCard.decisions;

  it("labels decisions", () => {
    expect(decisionLabel(entry)).toBe("paper TRADE buy 10");
    expect(decisionLabel(exit)).toBe("paper exit sell 10");
    expect(decisionLabel({ ...entry, decision: "no_trade", no_trade_reason: "excessive_risk" })).toBe(
      "NO TRADE: Excessive risk",
    );
    expect(decisionLabel({ ...entry, order_type: "limit", limit_price: "250" })).toBe(
      "paper TRADE buy 10 (limit $250.00)",
    );
  });

  it("formats money, points and the return against SPY", () => {
    expect(formatPnl("-1.90")).toBe("-$1.90");
    expect(formatPnl("150")).toBe("+$150.00");
    expect(formatPoints("3.9")).toBe("+3.90 pts");
    expect(performanceSummary(entry.performance!)).toBe("-0.06% vs SPY +1.83% (-1.89 pts)");
    expect(
      performanceSummary({ ...entry.performance!, status: "unavailable", return_pct: null, detail: "no close yet" }),
    ).toBe("no close yet");
  });
});
