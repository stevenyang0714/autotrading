"use client";

import { useActionState, useState } from "react";

import { Metric } from "@/components/Metric";

export interface HoldingFormState {
  errors: string[];
}

export type HoldingFormAction = (previous: HoldingFormState, form: FormData) => Promise<HoldingFormState>;

const input = "rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700";
const LISTED = new Set(["buy", "sell", "dividend"]);
const TRADES = new Set(["buy", "sell"]);

/**
 * Record one ledger entry (M3.10, ADR-041 H1): a buy or sell (shares, price, optional fee), a
 * cash dividend, or a deposit, withdrawal or fee (an amount in USD or TWD). Entries are
 * append-only: a mistake is reversed from the list below and entered again. Nothing is ever
 * sent to a broker.
 */
export function HoldingEntryForm({
  accounts,
  today,
  action,
}: {
  accounts: string[];
  today: string;
  action: HoldingFormAction;
}) {
  const [state, formAction, pending] = useActionState(action, { errors: [] });
  const [kind, setKind] = useState("buy");
  const [market, setMarket] = useState("US");
  const listed = LISTED.has(kind);
  const currency = listed ? (market === "TW" ? "TWD" : "USD") : null;
  return (
    <form action={formAction} aria-label="Record an entry" className="space-y-3 text-sm">
      <div className="flex flex-wrap items-end gap-2">
        <label className="space-y-1">
          <span className="block">
            <Metric termId="holding_entry" icon={false}>
              Kind
            </Metric>
          </span>
          <select name="kind" className={input} value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
            <option value="dividend">Cash dividend</option>
            <option value="deposit">Deposit</option>
            <option value="withdrawal">Withdrawal</option>
            <option value="fee">Fee</option>
          </select>
        </label>
        <label className="space-y-1">
          <span className="block">
            <Metric termId="holdings_account" icon={false}>
              Account
            </Metric>
          </span>
          <input
            name="account"
            required
            maxLength={40}
            list="holding-accounts"
            placeholder="e.g. Firstrade"
            defaultValue={accounts[0] ?? ""}
            className={`${input} w-40`}
          />
          <datalist id="holding-accounts">
            {accounts.map((account) => (
              <option key={account} value={account} />
            ))}
          </datalist>
        </label>
        <label className="space-y-1">
          <span className="block">Trade date</span>
          <input name="trade_date" type="date" required max={today} defaultValue={today} className={input} />
        </label>
        {listed ? (
          <>
            <label className="space-y-1">
              <span className="block">Market</span>
              <select name="market" className={input} value={market} onChange={(e) => setMarket(e.target.value)}>
                <option value="US">US listing (USD)</option>
                <option value="TW">TWSE listing (TWD)</option>
              </select>
            </label>
            <label className="space-y-1">
              <span className="block">Symbol</span>
              <input
                name="symbol"
                required
                maxLength={10}
                placeholder={market === "TW" ? "e.g. 2330" : "e.g. SPY"}
                className={`${input} w-28 uppercase`}
              />
            </label>
          </>
        ) : (
          <label className="space-y-1">
            <span className="block">Currency</span>
            <select name="currency" className={input} defaultValue="USD">
              <option value="USD">USD</option>
              <option value="TWD">TWD</option>
            </select>
          </label>
        )}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        {TRADES.has(kind) ? (
          <>
            <label className="space-y-1">
              <span className="block">Shares</span>
              <input name="quantity" type="number" min="0" step="any" required className={`${input} w-28`} />
            </label>
            <label className="space-y-1">
              <span className="block">{`Price (${currency})`}</span>
              <input name="price" type="number" min="0" step="any" required className={`${input} w-32`} />
            </label>
            <label className="space-y-1">
              <span className="block">{`Fee and tax (${currency}, optional)`}</span>
              <input name="fee" type="number" min="0" step="0.01" className={`${input} w-32`} />
            </label>
          </>
        ) : (
          <label className="space-y-1">
            <span className="block">{currency ? `Amount (${currency})` : "Amount"}</span>
            <input name="amount" type="number" min="0" step="0.01" required className={`${input} w-36`} />
          </label>
        )}
        <label className="min-w-[12rem] flex-1 space-y-1">
          <span className="block">Note (optional)</span>
          <input name="note" maxLength={500} className={`${input} w-full`} />
        </label>
        <button
          type="submit"
          disabled={pending}
          className="rounded border border-neutral-300 px-3 py-1 hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
        >
          {pending ? "Saving…" : "Record"}
        </button>
      </div>
      {state.errors.length > 0 ? (
        <ul role="alert" className="space-y-0.5 text-amber-400">
          {state.errors.map((error) => (
            <li key={error}>
              <Metric termId="holding_entry" icon={false}>
                {error}
              </Metric>
            </li>
          ))}
        </ul>
      ) : null}
    </form>
  );
}
