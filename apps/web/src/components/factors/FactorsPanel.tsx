import { Metric } from "@/components/Metric";
import type { FactorInput, FactorMeasure, InstrumentFactors, InstrumentFactorsResult } from "@/lib/api";
import { GROUPS, formatMeasure, groupLabel, meta, ordinal, windowText } from "@/lib/factors";
import { formatSgtEt } from "@/lib/time";

function trim(value: string): string {
  return value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
}

function inputText(input: FactorInput): string {
  const day = input.start && input.end && input.start !== input.end ? `${input.start} to ${input.end}` : input.end;
  const value = input.value !== null ? trim(input.value) : "unavailable";
  const sources = input.sources.length > 0 ? ` (${input.sources.join(", ")})` : "";
  return `${input.name}${day ? ` ${day}` : ""}: ${value}${input.note ? `, ${input.note}` : ""}${sources}`;
}

function MeasureItem({ measure, benchmark }: { measure: FactorMeasure; benchmark: string }) {
  const info = meta(measure.measure_id, benchmark);
  const window = windowText(measure);
  return (
    <li
      data-measure={measure.measure_id}
      data-reason={measure.reason ?? "value"}
      className="space-y-0.5 border-b border-neutral-900 py-1.5 text-sm"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <Metric termId={info.termId}>{info.label}</Metric>
        <Metric termId={info.termId} icon={false} className="tabular-nums font-medium">
          {measure.value !== null ? (
            formatMeasure(measure.value, measure.unit, measure.group)
          ) : (
            <span className="text-neutral-500">{measure.reason === "not_meaningful" ? "n/m" : "n/a"}</span>
          )}
        </Metric>
      </div>
      {measure.value !== null && measure.percentile !== null ? (
        <p className="text-xs text-neutral-400">
          <Metric termId="factor_percentile" icon={false}>
            {ordinal(measure.percentile)} of {measure.observations} month ends since {measure.since}
            {measure.median !== null ? ` · median ${formatMeasure(measure.median, measure.unit, measure.group)}` : ""}
          </Metric>
        </p>
      ) : null}
      <p className="text-xs text-neutral-500">
        <Metric termId={info.termId} icon={false}>
          {measure.detail}
          {window ? ` · ${window}` : ""}
        </Metric>
      </p>
      {measure.inputs.length > 0 ? (
        <p className="text-xs text-neutral-500">
          <Metric termId="total_return" icon={false}>
            {measure.inputs.map(inputText).join("; ")}
          </Metric>
        </p>
      ) : null}
      {measure.notes.map((note) => (
        <p key={note} className="text-xs text-amber-300" data-note="">
          <Metric termId="dividend_gap" icon={false}>
            {note}
          </Metric>
        </p>
      ))}
    </li>
  );
}

function Snapshot({ data }: { data: InstrumentFactors }) {
  const price = data.price;
  const full = data.fundamentals;
  if (price === null) {
    return (
      <p className="text-sm text-neutral-400">
        <Metric termId="factor_snapshot" icon={false}>
          No factor snapshot was stored by this date.
        </Metric>
      </p>
    );
  }
  return (
    <div className="space-y-4">
      <p className="text-xs text-neutral-400">
        <Metric termId="point_in_time" icon={false}>
          Snapshot for {formatSgtEt(price.known_at)} · last close {price.last_close ?? "none"}
          {price.backfilled ? " · backfilled (computed later from data known then)" : ""}
        </Metric>
        {full && full.known_at !== price.known_at ? (
          <>
            {" · "}
            <Metric termId="point_in_time" icon={false}>
              value and quality from {formatSgtEt(full.known_at)}
            </Metric>
          </>
        ) : null}
        {" · "}
        <Metric termId="factor_definition_set" icon={false}>
          factor definitions {data.definition_version}
        </Metric>
      </p>
      <div className="grid grid-cols-1 gap-x-6 gap-y-4 lg:grid-cols-2">
        {GROUPS.map(({ group, label, termId }) => {
          const measures = data.measures.filter((m) => m.group === group);
          if (measures.length === 0) return null;
          return (
            <div key={group} data-group={group}>
              <h3 className="text-sm font-medium text-neutral-300">
                <Metric termId={termId} icon={false}>
                  {groupLabel(label, data.benchmark)}
                </Metric>
              </h3>
              <ul aria-label={groupLabel(label, data.benchmark)}>
                {measures.map((measure) => (
                  <MeasureItem key={measure.measure_id} measure={measure} benchmark={data.benchmark} />
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Trend and factors on the instrument page (M2.2, ADR-030): the stored snapshot as known on the
 * chosen date, each measure with its percentile in the instrument's own history, its window,
 * inputs and any dividend that may be missing. Time-series only; not a forecast or a signal.
 */
export function FactorsPanel({ result }: { result: InstrumentFactorsResult }) {
  if (result.status === "not_found") return null;
  return (
    <section id="factors" className="space-y-3" data-block="factors" aria-labelledby="factors-title">
      <h2 id="factors-title" className="text-lg font-medium">
        <Metric termId="factor_snapshot" zh>
          Trend and factors
        </Metric>
      </h2>
      {result.status === "unavailable" ? (
        <p role="alert" className="text-sm text-neutral-400">
          Data unavailable: the factor snapshot could not be loaded.
        </p>
      ) : (
        <>
          <Snapshot data={result.data} />
          <p role="note" className="text-xs text-neutral-500">
            <Metric termId="factor_percentile" icon={false}>
              {result.data.detail}
            </Metric>
          </p>
        </>
      )}
    </section>
  );
}
