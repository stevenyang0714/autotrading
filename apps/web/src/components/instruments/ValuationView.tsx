import { Metric } from "@/components/Metric";
import { type CompleteTermId, GLOSSARY } from "@/generated/glossary";
import type { ValuationInput, ValuationMetric, ValuationResult } from "@/lib/api";
import { exactReported, formatReported } from "@/lib/format";

function term(id: string): CompleteTermId | null {
  return id in GLOSSARY ? (id as CompleteTermId) : null;
}

/** An input's own unit: the price and EPS per share, share counts in shares, the rest USD. */
function inputUnit(name: string): string {
  if (name === "price" || name.startsWith("eps_")) return "USD/shares";
  if (name.startsWith("shares_")) return "shares";
  return "USD";
}

function InputLabel({ name }: { name: string }) {
  if (name === "price") return <Metric termId="valuation_price" icon={false} />;
  const own = term(name);
  if (own) return <Metric termId={own} icon={false} />;
  const base = name.endsWith("_ttm") ? term(name.slice(0, -4)) : null;
  if (base) {
    return (
      <Metric termId="trailing_twelve_months" icon={false}>
        {GLOSSARY[base].display_name}, last twelve months
      </Metric>
    );
  }
  return <span>{name}</span>;
}

/** One input of a value: its amount and period, how it was built, and the filings behind it. */
export function ValuationInputItem({ input }: { input: ValuationInput }) {
  const unit = inputUnit(input.name);
  return (
    <li className="space-y-0.5">
      <span className="flex flex-wrap gap-x-2">
        <InputLabel name={input.name} />
        {input.value !== null ? (
          <Metric termId={term(input.name) ?? "valuation_price"} icon={false}>
            <span className="tabular-nums" title={exactReported(input.value, unit)}>
              {formatReported(input.value, unit)}
            </span>{" "}
            <span className="text-neutral-500">
              {input.period_start ? `${input.period_start} to ${input.period_end}` : `as of ${input.period_end}`}
            </span>
          </Metric>
        ) : null}
      </span>
      {input.note ? (
        <span className="block text-neutral-500">
          <Metric termId={term(input.name) ?? "valuation_price"} icon={false}>
            {input.note}
          </Metric>
        </span>
      ) : null}
      {input.sources.length > 0 ? (
        <span className="flex flex-wrap gap-x-2">
          {input.sources.map((source) => (
            <a
              key={`${source.metric_id}-${source.period_end}-${source.filing.accession}`}
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
}

function Value({ metric }: { metric: ValuationMetric }) {
  const id = term(metric.metric_id) ?? "valuation_price";
  if (metric.value === null) {
    return (
      <Metric termId={id} icon={false}>
        <span className="text-neutral-400">{metric.reason === "not_meaningful" ? "n/m" : "Data unavailable"}</span>
      </Metric>
    );
  }
  const text =
    metric.unit === "x"
      ? `${Number(metric.value).toFixed(2)}x`
      : metric.unit === "percent"
        ? `${Number(metric.value).toFixed(2)}%`
        : formatReported(metric.value, metric.unit);
  return (
    <Metric termId={id} icon={false}>
      <span className="text-xl tabular-nums" title={metric.unit === "USD" ? exactReported(metric.value, "USD") : undefined}>
        {text}
      </span>
    </Metric>
  );
}

/**
 * Valuation block of the instrument page (M1.2, ADR-022): market cap, EV and six multiples as
 * known at the page's As known on time, each with its inputs and the filings behind them.
 */
export function ValuationView({ result }: { result: ValuationResult }) {
  return (
    <section aria-labelledby="valuation-heading" className="space-y-3">
      <h2 id="valuation-heading" className="text-lg font-medium">
        Valuation
      </h2>
      {result.status !== "ok" ? (
        <p role="alert" className="text-sm text-neutral-400">
          Data unavailable: the API could not be reached.
        </p>
      ) : (
        <>
          <p className="text-sm text-neutral-400" data-price-status={result.data.price.status}>
            {result.data.price.status === "ok" && result.data.price.close !== null ? (
              <Metric termId="valuation_price" icon={false}>
                Priced at the {result.data.price.day} close,{" "}
                {formatReported(result.data.price.close, "USD/shares")}
              </Metric>
            ) : (
              <Metric termId="valuation_price" icon={false}>
                Data unavailable: {result.data.price.detail}
              </Metric>
            )}
          </p>
          <ul className="grid grid-cols-2 items-start gap-3 lg:grid-cols-4" aria-label="Valuation">
            {result.data.metrics.map((metric) => {
              const id = term(metric.metric_id);
              return (
                <li
                  key={metric.metric_id}
                  data-valuation={metric.metric_id}
                  className="space-y-1 rounded border border-neutral-800 p-3 text-sm"
                >
                  {id ? <Metric termId={id} /> : <span>{metric.metric_id}</span>}
                  <div>
                    <Value metric={metric} />
                  </div>
                  {metric.detail && metric.value === null && result.data.price.status === "ok" ? (
                    <p className="text-xs text-neutral-500">
                      <Metric termId={id ?? "valuation_price"} icon={false}>
                        {metric.detail}
                      </Metric>
                    </p>
                  ) : null}
                  {metric.inputs.length > 0 ? (
                    <details className="text-xs text-neutral-400">
                      <summary className="cursor-pointer select-none">Inputs</summary>
                      <ul className="mt-1 space-y-1.5">
                        {metric.inputs.map((input) => (
                          <ValuationInputItem key={input.name} input={input} />
                        ))}
                      </ul>
                    </details>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
