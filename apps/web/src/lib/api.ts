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

// ---------- valuation (M1.2, ADR-022) ----------

export type Valuation = components["schemas"]["Valuation"];
export type ValuationMetric = components["schemas"]["MetricOut"];
export type ValuationInput = components["schemas"]["InputOut"];

export type ValuationResult =
  | { status: "ok"; data: Valuation }
  | { status: "not_found" }
  | { status: "unavailable" };

/** Market cap, EV and multiples as known at `knownAt` (ISO timestamp; default now). */
export async function loadValuation(ticker: string, knownAt?: string): Promise<ValuationResult> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data, response } = await client.GET("/instruments/{ticker}/valuation", {
      params: { path: { ticker }, query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    if (data) return { status: "ok", data };
    return response.status === 404 ? { status: "not_found" } : { status: "unavailable" };
  } catch {
    return { status: "unavailable" };
  }
}

// ---------- fair value (M1.3a, ADR-023) ----------

export type FairValue = components["schemas"]["FairValueOut"];
export type FairValueScenario = components["schemas"]["ScenarioOut"];
export type RelativeValuation = components["schemas"]["RelativeOut"];
export type AssumptionVersion = components["schemas"]["AssumptionVersion"];
export type AssumptionList = components["schemas"]["AssumptionList"];
export type AssumptionParameters = components["schemas"]["Assumptions-Output"];
export type AssumptionInput = components["schemas"]["Assumptions-Input"];

export type FairValueResult =
  | { status: "ok"; data: FairValue }
  | { status: "not_found"; detail: string }
  | { status: "unavailable" };

/** DCF, reverse DCF and relative valuation as known at `knownAt` with one assumption version
 * ("default", a version number, or the latest saved by then when omitted). */
export async function loadFairValue(
  ticker: string,
  knownAt?: string,
  assumptions?: string,
): Promise<FairValueResult> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data, error, response } = await client.GET("/instruments/{ticker}/fair-value", {
      params: {
        path: { ticker },
        query: { ...(knownAt ? { known_at: knownAt } : {}), ...(assumptions ? { assumptions } : {}) },
      },
      cache: "no-store",
    });
    if (data) return { status: "ok", data };
    if (response.status === 404) {
      const detail = (error as { detail?: unknown } | undefined)?.detail;
      return { status: "not_found", detail: typeof detail === "string" ? detail : "not found" };
    }
    return { status: "unavailable" };
  } catch {
    return { status: "unavailable" };
  }
}

/** The built-in default and every saved version, newest first; null when unreachable. */
export async function loadAssumptions(ticker: string): Promise<AssumptionList | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/instruments/{ticker}/assumptions", {
      params: { path: { ticker } },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

export type SaveAssumptionsResult =
  | { status: "ok"; data: AssumptionVersion }
  | { status: "invalid"; errors: string[] }
  | { status: "unavailable" };

/** Save a new assumption version (append-only; the API validates and audits it). */
export async function saveAssumptions(
  ticker: string,
  parameters: AssumptionInput,
  reason: string,
): Promise<SaveAssumptionsResult> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data, error, response } = await client.POST("/instruments/{ticker}/assumptions", {
      params: { path: { ticker } },
      body: { parameters, reason },
      cache: "no-store",
    });
    if (data) return { status: "ok", data };
    if (response.status === 422 || response.status === 409) {
      return { status: "invalid", errors: validationMessages(error) };
    }
    return { status: "unavailable" };
  } catch {
    return { status: "unavailable" };
  }
}

/** FastAPI's 422 body ({detail: [{loc, msg}]}) or a plain {detail} as readable lines. */
export function validationMessages(error: unknown, fallback = "The API refused the assumptions."): string[] {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return [detail];
  if (!Array.isArray(detail)) return [fallback];
  return detail.map((item: { loc?: unknown[]; msg?: string }) => {
    const field = (item.loc ?? []).filter((part) => part !== "body" && part !== "parameters").join(".");
    const message = (item.msg ?? "invalid").replace(/^Value error, /, "");
    return field ? `${field}: ${message}` : message;
  });
}

// ---------- research record (M1.3b, ADR-024) ----------

export type ResearchRecord = components["schemas"]["ResearchRecordOut"];
export type ResearchRow = components["schemas"]["ResearchRow"];
export type ResearchPeriod = components["schemas"]["ResearchPeriod"];
export type ResearchDashboard = components["schemas"]["ResearchDashboard"];
export type ResearchSummaryRow = components["schemas"]["ResearchSummaryRow"];
export type ResearchValue = components["schemas"]["ResearchValue"];

export type ResearchResult =
  | { status: "ok"; data: ResearchRecord }
  | { status: "not_found" }
  | { status: "unavailable" };

/** A company's Research Record as known at `knownAt` (ISO timestamp; default now). */
export async function loadResearch(ticker: string, knownAt?: string): Promise<ResearchResult> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data, response } = await client.GET("/instruments/{ticker}/research", {
      params: { path: { ticker }, query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    if (data) return { status: "ok", data };
    return response.status === 404 ? { status: "not_found" } : { status: "unavailable" };
  } catch {
    return { status: "unavailable" };
  }
}

/** One row per universe equity for the Fundamental Research dashboard; null when unreachable. */
export async function loadResearchDashboard(knownAt?: string): Promise<ResearchDashboard | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/research", {
      params: { query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

// ---------- buybacks (M1.4a, ADR-025) ----------

export type Buybacks = components["schemas"]["BuybacksOut"];
export type AnnouncementEvent = components["schemas"]["AnnouncementEvent"];
export type AnnouncementSource = components["schemas"]["AnnouncementSourceOut"];

export type BuybacksResult =
  | { status: "ok"; data: Buybacks }
  | { status: "not_found" }
  | { status: "unavailable" };

/** Authorizations, actual repurchases and net share reduction as known at `knownAt`. */
export async function loadBuybacks(ticker: string, knownAt?: string): Promise<BuybacksResult> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data, response } = await client.GET("/instruments/{ticker}/buybacks", {
      params: { path: { ticker }, query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    if (data) return { status: "ok", data };
    return response.status === 404 ? { status: "not_found" } : { status: "unavailable" };
  } catch {
    return { status: "unavailable" };
  }
}

// ---------- buyback states (M1.4b, ADR-025) ----------

export type BuybackStates = components["schemas"]["BuybackStatesOut"];
export type CompanyStates = components["schemas"]["CompanyStates"];
export type StateAssignment = components["schemas"]["StateAssignmentOut"];
export type StatePoint = components["schemas"]["StatePoint"];
export type Assessment = components["schemas"]["AssessmentOut"];
export type StateCondition = components["schemas"]["ConditionOut"];
export type ScoreComponent = components["schemas"]["ComponentOut"];
export type RuleSet = components["schemas"]["RuleSetOut"];
export type StateId = Assessment["state"];

/** Every universe company's stored buyback state at or before `knownAt` (GET /buybacks). */
export async function loadBuybackStates(knownAt?: string): Promise<BuybackStates | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/buybacks", {
      params: { query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

// ---------- earnings (M1.5, ADR-026) ----------

export type Earnings = components["schemas"]["EarningsOut"];
export type EarningsEvent = components["schemas"]["EarningsEventOut"];
export type EarningsActual = components["schemas"]["ActualOut"];
export type EarningsGuidance = components["schemas"]["GuidanceOut"];
export type EarningsReaction = components["schemas"]["ReactionOut"];
export type EarningsDashboard = components["schemas"]["EarningsDashboard"];
export type EarningsSummary = components["schemas"]["EarningsSummary"];

export type EarningsResult =
  | { status: "ok"; data: Earnings }
  | { status: "not_found" }
  | { status: "unavailable" };

/** Earnings events (8-K Item 2.02) as known at `knownAt`, newest first. */
export async function loadEarnings(ticker: string, knownAt?: string): Promise<EarningsResult> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data, response } = await client.GET("/instruments/{ticker}/earnings", {
      params: { path: { ticker }, query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    if (data) return { status: "ok", data };
    return response.status === 404 ? { status: "not_found" } : { status: "unavailable" };
  } catch {
    return { status: "unavailable" };
  }
}

/** Every universe company's latest release and the last two years of releases. */
export async function loadEarningsDashboard(knownAt?: string): Promise<EarningsDashboard | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/earnings", {
      params: { query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

// ---------- paper journal and signals (M1.6, ADR-027) ----------

export type Journal = components["schemas"]["JournalOut"];
export type JournalRow = components["schemas"]["JournalRow"];
export type JournalCard = components["schemas"]["JournalCardOut"];
export type ThesisCard = components["schemas"]["CardOut"];
export type JournalDecision = components["schemas"]["JournalDecisionOut"];
export type JournalPerformance = components["schemas"]["PerformanceOut"];
export type JournalClose = components["schemas"]["CloseOut"];
export type EvidenceItem = components["schemas"]["EvidenceOut"];
export type EvidenceCandidates = components["schemas"]["CandidatesOut"];
export type ValuationSnapshot = components["schemas"]["ValuationSnapshot"];
export type Replay = components["schemas"]["ReplayOut"];
export type ReplayItem = components["schemas"]["ReplayItem"];
export type Signals = components["schemas"]["SignalsOut"];
export type Signal = components["schemas"]["SignalOut"];
export type NewJournalEntry = components["schemas"]["NewEntry"];
export type NewCardVersion = components["schemas"]["CardContent"];

/** The journal as known at `knownAt` (one company's with `ticker`), or null when the API is down. */
export async function loadJournal(knownAt?: string, ticker?: string): Promise<Journal | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/journal", {
      params: { query: { ...(knownAt ? { known_at: knownAt } : {}), ...(ticker ? { ticker } : {}) } },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

export type JournalCardResult =
  | { status: "ok"; data: JournalCard }
  | { status: "not_found" }
  | { status: "unavailable" };

/** One card (a version, or the latest known at `knownAt`) with its decisions. */
export async function loadJournalCard(
  cardId: string,
  knownAt?: string,
  version?: number,
): Promise<JournalCardResult> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data, response } = await client.GET("/journal/{card_id}", {
      params: {
        path: { card_id: cardId },
        query: { ...(knownAt ? { known_at: knownAt } : {}), ...(version ? { version } : {}) },
      },
      cache: "no-store",
    });
    if (data) return { status: "ok", data };
    return response.status === 404 || response.status === 422 ? { status: "not_found" } : { status: "unavailable" };
  } catch {
    return { status: "unavailable" };
  }
}

/** The card's evidence, valuation and closes read again at its stored time. */
export async function loadReplay(cardId: string, version?: number): Promise<Replay | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/journal/{card_id}/replay", {
      params: { path: { card_id: cardId }, query: version ? { version } : {} },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

/** Each company's current signal at `knownAt`, and one ticker's history. */
export async function loadSignals(knownAt?: string, ticker?: string): Promise<Signals | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/signals", {
      params: { query: { ...(knownAt ? { known_at: knownAt } : {}), ...(ticker ? { ticker } : {}) } },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

/** What a new card for `ticker` can cite: rows of the company known now. */
export async function loadEvidence(ticker: string): Promise<EvidenceCandidates | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/instruments/{ticker}/evidence", {
      params: { path: { ticker } },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

export type JournalWriteResult =
  | { status: "ok"; data: JournalCard }
  | { status: "invalid"; errors: string[] }
  | { status: "unavailable" };

async function journalWrite(
  call: (client: ReturnType<typeof createClient<paths>>) => Promise<{
    data?: JournalCard;
    error?: unknown;
    response: Response;
  }>,
): Promise<JournalWriteResult> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data, error, response } = await call(client);
    if (data) return { status: "ok", data };
    if ([404, 409, 422].includes(response.status)) {
      return { status: "invalid", errors: validationMessages(error, "The API refused the entry.") };
    }
    return { status: "unavailable" };
  } catch {
    return { status: "unavailable" };
  }
}

/** A new Thesis Card with its decision (paper TRADE or NO TRADE); nothing is ever sent. */
export async function createJournalEntry(body: NewJournalEntry): Promise<JournalWriteResult> {
  return journalWrite((client) => client.POST("/journal", { body, cache: "no-store" }));
}

/** A new version of a card. */
export async function addCardVersion(cardId: string, body: NewCardVersion): Promise<JournalWriteResult> {
  return journalWrite((client) =>
    client.POST("/journal/{card_id}/versions", { params: { path: { card_id: cardId } }, body, cache: "no-store" }),
  );
}

/** Exit an open paper TRADE at the last close known now. */
export async function exitPaperTrade(decisionId: string, note: string | null): Promise<JournalWriteResult> {
  return journalWrite((client) =>
    client.POST("/journal/decisions/{decision_id}/exit", {
      params: { path: { decision_id: decisionId } },
      body: { note },
      cache: "no-store",
    }),
  );
}

// ---------- alerts (M1.7, ADR-028) ----------

export type Alerts = components["schemas"]["AlertsOut"];
export type AlertEntry = components["schemas"]["AlertOut"];
export type AlertDetail = components["schemas"]["AlertDetail"];
export type Convergence = components["schemas"]["ConvergenceOut"];
export type CompanyLevel = components["schemas"]["CompanyLevel"];
export type AlertStatus = Alerts["status"];

export interface AlertQuery {
  knownAt?: string;
  status?: AlertStatus;
  levelMin?: number;
  ticker?: string;
  includeBackfilled?: boolean;
}

/** Alerts known at `knownAt`, newest first (open ones by default), or null when the API is down. */
export async function loadAlerts(query: AlertQuery = {}): Promise<Alerts | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/alerts", {
      params: {
        query: {
          ...(query.knownAt ? { known_at: query.knownAt } : {}),
          ...(query.status ? { status: query.status } : {}),
          ...(query.levelMin ? { level_min: query.levelMin } : {}),
          ...(query.ticker ? { ticker: query.ticker } : {}),
          ...(query.includeBackfilled ? { include_backfilled: true } : {}),
        },
      },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

/** Each company's convergence level at `knownAt`. */
export async function loadConvergence(knownAt?: string): Promise<Convergence | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/convergence", {
      params: { query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

export type AcknowledgeResult =
  | { status: "ok"; data: AlertDetail }
  | { status: "invalid"; errors: string[] }
  | { status: "unavailable" };

/** Acknowledge an alert once, with an optional note (audited). */
export async function acknowledgeAlert(alertId: string, note: string | null): Promise<AcknowledgeResult> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data, error, response } = await client.POST("/alerts/{alert_id}/acknowledge", {
      params: { path: { alert_id: alertId } },
      body: { note },
      cache: "no-store",
    });
    if (data) return { status: "ok", data };
    if ([404, 409, 422].includes(response.status)) {
      return { status: "invalid", errors: validationMessages(error, "The API refused the acknowledgement.") };
    }
    return { status: "unavailable" };
  } catch {
    return { status: "unavailable" };
  }
}

// ---------- macro regime (M2.1, ADR-029) ----------

export type RegimeResponse = components["schemas"]["RegimeOut"];
export type StoredRegime = components["schemas"]["StoredRegime"];
export type Regime = components["schemas"]["Regime"];
export type RegimeDimension = components["schemas"]["Dimension"];
export type RegimeReading = components["schemas"]["Reading"];
export type RegimeFlag = components["schemas"]["Flag"];
export type RegimeInput = components["schemas"]["RegimeInput"];
export type RegimePoint = components["schemas"]["RegimePoint"];

/** The stored regime as known at `knownAt` and its history, or null when the API is down. */
export async function loadRegime(knownAt?: string): Promise<RegimeResponse | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/regime", {
      params: { query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

// ---------- price, trend and factors (M2.2, ADR-030) ----------

export type InstrumentFactors = components["schemas"]["InstrumentFactorsOut"];
export type FactorMeasure = components["schemas"]["MeasureOut"];
export type FactorInput = components["schemas"]["FactorInput"];
export type FactorSnapshotRef = components["schemas"]["SnapshotRef"];
export type FactorsTable = components["schemas"]["FactorsOut"];
export type FactorRow = components["schemas"]["FactorRow"];
export type FactorValue = components["schemas"]["FactorValue"];

export type InstrumentFactorsResult =
  | { status: "ok"; data: InstrumentFactors }
  | { status: "not_found" }
  | { status: "unavailable" };

/** One universe instrument's stored factor measures as known at `knownAt` (default now). */
export async function loadInstrumentFactors(
  ticker: string,
  knownAt?: string,
): Promise<InstrumentFactorsResult> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data, response } = await client.GET("/instruments/{ticker}/factors", {
      params: { path: { ticker }, query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    if (data) return { status: "ok", data };
    return response.status === 404 ? { status: "not_found" } : { status: "unavailable" };
  } catch {
    return { status: "unavailable" };
  }
}

/** Every universe instrument's latest factor values as known at `knownAt` (Opportunity Radar). */
export async function loadFactors(knownAt?: string): Promise<FactorsTable | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/factors", {
      params: { query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

// ---------- paper portfolio and risk checks (M2.3, ADR-031) ----------

export type PortfolioResponse = components["schemas"]["PortfolioOut"];
export type PaperPortfolio = components["schemas"]["Portfolio"];
export type PortfolioPosition = components["schemas"]["Position"];
export type RiskRules = components["schemas"]["RulesOut"];
export type RiskCheckEntry = components["schemas"]["RiskCheckOut"];
export type RiskChecks = components["schemas"]["RiskChecksOut"];
export type RiskLimit = components["schemas"]["LimitResult"];
export type RiskCheckIn = components["schemas"]["CheckIn"];

/** The paper portfolio as known at `knownAt` (default now), or null when the API is down. */
export async function loadPortfolio(knownAt?: string): Promise<PortfolioResponse | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/portfolio", {
      params: { query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

/** The stored risk checks known at `knownAt` (of the given triggers), newest first, or null
 * when the API is down. */
export async function loadRiskChecks(
  knownAt?: string,
  limit = 30,
  trigger?: ("trade" | "on_demand" | "standard")[],
): Promise<RiskChecks | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/risk/checks", {
      params: { query: { ...(knownAt ? { known_at: knownAt } : {}), limit, ...(trigger ? { trigger } : {}) } },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

export type RiskCheckResult =
  | { status: "ok"; data: RiskCheckEntry }
  | { status: "invalid"; errors: string[] }
  | { status: "unavailable" };

/** Try a paper trade against the risk limits now: stored and audited, no decision recorded. */
export async function tryRiskCheck(body: RiskCheckIn): Promise<RiskCheckResult> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data, error, response } = await client.POST("/risk/checks", { body, cache: "no-store" });
    if (data) return { status: "ok", data };
    if ([404, 422].includes(response.status)) {
      return { status: "invalid", errors: validationMessages(error, "The API refused the check.") };
    }
    return { status: "unavailable" };
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

// ---------- S3 ETF rotation and Opportunity Radar candidates (M2.4, ADR-032) ----------

export type RotationResponse = components["schemas"]["RotationOut"];
export type StoredRotation = components["schemas"]["StoredRotation"];
export type Rotation = components["schemas"]["Rotation"];
export type EtfReading = components["schemas"]["EtfReading"];
export type TrendReading = components["schemas"]["TrendReading"];
export type RotationHolding = components["schemas"]["Holding"];
export type RotationPoint = components["schemas"]["RotationPoint"];
export type OpportunityCandidates = components["schemas"]["OpportunityCandidatesOut"];
export type CompanyCandidate = components["schemas"]["CompanyCandidate"];
export type EtfCandidate = components["schemas"]["EtfCandidate"];
export type MarketContext = components["schemas"]["MarketContext"];

/** The stored S3 rotation as known at `knownAt` and every target set since, or null when the
 * API is down. */
export async function loadRotation(knownAt?: string): Promise<RotationResponse | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/rotation", {
      params: { query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

/** The Opportunity Radar candidates as known at `knownAt`, or null when the API is down. */
export async function loadCandidates(knownAt?: string): Promise<OpportunityCandidates | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/candidates", {
      params: { query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

// ---------- S4 momentum (M3.0, ADR-036 D7) ----------

export type MomentumResponse = components["schemas"]["MomentumOut"];
export type StoredMomentum = components["schemas"]["StoredMomentum"];
export type MomentumAssessment = components["schemas"]["MomentumAssessment"];
export type CompanyReading = components["schemas"]["CompanyReading"];
export type MomentumPoint = components["schemas"]["MomentumPoint"];
export type MomentumCandidate = components["schemas"]["MomentumCandidate"];

/** The stored S4 assessment as known at `knownAt` and every target set since, or null when the
 * API is down. */
export async function loadMomentum(knownAt?: string): Promise<MomentumResponse | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/momentum", {
      params: { query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}

// ---------- backtests (M2.5, ADR-033) ----------

export type BacktestsResponse = components["schemas"]["BacktestsOut"];
export type StoredBacktest = components["schemas"]["StoredRun"];
export type BacktestRun = components["schemas"]["Run"];
export type BacktestFold = components["schemas"]["Fold"];
export type BacktestTrade = components["schemas"]["Trade"];
export type BacktestRebalance = components["schemas"]["Rebalance"];
export type BacktestOverlap = components["schemas"]["Overlap"];

/** Each strategy's latest stored backtest as known at `knownAt` and their factor overlap, or
 * null when the API is down. Performance is withheld (OD-7). */
export async function loadBacktests(knownAt?: string): Promise<BacktestsResponse | null> {
  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  try {
    const { data } = await client.GET("/backtests", {
      params: { query: knownAt ? { known_at: knownAt } : {} },
      cache: "no-store",
    });
    return data ?? null;
  } catch {
    return null;
  }
}
