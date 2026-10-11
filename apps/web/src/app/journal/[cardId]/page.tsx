import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ExitForm } from "@/components/journal/ExitForm";
import { JournalCardView } from "@/components/journal/JournalCardView";
import { exitAction } from "@/app/journal/actions";
import { loadJournalCard, loadReplay } from "@/lib/api";
import { endOfDaySgt } from "@/lib/time";

// Point-in-time data: always read live, never serve a cached page.
export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Thesis Card" };

export default async function JournalCardPage({ params, searchParams }: PageProps<"/journal/[cardId]">) {
  const { cardId } = await params;
  const query = await searchParams;
  const knownOn = typeof query.known_on === "string" && query.known_on ? query.known_on : undefined;
  const knownAt = knownOn ? endOfDaySgt(knownOn) : null;
  const version = typeof query.version === "string" && /^\d+$/.test(query.version) ? Number(query.version) : undefined;
  const [result, replay] = await Promise.all([
    loadJournalCard(cardId, knownAt ?? undefined, version),
    loadReplay(cardId, version),
  ]);
  if (result.status === "not_found") notFound();
  if (result.status === "unavailable") {
    return (
      <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
        <p className="font-medium">Data unavailable</p>
        <p className="mt-1 text-neutral-400">The API could not be reached, so the card is not shown.</p>
      </div>
    );
  }
  return (
    <JournalCardView
      data={result.data}
      replay={replay}
      knownOn={knownAt ? knownOn : undefined}
      invalidKnownOn={Boolean(knownOn) && knownAt === null}
      exitForm={
        knownAt
          ? undefined
          : (decision) => <ExitForm decisionId={decision.id} cardId={cardId} action={exitAction} />
      }
    />
  );
}
