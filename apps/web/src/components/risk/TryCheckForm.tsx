"use client";

import { useActionState } from "react";

import { Metric } from "@/components/Metric";
import type { RiskCheckEntry } from "@/lib/api";
import { LIMIT_TERMS } from "@/lib/risk";

export interface TryCheckState {
  errors: string[];
  result: RiskCheckEntry | null;
}

export type TryCheckAction = (previous: TryCheckState, form: FormData) => Promise<TryCheckState>;

const input = "rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700";

/** Try a paper trade against the risk limits now (M2.3): the check is stored and audited, no
 * decision is recorded and nothing is sent anywhere. */
export function TryCheckForm({ tickers, action }: { tickers: string[]; action: TryCheckAction }) {
  const [state, formAction, pending] = useActionState(action, { errors: [], result: null });
  const result = state.result;
  return (
    <div className="space-y-2" data-block="try">
      <form action={formAction} aria-label="Try a paper trade" className="flex flex-wrap items-end gap-2 text-sm">
        <label className="space-y-1">
          <span className="block">Company</span>
          <select name="ticker" className={input} defaultValue={tickers[0]}>
            {tickers.map((ticker) => (
              <option key={ticker} value={ticker}>
                {ticker}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="block">Side</span>
          <select name="side" className={input} defaultValue="buy">
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
          </select>
        </label>
        <label className="space-y-1">
          <span className="block">Shares</span>
          <input name="quantity" type="number" min="0.0001" step="any" required className={`${input} w-28`} />
        </label>
        <label className="space-y-1">
          <span className="block">
            <Metric termId="max_loss" icon={false}>
              Maximum loss (USD)
            </Metric>
          </span>
          <input name="max_loss" type="number" min="0.01" step="0.01" className={`${input} w-32`} />
        </label>
        <button
          type="submit"
          disabled={pending}
          className="rounded border border-neutral-300 px-3 py-1 hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
        >
          {pending ? "Checking…" : "Check"}
        </button>
      </form>
      {state.errors.length > 0 ? (
        <p role="alert" className="text-sm text-amber-400">
          <Metric termId="risk_check" icon={false}>
            {state.errors.join(" ")}
          </Metric>
        </p>
      ) : null}
      {result ? (
        <div data-try-result={result.verdict} className="space-y-1 rounded border border-neutral-800 px-3 py-2 text-sm">
          <p className={result.verdict === "pass" ? "text-emerald-300" : "text-rose-300"}>
            <Metric termId={result.verdict === "pass" ? "risk_check" : "risk_veto"} icon={false}>
              {result.verdict === "pass" ? "PASS" : "VETO"}: {result.check.proposal.side} {result.check.proposal.quantity}{" "}
              {result.ticker} under risk rules {result.rule_version} (stored, nothing recorded or sent)
            </Metric>
          </p>
          <ul className="space-y-0.5 text-xs">
            {result.check.limits.map((limit) => (
              <li key={limit.limit_id} data-limit={limit.limit_id} data-status={limit.status}>
                <Metric termId={LIMIT_TERMS[limit.limit_id] ?? "risk_check"} icon={false}>
                  <span className={limit.status === "pass" ? "text-neutral-300" : "text-rose-300"}>
                    {limit.status === "pass" ? "pass" : "veto"} · {limit.label}: {limit.detail} ({limit.threshold})
                  </span>
                </Metric>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
