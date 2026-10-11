/**
 * Labels and formats for the paper journal (M1.6, ADR-027). Every decision is a paper record;
 * every value has its glossary term.
 */

import type { CompleteTermId } from "@/generated/glossary";
import type { EvidenceItem, JournalDecision, JournalPerformance } from "@/lib/api";
import { formatChange, formatPrice, formatReported } from "@/lib/format";

export type EvidenceKind = EvidenceItem["kind"];
export type NoTradeReason = NonNullable<JournalDecision["no_trade_reason"]>;

export const EVIDENCE_KINDS: Record<EvidenceKind, { label: string; termId: CompleteTermId }> = {
  financial_fact: { label: "Reported values", termId: "evidence_item" },
  filing: { label: "Filings", termId: "evidence_item" },
  buyback_statement: { label: "Buyback statements", termId: "evidence_item" },
  guidance_statement: { label: "Guidance statements", termId: "guidance_statement" },
  buyback_state: { label: "Buyback state", termId: "buyback_state" },
  news: { label: "News", termId: "evidence_item" },
  price_close: { label: "Last close", termId: "evidence_item" },
};

export const NO_TRADE_REASONS: Record<NoTradeReason, string> = {
  priced_in: "Priced in",
  insufficient_evidence: "Insufficient evidence",
  excessive_risk: "Excessive risk",
  other: "Other",
};

/** "paper TRADE buy 10 (limit $250.00)", "paper exit sell 10" or "NO TRADE: Priced in". */
export function decisionLabel(decision: JournalDecision): string {
  if (decision.decision === "no_trade") {
    return `NO TRADE: ${NO_TRADE_REASONS[decision.no_trade_reason ?? "other"]}`;
  }
  const kind = decision.exits_decision_id ? "exit" : "TRADE";
  const limit = decision.limit_price ? ` (limit ${formatPrice(decision.limit_price)})` : "";
  return `paper ${kind} ${decision.side} ${decision.quantity}${limit}`;
}

/** "+16.60 pts" or "-1.89 pts". */
export function formatPoints(value: string): string {
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)} pts`;
}

/** "+$150.00" or "-$1.90". */
export function formatPnl(value: string): string {
  const number = Number(value);
  const text = formatPrice(String(Math.abs(number)));
  return `${number > 0 ? "+" : number < 0 ? "-" : ""}${text}`;
}

/** "-0.06% vs SPY +1.83% (-1.89 pts)", or why there is none. */
export function performanceSummary(performance: JournalPerformance): string {
  if (performance.status !== "ok" || performance.return_pct === null) {
    return performance.detail ?? "n/a";
  }
  const spy =
    performance.benchmark_return_pct !== null && performance.relative !== null
      ? ` vs ${performance.benchmark} ${formatChange(performance.benchmark_return_pct)} (${formatPoints(performance.relative)})`
      : ` (no ${performance.benchmark} close to compare)`;
  return `${formatChange(performance.return_pct)}${spy}`;
}

/** A snapshot value for display: money, per-share and share counts in their units. */
export function evidenceValue(item: EvidenceItem): string {
  const snapshot = item.snapshot as Record<string, string | null>;
  if (item.kind === "financial_fact" && snapshot.value != null && snapshot.unit != null) {
    return formatReported(snapshot.value, snapshot.unit);
  }
  if (item.kind === "price_close" && snapshot.close != null) return formatPrice(snapshot.close);
  return item.summary;
}

export function signedClass(value: string | null): string {
  if (value === null) return "";
  const number = Number(value);
  return number > 0 ? "text-emerald-300" : number < 0 ? "text-rose-300" : "";
}
