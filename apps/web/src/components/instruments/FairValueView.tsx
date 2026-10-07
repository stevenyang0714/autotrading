import Link from "next/link";

import { Metric } from "@/components/Metric";
import { AssumptionsForm, type SaveAction } from "@/components/instruments/AssumptionsForm";
import { ValuationInputItem } from "@/components/instruments/ValuationView";
import { type CompleteTermId, GLOSSARY } from "@/generated/glossary";
import type {
  AssumptionList,
  AssumptionParameters,
  FairValue,
  FairValueResult,
  RelativeValuation,
} from "@/lib/api";
import { exactReported, formatReported } from "@/lib/format";
import { formatSgtEt } from "@/lib/time";

const SCENARIO_LABELS = { bear: "Bear", base: "Base", bull: "Bull" } as const;

function percent(value: string): string {
  return `${Number(value).toFixed(2)}%`;
}

/** A rate as entered: "5%", "2.5%", "-1.25%". */
function rate(value: string): string {
  return `${Number(value)}%`;
}

function multiple(row: RelativeValuation, value: string): string {
  return row.unit === "percent" ? percent(value) : `${Number(value).toFixed(2)}x`;
}

function term(id: string): CompleteTermId | null {
  return id in GLOSSARY ? (id as CompleteTermId) : null;
}

function versionLabel(version: number | null): string {
  return version === null ? "default" : `v${version}`;
}

function Unavailable({ termId, detail }: { termId: CompleteTermId; detail?: string | null }) {
  return (
    <Metric termId={termId} icon={false}>
      <span className="text-neutral-400">Data unavailable{detail ? `: ${detail}` : ""}</span>
    </Metric>
  );
}

function Parameters({ parameters }: { parameters: AssumptionParameters }) {
  const rows: [CompleteTermId, string, string][] = [
    ["equity_risk_premium", "Equity risk premium", rate(parameters.equity_risk_premium)],
    ["terminal_growth", "Terminal growth", rate(parameters.terminal_growth)],
    [
      "scenario_range",
      "Growth, years 1-5",
      `bear ${rate(parameters.growth_bear)} · base ${rate(parameters.growth_base)} · bull ${rate(parameters.growth_bull)}`,
    ],
    ["owner_fcf", "Stock-based compensation", parameters.subtract_sbc ? "subtracted" : "left in"],
  ];
  return (
    <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2" aria-label="Assumption parameters">
      {rows.map(([termId, label, value]) => (
        <div key={label} className="flex flex-wrap gap-x-2">
          <dt className="text-neutral-400">
            <Metric termId={termId} icon={false}>
              {label}
            </Metric>
          </dt>
          <dd>
            <Metric termId={termId} icon={false}>
              {value}
            </Metric>
          </dd>
        </div>
      ))}
    </dl>
  );
}

function VersionPicker({
  ticker,
  knownOn,
  current,
  list,
}: {
  ticker: string;
  knownOn?: string;
  current: number | null;
  list: AssumptionList;
}) {
  return (
    <form method="get" action={`/instruments/${ticker}`} className="flex flex-wrap items-center gap-2">
      {knownOn ? <input type="hidden" name="known_on" value={knownOn} /> : null}
      <label htmlFor="assumptions-version">
        <Metric termId="valuation_assumptions" icon={false}>
          Version
        </Metric>
      </label>
      <select
        id="assumptions-version"
        name="assumptions"
        defaultValue={current === null ? "default" : String(current)}
        data-identifier=""
        className="rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700"
      >
        {list.versions.map((version) => (
          <option key={version.version} value={String(version.version)}>
            {versionLabel(version.version)}
            {version.created_at ? ` · ${version.created_at.slice(0, 10)}` : ""}
          </option>
        ))}
        <option value="default">default (not reviewed)</option>
      </select>
      <button
        type="submit"
        className="rounded border border-neutral-300 px-3 py-1 hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
      >
        Use
      </button>
    </form>
  );
}

function Assumptions({
  data,
  list,
  ticker,
  knownOn,
}: {
  data: FairValue;
  list: AssumptionList | null;
  ticker: string;
  knownOn?: string;
}) {
  const chosen = data.assumptions;
  return (
    <div
      className="space-y-2 rounded border border-neutral-800 p-3 text-sm"
      data-assumptions={versionLabel(chosen.version)}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Metric termId="valuation_assumptions">Assumptions</Metric>
        <span className="font-medium" data-identifier="" data-assumption-version="">
          {versionLabel(chosen.version)}
        </span>
        {chosen.created_at ? (
          <span className="text-neutral-400">
            saved{" "}
            <Metric termId="valuation_assumptions" icon={false}>
              {formatSgtEt(chosen.created_at)}
            </Metric>
          </span>
        ) : null}
        <span className="text-neutral-400" data-quoted="">
          “{chosen.reason}”
        </span>
        {list ? <VersionPicker ticker={ticker} knownOn={knownOn} current={chosen.version} list={list} /> : null}
      </div>
      <Parameters parameters={chosen.parameters} />
    </div>
  );
}

function DiscountRate({ data }: { data: FairValue }) {
  const { discount_rate: discount, terminal_growth: terminal } = data.dcf;
  const treasury = discount.risk_free;
  return (
    <p className="text-sm text-neutral-400" data-discount-rate="">
      <Metric termId="discount_rate">Discount rate</Metric>{" "}
      {discount.value !== null && treasury ? (
        <>
          <Metric termId="discount_rate" icon={false}>
            <span className="text-neutral-100">{rate(discount.value)}</span>
          </Metric>{" "}
          ={" "}
          <Metric termId="macro_treasury_10y" icon={false}>
            10-year Treasury {rate(treasury.value)} ({treasury.observation_date})
          </Metric>{" "}
          +{" "}
          <Metric termId="equity_risk_premium" icon={false}>
            equity risk premium {rate(discount.equity_risk_premium)}
          </Metric>
        </>
      ) : (
        <Unavailable termId="discount_rate" detail={treasury ? null : "no 10-year Treasury yield known then"} />
      )}
      {" · "}
      <Metric termId="terminal_growth" icon={false}>
        terminal growth {rate(terminal)}
      </Metric>
    </p>
  );
}

function Scenarios({ data }: { data: FairValue }) {
  const dcf = data.dcf;
  if (dcf.status !== "ok") {
    return (
      <p className="rounded border border-neutral-800 p-3 text-sm" data-dcf-status={dcf.status}>
        <Metric termId="fair_value_dcf" icon={false}>
          <span className="text-neutral-400">
            {dcf.status === "not_meaningful" ? "n/m" : "Data unavailable"}
            {dcf.detail ? `: ${dcf.detail}` : ""}
          </span>
        </Metric>
      </p>
    );
  }
  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-3" aria-label="Scenarios" data-dcf-status="ok">
      {dcf.scenarios.map((scenario) => (
        <li
          key={scenario.scenario}
          data-scenario={scenario.scenario}
          className={`space-y-1 rounded border p-3 text-sm ${
            scenario.scenario === "base" ? "border-neutral-500" : "border-neutral-800"
          }`}
        >
          <Metric termId="scenario_range" icon={false}>
            {SCENARIO_LABELS[scenario.scenario]}: {rate(scenario.growth)} a year, years 1-5
          </Metric>
          <div>
            <Metric termId="fair_value_dcf" icon={false}>
              <span className="text-xl tabular-nums" title={exactReported(scenario.per_share, "USD/shares")}>
                {formatReported(scenario.per_share, "USD/shares")}
              </span>
            </Metric>
          </div>
          <p className="text-xs text-neutral-500">
            <Metric termId="enterprise_value" icon={false}>
              EV {formatReported(scenario.enterprise_value, "USD")}, terminal value{" "}
              {formatReported(scenario.terminal_value, "USD")}
            </Metric>
          </p>
        </li>
      ))}
    </ul>
  );
}

function Comparison({ data }: { data: FairValue }) {
  const { price, implied_upside: upside, margin_of_safety: margin, detail } = data.comparison;
  const reverse = data.reverse_dcf;
  // Say why only when the DCF and the price are both there; otherwise the reason is shown once
  // above (the DCF line or the price card).
  const explain = data.dcf.status === "ok" && price.status === "ok";
  const cell = "space-y-1 rounded border border-neutral-800 p-3 text-sm";
  return (
    <ul
      className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4"
      aria-label="Price comparison"
      data-comparison-price={price.status}
    >
      <li className={cell} data-comparison="price">
        <Metric termId="valuation_price" />
        <div>
          {price.status === "ok" && price.close !== null ? (
            <Metric termId="valuation_price" icon={false}>
              <span className="text-xl tabular-nums">{formatReported(price.close, "USD/shares")}</span>{" "}
              <span className="text-xs text-neutral-500">{price.day} close</span>
            </Metric>
          ) : (
            <Unavailable termId="valuation_price" detail={price.detail} />
          )}
        </div>
      </li>
      <li className={cell} data-comparison="implied_upside">
        <Metric termId="implied_upside" />
        <div>
          {upside !== null ? (
            <Metric termId="implied_upside" icon={false}>
              <span className="text-xl tabular-nums">{percent(upside)}</span>
            </Metric>
          ) : (
            <Unavailable termId="implied_upside" />
          )}
        </div>
      </li>
      <li className={cell} data-comparison="margin_of_safety">
        <Metric termId="margin_of_safety" />
        <div>
          {margin !== null ? (
            <Metric termId="margin_of_safety" icon={false}>
              <span className="text-xl tabular-nums">{percent(margin)}</span>
            </Metric>
          ) : (
            <Unavailable termId="margin_of_safety" />
          )}
        </div>
        {detail && explain ? (
          <p className="text-xs text-neutral-500">
            <Metric termId="margin_of_safety" icon={false}>
              {detail}
            </Metric>
          </p>
        ) : null}
      </li>
      <li className={cell} data-comparison="reverse_dcf_growth">
        <Metric termId="reverse_dcf_growth" />
        <div>
          {reverse.growth !== null ? (
            <Metric termId="reverse_dcf_growth" icon={false}>
              <span className="text-xl tabular-nums">{percent(reverse.growth)}</span>{" "}
              <span className="text-xs text-neutral-500">a year, years 1-5</span>
            </Metric>
          ) : (
            <Unavailable termId="reverse_dcf_growth" detail={explain ? reverse.detail : null} />
          )}
        </div>
      </li>
    </ul>
  );
}

function Relative({ rows }: { rows: RelativeValuation[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[32rem] text-sm" aria-label="Relative valuation">
        <caption className="mb-1 text-left text-neutral-400">
          <Metric termId="multiple_percentile">Against its own history</Metric>
        </caption>
        <thead>
          <tr className="border-b border-neutral-800 text-left text-neutral-400">
            <th className="py-1 pr-3 font-normal">Multiple</th>
            <th className="py-1 pr-3 text-right font-normal">Now</th>
            <th className="py-1 pr-3 text-right font-normal">Median</th>
            <th className="py-1 pr-3 text-right font-normal">
              <Metric termId="multiple_percentile" icon={false}>
                Percentile
              </Metric>
            </th>
            <th className="py-1 text-right font-normal">Month ends</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const id = term(row.metric_id) ?? "multiple_percentile";
            return (
              <tr key={row.metric_id} data-relative={row.metric_id} className="border-b border-neutral-900">
                <th scope="row" className="py-1 pr-3 text-left font-normal">
                  <Metric termId={id} icon={false} />
                </th>
                <td className="py-1 pr-3 text-right tabular-nums">
                  {row.current !== null ? (
                    <Metric termId={id} icon={false}>
                      {multiple(row, row.current)}
                    </Metric>
                  ) : (
                    <Metric termId={id} icon={false}>
                      <span className="text-neutral-500">n/a</span>
                    </Metric>
                  )}
                </td>
                <td className="py-1 pr-3 text-right tabular-nums">
                  {row.median !== null ? (
                    <Metric termId="multiple_percentile" icon={false}>
                      {multiple(row, row.median)}
                    </Metric>
                  ) : (
                    <span className="text-neutral-500">-</span>
                  )}
                </td>
                <td className="py-1 pr-3 text-right tabular-nums">
                  {row.percentile !== null ? (
                    <Metric termId="multiple_percentile" icon={false}>
                      {Number(row.percentile)}
                    </Metric>
                  ) : (
                    <span className="text-neutral-500">-</span>
                  )}
                </td>
                <td className="py-1 text-right tabular-nums text-neutral-400">
                  <Metric termId="multiple_percentile" icon={false}>
                    {row.observations}
                    {row.since ? ` since ${row.since.slice(0, 7)}` : ""}
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

function DataDates({ data }: { data: FairValue }) {
  const { latest_filing: filing, price_day: priceDay, risk_free_date: riskFree } = data.data_as_of;
  return (
    <p className="text-xs text-neutral-500" data-model-dates="">
      Model date{" "}
      <Metric termId="point_in_time" icon={false}>
        {formatSgtEt(data.known_at)}
      </Metric>
      {" · "}data as of: latest filing{" "}
      {filing ? (
        <a href={filing.url} target="_blank" rel="noreferrer" data-identifier="" className="underline-offset-2 hover:underline">
          {filing.form ? `${filing.form} ` : ""}
          {filing.accession}
        </a>
      ) : (
        "none"
      )}
      {priceDay ? (
        <>
          {", "}
          <Metric termId="valuation_price" icon={false}>
            close {priceDay}
          </Metric>
        </>
      ) : null}
      {riskFree ? (
        <>
          {", "}
          <Metric termId="macro_treasury_10y" icon={false}>
            10-year Treasury {riskFree}
          </Metric>
        </>
      ) : null}
    </p>
  );
}

/**
 * Fair value block of the instrument page (M1.3a, ADR-023): DCF scenario range, price
 * comparison, reverse DCF and relative valuation as known at the page's As known on time, with
 * the assumption version used, which can be switched or edited (a save is a new version).
 * Model output, not fact.
 */
export function FairValueView({
  result,
  assumptions,
  ticker,
  knownOn,
  action,
}: {
  result: FairValueResult;
  assumptions: AssumptionList | null;
  ticker: string;
  knownOn?: string;
  action?: SaveAction;
}) {
  return (
    <section id="fair-value" aria-labelledby="fair-value-heading" className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="fair-value-heading" className="text-lg font-medium">
          <Metric termId="fair_value_dcf" zh>
            Fair value
          </Metric>
        </h2>
        <span
          className="rounded border border-amber-600/70 bg-amber-950/40 px-2 py-0.5 text-xs text-amber-200"
          data-model-output=""
        >
          <Metric termId="model_output" zh>
            Model output, not fact
          </Metric>
        </span>
      </div>
      {result.status === "unavailable" ? (
        <p role="alert" className="text-sm text-neutral-400">
          Data unavailable: the API could not be reached.
        </p>
      ) : result.status === "not_found" ? (
        <p role="alert" className="text-sm text-neutral-400">
          <Metric termId="valuation_assumptions" icon={false}>
            {result.detail}.
          </Metric>{" "}
          <Link
            href={`/instruments/${ticker}${knownOn ? `?known_on=${knownOn}` : ""}#fair-value`}
            className="underline underline-offset-2"
          >
            Show the latest version
          </Link>
        </p>
      ) : (
        <>
          <Assumptions data={result.data} list={assumptions} ticker={ticker} knownOn={knownOn} />
          <DiscountRate data={result.data} />
          <Scenarios data={result.data} />
          <Comparison data={result.data} />
          {result.data.dcf.inputs.length > 0 ? (
            <details className="text-xs text-neutral-400">
              <summary className="cursor-pointer select-none">DCF inputs</summary>
              <ul className="mt-1 space-y-1.5">
                {result.data.dcf.inputs.map((input) => (
                  <ValuationInputItem key={input.name} input={input} />
                ))}
              </ul>
            </details>
          ) : null}
          <Relative rows={result.data.relative} />
          <DataDates data={result.data} />
          <details className="text-xs text-neutral-400">
            <summary className="cursor-pointer select-none">Method</summary>
            <p className="mt-1">
              <Metric termId="fair_value_dcf" icon={false}>
                {result.data.method}
              </Metric>
            </p>
          </details>
          {assumptions && action ? (
            <details className="rounded border border-neutral-800 p-3" data-edit-assumptions="">
              <summary className="cursor-pointer select-none text-sm">
                Edit assumptions (saves a new version)
              </summary>
              <div className="mt-3">
                <AssumptionsForm
                  ticker={ticker}
                  knownOn={knownOn}
                  parameters={result.data.assumptions.parameters}
                  limits={assumptions.limits}
                  action={action}
                />
              </div>
            </details>
          ) : null}
        </>
      )}
    </section>
  );
}
