/** Recorded real API responses (tests/fixtures/api, see recorded_from in each file). */
import alertDetail from "../../tests/fixtures/api/alert-detail.json";
import alertsOpen from "../../tests/fixtures/api/alerts-open.json";
import alertsRegime from "../../tests/fixtures/api/alerts-regime.json";
import alerts from "../../tests/fixtures/api/alerts.json";
import auditDeletes from "../../tests/fixtures/api/audit-log-deletes.json";
import convergence from "../../tests/fixtures/api/convergence.json";
import auditSourceUpdates from "../../tests/fixtures/api/audit-log-sources-updates.json";
import auditLog from "../../tests/fixtures/api/audit-log.json";
import dataHealthSources from "../../tests/fixtures/api/data-health-sources.json";
import dataHealth from "../../tests/fixtures/api/data-health.json";
import deadLetters from "../../tests/fixtures/api/dead-letters.json";
import fundamentalsAapl from "../../tests/fixtures/api/fundamentals-aapl.json";
import fundamentalsAaplAfter from "../../tests/fixtures/api/fundamentals-aapl-after-10ka.json";
import fundamentalsAaplBefore from "../../tests/fixtures/api/fundamentals-aapl-before-10ka.json";
import fundamentalsMeta from "../../tests/fixtures/api/fundamentals-meta.json";
import fundamentalsXom from "../../tests/fixtures/api/fundamentals-xom.json";
import reconciliationAaplTenK from "../../tests/fixtures/api/reconciliation-aapl-10k.json";
import reconciliationList from "../../tests/fixtures/api/reconciliation.json";
import valuationAapl from "../../tests/fixtures/api/valuation-aapl.json";
import assumptionsAapl from "../../tests/fixtures/api/assumptions-aapl.json";
import buybacksAapl from "../../tests/fixtures/api/buybacks-aapl.json";
import buybacksXom from "../../tests/fixtures/api/buybacks-xom.json";
import buybacksNvda from "../../tests/fixtures/api/buybacks-nvda.json";
import buybackStates from "../../tests/fixtures/api/buyback-states.json";
import earningsAapl from "../../tests/fixtures/api/earnings-aapl.json";
import earningsAaplEvening from "../../tests/fixtures/api/earnings-aapl-evening.json";
import earningsDashboard from "../../tests/fixtures/api/earnings-dashboard.json";
import earningsMeta from "../../tests/fixtures/api/earnings-meta.json";
import evidenceAapl from "../../tests/fixtures/api/evidence-aapl.json";
import journalCard from "../../tests/fixtures/api/journal-card.json";
import journalReplay from "../../tests/fixtures/api/journal-replay.json";
import journal from "../../tests/fixtures/api/journal.json";
import signals from "../../tests/fixtures/api/signals.json";
import researchAapl from "../../tests/fixtures/api/research-aapl.json";
import researchDashboardStale from "../../tests/fixtures/api/research-dashboard-stale.json";
import researchDashboard from "../../tests/fixtures/api/research-dashboard.json";
import researchXom from "../../tests/fixtures/api/research-xom.json";
import fairValueAaplStale from "../../tests/fixtures/api/fair-value-aapl-stale.json";
import fairValueAaplV1 from "../../tests/fixtures/api/fair-value-aapl-v1.json";
import fairValueAapl from "../../tests/fixtures/api/fair-value-aapl.json";
import fairValueXom from "../../tests/fixtures/api/fair-value-xom.json";
import valuationAaplStale from "../../tests/fixtures/api/valuation-aapl-stale.json";
import ingestionRuns from "../../tests/fixtures/api/ingestion-runs.json";
import instrumentPricesAaplNoKey from "../../tests/fixtures/api/instrument-prices-aapl-no-key.json";
import instrumentPricesAapl from "../../tests/fixtures/api/instrument-prices-aapl.json";
import instrumentPricesNvdaBefore from "../../tests/fixtures/api/instrument-prices-nvda-before-split.json";
import instruments from "../../tests/fixtures/api/instruments.json";
import macroPayems from "../../tests/fixtures/api/macro-payems.json";
import macroPayemsBefore from "../../tests/fixtures/api/macro-payems-before-revision.json";
import macroSeries from "../../tests/fixtures/api/macro-series.json";
import newsNvdaAnnouncements from "../../tests/fixtures/api/news-nvda-announcements.json";
import newsNvdaCoverage from "../../tests/fixtures/api/news-nvda-coverage.json";
import newsNvda from "../../tests/fixtures/api/news-nvda.json";
import news from "../../tests/fixtures/api/news.json";
import overviewBefore from "../../tests/fixtures/api/overview-before-revision.json";
import overviewMarkets from "../../tests/fixtures/api/overview-markets.json";
import overview from "../../tests/fixtures/api/overview.json";
import pricesLatestNoKey from "../../tests/fixtures/api/prices-latest-no-key.json";
import pricesLatest from "../../tests/fixtures/api/prices-latest.json";
import progress from "../../tests/fixtures/api/progress.json";
import regimeEarlier from "../../tests/fixtures/api/regime-earlier.json";
import regime from "../../tests/fixtures/api/regime.json";
import factorsAapl from "../../tests/fixtures/api/factors-aapl.json";
import factorsNvdaEarlier from "../../tests/fixtures/api/factors-nvda-earlier.json";
import factorsNvda from "../../tests/fixtures/api/factors-nvda.json";
import factorsTlt from "../../tests/fixtures/api/factors-tlt.json";
import factors from "../../tests/fixtures/api/factors.json";

import type {
  AlertDetail,
  RegimeResponse,
  FactorsTable,
  InstrumentFactors,
  Alerts,
  AssumptionList,
  Convergence,
  EvidenceCandidates,
  Journal,
  JournalCard,
  Replay,
  Signals,
  AuditLogPage,
  BuybackStates,
  Earnings,
  EarningsDashboard,
  Buybacks,
  DataHealthData,
  DataHealthReport,
  DeadLetter,
  FairValue,
  Fundamentals,
  IngestionRun,
  InstrumentList,
  InstrumentPrices,
  LatestPrices,
  MacroSeriesList,
  NewsFeed,
  Overview,
  Progress,
  ReconciliationDetail,
  ReconciliationList,
  ResearchDashboard,
  ResearchRecord,
  SeriesObservations,
  SourceHealth,
  Valuation,
} from "@/lib/api";

export const recordedDataHealth: DataHealthData = {
  report: dataHealth.response as DataHealthReport,
  runs: ingestionRuns.response as IngestionRun[],
  deadLetters: deadLetters.response as DeadLetter[],
};

export const recordedInstruments = instruments.response as InstrumentList;

/** Apple now, and around its January 2010 10-K/A (end of 2010-01-25 / 2010-01-27 SGT). */
export const recordedFundamentals = {
  aapl: fundamentalsAapl.response as Fundamentals,
  aaplBefore10KA: fundamentalsAaplBefore.response as Fundamentals,
  aaplAfter10KA: fundamentalsAaplAfter.response as Fundamentals,
  xom: fundamentalsXom.response as Fundamentals,
  meta: fundamentalsMeta.response as Fundamentals,
};

/** Apple's valuation from end-of-day closes, and with only a stale close (M1.2). */
export const recordedValuation = {
  aapl: valuationAapl.response as Valuation,
  stale: valuationAaplStale.response as Valuation,
};

/** Fair value as known on 2026-10-06 (M1.3a): AAPL with the default and a saved v1, AAPL
 * after its last close went stale, and XOM (no separate SBC line, so no DCF). */
export const recordedFairValue = {
  aapl: fairValueAapl.response as FairValue,
  aaplV1: fairValueAaplV1.response as FairValue,
  stale: fairValueAaplStale.response as FairValue,
  xom: fairValueXom.response as FairValue,
};

export const recordedAssumptions = assumptionsAapl.response as AssumptionList;

/** Research Record and dashboard as known on 2026-10-06 (M1.3b): AAPL, XOM (no operating
 * income, SBC or recent diluted shares), and the dashboard then and after the closes went
 * stale. */
export const recordedResearch = {
  aapl: researchAapl.response as ResearchRecord,
  xom: researchXom.response as ResearchRecord,
};

export const recordedResearchDashboard = {
  current: researchDashboard.response as ResearchDashboard,
  stale: researchDashboardStale.response as ResearchDashboard,
};

/** Each issuer's latest 10-K and 10-Q reconciled (M1.1), and Apple's 10-K items. */
export const recordedReconciliation = {
  list: reconciliationList.response as ReconciliationList,
  aapl10K: reconciliationAaplTenK.response as ReconciliationDetail,
};

export const recordedMacroSeries = macroSeries.response as MacroSeriesList;

/** PAYEMS now, and as known at the end of 2026-09-30 SGT (before the August revision). */
export const recordedPayems = {
  now: macroPayems.response as SeriesObservations,
  beforeRevision: macroPayemsBefore.response as SeriesObservations,
};

/** The overview now and as known at the end of 2026-09-30 SGT, from the replayed FRED data. */
export const recordedOverview = {
  now: overview.response as Overview,
  beforeRevision: overviewBefore.response as Overview,
};

/** Source health with next_refresh_at, from the same database (FRED and SEC enabled). */
export const recordedSources = dataHealthSources.response.sources as SourceHealth[];

export const recordedProgress = progress.response as Progress;

/**
 * Prices from the recorded Alpaca data (2026-10-05 close), with the provider configured and
 * without keys; NVDA as known midday on 2024-06-07, before its 10-for-1 split.
 */
export const recordedPrices = {
  latest: pricesLatest.response as LatestPrices,
  latestNoKey: pricesLatestNoKey.response as LatestPrices,
  aapl: instrumentPricesAapl.response as InstrumentPrices,
  aaplNoKey: instrumentPricesAaplNoKey.response as InstrumentPrices,
  nvdaBeforeSplit: instrumentPricesNvdaBefore.response as InstrumentPrices,
};

/** The overview from the same database: the markets block (no macro data there). */
export const recordedMarketsOverview = overviewMarkets.response as Overview;

/** News from the recorded GDELT and feed responses (copies collapsed), and NVDA's stories. */
export const recordedNews = {
  all: news.response as NewsFeed,
  nvda: newsNvda.response as NewsFeed,
  nvdaAnnouncements: newsNvdaAnnouncements.response as NewsFeed,
  nvdaCoverage: newsNvdaCoverage.response as NewsFeed,
};

/** The audit log of a test database: config sync inserts, one config change, one deleted row. */
export const recordedAudit = {
  all: auditLog.response as AuditLogPage,
  sourceUpdates: auditSourceUpdates.response as AuditLogPage,
  deletes: auditDeletes.response as AuditLogPage,
};

/** Buybacks as known on 2026-10-06 (M1.4a): Apple (two recorded 8-K authorizations, the 2021
 * XBRL tag) and ExxonMobil (a yearly plan, no XBRL authorization). */
export const recordedBuybacks = {
  aapl: buybacksAapl.response as Buybacks,
  xom: buybacksXom.response as Buybacks,
  nvda: buybacksNvda.response as Buybacks,
};

/** Buyback states as known on 2026-10-06 (M1.4b), evaluated then and at 2026-03-31 under rule
 * 0.1.0: Apple and ExxonMobil ACTIVE, NVIDIA WATCH (its press release only), Meta none. */
export const recordedBuybackStates = buybackStates.response as BuybackStates;

/** Earnings events as known on 2026-10-06 (M1.5): Apple (its 2026-04-30 release after the
 * close, matched to the next morning's 10-Q; no numeric guidance), the same on that evening
 * (no reaction, no 10-Q yet), and Meta (a revenue outlook in its 2024-02-01 release). */
export const recordedEarnings = {
  aapl: earningsAapl.response as Earnings,
  aaplEvening: earningsAaplEvening.response as Earnings,
  meta: earningsMeta.response as Earnings,
};

export const recordedEarningsDashboard = earningsDashboard.response as EarningsDashboard;

/** The paper journal (M1.6) from tests/integration/test_journal.py: two AAPL cards written at
 * 2026-09-15 12:00 UTC (a NO TRADE, priced in, now at version 2; a paper TRADE buy 10, exited
 * at 2026-10-06), viewed as known on 2026-10-06; the TRADE card and its replay (all identical);
 * AAPL's evidence candidates at 2026-09-15; the signals as known on 2026-10-06. */
export const recordedJournal = journal.response as unknown as Journal;
export const recordedJournalCard = journalCard.response as unknown as JournalCard;
export const recordedReplay = journalReplay.response as unknown as Replay;
export const recordedEvidence = evidenceAapl.response as unknown as EvidenceCandidates;
export const recordedSignals = signals.response as unknown as Signals;

/** The Alerts Center (M1.7) from tests/integration/test_alerts.py, as known on 2026-10-06:
 * every alert (level changes are backfilled: evaluated after their date), the open live ones,
 * each company's level (Apple and ExxonMobil L1 Watch, Meta L0) and one level change. */
export const recordedAlerts = alerts.response as unknown as Alerts;
export const recordedOpenAlerts = alertsOpen.response as unknown as Alerts;
export const recordedConvergence = convergence.response as unknown as Convergence;
export const recordedAlertDetail = alertDetail.response as unknown as AlertDetail;

/** Alerts as known 2026-10-06 18:00 UTC (M2.1), with the market-wide stress alert the regime
 * integration test raises (tests/integration/test_regime.py). */
export const recordedRegimeAlerts = alertsRegime.response as unknown as Alerts;

/** The macro regime (M2.1) as known on 2026-10-06 (stress normal, 0 of 9 flags; growth
 * slowing, inflation above target) and on 2026-09-15 (the August month end). */
export const recordedRegime = regime.response as unknown as RegimeResponse;
export const recordedRegimeEarlier = regimeEarlier.response as unknown as RegimeResponse;
export const recordedFactors = factors.response as unknown as FactorsTable;
export const recordedFactorsNvda = factorsNvda.response as unknown as InstrumentFactors;
export const recordedFactorsNvdaEarlier = factorsNvdaEarlier.response as unknown as InstrumentFactors;
export const recordedFactorsAapl = factorsAapl.response as unknown as InstrumentFactors;
export const recordedFactorsTlt = factorsTlt.response as unknown as InstrumentFactors;
