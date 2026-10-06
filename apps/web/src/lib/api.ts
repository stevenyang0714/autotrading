/**
 * Server-side API access (M0.4, D2). Types are generated from the backend's OpenAPI schema
 * (`pnpm gen`, ADR-002). The web container reaches the API at http://api:8000 (API_URL);
 * `make dev-web` on the host falls back to 127.0.0.1:8000.
 */
import createClient from "openapi-fetch";

import type { components, paths } from "@/generated/api";

export type DataHealthReport = components["schemas"]["DataHealthReport"];
export type SourceHealth = components["schemas"]["SourceHealth"];
export type IngestionRun = components["schemas"]["RunOut"];
export type DeadLetter = components["schemas"]["DeadLetterOut"];

export interface DataHealthData {
  report: DataHealthReport;
  runs: IngestionRun[];
  deadLetters: DeadLetter[];
}

export function apiBaseUrl(): string {
  return process.env.API_URL ?? "http://127.0.0.1:8000";
}

/** All three Data Health reads, or null when the API is unreachable (UI: Data unavailable). */
export async function loadDataHealth(): Promise<DataHealthData | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const [health, runs, deadLetters] = await Promise.all([
      client.GET("/data-health", { cache: "no-store" }),
      client.GET("/ingestion-runs", { params: { query: { limit: 30, per_job: 3 } }, cache: "no-store" }),
      client.GET("/dead-letters", { cache: "no-store" }),
    ]);
    if (!health.data || !runs.data || !deadLetters.data) return null;
    return { report: health.data, runs: runs.data, deadLetters: deadLetters.data };
  } catch {
    return null;
  }
}

// ---------- instruments (M0.5b) ----------

export type InstrumentList = components["schemas"]["InstrumentList"];
export type InstrumentSummary = components["schemas"]["InstrumentSummary"];
export type Fundamentals = components["schemas"]["Fundamentals"];
export type FactTable = components["schemas"]["FactTable"];
export type FactCell = components["schemas"]["FactCell"];
export type EntityOut = components["schemas"]["EntityOut"];
export type FilingRef = components["schemas"]["FilingRef"];

/** Universe stocks, or null when the API is unreachable. */
export async function loadInstruments(): Promise<InstrumentList | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/instruments", { cache: "no-store" });
    return data ?? null;
  } catch {
    return null;
  }
}

export type FundamentalsResult =
  | { status: "ok"; data: Fundamentals }
  | { status: "not_found" }
  | { status: "unavailable" };

/** One stock's fundamentals as known at `knownAt` (ISO timestamp; default now). */
export async function loadFundamentals(
  ticker: string,
  knownAt?: string,
): Promise<FundamentalsResult> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data, response } = await client.GET("/instruments/{ticker}/fundamentals", {
      params: { path: { ticker }, query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    if (data) return { status: "ok", data };
    return response.status === 404 ? { status: "not_found" } : { status: "unavailable" };
  } catch {
    return { status: "unavailable" };
  }
}

// ---------- macro (M0.6) ----------

export type MacroSeriesList = components["schemas"]["MacroSeriesList"];
export type MacroSeriesSummary = components["schemas"]["SeriesSummary"];
export type MacroSeries = components["schemas"]["SeriesOut"];
export type SeriesObservations = components["schemas"]["SeriesObservations"];
export type MacroObservation = components["schemas"]["ObservationOut"];

/** The macro series registry with each series' latest value, or null when the API is down. */
export async function loadMacroSeries(): Promise<MacroSeriesList | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/macro/series", { cache: "no-store" });
    return data ?? null;
  } catch {
    return null;
  }
}

export type SeriesObservationsResult =
  | { status: "ok"; data: SeriesObservations }
  | { status: "not_found" }
  | { status: "unavailable" };

/** The latest observations of one series as known at `knownAt` (ISO timestamp; default now). */
export async function loadSeriesObservations(
  seriesId: string,
  knownAt?: string,
): Promise<SeriesObservationsResult> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data, response } = await client.GET("/macro/series/{series_id}/observations", {
      params: { path: { series_id: seriesId }, query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    if (data) return { status: "ok", data };
    return response.status === 404 ? { status: "not_found" } : { status: "unavailable" };
  } catch {
    return { status: "unavailable" };
  }
}

// ---------- overview, freshness, progress (M0.6, ADR-016) ----------

export type Overview = components["schemas"]["Overview"];
export type OverviewBlock = components["schemas"]["Block"];
export type OverviewIndicator = components["schemas"]["Indicator"];
export type OverviewChart = components["schemas"]["Chart"];
export type Progress = components["schemas"]["Progress"];

/** The macro dashboard as known at `knownAt` (ISO timestamp; default now), or null. */
export async function loadOverview(knownAt?: string): Promise<Overview | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/overview", {
      params: { query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

/** Source registry with freshness and next scheduled refresh, or null. */
export async function loadSourceHealth(): Promise<SourceHealth[] | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/data-health", { cache: "no-store" });
    return data?.sources ?? null;
  } catch {
    return null;
  }
}

/** Build progress parsed from the project documents, or null. */
export async function loadProgress(): Promise<Progress | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/progress", { cache: "no-store" });
    return data ?? null;
  } catch {
    return null;
  }
}

// ---------- prices (M0.7, ADR-017) ----------

export type LatestPrices = components["schemas"]["LatestPrices"];
export type Quote = components["schemas"]["QuoteOut"];
export type FeedStatus = Quote["feed_status"];
export type MarketState = components["schemas"]["MarketState"];
export type InstrumentPrices = components["schemas"]["InstrumentPrices"];
export type PriceTile = components["schemas"]["PriceTile"];

/** Latest quotes with their feed status (all universe symbols by default), or null. */
export async function loadLatestPrices(symbols?: string[]): Promise<LatestPrices | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/prices/latest", {
      params: { query: symbols ? { symbols: symbols.join(",") } : {} },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

export type InstrumentPricesResult =
  | { status: "ok"; data: InstrumentPrices }
  | { status: "not_found" }
  | { status: "unavailable" };

/** One instrument's quote (live view) and daily closes as known at `knownAt`. */
export async function loadInstrumentPrices(
  ticker: string,
  knownAt?: string,
): Promise<InstrumentPricesResult> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data, response } = await client.GET("/instruments/{ticker}/prices", {
      params: { path: { ticker }, query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    if (data) return { status: "ok", data };
    return response.status === 404 ? { status: "not_found" } : { status: "unavailable" };
  } catch {
    return { status: "unavailable" };
  }
}
