import type { Metadata } from "next";

import { Metric } from "@/components/Metric";
import { OpportunityRadarView } from "@/components/factors/OpportunityRadarView";
import { loadCandidates, loadFactors } from "@/lib/api";
import { isSortKey, type SortDir } from "@/lib/factors";
import { endOfDaySgt } from "@/lib/time";

// Point-in-time data: always read live, never serve a cached page.
export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Opportunity Radar" };

export default async function OpportunityRadarPage({ searchParams }: PageProps<"/dashboards/opportunity-radar">) {
  const query = await searchParams;
  const knownOn = typeof query.known_on === "string" && query.known_on ? query.known_on : undefined;
  const knownAt = knownOn ? endOfDaySgt(knownOn) : null;
  const sort = typeof query.sort === "string" && isSortKey(query.sort) ? query.sort : "ticker";
  const dir: SortDir = query.dir === "desc" ? "desc" : "asc";
  const [data, candidates] = await Promise.all([
    loadFactors(knownAt ?? undefined),
    loadCandidates(knownAt ?? undefined),
  ]);
  if (data === null) {
    return (
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold">
          <Metric termId="dashboard_opportunity_radar">Opportunity Radar</Metric>
        </h1>
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">The API could not be reached, so no instruments are shown.</p>
        </div>
      </section>
    );
  }
  return (
    <OpportunityRadarView
      data={data}
      candidates={candidates}
      knownOn={knownAt ? knownOn : undefined}
      invalidKnownOn={Boolean(knownOn) && knownAt === null}
      sort={sort}
      dir={dir}
    />
  );
}
