import type { CompleteTermId } from "@/generated/glossary";

/** The Taiwan screens (M3.11, ADR-042): labels and number formats for the page and its card. */

export const STATES: Record<string, string> = {
  entered: "新進 entered",
  on_watch: "觀察中 on watch",
  invalidated: "結束 ended",
  expired: "到期 expired",
};

export const STATUS_MARKS: Record<string, string> = {
  pass: "✓",
  fail: "✗",
  unavailable: "–",
  not_applicable: "n/a",
};

export const FLAGS: Record<string, string> = {
  action_in_window: "ex-date in window (adjusted)",
  gap_in_window: "a session without a trade in window",
  unexplained_gap: "unexplained gap (change 0, no recorded action)",
  volume_basis: "share count changed in the volume window",
  no_reading: "no reading this session",
};

export const SCREEN_TERMS: Record<string, CompleteTermId> = {
  tw_swing_trend: "screen_swing_trend",
  tw_range_breakout: "screen_range_breakout",
};

export function screenTerm(screenId: string): CompleteTermId {
  return SCREEN_TERMS[screenId] ?? "screen_rules";
}

/** A ratio as a signed percent (0.0612 -> +6.1%). */
export function signedPct(value: string | null | undefined): string {
  if (value === null || value === undefined) return "–";
  const n = Number(value) * 100;
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`;
}

export function times(value: string | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return `${Number(value).toFixed(1)}x`;
}

export function z(value: string | null | undefined): string {
  if (value === null || value === undefined) return "–";
  const n = Number(value);
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}`;
}

/** NT$ in millions (67,641,744,447 -> NT$67,641.7m). */
export function twdMillions(value: string | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return `NT$${(Number(value) / 1e6).toLocaleString("en-US", { maximumFractionDigits: 1 })}m`;
}

export function twd(value: string | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return `NT$${Number(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function share(value: string | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return `${(Number(value) * 100).toFixed(1)}%`;
}
