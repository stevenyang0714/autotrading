/**
 * Labels and formats for earnings events (M1.5, ADR-026). Values are formatted in the unit the
 * API states; every metric has its glossary term.
 */

import type { CompleteTermId } from "@/generated/glossary";
import type { EarningsEvent } from "@/lib/api";
import { formatChange, formatPrice, formatReported } from "@/lib/format";

export const TIMING_LABELS: Record<EarningsEvent["timing"], string> = {
  pre_market: "before the open",
  market_hours: "during the session",
  after_hours: "after the close",
  non_session: "on a day without a session",
};

export const ACTUAL_LABELS: Record<string, { label: string; termId: CompleteTermId }> = {
  revenue: { label: "Revenue", termId: "revenue" },
  eps_diluted: { label: "Diluted EPS", termId: "eps_diluted" },
  gross_margin: { label: "Gross margin", termId: "gross_margin" },
  operating_margin: { label: "Operating margin", termId: "operating_margin" },
  net_margin: { label: "Net margin", termId: "net_margin" },
  free_cash_flow: { label: "Free cash flow", termId: "free_cash_flow" },
};

export const GUIDANCE_LABELS: Record<string, string> = {
  revenue: "Revenue",
  revenue_growth: "Sales growth",
  eps: "EPS",
  gross_margin: "Gross margin",
  operating_margin: "Operating margin",
  net_margin: "Net margin",
};

/** "$111.184B", "$2.01", "49.27%": a value in its unit. */
export function formatValue(value: string | null, unit: string): string {
  if (value === null) return "n/a";
  if (unit === "percent") return `${Number(value).toFixed(2)}%`;
  if (unit === "USD/shares") return formatPrice(value);
  return formatReported(value, "USD");
}

/** "+16.60%" or "+2.22 pts". */
export function formatDelta(value: string | null, unit: string): string {
  if (value === null) return "n/a";
  if (unit === "percent") return formatChange(value);
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)} pts`;
}

/** "$34.500B to $37.000B", "$3.20 to $3.30", "4.0% to 6.0%", or one value. */
export function formatRange(low: string, high: string, unit: string): string {
  const one = (v: string) => (unit === "percent" ? `${Number(v)}%` : formatValue(v, unit));
  return low === high ? one(low) : `${one(low)} to ${one(high)}`;
}
