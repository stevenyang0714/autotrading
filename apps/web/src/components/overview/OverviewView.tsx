import Link from "next/link";

import { AsKnownOnForm } from "@/components/AsKnownOnForm";
import { Metric } from "@/components/Metric";
import { DemoBanner } from "@/components/prices/DemoBanner";
import { MarketSession } from "@/components/prices/MarketSession";
import { PriceBadge, changeTone } from "@/components/prices/PriceBadge";
import { SourceFreshness } from "@/components/SourceFreshness";
import { Sparkline } from "@/components/Sparkline";
import type { CompleteTermId } from "@/generated/glossary";
import type { MarketState, Overview, OverviewBlock, OverviewIndicator, PriceTile, SourceHealth } from "@/lib/api";
import { formatChange, formatPrice, groupDigits } from "@/lib/format";
import { completeTermId } from "@/lib/glossary";
import { formatSgtEt } from "@/lib/time";

interface Props {
  data: Overview;
  sources: SourceHealth[] | null;
  knownOn?: string;
  invalidKnownOn?: boolean;
}

const BLOCK_TERM: Record<OverviewBlock["id"], CompleteTermId> = {
  markets: "market_session",
  inflation: "cpi_inflation_yoy",
  labor: "macro_nonfarm_payrolls",
  growth: "macro_real_gdp",
  policy: "macro_fed_funds",
  curve: "macro_curve_10y_2y",
  risk: "macro_vix",
};

const LABEL_TONE: Record<string, string> = {
  above: "text-amber-300",
  triggered: "text-red-300",
  inverted: "text-amber-300",
  contraction: "text-red-300",
  high: "text-amber-300",
  low: "text-sky-300",
};

/** Indicator values as shown: units follow the API (percent, pp, thousands, ...). */
export function formatIndicator(indicator: OverviewIndicator): string {
  const value = Number(indicator.value);
  if (indicator.term_id === "price_change_1d") return formatChange(indicator.value);
  switch (indicator.unit) {
    case "percent":
      return `${value.toFixed(1)}%`;
    case "pp":
      return `${value >= 0 ? "+" : ""}${value.toFixed(2)} pp`;
    case "thousands":
      return `${value >= 0 ? "+" : ""}${value.toLocaleString("en-US")}K`;
    case "observations":
      return `${value.toLocaleString("en-US")} trading days`;
    case "percentile":
      return `${Math.round(value)}th percentile`;
    default:
      return value.toFixed(2);
  }
}

function chartFormat(unit: string): (value: number) => string {
  if (unit === "usd") return (v) => formatPrice(String(v));
  return unit === "percent" ? (v) => `${v.toFixed(1)}%` : unit === "pp" ? (v) => `${v.toFixed(2)}` : (v) => v.toFixed(1);
}

/**
 * Home dashboard (M0.6 overview, ADR-016): market prices (M0.7) and six macro blocks as known at
 * `data.known_at`, each with latest values, computed indicators, a chart and one rule-based
 * insight that cites its inputs. Every number renders through <Metric> or inside a chart figure
 * bound to a term; every price carries its feed status.
 */
export function OverviewView({ data, sources, knownOn, invalidKnownOn }: Props) {
  const newest = data.blocks
    .flatMap((block) => block.latest)
    .map((latest) => latest.vintage)
    .sort()
    .at(-1);
  const prices = data.blocks.flatMap((block) => block.prices ?? []);
  return (
    <section className="space-y-6">
      <DemoBanner statuses={prices.map((tile) => tile.feed_status)} />
      <header className="space-y-3">
        <h1 className="text-2xl font-semibold">
          <Metric termId="page_overview" zh>
            Overview
          </Metric>
        </h1>
        <p className="text-sm text-neutral-500">Research broadly. Trade narrowly.</p>
        <AsKnownOnForm href="/" knownOn={knownOn} invalid={invalidKnownOn} />
        <p className="text-sm text-neutral-400">
          Showing what was public by{" "}
          <Metric termId="point_in_time" icon={false} zh>
            {formatSgtEt(data.known_at)}
          </Metric>
        </p>
        <SourceFreshness
          sources={sources}
          ids={["alpaca_iex", "fred", "sec_edgar"]}
          newestPublishedAt={knownOn ? null : newest ? `${newest}T23:59:59-04:00` : null}
        />
      </header>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data.blocks.map((block) => (
          <BlockCard key={block.id} block={block} market={data.market ?? null} />
        ))}
      </div>
      <p className="text-xs text-neutral-500">
        Series detail and every vintage: <Link href="/macro" className="underline-offset-2 hover:underline">Macro</Link>.
        Insights are fixed rules on reported data, not forecasts or advice.
      </p>
    </section>
  );
}

function BlockCard({ block, market }: { block: OverviewBlock; market: MarketState | null }) {
  const chart = block.charts[0];
  const chartTerm = chart ? completeTermId(chart.term_id) : null;
  const isMarkets = block.id === "markets";
  return (
    <article
      aria-labelledby={`block-${block.id}`}
      className={`space-y-3 rounded border border-neutral-800 p-4 ${isMarkets ? "md:col-span-2 xl:col-span-3" : ""}`}
      data-block={block.id}
    >
      <h2 id={`block-${block.id}`} className="flex flex-wrap items-baseline gap-x-3 text-base font-medium">
        <Metric termId={BLOCK_TERM[block.id]} icon={false}>
          {block.title}
        </Metric>
        {isMarkets && market ? <MarketSession market={market} /> : null}
      </h2>
      {block.prices?.length ? <PriceTiles tiles={block.prices} /> : null}
      <dl className="space-y-1 text-sm">
        {block.latest.map((latest) => {
          const termId = completeTermId(latest.term_id) ?? "page_macro";
          return (
            <div key={latest.series_id} className="flex flex-wrap items-baseline justify-between gap-x-2">
              <dt className="text-neutral-400">
                <Link href={`/macro/${latest.series_id}`} className="underline-offset-2 hover:underline">
                  <Metric termId={termId} icon={false} zh />
                </Link>
              </dt>
              <dd className="tabular-nums">
                <Metric termId={termId} icon={false}>
                  {groupDigits(latest.value)}{" "}
                  <span className="text-xs text-neutral-500">{latest.units_short}</span>
                </Metric>{" "}
                <span className="text-xs text-neutral-500">
                  <Metric termId="observation_date" icon={false}>
                    {latest.observation_date}
                  </Metric>
                </span>
              </dd>
            </div>
          );
        })}
      </dl>
      {block.indicators.length ? (
        <ul className="space-y-1 text-sm" aria-label={`${block.title} indicators`}>
          {block.indicators.map((indicator) => {
            const termId = completeTermId(indicator.term_id) ?? "page_overview";
            return (
              <li key={indicator.term_id} className="flex flex-wrap items-baseline justify-between gap-x-2">
                <Metric termId={termId} icon={false} zh className="text-neutral-300" />
                <span className="tabular-nums">
                  <Metric termId={termId} icon={false}>
                    {formatIndicator(indicator)}
                  </Metric>
                  {indicator.label ? (
                    <span className={`ml-2 text-xs ${LABEL_TONE[indicator.label] ?? "text-neutral-400"}`}>
                      {indicator.label}
                    </span>
                  ) : null}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
      {chart && chartTerm ? (
        <Sparkline
          points={chart.points}
          termId={chartTerm}
          label={block.title}
          format={chartFormat(chart.unit)}
          zeroLine={chart.zero_line}
        />
      ) : null}
      {block.insight ? (
        <div className="space-y-1 border-t border-neutral-800 pt-2">
          <p className="text-sm">
            <Metric termId="rule_insight" icon={false}>
              {block.insight.text}
            </Metric>
          </p>
          <p className="text-[11px] text-neutral-500">
            Based on{" "}
            {block.insight.inputs.map((input, i) => (
              <span key={`${input.series_id}-${input.observation_date}-${input.vintage}`}>
                {i ? ", " : ""}
                <span data-identifier="">{input.series_id}</span>{" "}
                {isMarkets ? (
                  <>
                    price of{" "}
                    <Metric termId="as_of" icon={false}>
                      {input.observation_date}
                    </Metric>
                  </>
                ) : (
                  <Metric termId="vintage" icon={false}>
                    {input.observation_date} (released {input.vintage})
                  </Metric>
                )}
              </span>
            ))}
          </p>
        </div>
      ) : (
        <p className="text-sm text-neutral-500">Not enough data as of this date.</p>
      )}
    </article>
  );
}

/** ETF prices with their feed status; no number when a price is unavailable. */
function PriceTiles({ tiles }: { tiles: PriceTile[] }) {
  return (
    <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="Market prices">
      {tiles.map((tile) => (
        <li
          key={tile.symbol}
          data-symbol={tile.symbol}
          className="space-y-1 rounded border border-neutral-800 px-3 py-2"
        >
          <p className="flex items-center justify-between gap-2">
            <span data-identifier="" className="font-medium">
              {tile.symbol}
            </span>
            <PriceBadge status={tile.feed_status} />
          </p>
          {tile.last && tile.feed_status !== "unavailable" ? (
            <p className="flex flex-wrap items-baseline gap-x-2 tabular-nums">
              <Metric termId="last_price" icon={false}>
                <span title={`${tile.last} USD`}>{formatPrice(tile.last)}</span>
              </Metric>
              {tile.change_pct ? (
                <Metric termId="price_change_1d" icon={false}>
                  <span className={`text-sm ${changeTone(tile.change_pct)}`}>{formatChange(tile.change_pct)}</span>
                </Metric>
              ) : null}
            </p>
          ) : (
            <p className="text-sm text-neutral-500">No price</p>
          )}
        </li>
      ))}
    </ul>
  );
}
