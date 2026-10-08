"use server";

import { redirect } from "next/navigation";

import type { SaveState } from "@/components/instruments/AssumptionsForm";
import { saveAssumptions } from "@/lib/api";

/**
 * Save the edit form as a new assumption version (M1.3a, ADR-023 F4). The API validates,
 * numbers and audits it; on success the page reloads showing the new version, at the same
 * As known on date. Nothing is ever overwritten.
 */
export async function saveAssumptionsAction(_previous: SaveState, form: FormData): Promise<SaveState> {
  const ticker = String(form.get("ticker") ?? "");
  const rate = (name: string) => String(form.get(name) ?? "").trim();
  const result = await saveAssumptions(
    ticker,
    {
      equity_risk_premium: rate("equity_risk_premium"),
      terminal_growth: rate("terminal_growth"),
      growth_bear: rate("growth_bear"),
      growth_base: rate("growth_base"),
      growth_bull: rate("growth_bull"),
      subtract_sbc: form.get("subtract_sbc") === "on",
    },
    String(form.get("reason") ?? ""),
  );
  if (result.status === "invalid") return { errors: result.errors };
  if (result.status === "unavailable") {
    return { errors: ["Data unavailable: the API could not be reached, so nothing was saved."] };
  }
  const knownOn = String(form.get("known_on") ?? "");
  const query = new URLSearchParams({
    ...(knownOn ? { known_on: knownOn } : {}),
    assumptions: String(result.data.version),
  });
  redirect(`/instruments/${encodeURIComponent(ticker)}?${query.toString()}#fair-value`);
}
