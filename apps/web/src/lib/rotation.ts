/**
 * Labels for the S3 ETF rotation and the Opportunity Radar candidates (M2.4, ADR-032): every
 * reason, sleeve and measure has its glossary term. Pure.
 */
import type { CompleteTermId } from "@/generated/glossary";
import type { Rotation, TrendReading } from "@/lib/api";
import { MEASURES } from "@/lib/factors";

export const REASONS: Record<string, { label: string; termId: CompleteTermId }> = {
  month_start: { label: "Monthly target", termId: "rotation_rebalance" },
  defensive_switch: { label: "Defensive switch", termId: "defensive_switch" },
  carried: { label: "Carried within the month", termId: "rotation_rebalance" },
  unavailable: { label: "Unavailable", termId: "etf_rotation" },
};

export const SLEEVES: Record<string, { label: string; termId: CompleteTermId }> = {
  risk: { label: "Risk", termId: "risk_sleeve" },
  defensive: { label: "Defensive", termId: "defensive_sleeve" },
};

/** "+56.04%" for a trend measure, "1.433" for a beta. */
export function signedPct(value: string): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}

export function beta(value: string | null): string {
  if (value === null) return "n/a";
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(3) : value;
}

/** "25.00%": a weight as stored (exact to 0.01). */
export function weight(value: string): string {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)}%` : value;
}

export function measureMeta(measure: string): { label: string; short: string; termId: CompleteTermId } {
  return MEASURES[measure] ?? { label: measure.replaceAll("_", " "), short: measure, termId: "trend_filter" };
}

/** "12-1 mom. +56.04% > 0": one trend condition as read. */
export function trendText(reading: TrendReading): string {
  const meta = measureMeta(reading.measure);
  if (reading.value === null) return `${meta.short} unavailable`;
  const sign = reading.status === "pass" ? ">" : "≤";
  return `${meta.short} ${signedPct(reading.value)} ${sign} ${Number(reading.threshold)}`;
}

/** Whether any ETF reading used recorded demo closes (the CI fixtures). */
export function usesFixture(rotation: Rotation | null | undefined): boolean {
  return Boolean(rotation?.readings.some((r) => r.feed_status === "fixture"));
}

/** "SPY, QQQ (25.00% each)" or "cash only". */
export function heldText(target: Record<string, string>): string {
  const symbols = Object.keys(target);
  if (symbols.length === 0) return "cash only";
  const weights = new Set(Object.values(target).map((w) => Number(w).toFixed(2)));
  const each = weights.size === 1 ? ` (${[...weights][0]}% each)` : "";
  return `${symbols.join(", ")}${each}`;
}

/** A reading's reason with measure ids as words: "trend not up: vs 200d avg". */
export function readable(detail: string): string {
  return detail.replace(/\b[a-z]+(?:_[a-z0-9]+)+\b/g, (id) => MEASURES[id]?.short ?? id.replaceAll("_", " "));
}
