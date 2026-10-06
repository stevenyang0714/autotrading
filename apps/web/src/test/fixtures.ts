/** Recorded real API responses (tests/fixtures/api, see recorded_from in each file). */
import dataHealthSources from "../../tests/fixtures/api/data-health-sources.json";
import dataHealth from "../../tests/fixtures/api/data-health.json";
import deadLetters from "../../tests/fixtures/api/dead-letters.json";
import fundamentalsAapl from "../../tests/fixtures/api/fundamentals-aapl.json";
import fundamentalsAaplAfter from "../../tests/fixtures/api/fundamentals-aapl-after-10ka.json";
import fundamentalsAaplBefore from "../../tests/fixtures/api/fundamentals-aapl-before-10ka.json";
import fundamentalsXom from "../../tests/fixtures/api/fundamentals-xom.json";
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

import type {
  DataHealthData,
  DataHealthReport,
  DeadLetter,
  Fundamentals,
  IngestionRun,
  InstrumentList,
  InstrumentPrices,
  LatestPrices,
  MacroSeriesList,
  NewsFeed,
  Overview,
  Progress,
  SeriesObservations,
  SourceHealth,
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
