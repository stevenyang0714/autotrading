import Link from "next/link";

import { Metric } from "@/components/Metric";
import type { JournalRow } from "@/lib/api";
import { decisionLabel, formatPnl, performanceSummary, signedClass } from "@/lib/journal";
import { formatSgtEt } from "@/lib/time";

export function cardHref(cardId: string, knownOn?: string): string {
  return `/journal/${cardId}${knownOn ? `?known_on=${knownOn}` : ""}`;
}

function Row({ row, knownOn, showTicker }: { row: JournalRow; knownOn?: string; showTicker: boolean }) {
  const decision = row.decision;
  const performance = decision?.performance;
  return (
    <tr data-card={row.card_id} data-decision={decision?.decision} className="border-b border-neutral-900 align-top">
      <td className="px-3 py-2">
        <Metric termId="journal_entry" icon={false}>
          <span className="whitespace-nowrap">{formatSgtEt(row.known_at)}</span>
        </Metric>
        {row.version > 1 ? (
          <span className="block text-xs text-neutral-500">
            <Metric termId="thesis_card" icon={false}>
              version {row.version}
            </Metric>
          </span>
        ) : null}
      </td>
      {showTicker ? (
        <td className="px-2 py-2">
          <Link
            href={`/instruments/${row.ticker}${knownOn ? `?known_on=${knownOn}` : ""}#journal`}
            data-identifier=""
            className="font-medium underline-offset-2 hover:underline"
          >
            {row.ticker}
          </Link>
        </td>
      ) : null}
      <td className="px-2 py-2">
        {decision ? (
          <Metric termId={decision.decision === "no_trade" ? "no_trade" : "trade_decision"} icon={false}>
            <span className="whitespace-nowrap">{decisionLabel(decision)}</span>
          </Metric>
        ) : (
          <span className="text-neutral-500">no decision</span>
        )}
        {row.exit ? (
          <span className="block text-xs text-neutral-500">
            <Metric termId="trade_decision" icon={false}>
              exited {formatSgtEt(row.exit.known_at)}
            </Metric>
          </span>
        ) : null}
      </td>
      <td className="max-w-[22rem] px-2 py-2">
        <Link href={cardHref(row.card_id, knownOn)} className="underline-offset-2 hover:underline">
          <Metric termId="thesis_card" icon={false}>
            {row.thesis}
          </Metric>
        </Link>
      </td>
      <td className="px-2 py-2 text-right tabular-nums" data-column="performance">
        {performance ? (
          <Metric termId="paper_return" icon={false}>
            <span className={signedClass(performance.return_pct)}>{performanceSummary(performance)}</span>
            {performance.pnl !== null ? (
              <span className="block text-xs text-neutral-500">{formatPnl(performance.pnl)}</span>
            ) : null}
            {performance.max_loss_breached ? (
              <span className="block text-xs text-amber-400">maximum loss exceeded</span>
            ) : null}
          </Metric>
        ) : (
          <span className="text-neutral-500">n/a</span>
        )}
      </td>
      <td className="px-2 py-2 text-right">
        <Metric termId="signal" icon={false}>
          {row.signal_ids.length > 0 ? `${row.signal_ids.length} cited` : "none"}
        </Metric>
      </td>
    </tr>
  );
}

/**
 * Journal entries (M1.6, ADR-027): each Thesis Card with its first decision, its exit and the
 * paper return against SPY at the viewing time. Used by the Strategy Lab and instrument pages.
 */
export function JournalTable({
  rows,
  knownOn,
  showTicker = true,
}: {
  rows: JournalRow[];
  knownOn?: string;
  showTicker?: boolean;
}) {
  const head = "px-2 py-2 text-left align-bottom font-normal";
  return (
    <div className="overflow-x-auto rounded border border-neutral-800">
      <table className="w-full min-w-[48rem] text-sm" aria-label="Journal entries">
        <thead>
          <tr className="border-b border-neutral-800 text-xs text-neutral-400">
            <th scope="col" className="px-3 py-2 text-left align-bottom font-normal">
              <Metric termId="journal_entry" icon={false}>
                Written
              </Metric>
            </th>
            {showTicker ? (
              <th scope="col" className={head}>
                Company
              </th>
            ) : null}
            <th scope="col" className={head}>
              <Metric termId="trade_decision" icon={false}>
                Decision
              </Metric>
            </th>
            <th scope="col" className={head}>
              <Metric termId="thesis_card" icon={false}>
                Thesis
              </Metric>
            </th>
            <th scope="col" className="px-2 py-2 text-right align-bottom font-normal">
              <Metric termId="paper_return" icon={false}>
                Paper return vs SPY
              </Metric>
            </th>
            <th scope="col" className="px-2 py-2 text-right align-bottom font-normal">
              <Metric termId="signal" icon={false}>
                Signals
              </Metric>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <Row key={row.card_id} row={row} knownOn={knownOn} showTicker={showTicker} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
