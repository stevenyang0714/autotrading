"use client";

import { useActionState } from "react";

import { Metric } from "@/components/Metric";

export interface AcknowledgeState {
  errors: string[];
}

export type AcknowledgeAction = (previous: AcknowledgeState, form: FormData) => Promise<AcknowledgeState>;

/** Acknowledge one alert, once, with an optional note; recorded in the Audit Log. */
export function AcknowledgeForm({
  alertId,
  returnTo,
  action,
}: {
  alertId: string;
  returnTo: string;
  action: AcknowledgeAction;
}) {
  const [state, formAction, pending] = useActionState(action, { errors: [] });
  return (
    <form action={formAction} aria-label="Acknowledge" className="flex flex-wrap items-center gap-2 pt-1 text-sm">
      <input type="hidden" name="alert_id" value={alertId} />
      <input type="hidden" name="return_to" value={returnTo} />
      <input
        name="note"
        aria-label="Note (optional)"
        placeholder="Note (optional)"
        maxLength={500}
        className="min-w-0 flex-1 rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700"
      />
      <button
        type="submit"
        disabled={pending}
        className="rounded border border-neutral-300 px-3 py-1 hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
      >
        {pending ? "Saving…" : "Acknowledge"}
      </button>
      {state.errors.length > 0 ? (
        <p role="alert" className="w-full text-amber-400">
          <Metric termId="alert_acknowledgement" icon={false}>
            {state.errors.join(" ")}
          </Metric>
        </p>
      ) : null}
    </form>
  );
}
