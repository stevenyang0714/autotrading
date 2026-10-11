import Link from "next/link";

import { Metric } from "@/components/Metric";
import type { Signal } from "@/lib/api";
import { formatSgtEt } from "@/lib/time";

const STATE_TEXT: Record<string, string> = {
  active: "ACTIVE",
  high_conviction: "HIGH-CONVICTION",
};

/**
 * Current signals (M1.6, ADR-027 J1): each company whose latest buyback state assignment is
 * ACTIVE or HIGH-CONVICTION, with the rule version, score and a link to write a Thesis Card.
 * Every signal is paper only.
 */
export function SignalList({ signals, knownOn }: { signals: Signal[]; knownOn?: string }) {
  if (signals.length === 0) {
    return (
      <p className="text-sm text-neutral-400">
        <Metric termId="signal" icon={false}>
          No company is ACTIVE or HIGH-CONVICTION under the current buyback rules at this date.
        </Metric>
      </p>
    );
  }
  return (
    <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3" aria-label="Current signals">
      {signals.map((signal) => (
        <li
          key={signal.id}
          data-signal={signal.ticker}
          className="space-y-1 rounded border border-neutral-800 px-3 py-2 text-sm"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <Link
              href={`/instruments/${signal.ticker}${knownOn ? `?known_on=${knownOn}` : ""}#buybacks`}
              data-identifier=""
              className="font-medium underline-offset-2 hover:underline"
            >
              {signal.ticker}
            </Link>
            <Metric termId="buyback_state" icon={false} className="text-xs">
              {STATE_TEXT[signal.state] ?? signal.state} · {signal.direction}
            </Metric>
          </div>
          <p className="text-xs text-neutral-400">
            <Metric termId="signal" icon={false}>
              {signal.strategy_id} {signal.strategy} · rules {signal.rule_version} · {signal.evidence_independence}{" "}
              conditions passed
              {signal.backfilled ? " · backfilled" : ""}
            </Metric>
          </p>
          <p className="text-xs text-neutral-400">
            <Metric termId="buyback_quality_score" icon={false}>
              Score {signal.score ?? "unavailable"}
            </Metric>{" "}
            ·{" "}
            <Metric termId="execution_eligibility" icon={false}>
              paper only
            </Metric>
          </p>
          <p className="text-xs text-neutral-500">
            <Metric termId="point_in_time" icon={false}>
              as of {formatSgtEt(signal.generated_at)}
            </Metric>
          </p>
          <Link
            href={`/journal/new?ticker=${signal.ticker}&signal=${signal.id}`}
            className="inline-block text-xs underline-offset-2 hover:underline"
          >
            Write a Thesis Card
          </Link>
        </li>
      ))}
    </ul>
  );
}
