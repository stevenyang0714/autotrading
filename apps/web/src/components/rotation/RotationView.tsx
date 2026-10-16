import Link from "next/link";

import { Metric } from "@/components/Metric";
import { DemoBanner } from "@/components/prices/DemoBanner";
import type { EtfReading, FeedStatus, RotationPoint, RotationResponse, StoredRotation } from "@/lib/api";
import { QUADRANTS, STRESS } from "@/lib/regime";
import { REASONS, SLEEVES, beta, heldText, readable, trendText, weight } from "@/lib/rotation";
import { formatSgtEt } from "@/lib/time";

/** The stress state and quadrant a rotation read (the quadrant is context only, KI-7). */
export function StressContext({ stress, quadrant }: { stress: string | null; quadrant: string | null }) {
  const found = stress ? STRESS[stress] : undefined;
  return (
    <span className="inline-flex flex-wrap items-baseline gap-2">
      {found ? (
        <Metric termId={found.termId} icon={false}>
          <span className={`rounded border px-1.5 py-0.5 text-xs font-semibold ${found.className}`} data-stress={stress}>
            {found.label}
          </span>
        </Metric>
      ) : (
        <Metric termId="stress_state" icon={false}>
          <span className="text-xs text-neutral-400">stress unavailable</span>
        </Metric>
      )}
      <Metric termId="regime_quadrant" icon={false}>
        <span className="text-xs text-neutral-400">{quadrant ? (QUADRANTS[quadrant] ?? quadrant) : "quadrant unavailable"}</span>
      </Metric>
    </span>
  );
}

function ReadingRow({ reading, held, knownOn }: { reading: EtfReading; held: string | undefined; knownOn?: string }) {
  const sleeve = SLEEVES[reading.sleeve];
  return (
    <tr data-etf={reading.symbol} data-eligible={reading.eligible ? "yes" : "no"} className="border-b border-neutral-900">
      <td className="px-3 py-1.5">
        <Link
          href={`/instruments/${reading.symbol}${knownOn ? `?known_on=${knownOn}` : ""}#factors`}
          data-identifier=""
          className="font-medium underline-offset-2 hover:underline"
        >
          {reading.symbol}
        </Link>
      </td>
      <td className="px-3 py-1.5 text-neutral-400">
        <Metric termId={sleeve?.termId ?? "etf_rotation"} icon={false}>
          {sleeve?.label ?? reading.sleeve}
        </Metric>
      </td>
      <td className="px-3 py-1.5">
        <Metric termId="trend_filter" icon={false}>
          <span className={reading.trend_up ? "text-emerald-300" : "text-neutral-400"}>
            {reading.trend.length > 0 ? reading.trend.map(trendText).join(" · ") : "no reading"}
          </span>
        </Metric>
      </td>
      <td className="px-3 py-1.5 text-right tabular-nums">
        <Metric termId="high_beta" icon={false}>
          <span className={reading.high_beta ? "text-amber-300" : ""}>{beta(reading.beta)}</span>
        </Metric>
      </td>
      <td className="px-3 py-1.5">
        <Metric termId="regime_gate" icon={false}>
          <span className={reading.eligible ? "text-emerald-300" : "text-neutral-400"}>{readable(reading.detail)}</span>
        </Metric>
      </td>
      <td className="px-3 py-1.5 text-right tabular-nums">
        <Metric termId="rotation_target" icon={false}>
          {held ? weight(held) : "–"}
        </Metric>
      </td>
    </tr>
  );
}

function Current({ stored, knownOn }: { stored: StoredRotation; knownOn?: string }) {
  const rotation = stored.rotation;
  const reason = REASONS[rotation.reason] ?? REASONS.unavailable;
  const held = Object.fromEntries((rotation.target ?? []).map((h) => [h.symbol, h.weight_pct]));
  return (
    <div className="space-y-3">
      <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
        <Metric termId={reason.termId} icon={false}>
          <span className="font-medium" data-reason={rotation.reason}>
            {reason.label}
          </span>
        </Metric>
        <StressContext stress={rotation.stress} quadrant={rotation.quadrant} />
        <span className="text-xs text-neutral-500">
          <Metric termId="point_in_time" icon={false}>
            assessed {formatSgtEt(stored.known_at)}
            {stored.backfilled ? " · backfilled" : ""}
          </Metric>
        </span>
      </p>
      <p className="text-sm text-neutral-300" data-target="">
        <Metric termId="rotation_target" icon={false}>
          {rotation.target === null
            ? `No target: ${rotation.detail}`
            : `Target: ${heldText(held)}; cash ${weight(rotation.cash_pct ?? "0")}`}
        </Metric>
        {rotation.set_at && rotation.target !== null ? (
          <span className="text-xs text-neutral-500">
            {" "}
            <Metric termId="rotation_rebalance" icon={false}>
              set {formatSgtEt(rotation.set_at)}
            </Metric>
          </span>
        ) : null}
      </p>
      {rotation.readings.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[44rem] text-sm" aria-label="ETF readings">
            <thead>
              <tr className="border-b border-neutral-800 text-left text-xs text-neutral-400">
                <th className="px-3 py-1.5 font-normal">ETF</th>
                <th className="px-3 py-1.5 font-normal">Sleeve</th>
                <th className="px-3 py-1.5 font-normal">
                  <Metric termId="trend_filter">Trend</Metric>
                </th>
                <th className="px-3 py-1.5 text-right font-normal">
                  <Metric termId="high_beta">Beta</Metric>
                </th>
                <th className="px-3 py-1.5 font-normal">
                  <Metric termId="regime_gate">Gate and reason</Metric>
                </th>
                <th className="px-3 py-1.5 text-right font-normal">
                  <Metric termId="rotation_target">Target</Metric>
                </th>
              </tr>
            </thead>
            <tbody>
              {rotation.readings.map((reading) => (
                <ReadingRow key={reading.symbol} reading={reading} held={held[reading.symbol]} knownOn={knownOn} />
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="text-xs text-neutral-500">
        The readings are as of this assessment; a carried target keeps the ETFs chosen when it was set.
      </p>
    </div>
  );
}

function HistoryTable({ points, label }: { points: RotationPoint[]; label: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[32rem] text-sm" aria-label={label}>
        <thead>
          <tr className="border-b border-neutral-800 text-left text-xs text-neutral-400">
            <th className="px-3 py-1.5 font-normal">Set</th>
            <th className="px-3 py-1.5 font-normal">Why</th>
            <th className="px-3 py-1.5 font-normal">Stress</th>
            <th className="px-3 py-1.5 font-normal">Target</th>
          </tr>
        </thead>
        <tbody>
          {points.map((point) => {
            const reason = REASONS[point.reason] ?? REASONS.unavailable;
            const stress = point.stress ? STRESS[point.stress] : undefined;
            return (
              <tr key={point.id} data-point={point.known_at} className="border-b border-neutral-900">
                <td className="whitespace-nowrap px-3 py-1.5">
                  <Metric termId="point_in_time" icon={false}>
                    {formatSgtEt(point.known_at)}
                  </Metric>
                </td>
                <td className="px-3 py-1.5 text-neutral-400">
                  <Metric termId={reason.termId} icon={false}>
                    {reason.label}
                  </Metric>
                </td>
                <td className="px-3 py-1.5">
                  <Metric termId={stress?.termId ?? "stress_state"} icon={false}>
                    {stress?.label ?? "unavailable"}
                  </Metric>
                </td>
                <td className="px-3 py-1.5">
                  <Metric termId="rotation_target" icon={false}>
                    {heldText(point.target)}
                  </Metric>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The S3 ETF rotation (M2.4, ADR-032): the assessment in force as known on the chosen date,
 * each ETF's trend, beta and gate, and every target set since. Research only: paper signals,
 * no order, and ETFs cannot enter the journal yet.
 */
export function RotationView({ data, knownOn }: { data: RotationResponse | null; knownOn?: string }) {
  if (data === null) {
    return (
      <p role="alert" className="text-sm text-neutral-400">
        Data unavailable: the rotation could not be loaded.
      </p>
    );
  }
  const history = [...data.history].reverse(); // newest first
  const recent = history.slice(0, 12);
  return (
    <div className="space-y-4">
      <p className="text-sm text-neutral-400">
        <Metric termId="etf_rotation" icon={false}>
          {data.detail}
        </Metric>{" "}
        <Metric termId="rotation_rule_set" icon={false}>
          <span className="text-neutral-500">rotation rules {data.rule_version}</span>
        </Metric>
      </p>
      <DemoBanner statuses={(data.current?.rotation.readings ?? []).map((r) => r.feed_status as FeedStatus | null)} />
      {data.current ? (
        <Current stored={data.current} knownOn={knownOn} />
      ) : (
        <p className="text-sm text-neutral-400">
          <Metric termId="etf_rotation" icon={false}>
            No rotation assessment by this date. It is assessed daily at 11:15 SGT and backfilled for month ends since 2017.
          </Metric>
        </p>
      )}
      {recent.length > 0 ? (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-neutral-300">
            <Metric termId="rotation_rebalance">Targets set</Metric>
          </h3>
          <HistoryTable points={recent} label="Recent targets" />
          {history.length > recent.length ? (
            <details className="text-sm">
              <summary className="cursor-pointer select-none text-neutral-400">
                <Metric termId="rotation_target" icon={false}>
                  Every target since {formatSgtEt(data.history[0]?.known_at ?? data.known_at)}
                </Metric>
              </summary>
              <div className="mt-2">
                <HistoryTable points={history} label="All targets" />
              </div>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
