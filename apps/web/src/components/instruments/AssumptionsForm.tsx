"use client";

import { useActionState } from "react";

import { Metric } from "@/components/Metric";
import type { CompleteTermId } from "@/generated/glossary";
import type { AssumptionParameters } from "@/lib/api";

export interface SaveState {
  errors: string[];
}

export type SaveAction = (previous: SaveState, form: FormData) => Promise<SaveState>;

interface Limit {
  minimum: string;
  maximum: string;
}

const RATES: { name: keyof Omit<AssumptionParameters, "subtract_sbc">; termId: CompleteTermId; label: string }[] = [
  { name: "equity_risk_premium", termId: "equity_risk_premium", label: "Equity risk premium" },
  { name: "terminal_growth", termId: "terminal_growth", label: "Terminal growth" },
  { name: "growth_bear", termId: "scenario_range", label: "Bear growth, years 1-5" },
  { name: "growth_base", termId: "scenario_range", label: "Base growth, years 1-5" },
  { name: "growth_bull", termId: "scenario_range", label: "Bull growth, years 1-5" },
];

/**
 * Edit form for valuation assumptions (M1.3a, ADR-023 F4): prefilled with the version on
 * screen; saving always creates a new version with a reason (the API refuses invalid sets and
 * says why). Works without client JavaScript too: the server action reloads the page.
 */
export function AssumptionsForm({
  ticker,
  knownOn,
  parameters,
  limits,
  action,
}: {
  ticker: string;
  knownOn?: string;
  parameters: AssumptionParameters;
  limits: Record<string, Limit>;
  action: SaveAction;
}) {
  const [state, formAction, pending] = useActionState(action, { errors: [] });
  return (
    <form action={formAction} aria-label="Edit assumptions" className="space-y-3 text-sm">
      <input type="hidden" name="ticker" value={ticker} />
      {knownOn ? <input type="hidden" name="known_on" value={knownOn} /> : null}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {RATES.map(({ name, termId, label }) => {
          const limit = limits[name];
          return (
            <label key={name} className="space-y-1">
              <span className="block">
                <Metric termId={termId} icon={false}>
                  {label}
                </Metric>
              </span>
              <span className="flex items-center gap-1">
                <input
                  name={name}
                  type="number"
                  step="0.01"
                  min={limit?.minimum}
                  max={limit?.maximum}
                  required
                  defaultValue={parameters[name]}
                  className="w-24 rounded border border-neutral-300 bg-transparent px-2 py-1 tabular-nums dark:border-neutral-700"
                />
                <span>%</span>
                {limit ? (
                  <span className="text-xs text-neutral-500">
                    <Metric termId={termId} icon={false}>
                      {limit.minimum} to {limit.maximum}
                    </Metric>
                  </span>
                ) : null}
              </span>
            </label>
          );
        })}
        <label className="flex items-center gap-2 self-end">
          <input name="subtract_sbc" type="checkbox" defaultChecked={parameters.subtract_sbc} />
          <Metric termId="owner_fcf" icon={false}>
            Subtract stock-based compensation
          </Metric>
        </label>
      </div>
      <label className="block space-y-1">
        <span className="block">Reason for this version</span>
        <input
          name="reason"
          type="text"
          required
          maxLength={500}
          placeholder="What changed, and why"
          className="w-full rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700"
        />
      </label>
      {state.errors.length > 0 ? (
        <ul role="alert" className="space-y-0.5 text-amber-400">
          {state.errors.map((error) => (
            <li key={error}>
              <Metric termId="valuation_assumptions" icon={false}>
                {error}
              </Metric>
            </li>
          ))}
        </ul>
      ) : null}
      <button
        type="submit"
        disabled={pending}
        className="rounded border border-neutral-300 px-3 py-1 hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
      >
        {pending ? "Saving…" : "Save as a new version"}
      </button>
      <p className="text-xs text-neutral-500">
        Versions are never changed or deleted; each save is recorded in the Audit Log.
      </p>
    </form>
  );
}
