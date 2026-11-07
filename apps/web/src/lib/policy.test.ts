import { describe, expect, it } from "vitest";

import { band, membersText, parseMembers, points } from "./policy";

describe("policy display helpers", () => {
  it("writes drift and bands in percentage points", () => {
    expect(points("-0.0284")).toBe("-2.84 pp");
    expect(points("0.0474")).toBe("+4.74 pp");
    expect(points("0.0000")).toBe("0.00 pp");
    expect(points(null)).toBe("n/a");
    expect(band("0.0500")).toBe("± 5.00 pp");
  });

  it("reads the members as typed and writes them back the same way", () => {
    expect(parseMembers("us:spy=30, US:VOO;\nTW:2330")).toEqual([
      { key: "US:SPY", target_pct: "30" },
      { key: "US:VOO", target_pct: null },
      { key: "TW:2330", target_pct: null },
    ]);
    expect(membersText([{ key: "US:SPY", target_pct: "30.00" }, { key: "USD", target_pct: null }])).toBe("US:SPY=30, USD");
  });
});
