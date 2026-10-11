import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Metric } from "@/components/Metric";
import { EntryForm } from "@/components/journal/EntryForm";
import { PaperOnlyNotice } from "@/components/journal/StrategyLabView";
import { saveEntryAction } from "@/app/journal/actions";
import { loadEvidence, loadJournalCard, loadSignals } from "@/lib/api";
import { formatSgtEt } from "@/lib/time";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "New Thesis Card" };

function Unavailable() {
  return (
    <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
      <p className="font-medium">Data unavailable</p>
      <p className="mt-1 text-neutral-400">The API could not be reached, so no card can be written now.</p>
    </div>
  );
}

/**
 * Write a Thesis Card (?ticker=) or a new version of one (?card=), always as of now: the card
 * cites rows known now and is never backdated (M1.6, ADR-027).
 */
export default async function NewJournalPage({ searchParams }: PageProps<"/journal/new">) {
  const query = await searchParams;
  const cardId = typeof query.card === "string" ? query.card : undefined;
  const existing = cardId ? await loadJournalCard(cardId) : undefined;
  if (existing?.status === "not_found") notFound();
  if (existing?.status === "unavailable") return <Unavailable />;
  const card = existing?.status === "ok" ? existing.data.card : undefined;
  const ticker = (card?.ticker ?? (typeof query.ticker === "string" ? query.ticker : "")).trim().toUpperCase();
  if (!ticker) notFound();
  const [candidates, signals] = await Promise.all([loadEvidence(ticker), loadSignals(undefined, ticker)]);
  if (candidates === null) {
    if (signals === null) return <Unavailable />;
    notFound();
  }
  const current = (signals?.current ?? []).filter((s) => s.ticker === ticker);
  return (
    <section className="space-y-4">
      <header className="space-y-2">
        <p className="text-sm text-neutral-400">
          <Link href="/dashboards/strategy-lab" className="underline-offset-2 hover:underline">
            Strategy Lab
          </Link>{" "}
          ·{" "}
          <Link href={`/instruments/${ticker}`} data-identifier="" className="underline-offset-2 hover:underline">
            {ticker}
          </Link>
        </p>
        <h1 className="text-2xl font-semibold">
          <Metric termId="thesis_card" zh>
            {card ? "New version" : "New Thesis Card"}
          </Metric>{" "}
          <span data-identifier="" className="text-base text-neutral-400">
            {ticker}
            {card ? ` v${card.version + 1}` : ""}
          </span>
        </h1>
        <p className="text-sm text-neutral-400">
          Written as of now (
          <Metric termId="point_in_time" icon={false}>
            {formatSgtEt(candidates.known_at)}
          </Metric>
          ): the card can cite only rows known now and cannot be backdated.
        </p>
        <PaperOnlyNotice detail="Paper journal: decisions are records, never orders." />
      </header>
      <EntryForm
        ticker={ticker}
        candidates={candidates.candidates}
        signals={current}
        selectedSignal={typeof query.signal === "string" ? query.signal : undefined}
        card={card}
        action={saveEntryAction}
      />
    </section>
  );
}
