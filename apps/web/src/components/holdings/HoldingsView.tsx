import Link from "next/link";
import type { ReactNode } from "react";

import { AsKnownOnForm } from "@/components/AsKnownOnForm";
import { InstrumentName } from "@/components/InstrumentName";
import { Metric } from "@/components/Metric";
import type { CompleteTermId } from "@/generated/glossary";
import type { HoldingEntries, HoldingEntry, Holdings } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import { FLAG_LABELS, FLAG_TERMS, KIND_LABELS, money, quantity, signedMoney, weight } from "@/lib/holdings";
import { formatSgtEt } from "@/lib/time";

const HREF = "/holdings";
const cell = "px-3 py-1.5 text-right tabular-nums";
const head = "px-3 py-1.5 text-right font-normal text-neutral-400";

function Tile({ termId, label, value, sub }: { termId: CompleteTermId; label: string; value: string; sub?: string }) {
  return (
    <div className="space-y-0.5 rounded border border-neutral-800 px-3 py-2" data-tile={termId}>
      <p className="text-xs text-neutral-400">
        <Metric termId={termId}>{label}</Metric>
      </p>
      <p className="text-lg tabular-nums">
        <Metric termId={termId} icon={false}>
          {value}
        </Metric>
      </p>
      {sub ? (
        <p className="text-xs text-neutral-500">
          <Metric termId={termId} icon={false}>
            {sub}
          </Metric>
        </p>
      ) : null}
    </div>
  );
}

function Num({ termId, children, className = "" }: { termId: CompleteTermId; children: ReactNode; className?: string }) {
  return (
    <td className={`${cell} ${className}`}>
      <Metric termId={termId} icon={false}>
        {children}
      </Metric>
    </td>
  );
}

function tone(value: string | null | undefined): string {
  const number = Number(value);
  if (value === null || value === undefined || !Number.isFinite(number) || number === 0) return "";
  return number > 0 ? "text-emerald-300" : "text-rose-300";
}

function Summary({ data }: { data: Holdings }) {
  const fx = data.fx;
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
      <Tile
        termId="holdings_equity"
        label="Total (USD)"
        value={money(data.equity_usd, "USD")}
        sub={`${data.positions.length} positions · ${data.entries} entries`}
      />
      <Tile
        termId="holdings_change"
        label="Change (24 h)"
        value={signedMoney(data.change_usd, "USD")}
        sub={`since ${formatSgtEt(data.change_since)}`}
      />
      <Tile
        termId="fx_rate_used"
        label="TWD per USD"
        value={fx ? fx.value : "none known"}
        sub={fx ? `DEXTAUS for ${fx.observation_date} · ${fx.lag_days} days old` : "TWD amounts are not converted"}
      />
    </div>
  );
}

function Flags({ flags }: { flags: string[] }) {
  if (flags.length === 0) return null;
  return (
    <ul className="space-y-1 text-sm text-amber-300" aria-label="Holdings flags">
      {flags.map((flag) => (
        <li key={flag} data-flag={flag}>
          <Metric termId={FLAG_TERMS[flag] ?? "holding_flag"} icon={false}>
            {FLAG_LABELS[flag] ?? flag}
          </Metric>
        </li>
      ))}
    </ul>
  );
}

function Totals({ data }: { data: Holdings }) {
  if (data.totals.length === 0) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" aria-label="Totals by currency">
        <thead>
          <tr className="border-b border-neutral-800">
            <th className="px-3 py-1.5 text-left font-normal text-neutral-400">Currency</th>
            <th className={head}>Positions</th>
            <th className={head}>
              <Metric termId="cash_balance">Cash</Metric>
            </th>
            <th className={head}>Total</th>
            <th className={head}>
              <Metric termId="unrealized_pnl">Unrealized</Metric>
            </th>
            <th className={head}>
              <Metric termId="realized_pnl">Realized</Metric>
            </th>
            <th className={head}>
              <Metric termId="net_contributions">Net deposits</Metric>
            </th>
          </tr>
        </thead>
        <tbody>
          {data.totals.map((t) => (
            <tr key={t.currency} data-currency={t.currency} className="border-b border-neutral-900">
              <th scope="row" className="px-3 py-1.5 text-left font-normal">
                <span data-identifier="">{t.currency}</span>
              </th>
              <Num termId="holdings_equity">{formatMoney(t.positions, t.currency)}</Num>
              <Num termId="cash_balance">{formatMoney(t.cash, t.currency)}</Num>
              <Num termId="holdings_equity">{formatMoney(t.total, t.currency)}</Num>
              <Num termId="unrealized_pnl" className={tone(t.unrealized)}>
                {signedMoney(t.unrealized, t.currency)}
              </Num>
              <Num termId="realized_pnl" className={tone(t.realized)}>
                {signedMoney(t.realized, t.currency)}
              </Num>
              <Num termId="net_contributions">{formatMoney(t.contributions, t.currency)}</Num>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Positions({ data }: { data: Holdings }) {
  if (data.positions.length === 0) {
    return <p className="text-sm text-neutral-400">No open positions at this time.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" aria-label="Positions">
        <thead>
          <tr className="border-b border-neutral-800">
            <th className="px-3 py-1.5 text-left font-normal text-neutral-400">Holding</th>
            <th className="px-3 py-1.5 text-left font-normal text-neutral-400">
              <Metric termId="holdings_account">Account</Metric>
            </th>
            <th className={head}>Shares</th>
            <th className={head}>
              <Metric termId="average_cost">Avg cost</Metric>
            </th>
            <th className={head}>
              <Metric termId="price_mark">Mark</Metric>
            </th>
            <th className={head}>Value</th>
            <th className={head}>
              <Metric termId="unrealized_pnl">Unrealized</Metric>
            </th>
            <th className={head}>USD</th>
            <th className={head}>
              <Metric termId="holding_weight">Weight</Metric>
            </th>
          </tr>
        </thead>
        <tbody>
          {data.positions.map((p) => {
            // Research-universe listings have an instrument page; tracked ones do not (H4).
            const href = p.research ? `/instruments/${p.symbol}` : null;
            return (
              <tr
                key={`${p.account}:${p.instrument_id}`}
                data-symbol={p.symbol}
                data-account={p.account}
                className="border-b border-neutral-900 align-top"
              >
                <th scope="row" className="px-3 py-1.5 text-left font-normal">
                  {href ? (
                    <Link href={href} data-identifier="" className="font-medium underline-offset-2 hover:underline">
                      {p.symbol}
                    </Link>
                  ) : (
                    <span data-identifier="" className="font-medium">
                      {p.symbol}
                    </span>
                  )}
                  {p.name ? (
                    <span className="ml-2 text-neutral-400">
                      <InstrumentName name={p.name} zh={p.name_zh ?? p.name} />
                    </span>
                  ) : null}
                  {p.flags.length > 0 ? (
                    <span className="block text-xs text-amber-300">
                      {p.flags.map((flag) => (
                        <Metric key={flag} termId={FLAG_TERMS[flag] ?? "holding_flag"} icon={false} className="mr-2">
                          {FLAG_LABELS[flag] ?? flag}
                        </Metric>
                      ))}
                    </span>
                  ) : null}
                </th>
                <td className="px-3 py-1.5 text-left">
                  <span data-identifier="">{p.account}</span>
                </td>
                <Num termId="average_cost">{quantity(p.quantity)}</Num>
                <Num termId="average_cost">{money(p.average_cost, p.currency)}</Num>
                <Num termId="price_mark">
                  {p.price !== null && p.mark ? `${formatMoney(p.price, p.currency)} (${p.mark.session})` : "n/a"}
                </Num>
                <Num termId="price_mark">{formatMoney(p.market_value, p.currency)}</Num>
                <Num termId="unrealized_pnl" className={tone(p.unrealized)}>
                  {signedMoney(p.unrealized, p.currency)}
                </Num>
                <Num termId="fx_rate_used">{money(p.value_usd, "USD")}</Num>
                <Num termId="holding_weight">{weight(p.weight)}</Num>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Cash({ data }: { data: Holdings }) {
  if (data.cash.length === 0) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" aria-label="Cash">
        <thead>
          <tr className="border-b border-neutral-800">
            <th className="px-3 py-1.5 text-left font-normal text-neutral-400">
              <Metric termId="holdings_account">Account</Metric>
            </th>
            <th className="px-3 py-1.5 text-left font-normal text-neutral-400">Currency</th>
            <th className={head}>
              <Metric termId="cash_balance">Balance</Metric>
            </th>
            <th className={head}>USD</th>
            <th className={head}>
              <Metric termId="holding_weight">Weight</Metric>
            </th>
          </tr>
        </thead>
        <tbody>
          {data.cash.map((c) => (
            <tr key={`${c.account}:${c.currency}`} data-cash={`${c.account}:${c.currency}`} className="border-b border-neutral-900">
              <td className="px-3 py-1.5 text-left">
                <span data-identifier="">{c.account}</span>
              </td>
              <td className="px-3 py-1.5 text-left">
                <span data-identifier="">{c.currency}</span>
              </td>
              <Num termId="cash_balance" className={Number(c.balance) < 0 ? "text-rose-300" : ""}>
                {formatMoney(c.balance, c.currency)}
              </Num>
              <Num termId="fx_rate_used">{money(c.value_usd, "USD")}</Num>
              <Num termId="holding_weight">{weight(c.weight)}</Num>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function describe(e: HoldingEntry): string {
  if (e.kind === "reversal") return "reverses an earlier entry";
  if (e.quantity !== null && e.price !== null) {
    const fee = e.fee && Number(e.fee) > 0 ? `, fee ${formatMoney(e.fee, e.currency)}` : "";
    return `${quantity(e.quantity)} × ${formatMoney(e.price, e.currency)}${fee}`;
  }
  return e.amount !== null ? formatMoney(e.amount, e.currency) : "";
}

function Entries({
  entries,
  reverse,
}: {
  entries: HoldingEntries | null;
  reverse?: (entry: HoldingEntry) => ReactNode;
}) {
  if (entries === null) {
    return (
      <p role="alert" className="text-sm text-neutral-400">
        Data unavailable: the entries could not be loaded.
      </p>
    );
  }
  if (entries.entries.length === 0) {
    return <p className="text-sm text-neutral-400">No entries yet. Record a deposit first, then your buys.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" aria-label="Entries">
        <thead>
          <tr className="border-b border-neutral-800 text-left text-neutral-400">
            <th className="px-3 py-1.5 font-normal">Trade date</th>
            <th className="px-3 py-1.5 font-normal">
              <Metric termId="holding_entry">Entry</Metric>
            </th>
            <th className="px-3 py-1.5 font-normal">
              <Metric termId="holdings_account">Account</Metric>
            </th>
            <th className="px-3 py-1.5 font-normal">Amount</th>
            <th className="px-3 py-1.5 font-normal">Note</th>
            <th className="px-3 py-1.5 font-normal">Recorded</th>
            <th className="px-3 py-1.5 font-normal">
              <span className="sr-only">Correct</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.entries.map((e) => (
            <tr
              key={e.id}
              data-entry={e.id}
              data-kind={e.kind}
              data-status={e.status}
              className={`border-b border-neutral-900 align-top ${e.status === "reversed" ? "text-neutral-500 line-through" : ""}`}
            >
              <td className="px-3 py-1.5 tabular-nums">
                <Metric termId="holding_entry" icon={false}>
                  {e.trade_date}
                </Metric>
              </td>
              <td className="px-3 py-1.5">
                <Metric termId={e.kind === "reversal" ? "holding_reversal" : "holding_entry"} icon={false}>
                  {KIND_LABELS[e.kind] ?? e.kind}
                </Metric>
                {e.symbol ? (
                  <span data-identifier="" className="ml-2 font-medium">
                    {e.symbol}
                  </span>
                ) : null}
              </td>
              <td className="px-3 py-1.5">
                <span data-identifier="">{e.account}</span>
              </td>
              <td className="px-3 py-1.5 tabular-nums">
                <Metric termId="holding_entry" icon={false}>
                  {describe(e)}
                </Metric>
              </td>
              <td className="px-3 py-1.5 text-neutral-400">
                {e.note ? <span data-quoted="">{e.note}</span> : null}
              </td>
              <td className="px-3 py-1.5 text-xs text-neutral-500">
                <Metric termId="holding_entry" icon={false}>
                  {formatSgtEt(e.recorded_at)}
                </Metric>
              </td>
              <td className="px-3 py-1.5">{e.status === "counted" && reverse ? reverse(e) : null}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The Holdings page (M3.10, ADR-041 H9): Steven's real holdings as recorded, valued at the time
 * shown, kept apart from the paper portfolio and on this machine only. `form` and `reverse` are
 * given when viewing now (entries are written at the system time, never backdated in S).
 */
export function HoldingsView({
  data,
  entries,
  knownOn,
  invalidKnownOn = false,
  form,
  reverse,
}: {
  data: Holdings;
  entries: HoldingEntries | null;
  knownOn?: string;
  invalidKnownOn?: boolean;
  form?: ReactNode;
  reverse?: (entry: HoldingEntry) => ReactNode;
}) {
  return (
    <section className="space-y-6" data-page="holdings">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          <Metric termId="page_holdings" zh>
            Holdings
          </Metric>
        </h1>
        <p className="text-sm text-neutral-400">
          <Metric termId="page_holdings" icon={false}>
            {data.detail}
          </Metric>
        </p>
        <p className="text-sm">
          <Link href="/holdings/policy" className="underline-offset-2 hover:underline">
            <Metric termId="page_policy">Investment policy: drift and rebalancing</Metric>
          </Link>
        </p>
        <AsKnownOnForm href={HREF} knownOn={knownOn} invalid={invalidKnownOn} />
        <p className="text-xs text-neutral-500">
          <Metric termId="holdings_equity" icon={false}>
            {`Valued at ${formatSgtEt(data.known_at)} as recorded by ${formatSgtEt(data.system_time)}, valuation ${data.valuation_version}`}
          </Metric>
          {data.latest_snapshot ? (
            <>
              {" · "}
              <Metric termId="holdings_snapshot" icon={false}>
                {`last snapshot ${formatSgtEt(data.latest_snapshot.known_at)}`}
              </Metric>
            </>
          ) : null}
        </p>
      </header>
      <Summary data={data} />
      <Flags flags={data.flags} />
      <section className="space-y-2" aria-labelledby="positions-title">
        <h2 id="positions-title" className="text-lg font-semibold">
          Positions
        </h2>
        <Positions data={data} />
      </section>
      <section className="space-y-2" aria-labelledby="cash-title">
        <h2 id="cash-title" className="text-lg font-semibold">
          <Metric termId="cash_balance">Cash</Metric>
        </h2>
        <Cash data={data} />
        <Totals data={data} />
      </section>
      {form ? (
        <section className="space-y-2" aria-labelledby="record-title">
          <h2 id="record-title" className="text-lg font-semibold">
            <Metric termId="holding_entry">Record an entry</Metric>
          </h2>
          {form}
        </section>
      ) : null}
      <section className="space-y-2" aria-labelledby="entries-title">
        <h2 id="entries-title" className="text-lg font-semibold">
          <Metric termId="holding_entry">Entries</Metric>
        </h2>
        <Entries entries={entries} reverse={reverse} />
      </section>
    </section>
  );
}
