import type { Metadata } from "next";

import { Metric } from "@/components/Metric";
import { ResearchDashboardView } from "@/components/research/ResearchDashboardView";
import { loadResearchDashboard, loadSourceHealth } from "@/lib/api";
import { isSortKey, type SortDir } from "@/lib/research";
import { endOfDaySgt } from "@/lib/time";

// Point-in-time data: always read live, never serve a cached page.
export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Fundamental Research" };

export default async function FundamentalResearchPage({
  searchParams,
}: PageProps<"/dashboards/fundamental-research">) {
  const query = await searchParams;
  const knownOn = typeof query.known_on === "string" && query.known_on ? query.known_on : undefined;
  const knownAt = knownOn ? endOfDaySgt(knownOn) : null;
  const sort = typeof query.sort === "string" && isSortKey(query.sort) ? query.sort : "ticker";
  const dir: SortDir = query.dir === "desc" ? "desc" : "asc";
  const [data, sources] = await Promise.all([
    loadResearchDashboard(knownAt ?? undefined),
    loadSourceHealth(),
  ]);
  if (data === null) {
    return (
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold">
          <Metric termId="dashboard_fundamental_research">Fundamental Research</Metric>
        </h1>
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">The API could not be reached, so no companies are shown.</p>
        </div>
      </section>
    );
  }
  return (
    <ResearchDashboardView
      data={data}
      sources={sources}
      knownOn={knownAt ? knownOn : undefined}
      invalidKnownOn={Boolean(knownOn) && knownAt === null}
      sort={sort}
      dir={dir}
    />
  );
}
