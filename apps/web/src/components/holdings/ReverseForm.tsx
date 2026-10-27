"use client";

import { useActionState } from "react";

import type { HoldingFormAction } from "@/components/holdings/HoldingEntryForm";
import { Metric } from "@/components/Metric";

/** Reverse one entry from every date on (one reversal each); then enter it again if needed. */
export function ReverseForm({ entryId, action }: { entryId: string; action: HoldingFormAction }) {
  const [state, formAction, pending] = useActionState(action, { errors: [] });
  return (
    <form action={formAction} aria-label="Reverse this entry" className="space-y-1 text-xs">
      <input type="hidden" name="entry_id" value={entryId} />
      <button
        type="submit"
        disabled={pending}
        className="rounded border border-neutral-300 px-2 py-0.5 hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
      >
        <Metric termId="holding_reversal" icon={false}>
          {pending ? "Reversing…" : "Reverse"}
        </Metric>
      </button>
      {state.errors.length > 0 ? (
        <p role="alert" className="text-amber-400">
          <Metric termId="holding_reversal" icon={false}>
            {state.errors.join(" ")}
          </Metric>
        </p>
      ) : null}
    </form>
  );
}
