"use client";

import { useActionState } from "react";

import { Metric } from "@/components/Metric";
import type { JournalFormAction } from "@/components/journal/EntryForm";

/** Exit an open paper TRADE at the last close known now: a new decision, never an edit. */
export function ExitForm({
  decisionId,
  cardId,
  action,
}: {
  decisionId: string;
  cardId: string;
  action: JournalFormAction;
}) {
  const [state, formAction, pending] = useActionState(action, { errors: [] });
  return (
    <form action={formAction} aria-label="Exit" className="flex flex-wrap items-center gap-2 pt-1 text-sm">
      <input type="hidden" name="decision_id" value={decisionId} />
      <input type="hidden" name="card_id" value={cardId} />
      <input
        name="note"
        aria-label="Exit note (optional)"
        placeholder="Exit note (optional)"
        maxLength={1000}
        className="min-w-0 flex-1 rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700"
      />
      <button
        type="submit"
        disabled={pending}
        className="rounded border border-neutral-300 px-3 py-1 hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
      >
        {pending ? "Exiting…" : "Exit at the last close"}
      </button>
      {state.errors.length > 0 ? (
        <p role="alert" className="w-full text-amber-400">
          <Metric termId="trade_decision" icon={false}>
            {state.errors.join(" ")}
          </Metric>
        </p>
      ) : null}
    </form>
  );
}
