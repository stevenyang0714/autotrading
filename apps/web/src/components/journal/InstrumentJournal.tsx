import Link from "next/link";

import { Metric } from "@/components/Metric";
import { JournalTable } from "@/components/journal/JournalTable";
import type { Journal } from "@/lib/api";

/** The instrument page's paper journal (M1.6): this company's Thesis Cards and a way to write one. */
export function InstrumentJournal({
  ticker,
  journal,
  knownOn,
}: {
  ticker: string;
  journal: Journal | null;
  knownOn?: string;
}) {
  return (
    <section id="journal" aria-labelledby="journal-heading" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="journal-heading" className="text-lg font-medium">
          <Metric termId="journal_entry" zh>
            Paper journal
          </Metric>
        </h2>
        <Link
          href={`/journal/new?ticker=${ticker}`}
          className="rounded border border-neutral-300 px-3 py-1 text-sm hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
        >
          Write a Thesis Card
        </Link>
      </div>
      {journal === null ? (
        <p role="alert" className="text-sm text-neutral-400">
          Data unavailable: the API could not be reached.
        </p>
      ) : journal.entries.length === 0 ? (
        <p className="text-sm text-neutral-400">
          <Metric termId="thesis_card" icon={false}>
            No Thesis Card for this company was recorded by this date.
          </Metric>
        </p>
      ) : (
        <JournalTable rows={journal.entries} knownOn={knownOn} showTicker={false} />
      )}
      <p className="text-xs text-neutral-500">
        <Metric termId="paper_mode" icon={false}>
          Paper only: decisions are records, never orders.
        </Metric>
      </p>
    </section>
  );
}
