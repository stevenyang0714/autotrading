/**
 * Labels and formats for the price, trend and factor measures (M2.2, ADR-030): every measure
 * has its glossary term. Pure.
 */
import type { CompleteTermId } from "@/generated/glossary";
import type { FactorMeasure, FactorRow } from "@/lib/api";

export type FactorGroup = "trend" | "risk" | "relative" | "value" | "quality";
export type SortDir = "asc" | "desc";

export interface MeasureMeta {
  label: string;
  short: string;
  termId: CompleteTermId;
}

export const MEASURES: Record<string, MeasureMeta> = {
  momentum_12_1: { label: "12-1 month momentum", short: "12-1 mom.", termId: "momentum_12_1" },
  momentum_6_1: { label: "6-1 month momentum", short: "6-1 mom.", termId: "momentum_6_1" },
  reversal_1m: { label: "1-month return", short: "1 month", termId: "reversal_1m" },
  close_vs_sma_50: { label: "Close vs 50-session average", short: "vs 50d avg", termId: "close_vs_sma_50" },
  close_vs_sma_200: { label: "Close vs 200-session average", short: "vs 200d avg", termId: "close_vs_sma_200" },
  volatility_60d: { label: "60-session volatility", short: "Vol. 60d", termId: "volatility_60d" },
  beta_252d: { label: "Beta to SPY (252 sessions)", short: "Beta", termId: "beta_252d" },
  relative_momentum_12_1: { label: "12-1 momentum vs SPY", short: "12-1 vs SPY", termId: "relative_momentum_12_1" },
  relative_momentum_6_1: { label: "6-1 momentum vs SPY", short: "6-1 vs SPY", termId: "relative_momentum_6_1" },
  pe_ratio_ttm: { label: "P/E (TTM)", short: "P/E", termId: "pe_ratio_ttm" },
  ev_to_sales: { label: "EV / sales", short: "EV/sales", termId: "ev_to_sales" },
  price_to_book: { label: "Price / book", short: "P/B", termId: "price_to_book" },
  fcf_yield: { label: "FCF yield", short: "FCF yield", termId: "fcf_yield" },
  earnings_yield: { label: "Earnings yield", short: "Earn. yield", termId: "earnings_yield" },
  roic: { label: "ROIC", short: "ROIC", termId: "roic" },
  roe: { label: "ROE", short: "ROE", termId: "roe" },
  gross_margin: { label: "Gross margin", short: "Gross m.", termId: "gross_margin" },
  operating_margin: { label: "Operating margin", short: "Op. margin", termId: "operating_margin" },
  fcf_conversion: { label: "FCF conversion", short: "FCF conv.", termId: "fcf_conversion" },
  net_debt_to_ebitda: { label: "Net debt / EBITDA", short: "ND/EBITDA", termId: "net_debt_to_ebitda" },
  diluted_shares_change: { label: "Diluted shares change", short: "Shares", termId: "diluted_shares_change" },
  revenue_growth: { label: "Revenue growth", short: "Rev. growth", termId: "revenue_growth" },
};

export const GROUPS: { group: FactorGroup; label: string; termId: CompleteTermId }[] = [
  { group: "trend", label: "Trend", termId: "momentum_12_1" },
  { group: "risk", label: "Risk", termId: "volatility_60d" },
  { group: "relative", label: "Against SPY", termId: "relative_momentum_12_1" },
  { group: "value", label: "Value against own history", termId: "factor_percentile" },
  { group: "quality", label: "Quality against own history", termId: "factor_percentile" },
];

/** The trend table's columns (every instrument). */
export const TREND_COLUMNS = [
  "momentum_12_1",
  "momentum_6_1",
  "reversal_1m",
  "close_vs_sma_50",
  "close_vs_sma_200",
  "volatility_60d",
  "beta_252d",
  "relative_momentum_12_1",
  "relative_momentum_6_1",
] as const;

/** The value and quality table's columns (equities): their percentiles in own history. */
export const FUNDAMENTAL_COLUMNS = [
  "pe_ratio_ttm",
  "ev_to_sales",
  "fcf_yield",
  "roic",
  "gross_margin",
  "operating_margin",
  "revenue_growth",
  "net_debt_to_ebitda",
] as const;

export function meta(measureId: string): MeasureMeta {
  return MEASURES[measureId] ?? { label: measureId, short: measureId, termId: "factor_definition_set" };
}

/** "+21.09%", "+4.60 pts", "38.18x", "1.882". Returns and relative values carry a sign. */
export function formatMeasure(value: string, unit: string, group: string): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  if (unit === "x") return `${number.toFixed(2)}x`;
  if (unit === "ratio") return number.toFixed(3);
  const signed = group === "trend" || group === "relative";
  const text = `${signed && number > 0 ? "+" : ""}${number.toFixed(2)}`;
  return group === "relative" ? `${text} pts` : `${text}%`;
}

/** "62nd percentile". */
export function ordinal(value: string): string {
  const n = Math.round(Number(value));
  const mod100 = n % 100;
  const suffix = mod100 >= 11 && mod100 <= 13 ? "th" : (["th", "st", "nd", "rd"][n % 10] ?? "th");
  return `${n}${suffix} percentile`;
}

export function rowValue(row: FactorRow, measureId: string): FactorRow["values"][number] | undefined {
  return row.values.find((v) => v.measure_id === measureId);
}

export function isSortKey(key: string | undefined): key is string {
  return (
    key === "ticker" ||
    (TREND_COLUMNS as readonly string[]).includes(key ?? "") ||
    (FUNDAMENTAL_COLUMNS as readonly string[]).includes(key ?? "")
  );
}

/** Rows sorted by a measure (trend columns by value, value and quality columns by percentile);
 * rows without one always last, ties by ticker. */
export function sortRows(rows: FactorRow[], key: string, dir: SortDir): FactorRow[] {
  const sign = dir === "asc" ? 1 : -1;
  const fundamental = (FUNDAMENTAL_COLUMNS as readonly string[]).includes(key);
  const pick = (row: FactorRow): string | null => {
    const found = rowValue(row, key);
    return (fundamental ? found?.percentile : found?.value) ?? null;
  };
  return [...rows].sort((a, b) => {
    if (key === "ticker") return sign * a.ticker.localeCompare(b.ticker);
    const x = pick(a);
    const y = pick(b);
    if (x === null || y === null) {
      if (x === y) return a.ticker.localeCompare(b.ticker);
      return x === null ? 1 : -1;
    }
    const difference = Number(x) - Number(y);
    return difference !== 0 ? sign * difference : a.ticker.localeCompare(b.ticker);
  });
}

/** A measure's window: "2025-10-02 to 2026-09-03". */
export function windowText(measure: Pick<FactorMeasure, "start" | "end">): string | null {
  if (measure.start && measure.end) return `${measure.start} to ${measure.end}`;
  return measure.end ?? null;
}
