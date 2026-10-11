/**
 * Labels and formats for buyback states (M1.4b, ADR-025). Every condition, state and score
 * component has its own glossary term; values are formatted in the unit the API states.
 */

import type { CompleteTermId } from "@/generated/glossary";
import type { RuleSet, StateCondition, StateId } from "@/lib/api";

export const STATE_LABELS: Record<StateId, string> = {
  none: "No state",
  watch: "WATCH",
  active: "ACTIVE",
  high_conviction: "HIGH-CONVICTION candidate",
  trade_ready: "TRADE-READY",
};

export const STATE_TERMS: Record<StateId, CompleteTermId> = {
  none: "buyback_state",
  watch: "buyback_state_watch",
  active: "buyback_state_active",
  high_conviction: "buyback_state_high_conviction",
  trade_ready: "buyback_state_trade_ready",
};

/** Badge colours: the higher the state, the stronger; none stays neutral. */
export const STATE_STYLES: Record<StateId, string> = {
  none: "border-neutral-700 text-neutral-300",
  watch: "border-sky-700 bg-sky-950/50 text-sky-200",
  active: "border-emerald-700 bg-emerald-950/50 text-emerald-200",
  high_conviction: "border-amber-600 bg-amber-950/50 text-amber-200",
  trade_ready: "border-fuchsia-600 bg-fuchsia-950/50 text-fuchsia-200",
};

export type Level = StateCondition["level"];

export const LEVELS: { level: Level; label: string; termId: CompleteTermId }[] = [
  { level: "watch", label: "WATCH", termId: "buyback_state_watch" },
  { level: "active", label: "ACTIVE", termId: "buyback_state_active" },
  { level: "high_conviction", label: "HIGH-CONVICTION", termId: "buyback_state_high_conviction" },
  { level: "trade_ready", label: "TRADE-READY", termId: "buyback_state_trade_ready" },
];

export const CONDITIONS: Record<string, { label: string; short: string; termId: CompleteTermId }> = {
  "watch.announcement": {
    label: "Authorization or plan announced",
    short: "Announced",
    termId: "repurchase_announcement",
  },
  "watch.remaining": {
    label: "Remaining authorization / market cap",
    short: "Remaining",
    termId: "remaining_to_market_cap",
  },
  "active.quarter_repurchase": {
    label: "Quarter repurchases / market cap",
    short: "Quarter",
    termId: "quarter_repurchase_to_market_cap",
  },
  "active.diluted_shares": {
    label: "Diluted share change",
    short: "Diluted",
    termId: "diluted_shares_change",
  },
  "high_conviction.fcf_funding": {
    label: "Repurchases / free cash flow",
    short: "FCF funding",
    termId: "fcf_funding",
  },
  "high_conviction.net_debt": {
    label: "Net debt change",
    short: "Net debt",
    termId: "net_debt_change_yoy",
  },
  "high_conviction.fcf_yield": {
    label: "FCF yield / 5-year median",
    short: "FCF yield",
    termId: "fcf_yield_to_median",
  },
  "high_conviction.dcf_discount": {
    label: "Margin of safety to the base DCF",
    short: "DCF",
    termId: "margin_of_safety",
  },
  "trade_ready.above_average": {
    label: "Close vs 50-session average",
    short: "Trend",
    termId: "close_vs_moving_average",
  },
  "trade_ready.relative_return": {
    label: "1-month return vs SPY",
    short: "vs SPY",
    termId: "relative_return_1m",
  },
  "trade_ready.risk_check": { label: "Risk check", short: "Risk", termId: "risk_check" },
};

export function conditionMeta(id: string): { label: string; short: string; termId: CompleteTermId } {
  return CONDITIONS[id] ?? { label: id, short: id, termId: "condition_status" };
}

export const COMPONENTS: Record<string, { label: string; termId: CompleteTermId }> = {
  undervaluation: { label: "Undervaluation", termId: "buyback_score_undervaluation" },
  intensity: { label: "Repurchase intensity", termId: "buyback_score_intensity" },
  fcf_quality: { label: "FCF quality", termId: "buyback_score_fcf_quality" },
  balance_sheet: { label: "Balance sheet", termId: "buyback_score_balance_sheet" },
  discipline: { label: "Historical discipline", termId: "buyback_score_discipline" },
  share_count: { label: "Net share count", termId: "buyback_score_share_count" },
};

export function componentMeta(id: string): { label: string; termId: CompleteTermId } {
  return COMPONENTS[id] ?? { label: id, termId: "buyback_quality_score" };
}

/** "0.61%", "0.60x", "159 days", "+1.21 pts": a measured value in its unit. */
export function formatMeasure(value: string | null, unit: string): string {
  if (value === null) return "n/a";
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  switch (unit) {
    case "percent":
      return `${number.toFixed(2)}%`;
    case "x":
      return `${number.toFixed(2)}x`;
    case "days":
      return `${number} days ago`;
    case "percentage points":
      return `${number > 0 ? "+" : ""}${number.toFixed(2)} pts`;
    default:
      return value;
  }
}

const COMPARE: Record<string, string> = { at_least: "≥", at_most: "≤", above: ">" };

/** "≥ 0.5%", "≤ 1.2x", "within 365 days": what the rule asks for. */
export function formatThreshold(condition: StateCondition): string {
  if (condition.threshold === null || condition.comparison === null) return "Phase 2";
  const number = Number(condition.threshold);
  if (condition.unit === "days") return `within ${number} days`;
  const unit =
    condition.unit === "percent" ? "%" : condition.unit === "x" ? "x" : condition.unit === "percentage points" ? " pts" : "";
  return `${COMPARE[condition.comparison] ?? condition.comparison} ${number}${unit}`;
}

export const STATUS_STYLES: Record<StateCondition["status"], string> = {
  pass: "text-emerald-300",
  fail: "text-rose-300",
  unavailable: "text-neutral-500",
};

export const STATUS_LABELS: Record<StateCondition["status"], string> = {
  pass: "pass",
  fail: "fail",
  unavailable: "unavailable",
};

/** The units of a condition's inputs, by input name (the API names them). */
export function inputUnit(name: string): string {
  if (["fcf_yield", "fcf_yield_median", "return", "benchmark_return"].includes(name)) return "percent";
  if (["price", "moving_average", "fair_value_dcf"].includes(name)) return "USD/shares";
  if (name.startsWith("shares_outstanding") || name.includes("diluted_shares")) return "shares";
  return "USD";
}

export const INPUT_LABELS: Record<string, string> = {
  share_repurchases_quarter: "Repurchases in the quarter",
  share_repurchases: "Share repurchases",
  share_repurchases_ttm: "Share repurchases, last four quarters",
  free_cash_flow: "Free cash flow",
  free_cash_flow_ttm: "Free cash flow, last four quarters",
  market_cap: "Market cap",
  diluted_shares: "Diluted shares",
  net_debt: "Net debt",
  fcf_yield: "FCF yield at T",
  fcf_yield_median: "Median FCF yield",
  fair_value_dcf: "Base DCF value per share",
  price: "Price",
  moving_average: "Moving average",
  return: "Return",
  benchmark_return: "SPY return",
  net_income: "Net income",
  net_income_ttm: "Net income, last four quarters",
  repurchase_to_fcf: "Repurchases / FCF",
  net_share_reduction: "Net share reduction",
  shares_outstanding: "Shares outstanding",
};

/** "$500 billion": a rule's dollar line. */
export function formatBillions(value: string): string {
  return `$${(Number(value) / 1e9).toLocaleString("en-US")} billion`;
}

/** A column's threshold as the rule set states it, with the mega-cap exception (B13). */
export function ruleThreshold(rule: RuleSet, condition: StateCondition | undefined): string | null {
  if (!condition) return null;
  const active = rule.states.active;
  if (condition.condition_id === "active.quarter_repurchase") {
    const base = `≥ ${Number(active.quarter_repurchase_to_market_cap_min)}%`;
    return active.mega_cap_min ? `${base}; mega cap: any` : base;
  }
  return formatThreshold(condition);
}
