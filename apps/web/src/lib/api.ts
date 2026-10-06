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
// M1.1 (ADR-021)
export type DerivedCell = components["schemas"]["DerivedCell"];
export type DerivedInput = components["schemas"]["DerivedInput"];
export type QuarterTable = components["schemas"]["QuarterTable"];
export type SplitOut = components["schemas"]["SplitOut"];
export type SplitAdjusted = components["schemas"]["SplitAdjusted"];

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

// ---------- filing reconciliation (M1.1, ADR-021) ----------

export type ReconciliationList = components["schemas"]["ReconciliationList"];
export type ReconciliationOut = components["schemas"]["ReconciliationOut"];
export type ReconciliationDetail = components["schemas"]["ReconciliationDetail"];
export type ReconciliationItem = components["schemas"]["ItemOut"];
export type ReconciliationStatus = ReconciliationOut["status"];

export interface ReconciliationQuery {
  status?: ReconciliationStatus;
  form?: "10-K" | "10-Q";
}

/** Each issuer's latest 10-K and 10-Q reconciliation, or null when the API is unreachable. */
export async function loadReconciliations(
  query: ReconciliationQuery = {},
): Promise<ReconciliationList | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/reconciliation", { params: { query }, cache: "no-store" });
    return data ?? null;
  } catch {
    return null;
  }
}

export type ReconciliationDetailResult =
  | { status: "ok"; data: ReconciliationDetail }
  | { status: "not_found" }
  | { status: "unavailable" };

export async function loadReconciliation(accession: string): Promise<ReconciliationDetailResult> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data, response } = await client.GET("/reconciliation/{accession}", {
      params: { path: { accession } },
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

/**
 * Observations of one series as known at `knownAt` (ISO timestamp; default now), newest first:
 * the latest `limit` (default 24), or for a chart every observation since `since` (YYYY-MM-DD).
 */
export async function loadSeriesObservations(
  seriesId: string,
  knownAt?: string,
  range?: { since: string; limit: number },
): Promise<SeriesObservationsResult> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data, response } = await client.GET("/macro/series/{series_id}/observations", {
      params: {
        path: { series_id: seriesId },
        query: { ...(knownAt ? { known_at: knownAt } : {}), ...(range ?? {}) },
      },
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

// ---------- news (M0.8, ADR-018) ----------

export type NewsFeed = components["schemas"]["NewsFeed"];
export type NewsGroup = components["schemas"]["NewsGroupOut"];
export type NewsItem = components["schemas"]["NewsItemOut"];
export type NewsSource = components["schemas"]["NewsSourceOut"];

/** article: media coverage; press_release: the issuer's own announcements; official: government. */
export type NewsKind = "article" | "press_release" | "official";

export interface NewsQuery {
  ticker?: string;
  source?: string;
  maxTier?: number;
  kinds?: NewsKind[];
  knownAt?: string;
  limit?: number;
}

/** News stories (copies of one story collapsed), newest first, or null when the API is down. */
export async function loadNews(query: NewsQuery = {}): Promise<NewsFeed | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/news", {
      params: {
        query: {
          ...(query.ticker ? { ticker: query.ticker } : {}),
          ...(query.source ? { source: query.source } : {}),
          ...(query.maxTier ? { max_tier: query.maxTier } : {}),
          ...(query.kinds?.length ? { kind: query.kinds.join(",") } : {}),
          ...(query.knownAt ? { known_at: query.knownAt } : {}),
          ...(query.limit ? { limit: query.limit } : {}),
        },
      },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

// ---------- audit log (M0.9, ADR-019) ----------

export type AuditLogPage = components["schemas"]["AuditLogPage"];
export type AuditEntry = components["schemas"]["AuditEntry"];
export type AuditAction = "insert" | "update" | "delete" | "supersede";

export interface AuditQuery {
  table?: string;
  action?: AuditAction;
  actor?: string;
  objectId?: string;
  since?: string;
  until?: string;
  beforeId?: number;
}

/** One page of the audit log, newest first, or null when the API is unreachable. */
export async function loadAuditLog(query: AuditQuery = {}): Promise<AuditLogPage | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/audit-log", {
      params: {
        query: {
          ...(query.table ? { table: query.table } : {}),
          ...(query.action ? { action: query.action } : {}),
          ...(query.actor ? { actor: query.actor } : {}),
          ...(query.objectId ? { object_id: query.objectId } : {}),
          ...(query.since ? { since: query.since } : {}),
          ...(query.until ? { until: query.until } : {}),
          ...(query.beforeId ? { before_id: query.beforeId } : {}),
          limit: 50,
        },
      },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}
