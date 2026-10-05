import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { SeriesView } from "@/components/macro/SeriesView";
import { loadSeriesObservations } from "@/lib/api";
import { endOfDaySgt } from "@/lib/time";

// Point-in-time data: always read live, never serve a cached page.
export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: PageProps<"/macro/[series]">): Promise<Metadata> {
  const { series } = await params;
  return { title: series.toUpperCase() };
}

export default async function SeriesPage({ params, searchParams }: PageProps<"/macro/[series]">) {
  const { series } = await params;
  const query = await searchParams;
  const knownOn = typeof query.known_on === "string" && query.known_on ? query.known_on : undefined;
  const knownAt = knownOn ? endOfDaySgt(knownOn) : null;

  const result = await loadSeriesObservations(series, knownAt ?? undefined);
  if (result.status === "not_found") notFound();
  if (result.status === "unavailable") {
    return (
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold" data-identifier="">
          {series.toUpperCase()}
        </h1>
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">
            The API could not be reached, so no observations are shown.
          </p>
        </div>
      </section>
    );
  }
  return (
    <SeriesView
      data={result.data}
      knownOn={knownAt ? knownOn : undefined}
      invalidKnownOn={Boolean(knownOn) && knownAt === null}
    />
  );
}
