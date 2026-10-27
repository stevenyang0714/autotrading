import { describe, expect, it } from "vitest";

import { exactReported, formatAmount, formatMoney, formatReported, formatSigned } from "./format";

describe("formatReported", () => {
  it.each([
    ["416161000000", "USD", "$416.161B"],
    ["-147782000000", "USD", "-$147.782B"],
    ["7979000", "USD", "$7.979M"],
    ["7.46", "USD/shares", "$7.46"],
    ["6.7", "USD/shares", "$6.70"],
    ["15004697000", "shares", "15.005B shares"],
  ])("%s %s -> %s", (value, unit, expected) => {
    expect(formatReported(value, unit)).toBe(expected);
  });
});

describe("exactReported", () => {
  it("keeps every digit", () => {
    expect(exactReported("416161000000", "USD")).toBe("416,161,000,000 USD");
    expect(exactReported("-2.93", "USD/shares")).toBe("-2.93 USD/shares");
  });
});

describe("Taiwan amounts (M3.7)", () => {
  it("shows New Taiwan dollars as NT$ and keeps US prices in dollars", () => {
    expect(formatMoney("2420.00", "TWD")).toBe("NT$2,420.00");
    expect(formatMoney("-0.4", "TWD")).toBe("-NT$0.40");
    expect(formatMoney("774.74", "USD")).toBe("$774.74");
    expect(formatAmount("65515856247", "TWD")).toBe("NT$65.516B");
    expect(formatSigned("15.0000")).toBe("+15.00");
    expect(formatSigned("929", 0)).toBe("+929");
  });
});
