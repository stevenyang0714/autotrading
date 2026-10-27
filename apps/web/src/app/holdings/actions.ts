"use server";

import { redirect } from "next/navigation";

import type { HoldingFormState } from "@/components/holdings/HoldingEntryForm";
import { type NewHoldingEntry, createHoldingEntry, reverseHoldingEntry } from "@/lib/api";

const UNAVAILABLE = ["Data unavailable: the API could not be reached, so nothing was saved."];

function text(form: FormData, name: string): string {
  return String(form.get(name) ?? "").trim();
}

function optional(form: FormData, name: string): string | null {
  return text(form, name) || null;
}

/**
 * Record a holdings entry (M3.10, ADR-041 H1). The API checks the kind's fields, the symbol and
 * that a sell never leaves the account short, and audits the write as `web`; on success the
 * page reloads with the new valuation. Nothing is ever sent to a broker.
 */
export async function recordEntryAction(_previous: HoldingFormState, form: FormData): Promise<HoldingFormState> {
  const kind = text(form, "kind") as NewHoldingEntry["kind"];
  const listed = kind === "buy" || kind === "sell" || kind === "dividend";
  const trade = kind === "buy" || kind === "sell";
  const result = await createHoldingEntry({
    kind,
    account: text(form, "account"),
    trade_date: text(form, "trade_date"),
    market: listed ? (text(form, "market") === "TW" ? "TW" : "US") : null,
    symbol: listed ? text(form, "symbol").toUpperCase() : null,
    currency: listed ? null : text(form, "currency") === "TWD" ? "TWD" : "USD",
    quantity: trade ? text(form, "quantity") : null,
    price: trade ? text(form, "price") : null,
    fee: trade ? optional(form, "fee") : null,
    amount: trade ? null : text(form, "amount"),
    note: optional(form, "note"),
  });
  if (result.status === "invalid") return { errors: result.errors };
  if (result.status === "unavailable") return { errors: UNAVAILABLE };
  redirect("/holdings");
}

/** Reverse an entry from every date on. */
export async function reverseEntryAction(_previous: HoldingFormState, form: FormData): Promise<HoldingFormState> {
  const result = await reverseHoldingEntry(text(form, "entry_id"), null);
  if (result.status === "invalid") return { errors: result.errors };
  if (result.status === "unavailable") return { errors: UNAVAILABLE };
  redirect("/holdings");
}
