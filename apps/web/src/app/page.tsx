import type { Metadata } from "next";

import { Metric } from "@/components/Metric";
import { OverviewView } from "@/components/overview/OverviewView";
import { TodayPanel } from "@/components/today/TodayPanel";
import {
  loadAlerts,
  loadCandidates,
  loadHoldings,
  loadOverview,
  loadPolicy,
  loadSourceHealth,
  loadTaiwan,
  loadTaiwanScreens,
} from "@/lib/api";
import { endOfDaySgt } from "@/lib/time";

// Point-in-time data: always read live, never serve a cached page.
export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Today" };

export default async function Home({ searchParams }: PageProps<"/">) {
  const query = await searchParams;
  const knownOn = typeof query.known_on === "string" && query.known_on ? query.known_on : undefined;
  const knownAt = knownOn ? endOfDaySgt(knownOn) : null;
  const today = knownAt === null; // Today is about now; As known on shows the overview alone
  const [overview, sources, holdings, alerts, candidates, taiwan, screens, policy] = await Promise.all([
    loadOverview(knownAt ?? undefined),
    loadSourceHealth(),
    today ? loadHoldings() : null,
    today ? loadAlerts({ status: "all" }) : null,
    today ? loadCandidates() : null,
    today ? loadTaiwan() : null,
    today ? loadTaiwanScreens() : null,
    today ? loadPolicy() : null,
  ]);
  if (overview === null) {
    return (
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold">
          <Metric termId="page_overview">Overview</Metric>
        </h1>
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">The API could not be reached, so no overview is shown.</p>
        </div>
      </section>
    );
  }
  const overviewView = (
    <OverviewView
      data={overview}
      sources={sources}
      knownOn={knownAt ? knownOn : undefined}
      invalidKnownOn={Boolean(knownOn) && knownAt === null}
      level={today ? 2 : 1}
    />
  );
  if (!today) return overviewView;
  return (
    <div className="space-y-10">
      <TodayPanel
        holdings={holdings}
        alerts={alerts}
        candidates={candidates}
        screens={screens}
        policy={policy}
        us={overview.market ?? null}
        taiwan={taiwan}
        sources={sources}
        now={overview.known_at}
      />
      {overviewView}
    </div>
  );
}
