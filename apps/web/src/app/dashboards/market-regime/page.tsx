import type { Metadata } from "next";

import { Metric } from "@/components/Metric";
import { MarketRegimeView } from "@/components/regime/MarketRegimeView";
import { loadRegime } from "@/lib/api";
import { endOfDaySgt } from "@/lib/time";

// Point-in-time data: always read live, never serve a cached page.
export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Market Regime" };

export default async function MarketRegimePage({ searchParams }: PageProps<"/dashboards/market-regime">) {
  const query = await searchParams;
  const knownOn = typeof query.known_on === "string" && query.known_on ? query.known_on : undefined;
  const knownAt = knownOn ? endOfDaySgt(knownOn) : null;
  const data = await loadRegime(knownAt ?? undefined);
  if (data === null) {
    return (
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold">
          <Metric termId="dashboard_market_regime">Market Regime</Metric>
        </h1>
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">The API could not be reached, so no regime is shown.</p>
        </div>
      </section>
    );
  }
  return (
    <MarketRegimeView
      data={data}
      knownOn={knownAt ? knownOn : undefined}
      invalidKnownOn={Boolean(knownOn) && knownAt === null}
    />
  );
}
