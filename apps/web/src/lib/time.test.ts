import { describe, expect, it } from "vitest";

import { formatDuration, formatSgtEt } from "./time";

describe("time display (ADR-005)", () => {
  it("shows SGT with ET alongside", () => {
    // 01:30 UTC = 09:30 SGT = 21:30 EDT on the previous day.
    expect(formatSgtEt("2026-10-05T01:30:00Z")).toBe("2026-10-05 09:30 SGT · 10-04 21:30 ET");
  });

  it("formats SLA durations", () => {
    expect(formatDuration(172800)).toBe("2 days");
    expect(formatDuration(7200)).toBe("2 hours");
    expect(formatDuration(3600)).toBe("1 hour");
    expect(formatDuration(900)).toBe("15 min");
    expect(formatDuration(45)).toBe("45 s");
  });
});
