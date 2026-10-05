import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { FundamentalsView } from "@/components/instruments/FundamentalsView";
import { loadFundamentals, loadSourceHealth } from "@/lib/api";
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

  const [result, sources] = await Promise.all([
    loadFundamentals(ticker, knownAt ?? undefined),
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
  return (
    <FundamentalsView
      data={result.data}
      knownOn={knownAt ? knownOn : undefined}
      invalidKnownOn={Boolean(knownOn) && knownAt === null}
      sources={sources}
    />
  );
}
