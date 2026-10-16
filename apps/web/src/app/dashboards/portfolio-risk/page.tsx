import type { Metadata } from "next";

import { tryCheckAction } from "@/app/dashboards/portfolio-risk/actions";
import { Metric } from "@/components/Metric";
import { PortfolioRiskView } from "@/components/risk/PortfolioRiskView";
import { TryCheckForm } from "@/components/risk/TryCheckForm";
import { loadInstruments, loadPortfolio, loadRiskChecks } from "@/lib/api";
import { endOfDaySgt } from "@/lib/time";

// Point-in-time data: always read live, never serve a cached page.
export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Portfolio Risk" };

export default async function PortfolioRiskPage({ searchParams }: PageProps<"/dashboards/portfolio-risk">) {
  const query = await searchParams;
  const knownOn = typeof query.known_on === "string" && query.known_on ? query.known_on : undefined;
  const knownAt = knownOn ? endOfDaySgt(knownOn) : null;
  const [data, checks, standard, instruments] = await Promise.all([
    loadPortfolio(knownAt ?? undefined),
    loadRiskChecks(knownAt ?? undefined, 30, ["trade", "on_demand"]),
    loadRiskChecks(knownAt ?? undefined, 10, ["standard"]),
    loadInstruments(),
  ]);
  if (data === null) {
    return (
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold">
          <Metric termId="dashboard_portfolio_risk">Portfolio Risk</Metric>
        </h1>
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">The API could not be reached, so no portfolio is shown.</p>
        </div>
      </section>
    );
  }
  const tickers = (instruments?.instruments ?? []).map((i) => i.ticker);
  return (
    <PortfolioRiskView
      data={data}
      checks={checks}
      standard={standard}
      knownOn={knownAt ? knownOn : undefined}
      invalidKnownOn={Boolean(knownOn) && knownAt === null}
      tryForm={knownAt === null && tickers.length > 0 ? <TryCheckForm tickers={tickers} action={tryCheckAction} /> : undefined}
    />
  );
}
