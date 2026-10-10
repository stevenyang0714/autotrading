import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { saveAssumptionsAction } from "@/app/instruments/[ticker]/actions";
import { BuybacksView } from "@/components/instruments/BuybacksView";
import { FairValueView } from "@/components/instruments/FairValueView";
import { FundamentalsView } from "@/components/instruments/FundamentalsView";
import { ResearchRecordView } from "@/components/instruments/ResearchRecordView";
import { InstrumentNews } from "@/components/news/InstrumentNews";
import { DemoBanner } from "@/components/prices/DemoBanner";
import { InstrumentPricePanel } from "@/components/prices/InstrumentPricePanel";
import { ValuationView } from "@/components/instruments/ValuationView";
import {
  loadAssumptions,
  loadBuybacks,
  loadFairValue,
  loadFundamentals,
  loadInstrumentPrices,
  loadNews,
  loadResearch,
  loadSourceHealth,
  loadValuation,
} from "@/lib/api";
import { endOfDaySgt } from "@/lib/time";

// Point-in-time data: always read live, never serve a cached page.
export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: PageProps<"/instruments/[ticker]">): Promise<Metadata> {
  const { ticker } = await params;
  return { title: ticker.toUpperCase() };
}

export default async function InstrumentPage({
  params,
  searchParams,
}: PageProps<"/instruments/[ticker]">) {
  const { ticker } = await params;
  const query = await searchParams;
  const knownOn = typeof query.known_on === "string" && query.known_on ? query.known_on : undefined;
  const knownAt = knownOn ? endOfDaySgt(knownOn) : null;
  const version =
    typeof query.assumptions === "string" && /^(default|[1-9][0-9]*)$/.test(query.assumptions)
      ? query.assumptions
      : undefined;

  const newsQuery = { ticker: ticker.toUpperCase(), knownAt: knownAt ?? undefined, limit: 6 };
  const [
    result,
    prices,
    valuation,
    fairValue,
    assumptions,
    research,
    buybacks,
    announcements,
    coverage,
    sources,
  ] = await Promise.all([
      loadFundamentals(ticker, knownAt ?? undefined),
      loadInstrumentPrices(ticker, knownAt ?? undefined),
      loadValuation(ticker, knownAt ?? undefined),
      loadFairValue(ticker, knownAt ?? undefined, version),
      loadAssumptions(ticker),
      loadResearch(ticker, knownAt ?? undefined),
      loadBuybacks(ticker, knownAt ?? undefined),
      loadNews({ ...newsQuery, kinds: ["press_release"] }),
      loadNews({ ...newsQuery, kinds: ["article", "official"] }),
      loadSourceHealth(),
    ]);
  if (result.status === "not_found") notFound();
  if (result.status === "unavailable") {
    return (
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold" data-identifier="">
          {ticker.toUpperCase()}
        </h1>
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">
            The API could not be reached, so no fundamentals are shown.
          </p>
        </div>
      </section>
    );
  }
  const newsFixture = [announcements, coverage].some((feed) =>
    feed?.groups.some((g) => [g.lead, ...g.others].some((item) => item.data_mode === "fixture")),
  );
  const shown = [
    ...(prices.status === "ok" ? [prices.data.quote?.feed_status, prices.data.closes_feed_status] : []),
    ...(newsFixture ? (["fixture"] as const) : []),
  ];
  return (
    <div className="space-y-4">
      <DemoBanner statuses={shown} />
      <FundamentalsView
        data={result.data}
        knownOn={knownAt ? knownOn : undefined}
        invalidKnownOn={Boolean(knownOn) && knownAt === null}
        sources={sources}
        prices={prices.status === "not_found" ? undefined : <InstrumentPricePanel result={prices} />}
        valuation={valuation.status === "not_found" ? undefined : <ValuationView result={valuation} />}
        fairValue={
          <FairValueView
            result={fairValue}
            assumptions={assumptions}
            ticker={ticker.toUpperCase()}
            knownOn={knownAt ? knownOn : undefined}
            action={saveAssumptionsAction}
          />
        }
        research={research.status === "not_found" ? undefined : <ResearchRecordView result={research} />}
        buybacks={buybacks.status === "not_found" ? undefined : <BuybacksView result={buybacks} />}
        news={
          <InstrumentNews ticker={ticker.toUpperCase()} announcements={announcements} coverage={coverage} />
        }
      />
    </div>
  );
}
