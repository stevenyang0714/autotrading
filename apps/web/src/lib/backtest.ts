/**
 * Labels for the backtests (M2.5, ADR-033): every strategy, limit and withheld metric has its
 * glossary term. Pure.
 */
import type { CompleteTermId } from "@/generated/glossary";

export const STRATEGIES: Record<string, { name: string; termId: CompleteTermId; rules: string }> = {
  S1: { name: "Buyback + Value + Quality", termId: "signal", rules: "buyback rules" },
  S3: { name: "Macro Regime / ETF Rotation", termId: "etf_rotation", rules: "rotation rules" },
  S4: { name: "Medium-term Momentum", termId: "medium_term_momentum", rules: "momentum rules" },
};

export const WITHHELD_LABELS: Record<string, string> = {
  cagr: "CAGR",
  volatility: "Volatility",
  sharpe: "Sharpe",
  sortino: "Sortino",
  max_drawdown: "Maximum drawdown",
  hit_rate: "Hit rate",
  profit_factor: "Profit factor",
  tail_loss: "Tail loss",
  regime_performance: "Performance by regime",
  trade_pnl: "Trade P&L",
};

export const LIMIT_LABELS: Record<string, string> = {
  position: "position",
  sector: "sector",
  gross: "gross exposure",
  volume: "volume",
};

/** "16.66%". */
export function pct(value: string | number): string {
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toFixed(2)}%` : String(value);
}

/** "7 bps", "0.35 bps". */
export function bps(value: string | number): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return `${Number.isInteger(n) ? n.toFixed(0) : n.toFixed(2)} bps`;
}

/** "sector_name" -> "Sector name". */
export function sectorLabel(sector: string): string {
  const text = sector.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** A target's holdings sorted by symbol (stored JSON keeps no order). */
export function holdings(target: Record<string, string>): [string, string][] {
  return Object.entries(target).sort(([a], [b]) => a.localeCompare(b));
}
