"use server";

import { redirect } from "next/navigation";

import type { AcknowledgeState } from "@/components/alerts/AcknowledgeForm";
import { acknowledgeAlert } from "@/lib/api";

/**
 * Acknowledge an alert (M1.7, ADR-028 A4): once, with an optional note; the API records it in
 * the Audit Log as `web`. On success the Alerts Center reloads with the same filters.
 */
export async function acknowledgeAction(_previous: AcknowledgeState, form: FormData): Promise<AcknowledgeState> {
  const note = String(form.get("note") ?? "").trim();
  const result = await acknowledgeAlert(String(form.get("alert_id") ?? ""), note || null);
  if (result.status === "invalid") return { errors: result.errors };
  if (result.status === "unavailable") {
    return { errors: ["Data unavailable: the API could not be reached, so nothing was saved."] };
  }
  const back = String(form.get("return_to") ?? "");
  redirect(back.startsWith("/dashboards/alerts-center") ? back : "/dashboards/alerts-center");
}
