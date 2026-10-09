/**
 * Fundamental Research dashboard columns and sorting (M1.3b, ADR-024). Pure; the page sorts on
 * the server from ?sort=&dir= so it works without client JavaScript.
 */
import type { CompleteTermId } from "@/generated/glossary";
import type { ResearchSummaryRow } from "@/lib/api";

export type ColumnGroup = "economics" | "quality" | "capital_allocation" | "valuation" | "model";
export type ColumnUnit = "percent" | "x" | "USD/shares";
export type SortDir = "asc" | "desc";

export interface Column {
  key: string;
  termId: CompleteTermId;
  label: string;
  group: ColumnGroup;
  unit: ColumnUnit;
}

export const GROUPS: { group: ColumnGroup; label: string; termId: CompleteTermId }[] = [
  { group: "economics", label: "Economics", termId: "research_record" },
  { group: "quality", label: "Quality", termId: "research_record" },
  { group: "capital_allocation", label: "Capital allocation", termId: "cash_returned" },
  { group: "valuation", label: "Valuation", termId: "valuation_price" },
  { group: "model", label: "DCF: model output, not fact", termId: "model_output" },
];

export const COLUMNS: Column[] = [
  { key: "revenue_growth", termId: "revenue_growth", label: "Revenue growth", group: "economics", unit: "percent" },
  { key: "gross_margin", termId: "gross_margin", label: "Gross margin", group: "economics", unit: "percent" },
  { key: "operating_margin", termId: "operating_margin", label: "Operating margin", group: "economics", unit: "percent" },
  { key: "roic", termId: "roic", label: "ROIC", group: "quality", unit: "percent" },
  { key: "roe", termId: "roe", label: "ROE", group: "quality", unit: "percent" },
  { key: "fcf_conversion", termId: "fcf_conversion", label: "FCF conversion", group: "quality", unit: "percent" },
  { key: "net_debt_to_ebitda", termId: "net_debt_to_ebitda", label: "Net debt / EBITDA", group: "quality", unit: "x" },
  { key: "cash_returned_to_fcf", termId: "cash_returned_to_fcf", label: "Cash returned / FCF", group: "capital_allocation", unit: "percent" },
  { key: "diluted_shares_change", termId: "diluted_shares_change", label: "Diluted shares", group: "capital_allocation", unit: "percent" },
  { key: "pe_ratio_ttm", termId: "pe_ratio_ttm", label: "P/E", group: "valuation", unit: "x" },
  { key: "fcf_yield", termId: "fcf_yield", label: "FCF yield", group: "valuation", unit: "percent" },
  { key: "base_per_share", termId: "fair_value_dcf", label: "DCF base", group: "model", unit: "USD/shares" },
  { key: "implied_upside", termId: "implied_upside", label: "Implied upside", group: "model", unit: "percent" },
  { key: "reverse_dcf_growth", termId: "reverse_dcf_growth", label: "Reverse DCF growth", group: "model", unit: "percent" },
];

export interface Cell {
  value: string | null;
  /** "n/m" or "Data unavailable" when there is no value. */
  status: string | null;
  detail: string | null;
}

/** One column's cell of one row: the API value, its reason and detail. */
export function cell(row: ResearchSummaryRow, key: string): Cell {
  const fair = row.fair_value;
  if (key === "base_per_share" || key === "implied_upside" || key === "reverse_dcf_growth") {
    const value =
      key === "base_per_share"
        ? fair.base_per_share
        : key === "implied_upside"
          ? fair.implied_upside
          : fair.reverse_dcf_growth;
    if (value !== null) return { value, status: null, detail: null };
    const detail = key === "base_per_share" ? fair.detail : (fair.comparison_detail ?? fair.detail);
    return {
      value: null,
      status: fair.status === "not_meaningful" && key === "base_per_share" ? "n/m" : "Data unavailable",
      detail,
    };
  }
  const found = row.values.find((v) => v.metric_id === key);
  if (!found) return { value: null, status: "Data unavailable", detail: null };
  if (found.value !== null) return { value: found.value, status: null, detail: found.detail };
  return {
    value: null,
    status: found.reason === "not_meaningful" ? "n/m" : "Data unavailable",
    detail: found.detail,
  };
}

/** "46.91%", "0.43x", "$124.43". */
export function formatCell(value: string, unit: ColumnUnit): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  if (unit === "percent") return `${number.toFixed(2)}%`;
  if (unit === "x") return `${number.toFixed(2)}x`;
  return `$${number.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function isSortKey(key: string | undefined): key is string {
  return key === "ticker" || COLUMNS.some((column) => column.key === key);
}

/** Rows sorted by a column; rows without a value (n/m, unavailable) always last, ties by
 * ticker. */
export function sortRows(rows: ResearchSummaryRow[], key: string, dir: SortDir): ResearchSummaryRow[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    if (key === "ticker") return sign * a.ticker.localeCompare(b.ticker);
    const x = cell(a, key).value;
    const y = cell(b, key).value;
    if (x === null || y === null) {
      if (x === y) return a.ticker.localeCompare(b.ticker);
      return x === null ? 1 : -1;
    }
    const difference = Number(x) - Number(y);
    return difference !== 0 ? sign * difference : a.ticker.localeCompare(b.ticker);
  });
}
