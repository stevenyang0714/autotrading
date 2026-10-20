import { AsKnownOnForm } from "@/components/AsKnownOnForm";
import { Metric } from "@/components/Metric";
import type { RegimeDimension, RegimeFlag, RegimeInput, RegimePoint, RegimeResponse, StoredRegime } from "@/lib/api";
import { DIMENSIONS, FLAGS, QUADRANTS, STRESS, stateText, toneOf, trimDecimal } from "@/lib/regime";
import { dayIn, formatSgtEt } from "@/lib/time";

const HREF = "/dashboards/market-regime";
const HISTORY_ROWS = ["stress", "growth", "inflation", "policy", "credit", "volatility"] as const;

function inputText(input: RegimeInput): string {
  const value = trimDecimal(input.value);
  return input.vintage
    ? `${input.source} ${input.observation_date}: ${value} (vintage ${input.vintage})`
    : `${input.source} close ${input.observation_date}: ${value}`;
}

function StressBanner({ stored }: { stored: StoredRegime }) {
  const regime = stored.regime;
  const stress = regime.stress ? STRESS[regime.stress] : null;
  return (
    <div
      data-stress={regime.stress ?? "unavailable"}
      className={`space-y-1 rounded border px-4 py-3 ${stress?.className ?? "border-neutral-700 text-neutral-300"}`}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Metric termId="stress_state" className="text-sm">
          Market stress
        </Metric>
        <Metric termId={stress?.termId ?? "stress_state"} icon={false}>
          <span className="text-2xl font-semibold">{stress?.label ?? "UNAVAILABLE"}</span>
        </Metric>
        <Metric termId="stress_state" icon={false} className="text-sm">
          {regime.stress_detail}
        </Metric>
      </div>
      <p className="text-sm">
        <Metric termId="regime_quadrant" icon={false}>
          Growth x inflation: {regime.quadrant ? QUADRANTS[regime.quadrant] : "unavailable"}
        </Metric>
      </p>
      <p className="text-xs opacity-80">
        <Metric termId="point_in_time" icon={false}>
          Assessed for {formatSgtEt(stored.known_at)}
          {stored.backfilled ? " · backfilled (computed later from data known then)" : ""}
        </Metric>
      </p>
    </div>
  );
}

function DimensionCard({ dimension }: { dimension: RegimeDimension }) {
  const meta = DIMENSIONS[dimension.dimension] ?? { label: dimension.dimension, termId: "regime" as const };
  return (
    <li
      data-dimension={dimension.dimension}
      data-state={dimension.state}
      className="space-y-2 rounded border border-neutral-800 px-3 py-2 text-sm"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Metric termId={meta.termId}>{meta.label}</Metric>
        <span className={`rounded px-1.5 py-0.5 text-xs text-neutral-100 ${toneOf(dimension.state)}`}>
          <Metric termId={meta.termId} icon={false}>
            {stateText(dimension.state)}
            {dimension.trend ? `, ${dimension.trend}` : ""}
          </Metric>
        </span>
      </div>
      <p className="text-xs text-neutral-400">
        <Metric termId={meta.termId} icon={false}>
          {dimension.detail}
        </Metric>
      </p>
      <ul className="space-y-1" aria-label={`${meta.label} readings`}>
        {dimension.readings.map((reading) => (
          <li key={reading.reading_id} data-reading={reading.reading_id}>
            <Metric termId={meta.termId} icon={false} className="tabular-nums">
              {reading.label}:{" "}
              {reading.value !== null ? `${trimDecimal(reading.value)} ${reading.unit}` : "unavailable"}
              {reading.detail ? ` (${reading.detail})` : ""}
            </Metric>
            {reading.inputs.length > 0 ? (
              <span className="block text-xs text-neutral-500">
                <Metric termId="point_in_time" icon={false}>
                  {reading.inputs.map(inputText).join("; ")}
                </Metric>
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </li>
  );
}

function FlagRow({ flag }: { flag: RegimeFlag }) {
  const termId = FLAGS[flag.flag_id] ?? "stress_state";
  const tone =
    flag.status === "on" ? "text-amber-300" : flag.status === "off" ? "text-neutral-300" : "text-neutral-500";
  return (
    <li
      data-flag={flag.flag_id}
      data-status={flag.status}
      className="flex flex-wrap items-baseline justify-between gap-x-3 border-b border-neutral-900 py-1 text-sm"
    >
      <Metric termId={termId} icon={false}>
        <span className={tone}>{flag.label}</span>
      </Metric>
      <Metric termId={termId} icon={false} className="text-xs text-neutral-400">
        {flag.status === "unavailable" ? "no data then" : flag.status}
        {flag.value !== null ? ` · ${trimDecimal(flag.value)}` : ""} · {flag.threshold}
      </Metric>
    </li>
  );
}

/** The New York day of an assessment: month ends are the end of the month's last day there. */
function day(point: RegimePoint): string {
  return dayIn(point.known_at, "America/New_York");
}

/** One cell per calendar month (New York; the month's last assessment), oldest first. */
function months(history: RegimePoint[]): RegimePoint[] {
  const byMonth = new Map<string, RegimePoint>();
  for (const point of history) byMonth.set(day(point).slice(0, 7), point);
  return [...byMonth.values()];
}

function History({ history }: { history: RegimePoint[] }) {
  const cells = months(history);
  if (cells.length === 0) return null;
  const years = [...new Set(cells.map((c) => day(c).slice(0, 4)))];
  return (
    <div className="space-y-2" data-block="history">
      <h2 className="text-lg font-medium">
        <Metric termId="regime">History</Metric>
      </h2>
      <div className="overflow-x-auto rounded border border-neutral-800 p-3">
        <table className="text-xs" aria-label="Regime history">
          <tbody>
            {HISTORY_ROWS.map((row) => {
              const term = row === "stress" ? "stress_state" : DIMENSIONS[row].termId;
              return (
                <tr key={row} data-row={row}>
                  <th scope="row" className="whitespace-nowrap pr-2 text-left font-normal text-neutral-400">
                    <Metric termId={term} icon={false}>
                      {row === "stress" ? "Stress" : DIMENSIONS[row].label}
                    </Metric>
                  </th>
                  {cells.map((cell) => {
                    const state = row === "stress" ? cell.stress : cell.states[row];
                    return (
                      <td key={cell.known_at} className="p-px">
                        <span
                          title={`${day(cell)}: ${state ?? "unavailable"}${cell.backfilled ? " (backfilled)" : ""}`}
                          data-state={state ?? "unavailable"}
                          className={`block h-3 w-2 ${toneOf(state)} ${cell.backfilled ? "opacity-80" : ""}`}
                        />
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-neutral-500">
        <Metric termId="regime" icon={false}>
          One cell per month at its highest stress, {years[0]} to {years[years.length - 1]}; hover a cell for its date
          and state. Green is calm or easy, amber to red more stress or tighter conditions.
        </Metric>
      </p>
    </div>
  );
}

/**
 * Market Regime (M2.1, ADR-029): the stress state, the five macro dimensions with every input
 * and its vintage, the nine stress flags and the monthly history since 2016, as known on the
 * chosen date. Deterministic rules on data known then; not a forecast.
 */
export function MarketRegimeView({
  data,
  knownOn,
  invalidKnownOn = false,
}: {
  data: RegimeResponse;
  knownOn?: string;
  invalidKnownOn?: boolean;
}) {
  const current = data.current;
  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          <Metric termId="dashboard_market_regime" zh>
            Market Regime
          </Metric>
        </h1>
        <p className="text-sm text-neutral-400">
          Growth, inflation, policy and liquidity, credit and volatility, and how many stress signals are on together,
          each from the data known at the date.
        </p>
        <p role="note" className="text-xs text-neutral-500">
          <Metric termId="regime" icon={false}>
            {data.detail}
          </Metric>
        </p>
        <AsKnownOnForm href={HREF} knownOn={knownOn} invalid={invalidKnownOn} />
        <p className="text-sm text-neutral-400">
          Showing what was known by{" "}
          <Metric termId="point_in_time" icon={false}>
            {formatSgtEt(data.known_at)}
          </Metric>{" "}
          under{" "}
          <Metric termId="regime_rule_set" icon={false}>
            regime rules {data.rule_version}
          </Metric>
        </p>
      </header>

      {current === null ? (
        <p className="text-sm text-neutral-400">
          <Metric termId="regime" icon={false}>
            No regime was assessed by this date.
          </Metric>
        </p>
      ) : (
        <>
          <StressBanner stored={current} />
          <div className="space-y-2">
            <h2 className="text-lg font-medium">
              <Metric termId="regime" zh>
                Dimensions
              </Metric>
            </h2>
            <ul className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3" aria-label="Dimensions">
              {current.regime.dimensions.map((dimension) => (
                <DimensionCard key={dimension.dimension} dimension={dimension} />
              ))}
            </ul>
          </div>
          <div className="space-y-2">
            <h2 className="text-lg font-medium">
              <Metric termId="stress_state" zh>
                Stress flags
              </Metric>
            </h2>
            <ul aria-label="Stress flags">
              {current.regime.flags.map((flag) => (
                <FlagRow key={flag.flag_id} flag={flag} />
              ))}
            </ul>
          </div>
        </>
      )}
      <History history={data.history} />
    </section>
  );
}
