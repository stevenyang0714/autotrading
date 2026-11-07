/**
 * Display helpers for the investment policy page (M3.12, ADR-043). Targets, bands, weights and
 * drift arrive as fractions of the USD total ("0.4000" is 40%); amounts in their currency.
 */

import type { CompleteTermId } from "@/generated/glossary";

export const ASSET_CLASSES = ["equity", "bond", "commodity", "real_estate", "cash", "other"] as const;
export const SLEEVE_MARKETS = ["US", "TW", "cash", "mixed"] as const;

export const ASSET_CLASS_LABELS: Record<string, string> = {
  equity: "Equity",
  bond: "Bonds",
  commodity: "Commodities",
  real_estate: "Real estate",
  cash: "Cash",
  other: "Other",
};

export const SLEEVE_MARKET_LABELS: Record<string, string> = {
  US: "US listings",
  TW: "TWSE listings",
  cash: "Cash",
  mixed: "Mixed",
};

export const BLOCKED_LABELS: Record<string, string> = {
  no_policy: "No policy yet: write your first version below. The targets and bands are yours; nothing is filled in for you.",
  no_holdings: "Nothing held yet: record your holdings on the Holdings page first.",
  no_rate: "No TWD rate known: the USD total, and so the weights, are unavailable.",
  unassigned: "Some holdings belong to no sleeve: name them in a new version before any trade is listed.",
};

export const BLOCKED_TERMS: Record<string, CompleteTermId> = {
  no_policy: "investment_policy",
  no_holdings: "holdings_equity",
  no_rate: "fx_rate_used",
  unassigned: "policy_sleeve",
};

export const TRADE_FLAG_LABELS: Record<string, string> = {
  no_close: "no close known: the USD amount only",
  stale_mark: "close is old",
};

export const SIDE_LABELS: Record<string, string> = { buy: "Buy", sell: "Sell" };

/** "-2.84 pp": a drift (a fraction of the total) in percentage points, signed. */
export function points(value: string | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  const number = Number(value) * 100;
  if (!Number.isFinite(number)) return value;
  const text = `${Math.abs(number).toFixed(2)} pp`;
  return number > 0 ? `+${text}` : number < 0 ? `-${text}` : text;
}

/** "± 5.00 pp": a band (a fraction of the total) in percentage points. */
export function band(value: string): string {
  const number = Number(value) * 100;
  return Number.isFinite(number) ? `± ${number.toFixed(2)} pp` : value;
}

export interface MemberInput {
  key: string;
  target_pct: string | null;
}

/** Members as typed in the form: "US:SPY=30, US:VOO" (a listing's own target after `=`). */
export function membersText(members: { key: string; target_pct?: string | null }[]): string {
  return members.map((m) => (m.target_pct ? `${m.key}=${Number(m.target_pct)}` : m.key)).join(", ");
}

/** The form's members text as the API takes it; the API checks each key. */
export function parseMembers(text: string): MemberInput[] {
  return text
    .split(/[\s,;]+/)
    .filter(Boolean)
    .map((token) => {
      const [key, target] = token.split("=", 2);
      return { key: key.toUpperCase(), target_pct: target ? target : null };
    });
}
