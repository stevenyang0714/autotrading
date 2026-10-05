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
      client.GET("/ingestion-runs", { params: { query: { limit: 20 } }, cache: "no-store" }),
      client.GET("/dead-letters", { cache: "no-store" }),
    ]);
    if (!health.data || !runs.data || !deadLetters.data) return null;
    return { report: health.data, runs: runs.data, deadLetters: deadLetters.data };
  } catch {
    return null;
  }
}
