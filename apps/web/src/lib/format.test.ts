import { describe, expect, it } from "vitest";

import { exactReported, formatReported } from "./format";

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
