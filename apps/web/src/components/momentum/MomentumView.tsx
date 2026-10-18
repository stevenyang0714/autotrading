import Link from "next/link";

import { Metric } from "@/components/Metric";
import type { CompanyReading, MomentumPoint, MomentumResponse, StoredMomentum } from "@/lib/api";
import { MOMENTUM_REASONS } from "@/lib/momentum";
import { heldText, readable, trendText, weight } from "@/lib/rotation";
import { formatSgtEt } from "@/lib/time";

function ReadingRow({ reading, held, knownOn }: { reading: CompanyReading; held: string | undefined; knownOn?: string }) {
  return (
    <tr data-company={reading.symbol} data-selected={reading.selected ? "yes" : "no"} className="border-b border-neutral-900">
      <td className="px-3 py-1.5">
        <Link
          href={`/instruments/${reading.symbol}${knownOn ? `?known_on=${knownOn}` : ""}#factors`}
          data-identifier=""
          className="font-medium underline-offset-2 hover:underline"
        >
          {reading.symbol}
        </Link>
      </td>
      <td className="px-3 py-1.5">
        <Metric termId="medium_term_momentum" icon={false}>
          <span className={reading.selected ? "text-emerald-300" : "text-neutral-400"}>
            {reading.conditions.length > 0 ? reading.conditions.map(trendText).join(" · ") : "no reading"}
          </span>
        </Metric>
      </td>
      <td className="px-3 py-1.5">
        <Metric termId="medium_term_momentum" icon={false}>
          <span className={reading.selected ? "text-emerald-300" : "text-neutral-400"}>{readable(reading.detail)}</span>
        </Metric>
      </td>
      <td className="px-3 py-1.5 text-right tabular-nums">
        <Metric termId="momentum_target" icon={false}>
          {held ? weight(held) : "–"}
        </Metric>
      </td>
    </tr>
  );
}

function Current({ stored, knownOn }: { stored: StoredMomentum; knownOn?: string }) {
  const momentum = stored.momentum;
  const reason = MOMENTUM_REASONS[momentum.reason] ?? MOMENTUM_REASONS.unavailable;
  const held = momentum.target ?? {};
  return (
    <div className="space-y-3">
      <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
        <Metric termId={reason.termId} icon={false}>
          <span className="font-medium" data-reason={momentum.reason}>
            {reason.label}
          </span>
        </Metric>
        <span className="text-xs text-neutral-500">
          <Metric termId="point_in_time" icon={false}>
            assessed {formatSgtEt(stored.known_at)}
            {stored.backfilled ? " · backfilled" : ""}
          </Metric>
        </span>
      </p>
      <p className="text-sm text-neutral-300" data-target="">
        <Metric termId="momentum_target" icon={false}>
          {momentum.target === null
            ? `No target: ${momentum.detail}`
            : `Target: ${heldText(held)}; cash ${weight(momentum.cash_pct ?? "0")}`}
        </Metric>
        {momentum.set_at && momentum.target !== null ? (
          <span className="text-xs text-neutral-500">
            {" "}
            <Metric termId="momentum_target" icon={false}>
              set {formatSgtEt(momentum.set_at)}
            </Metric>
          </span>
        ) : null}
      </p>
      {momentum.readings.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm" aria-label="Company readings">
            <thead>
              <tr className="border-b border-neutral-800 text-left text-xs text-neutral-400">
                <th className="px-3 py-1.5 font-normal">Company</th>
                <th className="px-3 py-1.5 font-normal">
                  <Metric termId="momentum_12_1">Momentum</Metric>
                </th>
                <th className="px-3 py-1.5 font-normal">
                  <Metric termId="medium_term_momentum">Reason</Metric>
                </th>
                <th className="px-3 py-1.5 text-right font-normal">
                  <Metric termId="momentum_target">Target</Metric>
                </th>
              </tr>
            </thead>
            <tbody>
              {momentum.readings.map((reading) => (
                <ReadingRow key={reading.symbol} reading={reading} held={held[reading.symbol]} knownOn={knownOn} />
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="text-xs text-neutral-500">
        The readings are as of this assessment; a carried target keeps the companies chosen when it was set.
      </p>
    </div>
  );
}

function HistoryTable({ points, label }: { points: MomentumPoint[]; label: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[28rem] text-sm" aria-label={label}>
        <thead>
          <tr className="border-b border-neutral-800 text-left text-xs text-neutral-400">
            <th className="px-3 py-1.5 font-normal">Set</th>
            <th className="px-3 py-1.5 font-normal">Target</th>
          </tr>
        </thead>
        <tbody>
          {points.map((point) => (
            <tr key={point.id} data-point={point.known_at} className="border-b border-neutral-900">
              <td className="whitespace-nowrap px-3 py-1.5">
                <Metric termId="point_in_time" icon={false}>
                  {formatSgtEt(point.known_at)}
                </Metric>
              </td>
              <td className="px-3 py-1.5">
                <Metric termId="momentum_target" icon={false}>
                  {heldText(point.target)}
                </Metric>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * S4 momentum (M3.0, ADR-036 D7): the assessment in force as known on the chosen date, each
 * company's 12-1 momentum alone and against SPY, and every target set since. Research only:
 * paper signals, no order.
 */
export function MomentumView({ data, knownOn }: { data: MomentumResponse | null; knownOn?: string }) {
  if (data === null) {
    return (
      <p role="alert" className="text-sm text-neutral-400">
        Data unavailable: S4 momentum could not be loaded.
      </p>
    );
  }
  const history = [...data.history].reverse(); // newest first
  const recent = history.slice(0, 12);
  return (
    <div className="space-y-4">
      <p className="text-sm text-neutral-400">
        <Metric termId="medium_term_momentum" icon={false}>
          {data.detail}
        </Metric>{" "}
        <Metric termId="momentum_rule_set" icon={false}>
          <span className="text-neutral-500">momentum rules {data.rule_version}</span>
        </Metric>
      </p>
      {data.current ? (
        <Current stored={data.current} knownOn={knownOn} />
      ) : (
        <p className="text-sm text-neutral-400">
          <Metric termId="medium_term_momentum" icon={false}>
            No S4 assessment by this date. It is assessed daily at 11:17 SGT and backfilled for every session since 2017.
          </Metric>
        </p>
      )}
      {recent.length > 0 ? (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-neutral-300">
            <Metric termId="momentum_target">Targets set</Metric>
          </h3>
          <HistoryTable points={recent} label="Recent S4 targets" />
          {history.length > recent.length ? (
            <details className="text-sm">
              <summary className="cursor-pointer select-none text-neutral-400">
                <Metric termId="momentum_target" icon={false}>
                  Every target since {formatSgtEt(data.history[0]?.known_at ?? data.known_at)}
                </Metric>
              </summary>
              <div className="mt-2">
                <HistoryTable points={history} label="All S4 targets" />
              </div>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
