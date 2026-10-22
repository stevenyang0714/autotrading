import { describe, expect, it } from "vitest";

import { isTaiwanCode } from "./api";

describe("Taiwan codes (M3.7)", () => {
  it("tells a TWSE code from a US ticker", () => {
    expect(["2330", "0050", "00400A", "2330"].map(isTaiwanCode)).toEqual([true, true, true, true]);
    expect(["AAPL", "BRK.B", "SPY", "Q2"].map(isTaiwanCode)).toEqual([false, false, false, false]);
  });
});
