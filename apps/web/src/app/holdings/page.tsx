import type { Metadata } from "next";

import { recordEntryAction, reverseEntryAction } from "@/app/holdings/actions";
import { Metric } from "@/components/Metric";
import { HoldingEntryForm } from "@/components/holdings/HoldingEntryForm";
import { HoldingsView } from "@/components/holdings/HoldingsView";
import { ReverseForm } from "@/components/holdings/ReverseForm";
import { loadHoldingEntries, loadHoldings } from "@/lib/api";
import { dayIn, endOfDaySgt } from "@/lib/time";

// Holdings change with every entry and close: always read live, never serve a cached page.
export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Holdings" };

/** Steven's real holdings (M3.10, ADR-041): recorded here, valued live, local only. */
export default async function HoldingsPage({ searchParams }: PageProps<"/holdings">) {
  const query = await searchParams;
  const knownOn = typeof query.known_on === "string" && query.known_on ? query.known_on : undefined;
  const knownAt = knownOn ? endOfDaySgt(knownOn) : null;
  const [data, entries] = await Promise.all([loadHoldings(knownAt ?? undefined), loadHoldingEntries()]);
  if (data === null) {
    return (
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold">
          <Metric termId="page_holdings">Holdings</Metric>
        </h1>
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">The API could not be reached, so no holdings are shown.</p>
        </div>
      </section>
    );
  }
  const now = knownAt === null;
  return (
    <HoldingsView
      data={data}
      entries={entries}
      knownOn={knownAt ? knownOn : undefined}
      invalidKnownOn={Boolean(knownOn) && knownAt === null}
      form={
        now ? (
          <HoldingEntryForm
            accounts={entries?.accounts ?? []}
            today={dayIn(data.system_time, "Asia/Singapore")}
            action={recordEntryAction}
          />
        ) : undefined
      }
      reverse={now ? (entry) => <ReverseForm entryId={entry.id} action={reverseEntryAction} /> : undefined}
    />
  );
}
