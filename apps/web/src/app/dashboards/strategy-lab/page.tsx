import type { Metadata } from "next";

import { Metric } from "@/components/Metric";
import { StrategyLabView } from "@/components/journal/StrategyLabView";
import { loadJournal, loadRotation, loadSignals } from "@/lib/api";
import { endOfDaySgt } from "@/lib/time";

// Point-in-time data: always read live, never serve a cached page.
export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Strategy Lab" };

export default async function StrategyLabPage({ searchParams }: PageProps<"/dashboards/strategy-lab">) {
  const query = await searchParams;
  const knownOn = typeof query.known_on === "string" && query.known_on ? query.known_on : undefined;
  const knownAt = knownOn ? endOfDaySgt(knownOn) : null;
  const [journal, signals, rotation] = await Promise.all([
    loadJournal(knownAt ?? undefined),
    loadSignals(knownAt ?? undefined),
    loadRotation(knownAt ?? undefined),
  ]);
  if (journal === null) {
    return (
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold">
          <Metric termId="dashboard_strategy_lab">Strategy Lab</Metric>
        </h1>
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">The API could not be reached, so the journal is not shown.</p>
        </div>
      </section>
    );
  }
  return (
    <StrategyLabView
      journal={journal}
      signals={signals}
      rotation={rotation}
      knownOn={knownAt ? knownOn : undefined}
      invalidKnownOn={Boolean(knownOn) && knownAt === null}
    />
  );
}
