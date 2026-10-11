import { Metric } from "@/components/Metric";
import type { EarningsActual, EarningsEvent, EarningsResult } from "@/lib/api";
import {
  ACTUAL_LABELS,
  GUIDANCE_LABELS,
  TIMING_LABELS,
  formatDelta,
  formatRange,
  formatValue,
} from "@/lib/earnings";
import { formatChange } from "@/lib/format";
import { formatSgtEt } from "@/lib/time";

const SHOWN = 4; // events shown open; earlier ones fold away

function Consensus() {
  return (
    <p className="text-xs text-neutral-400" data-consensus="">
      <Metric termId="consensus_estimate" icon={false}>
        Consensus estimate: Data unavailable
      </Metric>{" "}
      ·{" "}
      <Metric termId="earnings_surprise" icon={false}>
        Surprise: Data unavailable
      </Metric>{" "}
      (no consensus provider)
    </p>
  );
}

function ActualRow({ actual }: { actual: EarningsActual }) {
  const meta = ACTUAL_LABELS[actual.metric] ?? { label: actual.metric, termId: "earnings_actuals" as const };
  const cells = [actual.current, actual.prior_quarter, actual.year_ago];
  return (
    <tr data-row={actual.metric} className="border-b border-neutral-900">
      <th scope="row" className="py-1 pr-3 text-left font-normal">
        <Metric termId={meta.termId} icon={false}>
          {meta.label}
        </Metric>
      </th>
      {cells.map((cell, i) => (
        <td key={i} className="px-2 py-1 text-right tabular-nums" title={cell.detail ?? undefined}>
          <Metric termId={meta.termId} icon={false}>
            {cell.value !== null ? (
              formatValue(cell.value, actual.unit)
            ) : (
              <span className="text-neutral-500">n/a</span>
            )}
          </Metric>
        </td>
      ))}
      {(
        [
          ["change_qoq", actual.change_qoq],
          ["change_yoy", actual.change_yoy],
        ] as const
      ).map(([termId, value]) => (
        <td key={termId} className="px-2 py-1 text-right tabular-nums" data-change={termId}>
          <Metric termId={termId} icon={false}>
            {value !== null ? (
              formatDelta(value, actual.change_unit === "percent" ? "percent" : "points")
            ) : (
              <span className="text-neutral-500">n/a</span>
            )}
          </Metric>
        </td>
      ))}
    </tr>
  );
}

function Actuals({ event }: { event: EarningsEvent }) {
  if (!event.report) {
    return (
      <p className="text-sm text-neutral-400">
        <Metric termId="earnings_report" icon={false}>
          No actuals yet: {event.report_detail}
        </Metric>
      </p>
    );
  }
  return (
    <div className="space-y-1" data-block="actuals">
      <p className="text-xs text-neutral-400">
        <Metric termId="earnings_actuals" icon={false}>
          Quarter to {event.report.period_end}, from the
        </Metric>{" "}
        <a href={event.report.url} target="_blank" rel="noreferrer" data-identifier="" className="underline-offset-2 hover:underline">
          {event.report.form} {event.report.accession}
        </a>{" "}
        <Metric termId="earnings_report" icon={false}>
          (public {formatSgtEt(event.report.published_at)})
        </Metric>
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[34rem] text-sm" aria-label="Quarter actuals">
          <thead>
            <tr className="border-b border-neutral-800 text-xs text-neutral-400">
              <th scope="col" className="py-1 pr-3 text-left font-normal">
                <Metric termId="earnings_actuals" icon={false}>
                  Metric
                </Metric>
              </th>
              {["This quarter", "Quarter before", "A year earlier"].map((label) => (
                <th key={label} scope="col" className="px-2 py-1 text-right font-normal">
                  <Metric termId="earnings_actuals" icon={false}>
                    {label}
                  </Metric>
                </th>
              ))}
              <th scope="col" className="px-2 py-1 text-right font-normal">
                <Metric termId="change_qoq" icon={false}>
                  vs quarter before
                </Metric>
              </th>
              <th scope="col" className="px-2 py-1 text-right font-normal">
                <Metric termId="change_yoy" icon={false}>
                  vs a year earlier
                </Metric>
              </th>
            </tr>
          </thead>
          <tbody>
            {event.actuals.map((actual) => (
              <ActualRow key={actual.metric} actual={actual} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Guidance({ event }: { event: EarningsEvent }) {
  if (event.guidance_status !== "extracted") {
    return (
      <p className="text-sm text-neutral-400" data-guidance={event.guidance_status}>
        <Metric termId="guidance_statement" icon={false}>
          {event.guidance_status === "none"
            ? "Guidance not extracted: no numeric revenue, EPS or margin outlook in the release."
            : "The release has not been read for guidance yet."}
        </Metric>
      </p>
    );
  }
  return (
    <ul className="space-y-1 text-sm" aria-label="Guidance" data-guidance="extracted">
      {event.guidance.map((g) => (
        <li key={`${g.metric}-${g.low}-${g.high}-${g.adjusted}`} className="space-y-0.5">
          <Metric termId="guidance_statement" icon={false}>
            <span className="text-neutral-200">
              {GUIDANCE_LABELS[g.metric] ?? g.metric}
              {g.adjusted ? " (adjusted)" : ""} {formatRange(g.low, g.high, g.unit)}
            </span>{" "}
            <span className="text-xs text-neutral-500">{g.period}</span>
          </Metric>
          <span className="block text-xs text-neutral-400">
            <q data-quoted="" className="text-neutral-300">
              {g.sentence}
            </q>{" "}
            <a href={g.url} target="_blank" rel="noreferrer" data-identifier="" className="underline-offset-2 hover:underline">
              {g.document_type}
            </a>
          </span>
        </li>
      ))}
    </ul>
  );
}

function Reaction({ event }: { event: EarningsEvent }) {
  const reaction = event.reaction;
  if (reaction.detail) {
    return (
      <p className="text-sm text-neutral-400">
        <Metric termId="earnings_reaction" icon={false}>
          Reaction: {reaction.detail}
        </Metric>
      </p>
    );
  }
  return (
    <div className="space-y-1" data-block="reaction">
      <p className="text-xs text-neutral-400">
        <Metric termId="earnings_reaction" icon={false}>
          From the close of {reaction.base_day} against {reaction.benchmark}
        </Metric>
        {" · "}
        <Metric termId="earnings_volume_ratio" icon={false}>
          {reaction.volume_ratio !== null
            ? `day-0 volume ${reaction.volume_ratio}x the 20-session average`
            : `volume: ${reaction.volume_detail}`}
        </Metric>
      </p>
      <table className="text-sm" aria-label="Reaction">
        <tbody>
          {reaction.windows.map((w) => (
            <tr key={w.label} data-window={w.label} className="border-b border-neutral-900">
              <th scope="row" className="py-1 pr-3 text-left font-normal">
                <Metric termId="earnings_reaction" icon={false}>
                  {w.label}
                  {w.day ? ` (${w.day})` : ""}
                </Metric>
              </th>
              <td className="px-2 py-1 text-right tabular-nums" title={w.detail ?? undefined}>
                <Metric termId="earnings_reaction" icon={false}>
                  {w.relative !== null ? (
                    <>
                      <span className={Number(w.relative) >= 0 ? "text-emerald-300" : "text-rose-300"}>
                        {formatDelta(w.relative, "points")}
                      </span>{" "}
                      <span className="text-xs text-neutral-500">
                        stock {formatChange(w.stock_return ?? "0")}, {reaction.benchmark}{" "}
                        {formatChange(w.benchmark_return ?? "0")}
                      </span>
                    </>
                  ) : (
                    <span className="text-neutral-500">{w.detail ?? "n/a"}</span>
                  )}
                </Metric>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EventCard({ event }: { event: EarningsEvent }) {
  return (
    <div className="space-y-3 pt-2">
      <Actuals event={event} />
      <div className="space-y-1">
        <h4 className="text-sm font-medium">
          <Metric termId="guidance_statement">Guidance</Metric>
        </h4>
        <Guidance event={event} />
      </div>
      <Reaction event={event} />
      <Consensus />
    </div>
  );
}

function Summary({ event }: { event: EarningsEvent }) {
  const revenue = event.actuals.find((a) => a.metric === "revenue");
  const day0 = event.reaction.windows.find((w) => w.sessions_after === 0);
  return (
    <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <Metric termId="earnings_event" icon={false}>
        <span className="font-medium text-neutral-100">{formatSgtEt(event.accepted_at)}</span>
      </Metric>
      <Metric termId="earnings_timing" icon={false}>
        <span className="text-xs text-neutral-400">{TIMING_LABELS[event.timing]}</span>
      </Metric>
      <a href={event.url} target="_blank" rel="noreferrer" data-identifier="" className="text-xs underline-offset-2 hover:underline">
        {event.form} {event.accession}
      </a>
      {revenue?.change_yoy ? (
        <Metric termId="change_yoy" icon={false}>
          <span className="text-xs">revenue {formatChange(revenue.change_yoy)} a year on</span>
        </Metric>
      ) : null}
      {day0?.relative ? (
        <Metric termId="earnings_reaction" icon={false}>
          <span className="text-xs">day 0 {formatDelta(day0.relative, "points")} vs SPY</span>
        </Metric>
      ) : null}
    </span>
  );
}

/**
 * Earnings section of the instrument page (M1.5, ADR-026): each results release since 2021 at
 * its EDGAR acceptance time, the quarter's actuals once the 10-Q/10-K is public, the company's
 * own numeric guidance, and the price reaction against SPY. Consensus has no provider and shows
 * Data unavailable (errata E6).
 */
export function EarningsView({ result }: { result: EarningsResult }) {
  return (
    <section id="earnings" aria-labelledby="earnings-heading" className="space-y-3">
      <h2 id="earnings-heading" className="text-lg font-medium">
        <Metric termId="earnings_event" zh>
          Earnings
        </Metric>
      </h2>
      {result.status !== "ok" ? (
        <p role="alert" className="text-sm text-neutral-400">
          Data unavailable: the API could not be reached.
        </p>
      ) : result.data.events.length === 0 ? (
        <p className="text-sm text-neutral-400">
          <Metric termId="earnings_event" icon={false}>
            No results release (8-K Item 2.02) since 2021 is public by this date.
          </Metric>
        </p>
      ) : (
        <>
          <p className="text-sm text-neutral-400">
            Results releases, each at its EDGAR acceptance time, as known at{" "}
            <Metric termId="point_in_time" icon={false}>
              {formatSgtEt(result.data.known_at)}
            </Metric>
            . Actuals come from the <span data-identifier="">10-Q</span> or{" "}
            <span data-identifier="">10-K</span> that follows; there is no consensus to compare with.
          </p>
          <ol className="space-y-2" aria-label="Earnings events">
            {result.data.events.map((event, i) => (
              <li key={event.accession} data-event={event.accession} className="rounded border border-neutral-800 px-3 py-2">
                <details open={i < 1}>
                  <summary className="cursor-pointer select-none">
                    <Summary event={event} />
                  </summary>
                  <EventCard event={event} />
                </details>
              </li>
            )).slice(0, SHOWN)}
          </ol>
          {result.data.events.length > SHOWN ? (
            <details className="text-sm">
              <summary className="cursor-pointer select-none text-xs text-neutral-400">
                <Metric termId="earnings_event" icon={false}>
                  {result.data.events.length - SHOWN} earlier releases
                </Metric>
              </summary>
              <ol className="mt-2 space-y-2" aria-label="Earlier earnings events">
                {result.data.events.slice(SHOWN).map((event) => (
                  <li key={event.accession} data-event={event.accession} className="rounded border border-neutral-900 px-3 py-2">
                    <details>
                      <summary className="cursor-pointer select-none">
                        <Summary event={event} />
                      </summary>
                      <EventCard event={event} />
                    </details>
                  </li>
                ))}
              </ol>
            </details>
          ) : null}
        </>
      )}
    </section>
  );
}
