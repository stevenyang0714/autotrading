/**
 * Macro series chart data (M0.9, ADR-019): the value known at the chosen date and the value as
 * first released, per observation, oldest first. Pure, so it is tested without a canvas.
 */
import type { MacroObservation } from "@/lib/api";

export interface ChartRow {
  day: string;
  latest: number;
  latestVintage: string;
  first: number;
  firstVintage: string;
  revised: boolean;
}

export function chartRows(observations: MacroObservation[]): ChartRow[] {
  return [...observations]
    .sort((a, b) => a.observation_date.localeCompare(b.observation_date))
    .map((obs) => ({
      day: obs.observation_date,
      latest: Number(obs.value),
      latestVintage: obs.vintage,
      first: Number(obs.first_release?.value ?? obs.value),
      firstVintage: obs.first_release?.vintage ?? obs.vintage,
      revised: obs.revised,
    }));
}

/** Years of history the chart shows, by FRED frequency (Daily, Weekly, Monthly, Quarterly, Annual). */
const YEARS_BY_FREQUENCY: Record<string, number> = { D: 2, W: 5, M: 10, Q: 20, A: 30 };
export const CHART_LIMIT = 1000;

/** The first observation day the chart asks for: years back from the as-known-at day. */
export function chartSince(knownAt: string, frequency: string | null | undefined): string {
  const years = YEARS_BY_FREQUENCY[(frequency ?? "").slice(0, 1).toUpperCase()] ?? 10;
  const day = new Date(knownAt);
  day.setUTCFullYear(day.getUTCFullYear() - years);
  return day.toISOString().slice(0, 10);
}

export interface ChartSummary {
  from: string;
  to: string;
  low: number;
  high: number;
  last: number;
  revisedCount: number;
  lastRevised: string | null; // the newest observation whose first release was revised
}

export function chartSummary(rows: ChartRow[]): ChartSummary | null {
  if (rows.length === 0) return null;
  const values = rows.map((r) => r.latest);
  return {
    from: rows[0].day,
    to: rows[rows.length - 1].day,
    low: Math.min(...values),
    high: Math.max(...values),
    last: values[values.length - 1],
    revisedCount: rows.filter((r) => r.revised).length,
    lastRevised: rows.filter((r) => r.revised).at(-1)?.day ?? null,
  };
}
