import { Metric } from "@/components/Metric";
import type { BacktestOverlap, BacktestRun, BacktestsResponse, StoredBacktest } from "@/lib/api";
import { LIMIT_LABELS, STRATEGIES, WITHHELD_LABELS, bps, holdings, pct, sectorLabel } from "@/lib/backtest";
import { formatSgtEt } from "@/lib/time";

const RECENT_TRADES = 20;
const SHOWN_TRADES = 200;

function Method({ run }: { run: BacktestRun }) {
  const strategy = STRATEGIES[run.strategy_id];
  return (
    <p className="text-xs text-neutral-400">
      <Metric termId="backtest" icon={false}>
        {strategy?.rules ?? "rules"} {run.strategy_rule_version} · backtest rules {run.rule_version} · since {run.since}
      </Metric>
      {" · "}
      <Metric termId="next_close_fill" icon={false}>
        filled at the next session close
      </Metric>
      {" · "}
      <Metric termId="cost_model" icon={false}>
        costs per side: equities {bps(run.cost_bps.equity)}, ETFs {bps(run.cost_bps.etf)}
      </Metric>
    </p>
  );
}

function Samples({ run }: { run: BacktestRun }) {
  const folds = run.scenarios[0]?.folds ?? [];
  const outside = folds.filter((f) => f.sample === "out_of_sample");
  const sessions = outside.reduce((n, f) => n + f.sessions, 0);
  return (
    <p className="text-xs text-neutral-400" data-samples="">
      <Metric termId="in_sample" icon={false}>
        In-sample {run.start ?? "–"} to {run.released}: the rules were set after seeing this history
      </Metric>
      {" · "}
      <Metric termId="out_of_sample" icon={false}>
        {sessions > 0
          ? `out-of-sample after ${run.released}: ${sessions} session${sessions === 1 ? "" : "s"}`
          : `out-of-sample after ${run.released}: no session yet`}
      </Metric>
    </p>
  );
}

function Folds({ run }: { run: BacktestRun }) {
  const base = run.scenarios.find((s) => s.scenario === "base") ?? run.scenarios[0];
  if (!base || base.folds.length === 0) {
    return (
      <p className="text-sm text-neutral-400">
        <Metric termId="walk_forward" icon={false}>
          No target was filled by this date.
        </Metric>
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] text-sm" aria-label={`${run.strategy_id} folds`}>
        <thead>
          <tr className="border-b border-neutral-800 text-left text-xs text-neutral-400">
            <th className="px-2 py-1 font-normal">
              <Metric termId="walk_forward">Year</Metric>
            </th>
            <th className="px-2 py-1 text-right font-normal">Rebalances</th>
            <th className="px-2 py-1 text-right font-normal">Trades</th>
            <th className="px-2 py-1 text-right font-normal">
              <Metric termId="turnover">Turnover</Metric>
            </th>
            <th className="px-2 py-1 text-right font-normal">
              <Metric termId="cost_drag">Cost per year</Metric>
            </th>
            <th className="px-2 py-1 text-right font-normal">
              <Metric termId="gross_exposure">Exposure</Metric>
            </th>
          </tr>
        </thead>
        <tbody>
          {base.folds.map((fold) => (
            <tr key={fold.label} data-fold={fold.label} data-sample={fold.sample} className="border-b border-neutral-900">
              <td className="px-2 py-1">
                <Metric termId={fold.sample === "out_of_sample" ? "out_of_sample" : "in_sample"} icon={false}>
                  {fold.label}
                </Metric>
              </td>
              <td className="px-2 py-1 text-right tabular-nums">
                <Metric termId="walk_forward" icon={false}>
                  {fold.rebalances}
                </Metric>
              </td>
              <td className="px-2 py-1 text-right tabular-nums">
                <Metric termId="walk_forward" icon={false}>
                  {fold.trades}
                </Metric>
              </td>
              <td className="px-2 py-1 text-right tabular-nums">
                <Metric termId="turnover" icon={false}>
                  {pct(fold.turnover_pct)}
                </Metric>
              </td>
              <td className="px-2 py-1 text-right tabular-nums">
                <Metric termId="cost_drag" icon={false}>
                  {bps(fold.cost_bps_per_year)}
                </Metric>
              </td>
              <td className="px-2 py-1 text-right tabular-nums">
                <Metric termId="gross_exposure" icon={false}>
                  {pct(fold.average_gross_pct)}
                </Metric>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Scenarios({ run }: { run: BacktestRun }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-400" aria-label={`${run.strategy_id} cost scenarios`}>
      {run.scenarios.map((scenario) => (
        <li key={scenario.scenario} data-scenario={scenario.scenario}>
          <Metric termId="cost_model" icon={false}>
            {scenario.scenario === "base" ? "Base costs" : `Costs ×${Number(scenario.multiplier)}`}: {scenario.trades} trades,{" "}
            {bps(scenario.cost_bps)} of the portfolio in all
          </Metric>
        </li>
      ))}
    </ul>
  );
}

function Withheld({ run }: { run: BacktestRun }) {
  return (
    <div className="rounded border border-amber-700/50 bg-amber-950/20 px-3 py-2 text-xs text-amber-100" data-withheld="">
      <p>
        <Metric termId="performance_withheld" icon={false}>
          {run.withheld.map((w) => WITHHELD_LABELS[w.metric] ?? w.metric).join(", ")}: Data unavailable
        </Metric>
      </p>
      <p className="mt-1 text-amber-200/80">
        <Metric termId="survivorship_bias" icon={false}>
          {run.withheld_reason}
        </Metric>
      </p>
    </div>
  );
}

function Latest({ run }: { run: BacktestRun }) {
  const filled = run.rebalances.filter((r) => r.fill_day !== null);
  const last = filled[filled.length - 1];
  const vetoed = filled.filter((r) => r.vetoes.length > 0);
  const example = vetoed[vetoed.length - 1]?.vetoes[0];
  return (
    <div className="space-y-1 text-xs text-neutral-400">
      {last ? (
        <p data-latest-target="">
          <Metric termId="rotation_target" icon={false}>
            Target filled {last.fill_day}:{" "}
            {holdings(last.target)
              .map(([symbol, weight]) => `${symbol} ${pct(weight)}`)
              .join(", ") || "cash only"}
          </Metric>
          {last.beta !== null ? (
            <>
              {" · "}
              <Metric termId="beta_252d" icon={false}>
                beta {Number(last.beta).toFixed(3)}
              </Metric>
            </>
          ) : null}
        </p>
      ) : null}
      <p data-risk-reference="">
        <Metric termId="risk_overlay" icon={false}>
          {vetoed.length} of {filled.length} targets would break the risk limits
          {example
            ? ` (latest: ${LIMIT_LABELS[example.limit] ?? example.limit} ${example.subject} ${pct(example.value)} against ${pct(example.threshold)})`
            : ""}
          ; they are a reference only, the backtest follows the strategy.
        </Metric>
      </p>
      <p>
        <Metric termId="holding_period" icon={false}>
          {run.positions.filter((p) => p.exit !== null).length} positions closed,{" "}
          {run.positions.filter((p) => p.exit === null).length} open
        </Metric>
      </p>
    </div>
  );
}

function Trades({ run }: { run: BacktestRun }) {
  if (run.trades.length === 0) return null;
  const recent = [...run.trades].reverse();
  const rows = (count: number) =>
    recent.slice(0, count).map((trade, i) => (
      <tr key={`${trade.day}-${trade.symbol}-${i}`} className="border-b border-neutral-900" data-trade={trade.symbol}>
        <td className="px-2 py-1 whitespace-nowrap">
          <Metric termId="next_close_fill" icon={false}>
            {trade.day}
          </Metric>
        </td>
        <td className="px-2 py-1" data-identifier="">
          {trade.symbol}
        </td>
        <td className="px-2 py-1">{trade.side}</td>
        <td className="px-2 py-1 text-right tabular-nums">
          <Metric termId="turnover" icon={false}>
            {pct(trade.weight_before)} → {pct(trade.weight_after)}
          </Metric>
        </td>
        <td className="px-2 py-1 text-right tabular-nums">
          <Metric termId="next_close_fill" icon={false}>
            {Number(trade.price).toFixed(2)}
          </Metric>
        </td>
        <td className="px-2 py-1 text-right tabular-nums">
          <Metric termId="cost_model" icon={false}>
            {bps(trade.cost_bps)}
          </Metric>
        </td>
      </tr>
    ));
  const head = (
    <thead>
      <tr className="border-b border-neutral-800 text-left text-xs text-neutral-400">
        <th className="px-2 py-1 font-normal">Filled</th>
        <th className="px-2 py-1 font-normal">Symbol</th>
        <th className="px-2 py-1 font-normal">Side</th>
        <th className="px-2 py-1 text-right font-normal">Weight</th>
        <th className="px-2 py-1 text-right font-normal">Close</th>
        <th className="px-2 py-1 text-right font-normal">Cost</th>
      </tr>
    </thead>
  );
  return (
    <details className="text-sm">
      <summary className="cursor-pointer select-none text-xs text-neutral-400">
        <Metric termId="backtest" icon={false}>
          Trades: the latest {Math.min(RECENT_TRADES, run.trades.length)} of {run.trades.length}
        </Metric>
      </summary>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[34rem] text-xs" aria-label={`${run.strategy_id} trades`}>
          {head}
          <tbody>{rows(RECENT_TRADES)}</tbody>
        </table>
        {run.trades.length > RECENT_TRADES ? (
          <details className="mt-2">
            <summary className="cursor-pointer select-none text-xs text-neutral-500">
              <Metric termId="backtest" icon={false}>
                The latest {Math.min(SHOWN_TRADES, run.trades.length)} trades (all {run.trades.length} are stored with the run)
              </Metric>
            </summary>
            <table className="mt-1 w-full min-w-[34rem] text-xs" aria-label={`${run.strategy_id} more trades`}>
              {head}
              <tbody>{rows(SHOWN_TRADES)}</tbody>
            </table>
          </details>
        ) : null}
      </div>
    </details>
  );
}

function RunCard({ stored }: { stored: StoredBacktest }) {
  const run = stored.run;
  const strategy = STRATEGIES[run.strategy_id];
  return (
    <li data-backtest={run.strategy_id} className="space-y-2 rounded border border-neutral-800 px-3 py-2">
      <h3 className="flex flex-wrap items-baseline gap-x-2 text-sm font-medium">
        <Metric termId={strategy?.termId ?? "backtest"} icon={false}>
          {run.strategy_id} {strategy?.name ?? ""}
        </Metric>
        <span className="text-xs font-normal text-neutral-500">
          <Metric termId="point_in_time" icon={false}>
            run {formatSgtEt(stored.known_at)}
          </Metric>
        </span>
      </h3>
      <Method run={run} />
      <Samples run={run} />
      <Withheld run={run} />
      <Folds run={run} />
      <Scenarios run={run} />
      <Latest run={run} />
      <Trades run={run} />
      {run.notes.length > 0 ? (
        <ul className="list-disc pl-4 text-xs text-neutral-500">
          {run.notes.map((note) => (
            <li key={note}>
              <Metric termId="backtest" icon={false}>
                {note}
              </Metric>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function OverlapBlock({ overlap }: { overlap: BacktestOverlap }) {
  return (
    <div className="space-y-1 text-sm" data-overlap="">
      <h3 className="text-sm font-medium text-neutral-300">
        <Metric termId="factor_overlap">Factor overlap</Metric>
      </h3>
      <p className="text-xs text-neutral-400">
        <Metric termId="factor_overlap" icon={false}>
          {overlap.shared_pct !== null
            ? `S4 held ${pct(overlap.shared_pct)} of its companies in common with S1, on average over ${overlap.shared_months} months`
            : "S4 and S1 never held companies at the same time"}
        </Metric>
      </p>
      <ul className="space-y-0.5 text-xs text-neutral-400" aria-label="Exposure by strategy">
        {overlap.strategies.map((s) => {
          const top = Object.entries(s.sectors)
            .sort(([, a], [, b]) => Number(b) - Number(a))
            .slice(0, 3);
          return (
            <li key={s.strategy_id} data-overlap-strategy={s.strategy_id}>
              <Metric termId="factor_overlap" icon={false}>
                {s.strategy_id}: average beta {s.average_beta !== null ? Number(s.average_beta).toFixed(3) : "n/a"} ·{" "}
                {top.map(([sector, weight]) => `${sectorLabel(sector)} ${pct(weight)}`).join(", ")}
              </Metric>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * Backtests (M2.5, ADR-033): each strategy's latest stored run as known on the chosen date, with
 * its method, in-sample and out-of-sample periods, yearly folds, cost scenarios, trades and the
 * risk limits for reference, and the factor overlap between them. Performance is withheld
 * (OD-7): no return, ratio or drawdown is shown.
 */
export function BacktestsView({ data }: { data: BacktestsResponse | null }) {
  if (data === null) {
    return (
      <p role="alert" className="text-sm text-neutral-400">
        Data unavailable: the backtests could not be loaded.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-sm text-neutral-400">
        <Metric termId="backtest" icon={false}>
          {data.detail}
        </Metric>{" "}
        <Metric termId="backtest_rule_set" icon={false}>
          <span className="text-neutral-500">backtest rules {data.rule_version}</span>
        </Metric>
      </p>
      {data.runs.length === 0 ? (
        <p className="text-sm text-neutral-400">
          <Metric termId="backtest" icon={false}>
            No backtest was run by this date. They run once a month after the rotation, or with make backtest-run.
          </Metric>
        </p>
      ) : (
        <ul className="space-y-3" aria-label="Backtest runs">
          {data.runs.map((stored) => (
            <RunCard key={stored.id} stored={stored} />
          ))}
        </ul>
      )}
      {data.overlap ? <OverlapBlock overlap={data.overlap} /> : null}
    </div>
  );
}
