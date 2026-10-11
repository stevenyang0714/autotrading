import { AsKnownOnForm } from "@/components/AsKnownOnForm";
import { Metric } from "@/components/Metric";
import { JournalTable } from "@/components/journal/JournalTable";
import { SignalList } from "@/components/journal/SignalList";
import type { Journal, Signals } from "@/lib/api";
import { formatSgtEt } from "@/lib/time";

const HREF = "/dashboards/strategy-lab";

export function PaperOnlyNotice({ detail }: { detail: string }) {
  return (
    <p
      role="note"
      data-paper-only=""
      className="rounded border border-sky-700/60 bg-sky-950/30 px-3 py-2 text-sm text-sky-100"
    >
      <Metric termId="paper_mode" icon={false}>
        PAPER ONLY
      </Metric>
      {" · "}
      {detail} No broker is connected and no order can be sent.
    </p>
  );
}

/**
 * Strategy Lab (M1.6, ADR-027): the paper journal as known on the chosen date, the current
 * signals, and where to write a new Thesis Card. Backtests arrive in Phase 2.
 */
export function StrategyLabView({
  journal,
  signals,
  knownOn,
  invalidKnownOn = false,
}: {
  journal: Journal;
  signals: Signals | null;
  knownOn?: string;
  invalidKnownOn?: boolean;
}) {
  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          <Metric termId="dashboard_strategy_lab" zh>
            Strategy Lab
          </Metric>
        </h1>
        <p className="text-sm text-neutral-400">
          The paper journal: every Thesis Card with its TRADE or NO TRADE decision and its paper return against SPY.
          Backtests and walk-forward validation come in{" "}
          <Metric termId="planned_phase" icon={false}>
            Phase 2
          </Metric>
          .
        </p>
        <PaperOnlyNotice detail={journal.detail} />
        <AsKnownOnForm href={HREF} knownOn={knownOn} invalid={invalidKnownOn} />
        <p className="text-sm text-neutral-400">
          Showing what was recorded by{" "}
          <Metric termId="point_in_time" icon={false}>
            {formatSgtEt(journal.known_at)}
          </Metric>
        </p>
      </header>
      <div className="space-y-2" data-block="signals">
        <h2 className="text-lg font-medium">
          <Metric termId="signal" zh>
            Current signals
          </Metric>
        </h2>
        {signals === null ? (
          <p role="alert" className="text-sm text-neutral-400">
            Data unavailable: the signals could not be loaded.
          </p>
        ) : (
          <SignalList signals={signals.current} knownOn={knownOn} />
        )}
      </div>
      <div className="space-y-2" data-block="journal">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-medium">
            <Metric termId="journal_entry" zh>
              Journal
            </Metric>
          </h2>
          <form method="get" action="/journal/new" className="flex items-center gap-2 text-sm">
            <label htmlFor="new-ticker">
              <Metric termId="thesis_card" icon={false}>
                New Thesis Card for
              </Metric>
            </label>
            <input
              id="new-ticker"
              name="ticker"
              required
              maxLength={10}
              placeholder="AAPL"
              className="w-20 rounded border border-neutral-300 bg-transparent px-2 py-1 uppercase dark:border-neutral-700"
            />
            <button
              type="submit"
              className="rounded border border-neutral-300 px-3 py-1 hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
            >
              Write
            </button>
          </form>
        </div>
        {journal.entries.length === 0 ? (
          <p className="text-sm text-neutral-400">
            <Metric termId="journal_entry" icon={false}>
              No Thesis Card was recorded by this date.
            </Metric>
          </p>
        ) : (
          <JournalTable rows={journal.entries} knownOn={knownOn} />
        )}
      </div>
    </section>
  );
}
