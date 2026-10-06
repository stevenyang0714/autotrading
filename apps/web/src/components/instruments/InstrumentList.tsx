import Link from "next/link";

import { Metric } from "@/components/Metric";
import { DemoBanner } from "@/components/prices/DemoBanner";
import { PriceBadge, changeTone } from "@/components/prices/PriceBadge";
import { SourceFreshness } from "@/components/SourceFreshness";
import type { InstrumentList as InstrumentListData, LatestPrices, Quote, SourceHealth } from "@/lib/api";
import { formatChange, formatPrice } from "@/lib/format";
import { formatSgtEt } from "@/lib/time";

/**
 * Instruments index (M0.5b), with the latest price of each (M0.7). `data` is null when the API
 * is unreachable; `prices` null shows every price as unavailable.
 */
export function InstrumentList({
  data,
  prices,
  sources,
}: {
  data: InstrumentListData | null;
  prices?: LatestPrices | null;
  sources?: SourceHealth[] | null;
}) {
  const quotes = new Map((prices?.quotes ?? []).map((quote) => [quote.symbol, quote]));
  const newest = data?.instruments
    .map((i) => i.latest_report?.published_at)
    .filter((v): v is string => Boolean(v))
    .sort()
    .at(-1);
  return (
    <section className="space-y-6">
      <DemoBanner statuses={[...quotes.values()].map((quote) => quote.feed_status)} />
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          <Metric termId="page_instruments" zh>
            Instruments
          </Metric>
        </h1>
        {sources !== undefined ? (
          <SourceFreshness sources={sources} ids={["alpaca_iex", "sec_edgar"]} newestPublishedAt={newest} />
        ) : null}
        {data?.last_refresh_at ? (
          <p className="text-sm text-neutral-500">
            Last SEC refresh{" "}
            <Metric termId="as_of" icon={false}>
              {formatSgtEt(data.last_refresh_at)}
            </Metric>
          </p>
        ) : null}
      </header>
      {data === null ? (
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">
            The API could not be reached, so no instruments are shown.
          </p>
        </div>
      ) : data.instruments.length === 0 ? (
        <p className="text-sm text-neutral-500">
          No instruments yet. They appear after the first SEC refresh (make sec-refresh).
        </p>
      ) : (
        <ul className="divide-y divide-neutral-800" aria-label="Instruments">
          {data.instruments.map((instrument) => (
            <li key={instrument.ticker} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-3">
              <Link
                href={`/instruments/${instrument.ticker}`}
                data-identifier=""
                className="w-16 font-medium underline-offset-2 hover:underline"
              >
                {instrument.ticker}
              </Link>
              <span className="min-w-[12rem]">{instrument.name}</span>
              {prices !== undefined ? <ListPrice quote={quotes.get(instrument.ticker)} /> : null}
              <span className="text-sm text-neutral-400" data-identifier="">
                {[instrument.exchange, instrument.cik ? `CIK ${instrument.cik}` : null]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              {instrument.latest_report ? (
                <span className="text-sm text-neutral-400">
                  Latest report{" "}
                  <a
                    href={instrument.latest_report.url}
                    target="_blank"
                    rel="noreferrer"
                    data-identifier=""
                    className="underline-offset-2 hover:underline"
                  >
                    {instrument.latest_report.form}
                  </a>{" "}
                  <Metric termId="filing_date" icon={false}>
                    {formatSgtEt(instrument.latest_report.published_at)}
                  </Metric>
                </span>
              ) : null}
              {instrument.predecessors.length > 0 ? (
                <span className="text-sm text-neutral-400">
                  history incl.{" "}
                  <Metric termId="predecessor_issuer" icon={false}>
                    {instrument.predecessors.join(", ")}
                  </Metric>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Last price, day change and feed status; only the badge when there is no price. */
function ListPrice({ quote }: { quote: Quote | undefined }) {
  if (!quote?.last || quote.feed_status === "unavailable") {
    return (
      <span className="inline-flex min-w-[11rem] items-center gap-2 text-sm">
        <PriceBadge status="unavailable" />
      </span>
    );
  }
  return (
    <span className="inline-flex min-w-[11rem] flex-wrap items-baseline gap-x-2 text-sm tabular-nums">
      <Metric termId="last_price" icon={false}>
        <span title={`${quote.last} USD`}>{formatPrice(quote.last)}</span>
      </Metric>
      {quote.change_pct ? (
        <Metric termId="price_change_1d" icon={false}>
          <span className={changeTone(quote.change_pct)}>{formatChange(quote.change_pct)}</span>
        </Metric>
      ) : null}
      <PriceBadge status={quote.feed_status} />
    </span>
  );
}
