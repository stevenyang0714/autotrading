/** Recorded real API responses (tests/fixtures/api, see recorded_from in each file). */
import dataHealth from "../../tests/fixtures/api/data-health.json";
import deadLetters from "../../tests/fixtures/api/dead-letters.json";
import ingestionRuns from "../../tests/fixtures/api/ingestion-runs.json";

import type { DataHealthData, DataHealthReport, DeadLetter, IngestionRun } from "@/lib/api";

export const recordedDataHealth: DataHealthData = {
  report: dataHealth.response as DataHealthReport,
  runs: ingestionRuns.response as IngestionRun[],
  deadLetters: deadLetters.response as DeadLetter[],
};
