/**
 * Labels for the Market Regime page (M2.1, ADR-029): every dimension, state and flag has its
 * glossary term.
 */

import type { CompleteTermId } from "@/generated/glossary";

export const DIMENSIONS: Record<string, { label: string; termId: CompleteTermId }> = {
  growth: { label: "Growth", termId: "regime_growth" },
  inflation: { label: "Inflation", termId: "regime_inflation" },
  policy: { label: "Policy and liquidity", termId: "regime_policy" },
  credit: { label: "Credit", termId: "regime_credit" },
  volatility: { label: "Volatility", termId: "regime_volatility" },
};

export const STRESS: Record<string, { label: string; termId: CompleteTermId; className: string }> = {
  normal: { label: "NORMAL", termId: "stress_normal", className: "border-emerald-700 bg-emerald-950/40 text-emerald-100" },
  elevated: { label: "ELEVATED", termId: "stress_elevated", className: "border-amber-600 bg-amber-950/40 text-amber-100" },
  high: { label: "HIGH", termId: "stress_high", className: "border-orange-600 bg-orange-950/40 text-orange-100" },
  crisis: { label: "CRISIS", termId: "stress_crisis", className: "border-rose-600 bg-rose-950/50 text-rose-100" },
};

export const FLAGS: Record<string, CompleteTermId> = {
  credit_stress: "stress_flag_credit",
  volatility_stress: "stress_flag_volatility",
  nfci_tight: "stress_flag_nfci",
  stlfsi_high: "stress_flag_stlfsi",
  vix_inverted: "stress_flag_vix_term",
  equity_drawdown: "stress_flag_drawdown",
  dollar_surge: "stress_flag_dollar",
  oil_shock: "stress_flag_oil",
  stock_bond_selloff: "stress_flag_stock_bond",
};

export const QUADRANTS: Record<string, string> = {
  goldilocks: "Goldilocks",
  reflation: "Reflation",
  stagflation: "Stagflation",
  disinflationary_slowdown: "Disinflationary slowdown",
};

/** "near target", "above target": a state as words. */
export function stateText(state: string): string {
  return state.replace(/_/g, " ");
}

/** Cell colour of a dimension state in the history grid, from calm/easy to stressed/tight. */
const TONE: Record<string, string> = {
  expanding: "bg-emerald-800",
  slowing: "bg-amber-700",
  contracting: "bg-rose-700",
  below_target: "bg-sky-800",
  near_target: "bg-emerald-800",
  above_target: "bg-amber-700",
  hot: "bg-rose-700",
  easy: "bg-sky-800",
  neutral: "bg-emerald-800",
  tight: "bg-amber-700",
  calm: "bg-emerald-800",
  normal: "bg-emerald-700",
  stressed: "bg-orange-700",
  distressed: "bg-rose-700",
  elevated: "bg-amber-700",
  high: "bg-orange-700",
  crisis: "bg-rose-700",
};

export function toneOf(state: string | null | undefined): string {
  return (state && TONE[state]) || "bg-neutral-800";
}

/** "-0.548" for "-0.54800": a stored decimal without trailing zeros past two places. */
export function trimDecimal(value: string): string {
  if (!value.includes(".")) return value;
  const [whole, fraction] = value.split(".");
  const kept = fraction.replace(/0+$/, "");
  return kept.length >= 2 ? `${whole}.${kept}` : `${whole}.${(kept + "00").slice(0, 2)}`;
}
