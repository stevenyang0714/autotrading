import Link from "next/link";
import type { ReactNode } from "react";

import { AsKnownOnForm } from "@/components/AsKnownOnForm";
import { Metric } from "@/components/Metric";
import { SourceFreshness } from "@/components/SourceFreshness";
import type { SourceHealth } from "@/lib/api";

/**
 * A universe ETF's page (M2.2, ADR-030): its price and its trend and factor measures. ETFs file
 * no company reports, so there is no valuation, Research Record or buyback block.
 */
export function EtfView({
  ticker,
  knownOn,
  invalidKnownOn = false,
  sources,
  prices,
  factors,
}: {
  ticker: string;
  knownOn?: string;
  invalidKnownOn?: boolean;
  sources?: SourceHealth[] | null;
  prices?: ReactNode;
  factors: ReactNode;
}) {
  return (
    <section className="space-y-8">
      <header className="space-y-3">
        <p className="text-sm">
          <Link href="/dashboards/opportunity-radar" className="text-neutral-400 hover:underline">
            <Metric termId="dashboard_opportunity_radar" icon={false}>
              Opportunity Radar
            </Metric>
          </Link>
        </p>
        <h1 className="text-2xl font-semibold">
          <span data-identifier="">{ticker}</span> <span className="text-neutral-400">·</span>{" "}
          <Metric termId="page_instruments" icon={false}>
            Exchange-traded fund
          </Metric>
        </h1>
        <p className="text-sm text-neutral-400">
          A fund in the universe: its price and its trend measures. Funds file no company reports, so
          there is no valuation, Research Record or buyback section.
        </p>
        <AsKnownOnForm href={`/instruments/${encodeURIComponent(ticker)}`} knownOn={knownOn} invalid={invalidKnownOn} />
        {sources !== undefined ? <SourceFreshness sources={sources} ids={["alpaca_iex"]} /> : null}
      </header>
      {prices}
      {factors}
    </section>
  );
}
