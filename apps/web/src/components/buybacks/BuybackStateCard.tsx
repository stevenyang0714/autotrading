import { Metric } from "@/components/Metric";
import type { CompleteTermId } from "@/generated/glossary";
import type { ScoreComponent, StateAssignment, StateCondition, StatePoint, ValuationInput } from "@/lib/api";
import {
  INPUT_LABELS,
  LEVELS,
  STATE_LABELS,
  STATE_STYLES,
  STATE_TERMS,
  STATUS_LABELS,
  STATUS_STYLES,
  componentMeta,
  conditionMeta,
  formatMeasure,
  formatThreshold,
  inputUnit,
} from "@/lib/buybackStates";
import { exactReported, formatReported } from "@/lib/format";
import { formatSgtEt } from "@/lib/time";

import { StateHistory } from "./StateHistory";

/** "2.08%", "$27.78", "$90.711B": an input value in its unit (exact value in the title). */
function inputValue(value: string, unit: string): string {
  if (unit === "percent") return `${Number(value).toFixed(2)}%`;
  return formatReported(value, unit);
}

/** The inputs of a condition or score component: value, period, note, filings. */
export function StateInputs({ inputs, termId }: { inputs: ValuationInput[]; termId: CompleteTermId }) {
  if (inputs.length === 0) return null;
  return (
    <ul className="space-y-1 text-xs text-neutral-400">
      {inputs.map((input, index) => {
        const unit = inputUnit(input.name);
        return (
          <li key={`${input.name}-${index}`} className="space-y-0.5">
            <Metric termId={termId} icon={false}>
              <span>{INPUT_LABELS[input.name] ?? input.name.replaceAll("_", " ")}</span>{" "}
              {input.value !== null ? (
                <span className="tabular-nums text-neutral-200" title={exactReported(input.value, unit)}>
                  {inputValue(input.value, unit)}
                </span>
              ) : null}{" "}
              <span className="text-neutral-500">
                {input.period_start ? `${input.period_start} to ${input.period_end}` : input.period_end ? `on ${input.period_end}` : ""}
              </span>
              {input.note ? <span className="block text-neutral-500">{input.note}</span> : null}
            </Metric>
            {input.sources.length > 0 ? (
              <span className="flex flex-wrap gap-x-2">
                {input.sources
                  .filter((s, i, all) => all.findIndex((o) => o.filing.accession === s.filing.accession) === i)
                  .map((source) => (
                    <a
                      key={source.filing.accession}
                      href={source.filing.url}
                      target="_blank"
                      rel="noreferrer"
                      data-identifier=""
                      className="whitespace-nowrap underline-offset-2 hover:underline"
                    >
                      {source.filing.form ? `${source.filing.form} ` : ""}
                      {source.filing.accession}
                    </a>
                  ))}
              </span>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export function StatusText({ status }: { status: StateCondition["status"] }) {
  return (
    <Metric termId="condition_status" icon={false}>
      <span className={STATUS_STYLES[status]} data-status={status}>
        {STATUS_LABELS[status]}
      </span>
    </Metric>
  );
}

function ConditionRow({ condition }: { condition: StateCondition }) {
  const meta = conditionMeta(condition.condition_id);
  return (
    <li className="space-y-1 border-b border-neutral-900 py-2" data-condition={condition.condition_id}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Metric termId={meta.termId} icon={false}>
          <span className="text-neutral-200">{meta.label}</span>
        </Metric>
        <Metric termId={meta.termId} icon={false}>
          <span className="tabular-nums">{formatMeasure(condition.value, condition.unit)}</span>{" "}
          <span className="text-neutral-500">({formatThreshold(condition)})</span>
        </Metric>
        <StatusText status={condition.status} />
      </div>
      <p className="text-xs text-neutral-400">
        <Metric termId={meta.termId} icon={false}>
          {condition.detail}
        </Metric>
      </p>
      {condition.announcements.map((event) => (
        <p key={`${event.kind}-${event.day}`} className="text-xs text-neutral-400">
          {event.sources.slice(0, 1).map((source) => (
            <span key={source.url}>
              <q data-quoted="" className="text-neutral-300">
                {source.sentence.replace(/^[“"‘']+|[”"’']+$/g, "")}
              </q>{" "}
              <a href={source.url} target="_blank" rel="noreferrer" data-identifier="" className="underline-offset-2 hover:underline">
                {source.channel === "sec_8k" ? `${source.document_type ?? "8-K"} ${source.accession ?? ""}` : "Press release"}
              </a>
            </span>
          ))}
        </p>
      ))}
      {condition.inputs.length > 0 ? (
        <details className="text-xs">
          <summary className="cursor-pointer select-none text-neutral-500">Inputs and filings</summary>
          <div className="mt-1">
            <StateInputs inputs={condition.inputs} termId={meta.termId} />
          </div>
        </details>
      ) : null}
    </li>
  );
}

function Score({ assignment }: { assignment: StateAssignment }) {
  const score = assignment.assessment.score;
  return (
    <div className="space-y-2" data-block="score">
      <h4 className="flex flex-wrap items-baseline gap-x-2 text-sm font-medium">
        <Metric termId="buyback_quality_score">Buyback Quality Score</Metric>
        <Metric termId="buyback_quality_score" icon={false}>
          <span className="tabular-nums" data-score="">
            {score.total !== null ? score.total : "Data unavailable"}
          </span>
        </Metric>
        <span className="text-xs font-normal text-amber-300">{score.label}</span>
      </h4>
      {score.detail ? (
        <p className="text-xs text-neutral-400">
          <Metric termId="buyback_quality_score" icon={false}>
            {score.detail}
          </Metric>
        </p>
      ) : null}
      <ul className="grid gap-x-6 sm:grid-cols-2" aria-label="Score components">
        {score.components.map((component: ScoreComponent) => {
          const meta = componentMeta(component.component);
          return (
            <li key={component.component} className="border-b border-neutral-900 py-1 text-xs" data-component={component.component}>
              <Metric termId={meta.termId} icon={false}>
                <span className="text-neutral-200">{meta.label}</span>{" "}
                <span className="text-neutral-500">weight {component.weight}</span>{" "}
                <span className="tabular-nums">{component.score !== null ? `${component.score} / 100` : "n/a"}</span>
                {component.detail ? <span className="block text-neutral-500">{component.detail}</span> : null}
              </Metric>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * The buyback state of one company (M1.4b, ADR-025): the latest stored assignment at or before
 * the page's As known on time, every condition against its threshold with its evidence, and
 * the score. A state is a label for research; none triggers a trade.
 */
export function BuybackStateCard({
  state,
  history,
  ruleVersion,
}: {
  state: StateAssignment | null;
  history: StatePoint[];
  ruleVersion: string;
}) {
  // Rules 0.1.0 and 0.2.0 never reach TRADE-READY (P1-4); 0.3.0 reads the standard risk check.
  const phase1 = Boolean(
    state?.assessment.conditions
      .find((c) => c.condition_id === "trade_ready.risk_check")
      ?.detail.includes("unreachable in Phase 1"),
  );
  return (
    <div className="space-y-3 rounded border border-neutral-800 p-3" data-block="state">
      <h3 className="flex flex-wrap items-center gap-2 text-sm font-medium">
        <Metric termId="buyback_state" zh>
          Buyback state
        </Metric>
        {state ? (
          <Metric termId={STATE_TERMS[state.assessment.state]} icon={false}>
            <span
              className={`rounded border px-2 py-0.5 text-xs font-semibold tracking-wide ${STATE_STYLES[state.assessment.state]}`}
              data-state={state.assessment.state}
            >
              {STATE_LABELS[state.assessment.state]}
            </span>
          </Metric>
        ) : null}
        <Metric termId="buyback_rule_version" icon={false}>
          <span className="text-xs font-normal text-neutral-500">rule v{ruleVersion}</span>
        </Metric>
      </h3>
      {state === null ? (
        <p className="text-sm text-neutral-400">
          Not evaluated by this date. States are evaluated daily at{" "}
          <Metric termId="buyback_state" icon={false}>
            11:00 SGT
          </Metric>{" "}
          and backfilled for month ends.
        </p>
      ) : (
        <>
          <p className="text-xs text-neutral-400">
            Evaluated as known at{" "}
            <Metric termId="point_in_time" icon={false}>
              {formatSgtEt(state.known_at)}
            </Metric>
            {state.backfilled ? (
              <>
                {" "}
                (
                <Metric termId="backfilled_evaluation" icon={false}>
                  backfilled on {formatSgtEt(state.system_time)}
                </Metric>
                )
              </>
            ) : null}
            {state.assessment.period ? (
              <>
                {" "}
                from the{" "}
                <Metric termId={state.assessment.period.kind === "ttm" ? "trailing_twelve_months" : "reporting_period"} icon={false}>
                  {state.assessment.period.kind === "ttm" ? "four quarters" : "fiscal year"} to {state.assessment.period.period_end}
                </Metric>
              </>
            ) : null}
            . No state triggers a trade; the thresholds are defaults, not validated.
          </p>
          <ol className="space-y-3">
            {LEVELS.map(({ level, label, termId }) => {
              const result = state.assessment.levels.find((r) => r.level === level);
              const conditions = state.assessment.conditions.filter((c) => c.level === level);
              return (
                <li key={level} data-level={level}>
                  <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
                    <Metric termId={termId}>{label}</Metric>
                    {result ? <StatusText status={result.status} /> : null}
                    <span className="text-xs text-neutral-500">{result?.rule}</span>
                    {level === "trade_ready" ? (
                      phase1 ? (
                        <Metric termId="buyback_state_trade_ready" icon={false} className="text-xs text-neutral-500">
                          Unreachable in Phase 1.
                        </Metric>
                      ) : (
                        <Metric termId="standard_position_check" icon={false} className="text-xs text-neutral-500">
                          Needs the standard paper position to pass the risk check.
                        </Metric>
                      )
                    ) : null}
                  </div>
                  <ul>
                    {conditions.map((condition) => (
                      <ConditionRow key={condition.condition_id} condition={condition} />
                    ))}
                  </ul>
                </li>
              );
            })}
          </ol>
          <Score assignment={state} />
          <p className="text-xs text-neutral-500">
            The DCF used{" "}
            <Metric termId="valuation_assumptions" icon={false}>
              {state.assessment.assumption_version !== null
                ? `assumption version ${state.assessment.assumption_version}`
                : "the built-in default assumptions"}
            </Metric>
            ; announcements from extractor{" "}
            <Metric termId="repurchase_announcement" icon={false}>
              {state.assessment.extractor_version}
            </Metric>
            .
          </p>
        </>
      )}
      {history.length > 0 ? <StateHistory history={history} label="State history" /> : null}
    </div>
  );
}
