/**
 * Display helpers for the Holdings page (M3.10, ADR-041). Amounts arrive as decimal strings in
 * their currency (USD for US listings, TWD for TWSE listings); USD is the base currency.
 */

import type { CompleteTermId } from "@/generated/glossary";
import { formatMoney } from "@/lib/format";

export const KIND_LABELS: Record<string, string> = {
  buy: "Buy",
  sell: "Sell",
  dividend: "Dividend",
  deposit: "Deposit",
  withdrawal: "Withdrawal",
  fee: "Fee",
  reversal: "Reversal",
};

export const FLAG_LABELS: Record<string, string> = {
  stale_mark: "close is old",
  no_mark: "no close yet: valued at cost",
  oversold: "more sold than bought",
  negative_cash: "a cash balance is below zero",
  fx_missing: "no TWD rate known: the USD total is unavailable",
  fx_stale: "the TWD rate is more than 10 days old",
};

export const FLAG_TERMS: Record<string, CompleteTermId> = {
  stale_mark: "price_mark",
  no_mark: "price_mark",
  oversold: "holding_reversal",
  negative_cash: "cash_balance",
  fx_missing: "fx_rate_used",
  fx_stale: "fx_lag",
};

/** "6", "1,050", "0.65": a share count without trailing zeros. */
export function quantity(value: string): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return number.toLocaleString("en-US", { maximumFractionDigits: 6 });
}

/** "21.96%": a weight (a fraction of the USD total) in percent. */
export function weight(value: string | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(2)}%` : value;
}

/** "+$180.00", "-NT$5,000.00": a gain or loss in its currency, signed. */
export function signedMoney(value: string | null | undefined, currency: string): string {
  if (value === null || value === undefined) return "n/a";
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  const text = formatMoney(String(Math.abs(number)), currency);
  return number > 0 ? `+${text}` : number < 0 ? `-${text}` : text;
}

/** "$16,664.67", or "n/a" when unavailable. */
export function money(value: string | null | undefined, currency: string): string {
  return value === null || value === undefined ? "n/a" : formatMoney(value, currency);
}
