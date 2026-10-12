/**
 * Labels for the Alerts Center (M1.7, ADR-028): every level has its glossary term.
 */

import type { CompleteTermId } from "@/generated/glossary";

export const LEVEL_TERMS: CompleteTermId[] = [
  "convergence_l0",
  "convergence_l1",
  "convergence_l2",
  "convergence_l3",
  "convergence_l4",
];

const LEVEL_CLASSES = [
  "border-neutral-600 text-neutral-300",
  "border-sky-700 text-sky-200",
  "border-amber-600 text-amber-200",
  "border-emerald-600 text-emerald-200",
  "border-rose-600 text-rose-200",
];

export function levelTerm(level: number | null): CompleteTermId {
  return level === null ? "convergence_level" : LEVEL_TERMS[level];
}

export function levelClass(level: number | null): string {
  return level === null ? "border-neutral-800 text-neutral-500" : LEVEL_CLASSES[level];
}

export const STATUS_TEXT: Record<string, string> = {
  pass: "pass",
  fail: "fail",
  unavailable: "unavailable",
};

export const FAMILY_NAMES: Record<number, string> = {
  2: "Corporate Actions",
  3: "Fundamental & Valuation",
  4: "Earnings",
  5: "Price / Trend",
};

/** Where an evidence row is shown: EDGAR for filings, the company page for a buyback state. */
export function evidenceHref(table: string, url: string | null, ticker: string): string | null {
  if (url) return url;
  return table === "buyback_state_assignments" ? `/instruments/${ticker}#buybacks` : null;
}
