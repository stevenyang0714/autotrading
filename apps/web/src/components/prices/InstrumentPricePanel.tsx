import { Metric } from "@/components/Metric";
import { Sparkline } from "@/components/Sparkline";
import type { InstrumentPricesResult, Quote } from "@/lib/api";
import { formatChange, formatPrice, groupDigits } from "@/lib/format";
import { formatSgtEt } from "@/lib/time";

import { MarketSession } from "./MarketSession";
import { PriceBadge, changeTone } from "./PriceBadge";

/**
 * Price block of the instrument page (M0.7, ADR-017): the latest IEX quote in the live view,
 * the latest daily close for a past date, one year of split-adjusted closes and the distance
 * from the 52-week high. Every price carries its feed status; nothing is shown without data.
 */
export function InstrumentPricePanel({ result }: { result: InstrumentPricesResult }) {
  if (result.status === "not_found") return null;
  if (result.status === "unavailable") {
    return (
      <section aria-label="Price" className="flex flex-wrap items-center gap-2 text-sm text-neutral-400">
        <PriceBadge status="unavailable" /> Price data unavailable: the API could not be reached.
      </section>
    );
  }
  const data = result.data;
  const live = data.quote;
  const closes = data.closes_feed_status;
  return (
    <section aria-label="Price" className="space-y-3 rounded border border-neutral-800 p-4">
      {live ? <LiveQuote quote={live} /> : <PastClose data={data} />}
      {live ? <MarketSession market={data.market} /> : null}
      {data.history.length > 1 ? (
        <div className="space-y-1">
          <p className="flex flex-wrap items-center gap-2 text-sm text-neutral-400">
            <Metric termId="price_history" zh />
            <PriceBadge status={closes} />
          </p>
          <Sparkline
            points={data.history.map((p) => ({ day: p.day, value: p.close }))}
            termId="price_history"
            label={`${data.ticker} daily closes`}
            format={(v) => formatPrice(String(v))}
            heightClass="h-32"
            width={480}
            height={128}
          />
          {data.high_52w && data.pct_below_52w_high !== null && data.pct_below_52w_high !== undefined ? (
            <p className="text-sm">
              <Metric termId="pct_below_52w_high" zh className="text-neutral-400" />{" "}
              <Metric termId="pct_below_52w_high" icon={false}>
                <span className="tabular-nums">
                  {Number(data.pct_below_52w_high) === 0
                    ? "at the 52-week high"
                    : `${Number(data.pct_below_52w_high).toFixed(1)}% below ${formatPrice(data.high_52w)}`}
                </span>
              </Metric>
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function LiveQuote({ quote }: { quote: Quote }) {
  if (quote.feed_status === "unavailable" || !quote.last) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-sm text-neutral-400">
        <Metric termId="last_price" zh />
        <PriceBadge status="unavailable" />
        <span>No price: the price provider is not configured or has no data yet.</span>
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Metric termId="last_price" icon={false}>
          <span className="text-3xl font-semibold tabular-nums" title={`${quote.last} USD`}>
            {formatPrice(quote.last)}
          </span>
        </Metric>
        {quote.change_pct ? (
          <Metric termId="price_change_1d" icon={false}>
            <span className={`tabular-nums ${changeTone(quote.change_pct)}`}>{formatChange(quote.change_pct)}</span>
          </Metric>
        ) : null}
        <PriceBadge status={quote.feed_status} zh />
      </p>
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-400">
        {quote.bid && quote.ask ? (
          <span>
            <Metric termId="bid" icon={false}>
              bid <span className="tabular-nums">{formatPrice(quote.bid)}</span>
            </Metric>{" "}
            ·{" "}
            <Metric termId="ask" icon={false}>
              ask <span className="tabular-nums">{formatPrice(quote.ask)}</span>
            </Metric>
          </span>
        ) : null}
        {quote.day_volume !== null && quote.day_volume !== undefined ? (
          <Metric termId="volume" icon={false}>
            volume <span className="tabular-nums">{groupDigits(String(quote.day_volume))}</span>
            {quote.venue ? ` (${quote.venue})` : ""}
          </Metric>
        ) : null}
        {quote.published_at ? (
          <span>
            as of{" "}
            <Metric termId="as_of" icon={false}>
              {formatSgtEt(quote.published_at)}
            </Metric>
          </span>
        ) : null}
      </p>
    </div>
  );
}

function PastClose({ data }: { data: Extract<InstrumentPricesResult, { status: "ok" }>["data"] }) {
  const close = data.last_close;
  if (!close) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-sm text-neutral-400">
        <Metric termId="last_price" zh />
        <PriceBadge status="unavailable" />
        <span>No closing price known on this date.</span>
      </div>
    );
  }
  const change = data.close_change_pct;
  return (
    <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <Metric termId="last_price" icon={false}>
        <span className="text-3xl font-semibold tabular-nums" title={`${close.close} USD`}>
          {formatPrice(close.close)}
        </span>
      </Metric>
      {change ? (
        <Metric termId="price_change_1d" icon={false}>
          <span className={`tabular-nums ${changeTone(change)}`}>{formatChange(change)}</span>
        </Metric>
      ) : null}
      <PriceBadge status={data.closes_feed_status} zh />
      <span className="text-xs text-neutral-400">
        close of{" "}
        <Metric termId="as_of" icon={false}>
          {close.day}
        </Metric>
      </span>
    </p>
  );
}
