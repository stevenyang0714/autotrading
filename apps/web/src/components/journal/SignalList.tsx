import Link from "next/link";

import { Metric } from "@/components/Metric";
import type { Signal } from "@/lib/api";
import { STRESS } from "@/lib/regime";
import { signedPct, weight } from "@/lib/rotation";
import { formatSgtEt } from "@/lib/time";

const STATE_TEXT: Record<string, string> = {
  active: "ACTIVE",
  high_conviction: "HIGH-CONVICTION",
  trade_ready: "TRADE-READY",
};
const ROTATION = "S3";
const MOMENTUM = "S4";

/** S3 rotation signals (M2.4, ADR-032): one card per ETF of the target in force, with its
 * family 5 (trend) and family 1 (gate) signals. ETFs cannot enter the journal yet. */
function RotationSignals({ signals, knownOn }: { signals: Signal[]; knownOn?: string }) {
  const tickers = [...new Set(signals.map((s) => s.ticker))];
  return (
    <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-label="S3 rotation signals">
      {tickers.map((ticker) => {
        const own = signals.filter((s) => s.ticker === ticker);
        const trend = own.find((s) => s.family_id === 5);
        const gate = own.find((s) => s.family_id === 1);
        const first = trend ?? gate ?? own[0];
        const stress = first.stress ? STRESS[first.stress] : undefined;
        return (
          <li
            key={ticker}
            data-signal={ticker}
            data-strategy={ROTATION}
            className="space-y-1 rounded border border-neutral-800 px-3 py-2 text-sm"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <Link
                href={`/instruments/${ticker}${knownOn ? `?known_on=${knownOn}` : ""}#factors`}
                data-identifier=""
                className="font-medium underline-offset-2 hover:underline"
              >
                {ticker}
              </Link>
              <Metric termId="rotation_target" icon={false} className="text-xs">
                {first.weight_pct ? weight(first.weight_pct) : "held"} · {first.direction}
              </Metric>
            </div>
            <p className="text-xs text-neutral-400">
              <Metric termId="signal" icon={false}>
                {first.strategy_id} {first.strategy} · rules {first.rule_version}
                {first.backfilled ? " · backfilled" : ""}
              </Metric>
            </p>
            <p className="text-xs text-neutral-400">
              {trend ? (
                <Metric termId="trend_filter" icon={false}>
                  family {trend.family_id} trend: 12-1 mom. {trend.score ? signedPct(trend.score) : "n/a"}
                </Metric>
              ) : null}
              {trend && gate ? " · " : null}
              {gate ? (
                <Metric termId="regime_gate" icon={false}>
                  family {gate.family_id} gate: {stress?.label ?? "unavailable"}
                </Metric>
              ) : null}
            </p>
            <p className="text-xs text-neutral-500">
              <Metric termId="execution_eligibility" icon={false}>
                paper only
              </Metric>{" "}
              ·{" "}
              <Metric termId="point_in_time" icon={false}>
                set {formatSgtEt(first.generated_at)}
              </Metric>
            </p>
          </li>
        );
      })}
    </ul>
  );
}

/** S4 momentum signals (M3.0, ADR-036 D7): one card per company of the target in force, with
 * its family 5 signal (12-1 momentum). A company can enter the journal; no signal is an order. */
function MomentumSignals({ signals, knownOn }: { signals: Signal[]; knownOn?: string }) {
  return (
    <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-label="S4 momentum signals">
      {signals.map((signal) => (
        <li
          key={signal.id}
          data-signal={signal.ticker}
          data-strategy={MOMENTUM}
          className="space-y-1 rounded border border-neutral-800 px-3 py-2 text-sm"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <Link
              href={`/instruments/${signal.ticker}${knownOn ? `?known_on=${knownOn}` : ""}#factors`}
              data-identifier=""
              className="font-medium underline-offset-2 hover:underline"
            >
              {signal.ticker}
            </Link>
            <Metric termId="momentum_target" icon={false} className="text-xs">
              {signal.weight_pct ? weight(signal.weight_pct) : "held"} · {signal.direction}
            </Metric>
          </div>
          <p className="text-xs text-neutral-400">
            <Metric termId="signal" icon={false}>
              {signal.strategy_id} {signal.strategy} · rules {signal.rule_version}
              {signal.backfilled ? " · backfilled" : ""}
            </Metric>
          </p>
          <p className="text-xs text-neutral-400">
            <Metric termId="momentum_12_1" icon={false}>
              family {signal.family_id}: 12-1 mom. {signal.score ? signedPct(signal.score) : "n/a"} ·{" "}
              {signal.evidence_independence} conditions passed
            </Metric>
          </p>
          <p className="text-xs text-neutral-500">
            <Metric termId="execution_eligibility" icon={false}>
              paper only
            </Metric>{" "}
            ·{" "}
            <Metric termId="point_in_time" icon={false}>
              set {formatSgtEt(signal.generated_at)}
            </Metric>
          </p>
          <Link
            href={`/journal/new?ticker=${signal.ticker}`}
            className="inline-block text-xs underline-offset-2 hover:underline"
          >
            Write a Thesis Card
          </Link>
        </li>
      ))}
    </ul>
  );
}

/**
 * Current signals (M1.6, ADR-027 J1): each company whose latest buyback state assignment is
 * ACTIVE, HIGH-CONVICTION or TRADE-READY (S1), with the rule version, score and a link to write
 * a Thesis Card; since M2.4 the ETFs of the S3 rotation target in force, and since M3.0 the
 * companies of the S4 momentum target. Every signal is paper only.
 */
export function SignalList({ signals, knownOn }: { signals: Signal[]; knownOn?: string }) {
  const companies = signals.filter((s) => s.strategy_id !== ROTATION && s.strategy_id !== MOMENTUM);
  const etfs = signals.filter((s) => s.strategy_id === ROTATION);
  const momentum = signals.filter((s) => s.strategy_id === MOMENTUM);
  return (
    <div className="space-y-3">
      <CompanySignals signals={companies} knownOn={knownOn} />
      {etfs.length > 0 ? (
        <>
          <h3 className="text-sm font-medium text-neutral-300">
            <Metric termId="etf_rotation">ETF rotation target (S3)</Metric>
          </h3>
          <RotationSignals signals={etfs} knownOn={knownOn} />
        </>
      ) : null}
      {momentum.length > 0 ? (
        <>
          <h3 className="text-sm font-medium text-neutral-300">
            <Metric termId="medium_term_momentum">Momentum target (S4)</Metric>
          </h3>
          <MomentumSignals signals={momentum} knownOn={knownOn} />
        </>
      ) : null}
    </div>
  );
}

function CompanySignals({ signals, knownOn }: { signals: Signal[]; knownOn?: string }) {
  if (signals.length === 0) {
    return (
      <p className="text-sm text-neutral-400">
        <Metric termId="signal" icon={false}>
          No company is ACTIVE, HIGH-CONVICTION or TRADE-READY under the current buyback rules at this date.
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
