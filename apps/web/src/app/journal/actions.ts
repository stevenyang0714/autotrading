"use server";

import { redirect } from "next/navigation";

import type { JournalFormState } from "@/components/journal/EntryForm";
import { type NewCardVersion, addCardVersion, createJournalEntry, exitPaperTrade } from "@/lib/api";

const UNAVAILABLE = ["Data unavailable: the API could not be reached, so nothing was saved."];

function text(form: FormData, name: string): string {
  return String(form.get(name) ?? "").trim();
}

function optional(form: FormData, name: string): string | null {
  return text(form, name) || null;
}

/** The card fields of the form: each checked row with its note, catalysts with a description. */
function content(form: FormData): NewCardVersion {
  const evidence = form.getAll("evidence").map((value) => {
    const ref = JSON.parse(String(value)) as { kind: string; id?: string; day?: string };
    const note = text(form, `note:${ref.kind}:${ref.id ?? ref.day}`);
    return { ...ref, note: note || null } as NewCardVersion["evidence"][number];
  });
  const dates = form.getAll("catalyst_expected").map((value) => String(value));
  const catalysts = form
    .getAll("catalyst_description")
    .map((value, i) => ({ description: String(value).trim(), expected: dates[i] || null }))
    .filter((catalyst) => catalyst.description);
  return {
    thesis: text(form, "thesis"),
    evidence,
    catalysts,
    invalidation: text(form, "invalidation"),
    notes: optional(form, "notes"),
    signal_ids: form.getAll("signal").map(String),
  };
}

/**
 * Save a Thesis Card with its decision, or a new version of a card (M1.6, ADR-027). The API
 * reads every cited row again, refuses what it cannot find and audits the write; on success
 * the card's page opens. Nothing is ever sent to a broker.
 */
export async function saveEntryAction(_previous: JournalFormState, form: FormData): Promise<JournalFormState> {
  const cardId = text(form, "card_id");
  const fields = content(form);
  let result;
  if (cardId) {
    result = await addCardVersion(cardId, fields);
  } else {
    const trade = text(form, "decision") === "trade";
    const orderType = text(form, "order_type") === "limit" ? "limit" : "market";
    result = await createJournalEntry({
      ...fields,
      ticker: text(form, "ticker"),
      decision: trade
        ? {
            decision: "trade",
            side: text(form, "side") === "sell" ? "sell" : "buy",
            quantity: text(form, "quantity"),
            order_type: orderType,
            limit_price: orderType === "limit" ? text(form, "limit_price") : null,
            max_loss: optional(form, "max_loss"),
            note: optional(form, "decision_note"),
          }
        : {
            decision: "no_trade",
            no_trade_reason: (text(form, "no_trade_reason") || "other") as "priced_in",
            note: optional(form, "decision_note"),
          },
    });
  }
  if (result.status === "invalid") return { errors: result.errors };
  if (result.status === "unavailable") return { errors: UNAVAILABLE };
  redirect(`/journal/${result.data.card.card_id}`);
}

/** Exit an open paper TRADE at the last close known now. */
export async function exitAction(_previous: JournalFormState, form: FormData): Promise<JournalFormState> {
  const result = await exitPaperTrade(text(form, "decision_id"), optional(form, "note"));
  if (result.status === "invalid") return { errors: result.errors };
  if (result.status === "unavailable") return { errors: UNAVAILABLE };
  redirect(`/journal/${text(form, "card_id")}`);
}
