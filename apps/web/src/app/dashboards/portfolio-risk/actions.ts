"use server";

import type { TryCheckState } from "@/components/risk/TryCheckForm";
import { tryRiskCheck } from "@/lib/api";

/**
 * Try a paper trade against the risk limits now (M2.3, ADR-031): the API stores the check and
 * audits it as `web`; no decision is recorded and nothing is sent anywhere.
 */
export async function tryCheckAction(_previous: TryCheckState, form: FormData): Promise<TryCheckState> {
  const value = (name: string) => String(form.get(name) ?? "").trim();
  const result = await tryRiskCheck({
    ticker: value("ticker"),
    side: value("side") === "sell" ? "sell" : "buy",
    quantity: value("quantity"),
    max_loss: value("max_loss") || null,
  });
  if (result.status === "ok") return { errors: [], result: result.data };
  if (result.status === "invalid") return { errors: result.errors, result: null };
  return { errors: ["Data unavailable: the API could not be reached, so nothing was checked."], result: null };
}
