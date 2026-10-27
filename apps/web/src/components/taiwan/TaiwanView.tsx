import Link from "next/link";
import type { ReactNode } from "react";

import { AsKnownOnForm } from "@/components/AsKnownOnForm";
import { InstrumentName } from "@/components/InstrumentName";
import { Metric } from "@/components/Metric";
import { SourceFreshness } from "@/components/SourceFreshness";
import { Sparkline } from "@/components/Sparkline";
import type { CompleteTermId } from "@/generated/glossary";
import type {
  SourceHealth,
  TaiwanAttribution,
  TaiwanInstrument,
  TaiwanInstrumentResult,
  TaiwanSourceRef,
} from "@/lib/api";
import { ordinal } from "@/lib/factors";
import { formatAmount, formatMoney, formatSigned, groupDigits } from "@/lib/format";
import { formatTaipei } from "@/lib/time";

const VALUATION: Record<string, { label: string; termId: CompleteTermId; unit: "x" | "percent" }> = {
  exchange_pe_ratio: { label: "P/E (TWSE)", termId: "exchange_pe_ratio", unit: "x" },
  exchange_pb_ratio: { label: "P/B (TWSE)", termId: "exchange_pb_ratio", unit: "x" },
  exchange_dividend_yield: { label: "Dividend yield (TWSE)", termId: "exchange_dividend_yield", unit: "percent" },
};

function ratio(value: string, unit: "x" | "percent"): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return unit === "x" ? `${number.toFixed(2)}x` : `${number.toFixed(2)}%`;
}

/** Where a block's numbers come from: the TWSE file, its publication time, the run, the bytes. */
export function SourceLine({ source }: { source: TaiwanSourceRef }) {
  return (
    <p className="text-xs text-neutral-500" data-source="">
      <Metric termId="open_data_attribution" icon={false}>
        {source.dataset}
      </Metric>
      {" · "}
      <Metric termId="point_in_time" icon={false}>
        public from {formatTaipei(source.published_at)} · fetched {formatTaipei(source.ingested_at)}
      </Metric>
      {Number(source.confidence) < 1 ? (
        <>
          {" · "}
          <Metric termId="margin_balance" icon={false}>
            not yet checked against the session before (confidence {source.confidence})
          </Metric>
        </>
      ) : null}
      {source.raw_payload_sha256 ? (
        <>
          {" · "}
          <span data-identifier="" title={source.raw_payload_sha256}>
            sha256 {source.raw_payload_sha256.slice(0, 12)}
          </span>
        </>
      ) : null}
    </p>
  );
}

export function TwseAttribution({ attribution }: { attribution: TaiwanAttribution }) {
  return (
    <p className="border-t border-neutral-800 pt-3 text-xs text-neutral-500" data-block="attribution">
      <Metric termId="open_data_attribution" icon={false}>
        <span data-quoted="">{attribution.text}</span>
      </Metric>{" "}
      <a href={attribution.license_url} className="underline-offset-2 hover:underline" rel="noreferrer" target="_blank">
        Open Government Data License
      </a>
    </p>
  );
}

function PricePanel({ data }: { data: TaiwanInstrument }) {
  const price = data.price;
  return (
    <section className="space-y-2" data-block="taiwan-prices" aria-labelledby="tw-prices">
      <h2 id="tw-prices" className="text-lg font-medium">
        <Metric termId="twse_close" zh>
          Close
        </Metric>
      </h2>
      {price === null ? (
        <p className="text-sm text-neutral-400">No close stored by this date.</p>
      ) : (
        <>
          <p className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <Metric termId="twse_close" icon={false} className="text-2xl font-semibold tabular-nums">
              {formatMoney(price.close, data.currency)}
            </Metric>
            {price.change !== null ? (
              <Metric termId="twse_price_change" icon={false} className="tabular-nums">
                {formatSigned(price.change)}
              </Metric>
            ) : null}
            <Metric termId="taiwan_market_session" icon={false} className="text-sm text-neutral-400">
              session {price.session}
            </Metric>
          </p>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-neutral-400">
                <Metric termId="twse_reference_price">Reference</Metric>
              </dt>
              <dd className="tabular-nums">
                <Metric termId="twse_reference_price" icon={false}>
                  {price.reference !== null ? formatMoney(price.reference, data.currency) : "n/a"}
                </Metric>
              </dd>
            </div>
            <div>
              <dt className="text-neutral-400">
                <Metric termId="volume">Volume</Metric>
              </dt>
              <dd className="tabular-nums">
                <Metric termId="volume" icon={false}>
                  {groupDigits(String(price.volume))} shares
                </Metric>
              </dd>
            </div>
            <div>
              <dt className="text-neutral-400">
                <Metric termId="trade_value">Trade value</Metric>
              </dt>
              <dd className="tabular-nums">
                <Metric termId="trade_value" icon={false}>
                  {price.trade_value !== null ? formatAmount(price.trade_value, data.currency) : "n/a"}
                </Metric>
              </dd>
            </div>
            <div>
              <dt className="text-neutral-400">
                <Metric termId="price_history">History</Metric>
              </dt>
              <dd>
                <Metric termId="price_history" icon={false}>
                  {price.sessions} sessions since {price.history_since}
                </Metric>
              </dd>
            </div>
          </dl>
          <Sparkline
            points={price.history.map((p) => ({ day: p.session, value: p.adjusted_close }))}
            termId="twse_close"
            label={`${data.code} close, on the split basis of the date shown`}
            format={(v) => formatMoney(String(v), data.currency)}
          />
          <SourceLine source={price.source} />
        </>
      )}
    </section>
  );
}

function ValuationPanel({ data }: { data: TaiwanInstrument }) {
  const valuation = data.valuation;
  return (
    <section className="space-y-2" data-block="taiwan-valuation" aria-labelledby="tw-valuation">
      <h2 id="tw-valuation" className="text-lg font-medium">
        <Metric termId="exchange_pe_ratio" zh>
          Valuation (as TWSE publishes it)
        </Metric>
      </h2>
      {valuation === null ? (
        <p className="text-sm text-neutral-400">No valuation stored by this date.</p>
      ) : (
        <>
          <ul className="divide-y divide-neutral-900 text-sm" aria-label="Exchange valuation">
            {valuation.measures.map((m) => {
              const info = VALUATION[m.measure_id];
              return (
                <li key={m.measure_id} data-measure={m.measure_id} className="space-y-0.5 py-1.5">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <Metric termId={info.termId}>{info.label}</Metric>
                    <Metric termId={info.termId} icon={false} className="tabular-nums font-medium">
                      {m.value !== null ? (
                        ratio(m.value, info.unit)
                      ) : (
                        <span className="text-neutral-500">{m.reason === "not_meaningful" ? "n/m" : "n/a"}</span>
                      )}
                    </Metric>
                  </div>
                  <p className="text-xs text-neutral-400">
                    <Metric termId="factor_percentile" icon={false}>
                      {m.percentile !== null
                        ? `${ordinal(m.percentile)} of ${m.observations} month ends since ${m.since}`
                        : `no percentile yet: ${m.observations} of ${valuation.percentile_min_observations} month ends`}
                    </Metric>
                    {m.detail ? (
                      <>
                        {" · "}
                        <Metric termId={info.termId} icon={false}>
                          {m.detail}
                        </Metric>
                      </>
                    ) : null}
                  </p>
                </li>
              );
            })}
          </ul>
          <SourceLine source={valuation.source} />
        </>
      )}
    </section>
  );
}

function MarginPanel({ data }: { data: TaiwanInstrument }) {
  const margin = data.margin;
  const rows: { termId: CompleteTermId; label: string; value: string | null; change?: string | null; unit: string }[] =
    margin === null
      ? []
      : [
          {
            termId: "margin_balance",
            label: "Margin purchase balance",
            value: margin.values.margin_balance ?? null,
            change: margin.margin_change,
            unit: "lots",
          },
          {
            termId: "short_balance",
            label: "Short sale balance",
            value: margin.values.short_balance ?? null,
            change: margin.short_change,
            unit: "lots",
          },
          { termId: "margin_usage", label: "Margin usage", value: margin.margin_usage, unit: "%" },
          { termId: "short_to_margin_ratio", label: "Short-to-margin ratio", value: margin.short_to_margin, unit: "%" },
        ];
  return (
    <section className="space-y-2" data-block="taiwan-margin" aria-labelledby="tw-margin">
      <h2 id="tw-margin" className="text-lg font-medium">
        <Metric termId="margin_balance" zh>
          Margin and short balances
        </Metric>
      </h2>
      {margin === null ? (
        <p className="text-sm text-neutral-400">No margin balances stored by this date.</p>
      ) : (
        <>
          <p className="text-xs text-neutral-400">
            <Metric termId="taiwan_market_session" icon={false}>
              session {margin.session}
            </Metric>
            {margin.note ? (
              <>
                {" · "}
                <Metric termId="margin_balance" icon={false}>
                  TWSE note: {margin.note}
                </Metric>
              </>
            ) : null}
          </p>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
            {rows.map((row) => (
              <div key={row.termId} className="flex items-baseline justify-between gap-3" data-measure={row.termId}>
                <dt className="text-neutral-400">
                  <Metric termId={row.termId}>{row.label}</Metric>
                </dt>
                <dd className="tabular-nums">
                  <Metric termId={row.termId} icon={false}>
                    {row.value === null
                      ? "n/a"
                      : row.unit === "%"
                        ? `${Number(row.value).toFixed(2)}%`
                        : `${groupDigits(row.value)} lots`}
                    {row.change !== undefined && row.change !== null ? ` (${formatSigned(row.change, 0)})` : ""}
                  </Metric>
                </dd>
              </div>
            ))}
          </dl>
          <SourceLine source={margin.source} />
        </>
      )}
    </section>
  );
}

function ActionsPanel({ data }: { data: TaiwanInstrument }) {
  return (
    <section className="space-y-2" data-block="taiwan-actions" aria-labelledby="tw-actions">
      <h2 id="tw-actions" className="text-lg font-medium">
        <Metric termId="cash_dividend" zh>
          Dividends and reference prices
        </Metric>
      </h2>
      {data.actions.length === 0 ? (
        <p className="text-sm text-neutral-400">No ex-dividend date recorded since collection began.</p>
      ) : (
        <ul className="text-sm" aria-label="Dividends">
          {data.actions.map((a) => (
            <li key={`${a.ex_date}-${a.kind}`} data-action={a.kind}>
              <Metric termId={a.kind === "cash_dividend" ? "cash_dividend" : "split_adjusted"} icon={false}>
                {a.ex_date}:{" "}
                {a.kind === "cash_dividend"
                  ? `cash dividend ${formatMoney(a.value, data.currency)} per share`
                  : `stock dividend ${a.value} shares per share`}
              </Metric>
            </li>
          ))}
        </ul>
      )}
      {data.reference_gaps.length === 0 ? (
        <p className="text-xs text-neutral-500">
          <Metric termId="reference_price_gap" icon={false}>
            Every stored reference price matches the previous close and the recorded dividends.
          </Metric>
        </p>
      ) : (
        <ul className="space-y-1 text-xs text-amber-300" aria-label="Reference price gaps">
          {data.reference_gaps.map((g) => (
            <li key={g.session} data-gap="">
              <Metric termId="reference_price_gap" icon={false}>
                {g.note}
              </Metric>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function FlowsPanel({ data }: { data: TaiwanInstrument }) {
  return (
    <section className="space-y-2" data-block="taiwan-flows" aria-labelledby="tw-flows">
      <h2 id="tw-flows" className="text-lg font-medium">
        <Metric termId="institutional_flows" zh>
          Institutional flows and foreign ownership
        </Metric>
      </h2>
      <div role="note" className="rounded border border-neutral-700 bg-neutral-900/60 p-3 text-sm">
        <p className="font-medium">Data unavailable</p>
        <p className="mt-1 text-neutral-400">
          <Metric termId="institutional_flows" icon={false}>
            {data.flows.reason}
          </Metric>
        </p>
      </div>
    </section>
  );
}

/**
 * A Taiwan universe instrument's page (M3.7, ADR-039 TW13): what the TWSE OpenAPI published,
 * as known on the chosen date, each block with its file and time, and the attribution the open
 * data licence requires. Research only; no strategy, signal or portfolio reads it.
 */
export function TaiwanView({
  code,
  result,
  factors,
  knownOn,
  invalidKnownOn = false,
  sources,
}: {
  code: string;
  result: TaiwanInstrumentResult;
  factors?: ReactNode;
  knownOn?: string;
  invalidKnownOn?: boolean;
  sources?: SourceHealth[] | null;
}) {
  if (result.status !== "ok") {
    return (
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold" data-identifier="">
          {code}
        </h1>
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">
            {result.status === "not_found"
              ? "No TWSE data is stored for this code yet."
              : "The API could not be reached, so nothing is shown."}
          </p>
        </div>
      </section>
    );
  }
  const data = result.data;
  const session = data.market_session;
  return (
    <section className="space-y-8" data-market="TW">
      <header className="space-y-3">
        <p className="text-sm">
          <Link href="/instruments#taiwan" className="text-neutral-400 hover:underline">
            <Metric termId="taiwan_universe" icon={false}>
              Taiwan universe
            </Metric>
          </Link>
        </p>
        <h1 className="flex flex-wrap items-baseline gap-x-3 text-2xl font-semibold">
          <span data-identifier="">{data.code}</span>
          <InstrumentName name={data.name} zh={data.name_zh} />
        </h1>
        <p className="text-sm text-neutral-400">
          <span data-identifier="">
            {[data.sector_zh, data.about_zh].filter(Boolean).join(" · ")}
          </span>
          {" · "}
          <Metric termId="taiwan_market_session" icon={false}>
            {data.instrument_type === "etf" ? "ETF" : "listed company"} on the Taiwan Stock Exchange, in TWD ·{" "}
            {session.open ? "open now" : "closed"} · last close {formatTaipei(session.last_close)} · next open{" "}
            {formatTaipei(session.next_open)}
          </Metric>
        </p>
        <p role="note" className="text-xs text-neutral-500">
          <Metric termId="taiwan_universe" icon={false}>
            {data.detail}
          </Metric>
        </p>
        {data.missing_sessions.length > 0 ? (
          <p className="text-xs text-amber-300" data-missing="">
            <Metric termId="missed_session" icon={false}>
              Sessions no run caught: {data.missing_sessions.join(", ")}
            </Metric>
          </p>
        ) : null}
        <AsKnownOnForm href={`/instruments/${encodeURIComponent(data.code)}`} knownOn={knownOn} invalid={invalidKnownOn} />
        {sources !== undefined ? <SourceFreshness sources={sources} ids={["twse_openapi"]} /> : null}
      </header>
      <PricePanel data={data} />
      {factors}
      <ValuationPanel data={data} />
      <MarginPanel data={data} />
      <ActionsPanel data={data} />
      <FlowsPanel data={data} />
      <TwseAttribution attribution={data.attribution} />
    </section>
  );
}
