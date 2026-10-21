import Link from "next/link";

import { InstrumentName } from "@/components/InstrumentName";
import { Metric } from "@/components/Metric";
import { StressContext } from "@/components/rotation/RotationView";
import type { CompanyCandidate, EtfCandidate, MomentumCandidate, OpportunityCandidates } from "@/lib/api";
import { levelClass, levelTerm } from "@/lib/alerts";
import { MOMENTUM_REASONS } from "@/lib/momentum";
import { REASONS, beta, trendText, weight } from "@/lib/rotation";
import { formatSgtEt } from "@/lib/time";

function suffix(knownOn?: string): string {
  return knownOn ? `?known_on=${knownOn}` : "";
}

function Company({ candidate, knownOn }: { candidate: CompanyCandidate; knownOn?: string }) {
  const level = candidate.convergence;
  const checks = level.levels.filter((c) => c.level >= 2);
  return (
    <li
      data-candidate={candidate.ticker}
      data-strategy={candidate.strategy_id}
      className="space-y-1 rounded border border-neutral-800 px-3 py-2 text-sm"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Link
          href={`/instruments/${candidate.ticker}${suffix(knownOn)}#buybacks`}
          data-identifier=""
          className="font-medium underline-offset-2 hover:underline"
        >
          {candidate.ticker}
        </Link>
        <InstrumentName name={candidate.name} zh={candidate.name_zh} />
        <span className={`inline-block rounded border px-1.5 py-0.5 text-xs ${levelClass(level.level)}`}>
          <Metric termId={levelTerm(level.level)} icon={false}>
            {level.level_name}
          </Metric>
        </span>
      </div>
      <p className="text-xs text-neutral-400">
        <Metric termId="opportunity_candidate" icon={false}>
          {candidate.strategy_id} {candidate.strategy}
        </Metric>
      </p>
      <ul className="space-y-0.5 text-xs text-neutral-400" aria-label={`${candidate.ticker} levels`}>
        {checks.map((check) => (
          <li key={check.level} data-check={check.level} data-status={check.status}>
            <Metric termId={levelTerm(check.level)} icon={false}>
              {check.name} {check.status}: {check.detail}
            </Metric>
          </li>
        ))}
      </ul>
      <p className="text-xs text-neutral-500">
        <Metric termId="alert_rule_set" icon={false}>
          alert rules {candidate.alert_rule_version}
        </Metric>{" "}
        ·{" "}
        <Metric termId="buyback_rule_version" icon={false}>
          buyback rules {candidate.buyback_rule_version}
        </Metric>{" "}
        ·{" "}
        <Metric termId="point_in_time" icon={false}>
          assessed {formatSgtEt(level.known_at)}
          {level.backfilled ? " · backfilled" : ""}
        </Metric>
      </p>
    </li>
  );
}

function Etf({ candidate, knownOn }: { candidate: EtfCandidate; knownOn?: string }) {
  const reading = candidate.reading;
  const reason = REASONS[candidate.reason] ?? REASONS.carried;
  return (
    <li
      data-candidate={candidate.ticker}
      data-strategy={candidate.strategy_id}
      className="space-y-1 rounded border border-neutral-800 px-3 py-2 text-sm"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Link
          href={`/instruments/${candidate.ticker}${suffix(knownOn)}#factors`}
          data-identifier=""
          className="font-medium underline-offset-2 hover:underline"
        >
          {candidate.ticker}
        </Link>
        <InstrumentName name={candidate.name} zh={candidate.name_zh} />
        <Metric termId="rotation_target" icon={false} className="text-xs">
          {weight(candidate.weight_pct)}
        </Metric>
      </div>
      <p className="text-xs text-neutral-400">
        <Metric termId="etf_rotation" icon={false}>
          {candidate.strategy_id} {candidate.strategy}
        </Metric>
      </p>
      <p className="text-xs text-neutral-400">
        <Metric termId="trend_filter" icon={false}>
          {reading.trend.length > 0 ? reading.trend.map(trendText).join(" · ") : "no reading"}
        </Metric>{" "}
        ·{" "}
        <Metric termId="high_beta" icon={false}>
          beta {beta(reading.beta)}
        </Metric>
      </p>
      <p className="text-xs text-neutral-500">
        <Metric termId={reason.termId} icon={false}>
          {reason.label}, set {formatSgtEt(candidate.set_at)}
        </Metric>{" "}
        ·{" "}
        <Metric termId="rotation_rule_set" icon={false}>
          rotation rules {candidate.rotation_rule_version}
        </Metric>
        {" · "}
        <Metric termId="regime_rule_set" icon={false}>
          regime rules {candidate.regime_rule_version}
        </Metric>
        {" · "}
        <Metric termId="factor_definition_set" icon={false}>
          factor definitions {candidate.factor_definition_version}
        </Metric>
      </p>
    </li>
  );
}

function Momentum({ candidate, knownOn }: { candidate: MomentumCandidate; knownOn?: string }) {
  const reading = candidate.reading;
  const reason = MOMENTUM_REASONS[candidate.reason] ?? MOMENTUM_REASONS.carried;
  return (
    <li
      data-candidate={candidate.ticker}
      data-strategy={candidate.strategy_id}
      className="space-y-1 rounded border border-neutral-800 px-3 py-2 text-sm"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Link
          href={`/instruments/${candidate.ticker}${suffix(knownOn)}#factors`}
          data-identifier=""
          className="font-medium underline-offset-2 hover:underline"
        >
          {candidate.ticker}
        </Link>
        <InstrumentName name={candidate.name} zh={candidate.name_zh} />
        <Metric termId="momentum_target" icon={false} className="text-xs">
          {weight(candidate.weight_pct)}
        </Metric>
      </div>
      <p className="text-xs text-neutral-400">
        <Metric termId="medium_term_momentum" icon={false}>
          {candidate.strategy_id} {candidate.strategy}
        </Metric>
      </p>
      <p className="text-xs text-neutral-400">
        <Metric termId="momentum_12_1" icon={false}>
          {reading.conditions.length > 0 ? reading.conditions.map(trendText).join(" · ") : "no reading"}
        </Metric>
      </p>
      <p className="text-xs text-neutral-500">
        <Metric termId={reason.termId} icon={false}>
          {reason.label}, set {formatSgtEt(candidate.set_at)}
        </Metric>{" "}
        ·{" "}
        <Metric termId="momentum_rule_set" icon={false}>
          momentum rules {candidate.momentum_rule_version}
        </Metric>
        {" · "}
        <Metric termId="factor_definition_set" icon={false}>
          factor definitions {candidate.factor_definition_version}
        </Metric>
      </p>
    </li>
  );
}

/**
 * Opportunity Radar candidates (M2.4, ADR-032 Q3): what the rules flag as known on the chosen
 * date, companies at L3 or L4 (S1), the ETFs of the S3 rotation target and, since M3.0, the
 * companies of the S4 momentum target, with the market's stress state as context. Long only;
 * no score and no ranking across instruments.
 */
export function CandidatesView({ data, knownOn }: { data: OpportunityCandidates | null; knownOn?: string }) {
  if (data === null) {
    return (
      <p role="alert" className="text-sm text-neutral-400">
        Data unavailable: the candidates could not be loaded.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <p role="note" className="text-sm text-neutral-400">
        <Metric termId="opportunity_candidate" icon={false}>
          {data.detail}
        </Metric>
      </p>
      <p className="flex flex-wrap items-baseline gap-2 text-sm text-neutral-400" data-context="">
        {data.context ? (
          <>
            <span>Market as assessed</span>
            <Metric termId="point_in_time" icon={false}>
              {formatSgtEt(data.context.known_at)}
            </Metric>
            <StressContext stress={data.context.stress} quadrant={data.context.quadrant} />
          </>
        ) : (
          <Metric termId="stress_state" icon={false}>
            No regime assessment by this date.
          </Metric>
        )}
      </p>
      <div className="space-y-2" data-candidates="S1">
        <h3 className="text-sm font-medium text-neutral-300">
          <Metric termId="convergence_level">Companies at L3 or L4 (S1)</Metric>
        </h3>
        {data.companies.length > 0 ? (
          <ul className="grid grid-cols-1 gap-2 md:grid-cols-2" aria-label="Company candidates">
            {data.companies.map((c) => (
              <Company key={c.ticker} candidate={c} knownOn={knownOn} />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-neutral-400">
            <Metric termId="convergence_level" icon={false}>
              No company is at L3 or L4 at this date.
            </Metric>
          </p>
        )}
      </div>
      <div className="space-y-2" data-candidates="S3">
        <h3 className="text-sm font-medium text-neutral-300">
          <Metric termId="etf_rotation">ETFs of the rotation target (S3)</Metric>
        </h3>
        {data.etfs.length > 0 ? (
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-label="ETF candidates">
            {data.etfs.map((e) => (
              <Etf key={e.ticker} candidate={e} knownOn={knownOn} />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-neutral-400">
            <Metric termId="rotation_target" icon={false}>
              The rotation holds no ETF at this date (cash only, or not assessed).
            </Metric>
          </p>
        )}
        <p className="text-xs text-neutral-500">
          <Link href={`/dashboards/strategy-lab${suffix(knownOn)}#rotation`} className="underline-offset-2 hover:underline">
            <Metric termId="etf_rotation" icon={false}>
              Every ETF&apos;s trend and gate, and the targets since 2017
            </Metric>
          </Link>
        </p>
      </div>
      <div className="space-y-2" data-candidates="S4">
        <h3 className="text-sm font-medium text-neutral-300">
          <Metric termId="medium_term_momentum">Companies of the momentum target (S4)</Metric>
        </h3>
        {(data.momentum ?? []).length > 0 ? (
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-label="Momentum candidates">
            {(data.momentum ?? []).map((m) => (
              <Momentum key={m.ticker} candidate={m} knownOn={knownOn} />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-neutral-400">
            <Metric termId="momentum_target" icon={false}>
              S4 holds no company at this date (cash only, or not assessed).
            </Metric>
          </p>
        )}
        <p className="text-xs text-neutral-500">
          <Link href={`/dashboards/strategy-lab${suffix(knownOn)}#momentum`} className="underline-offset-2 hover:underline">
            <Metric termId="medium_term_momentum" icon={false}>
              Every company&apos;s momentum, and the targets since 2017
            </Metric>
          </Link>
        </p>
      </div>
    </div>
  );
}
