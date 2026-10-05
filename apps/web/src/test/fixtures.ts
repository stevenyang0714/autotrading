/** Recorded real API responses (tests/fixtures/api, see recorded_from in each file). */
import dataHealth from "../../tests/fixtures/api/data-health.json";
import deadLetters from "../../tests/fixtures/api/dead-letters.json";
import fundamentalsAapl from "../../tests/fixtures/api/fundamentals-aapl.json";
import fundamentalsAaplAfter from "../../tests/fixtures/api/fundamentals-aapl-after-10ka.json";
import fundamentalsAaplBefore from "../../tests/fixtures/api/fundamentals-aapl-before-10ka.json";
import fundamentalsXom from "../../tests/fixtures/api/fundamentals-xom.json";
import ingestionRuns from "../../tests/fixtures/api/ingestion-runs.json";
import instruments from "../../tests/fixtures/api/instruments.json";

import type {
  DataHealthData,
  DataHealthReport,
  DeadLetter,
  Fundamentals,
  IngestionRun,
  InstrumentList,
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
