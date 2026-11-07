"use server";

import { redirect } from "next/navigation";

import type { PolicyFormState } from "@/components/holdings/PolicyForm";
import { type NewPolicy, savePolicy } from "@/lib/api";
import { parseMembers } from "@/lib/policy";

const UNAVAILABLE = ["Data unavailable: the API could not be reached, so nothing was saved."];

type SleeveIn = NewPolicy["content"]["sleeves"][number];

function text(form: FormData, name: string): string {
  return String(form.get(name) ?? "").trim();
}

function optional(form: FormData, name: string): string | null {
  return text(form, name) || null;
}

/**
 * Save a new version of the investment policy (M3.12, ADR-043 IP2-IP4). The API checks that the
 * sleeves add up to 100%, that each listing or currency is in one sleeve and that each sleeve's
 * members fit it, and audits the write as `web`; on success the page reloads with the new
 * version in force. Nothing is ever sent to a broker.
 */
export async function savePolicyAction(_previous: PolicyFormState, form: FormData): Promise<PolicyFormState> {
  const count = Number(text(form, "sleeve_count")) || 0;
  const sleeves: SleeveIn[] = Array.from({ length: count }, (_, i) => ({
    name: text(form, `sleeve_${i}_name`),
    asset_class: text(form, `sleeve_${i}_asset_class`) as SleeveIn["asset_class"],
    market: text(form, `sleeve_${i}_market`) as SleeveIn["market"],
    target_pct: text(form, `sleeve_${i}_target_pct`),
    band_pp: text(form, `sleeve_${i}_band_pp`),
    members: parseMembers(text(form, `sleeve_${i}_members`)),
  }));
  const result = await savePolicy({
    content: {
      goals: text(form, "goals"),
      horizon_years: Number(text(form, "horizon_years")),
      risk: text(form, "risk"),
      max_drawdown_pct: optional(form, "max_drawdown_pct"),
      position_cap_pct: optional(form, "position_cap_pct"),
      sleeves,
    },
    reason: text(form, "reason"),
  });
  if (result.status === "invalid") return { errors: result.errors };
  if (result.status === "unavailable") return { errors: UNAVAILABLE };
  redirect("/holdings/policy");
}
