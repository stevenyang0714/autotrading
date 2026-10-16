import Link from "next/link";
import type { ReactNode } from "react";

import { AsKnownOnForm } from "@/components/AsKnownOnForm";
import { Metric } from "@/components/Metric";
import { Sparkline } from "@/components/Sparkline";
import type { CompleteTermId } from "@/generated/glossary";
import type { PortfolioResponse, RiskChecks } from "@/lib/api";
import {
  LIMIT_TERMS,
  TRIGGER_LABELS,
  pct,
  sectorLabel,
  trim,
  usd,
} from "@/lib/risk";
import { formatSgtEt } from "@/lib/time";

const HREF = "/dashboards/portfolio-risk";

function Tile({
  termId,
  label,
  value,
  sub,
}: {
  termId: CompleteTermId;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div
      className="space-y-0.5 rounded border border-neutral-800 px-3 py-2"
      data-tile={termId}
    >
      <p className="text-xs text-neutral-400">
        <Metric termId={termId}>{label}</Metric>
      </p>
      <p className="text-lg tabular-nums">
        <Metric termId={termId} icon={false}>
          {value}
        </Metric>
      </p>
      {sub ? (
        <p className="text-xs text-neutral-500">
          <Metric termId={termId} icon={false}>
            {sub}
          </Metric>
        </p>
      ) : null}
    </div>
  );
}

function Usage({
  termId,
  label,
  used,
  limit,
  note,
}: {
  termId: CompleteTermId;
  label: string;
  used: string | null;
  limit: string;
  note?: string;
}) {
  const over = used !== null && Number(used) > Number(limit);
  return (
    <tr data-limit={termId} className="border-b border-neutral-900">
      <th scope="row" className="px-3 py-1.5 text-left font-normal">
        <Metric termId={termId}>{label}</Metric>
      </th>
      <td
        className={`px-3 py-1.5 text-right tabular-nums ${over ? "text-rose-300" : ""}`}
      >
        <Metric termId={termId} icon={false}>
          {used === null ? "n/a" : pct(used)}
        </Metric>
      </td>
      <td className="px-3 py-1.5 text-right tabular-nums text-neutral-400">
        <Metric termId={termId} icon={false}>
          {`at most ${pct(limit)}`}
        </Metric>
      </td>
      <td className="px-3 py-1.5 text-xs text-neutral-500">
        {note ? (
          <Metric termId={termId} icon={false}>
            {note}
          </Metric>
        ) : null}
      </td>
    </tr>
  );
}

function CheckList({
  checks,
  label,
  empty,
}: {
  checks: RiskChecks | null;
  label: string;
  empty: string;
}) {
  return (
    <>
      {checks === null ? (
        <p role="alert" className="text-sm text-neutral-400">
          Data unavailable: the risk checks could not be loaded.
        </p>
      ) : checks.checks.length === 0 ? (
        <p className="text-sm text-neutral-400">{empty}</p>
      ) : (
        <ol className="space-y-1" aria-label={label}>
          {checks.checks.map((c) => {
            const vetoes = c.check.limits.filter((l) => l.status === "veto");
            return (
              <li
                key={c.id}
                data-check={c.id}
                data-verdict={c.verdict}
                data-trigger={c.trigger}
                className="rounded border border-neutral-800 px-3 py-1.5 text-sm"
              >
                <p className="flex flex-wrap items-baseline gap-x-2">
                  <span
                    className={
                      c.verdict === "pass"
                        ? "text-emerald-300"
                        : "text-rose-300"
                    }
                  >
                    <Metric
                      termId={c.verdict === "pass" ? "risk_check" : "risk_veto"}
                      icon={false}
                    >
                      {c.verdict === "pass" ? "PASS" : "VETO"}
                    </Metric>
                  </span>
                  <Metric
                    termId={
                      c.trigger === "standard"
                        ? "standard_position_check"
                        : "risk_check"
                    }
                    icon={false}
                  >
                    {`${TRIGGER_LABELS[c.trigger] ?? c.trigger}: ${c.check.proposal.side} ${trim(c.check.proposal.quantity)} ${c.ticker}`}
                  </Metric>
                  <span className="text-xs text-neutral-500">
                    <Metric termId="point_in_time" icon={false}>
                      {formatSgtEt(c.known_at)}
                      {c.backfilled ? " · backfilled" : ""}
                    </Metric>
                  </span>
                </p>
                {vetoes.length > 0 ? (
                  <ul className="text-xs text-rose-300">
                    {vetoes.map((l) => (
                      <li key={l.limit_id} data-limit={l.limit_id}>
                        <Metric
                          termId={LIMIT_TERMS[l.limit_id] ?? "risk_check"}
                          icon={false}
                        >
                          {`${l.label}: ${l.detail} (${l.threshold})`}
                        </Metric>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
    </>
  );
}

/**
 * Portfolio Risk (M2.3, ADR-031): the paper portfolio as known on the chosen date, each limit
 * of the risk rules with its use, the risk check history with vetoes, and a form to try a paper
 * trade now. Paper only: no order is placed or prepared.
 */
export function PortfolioRiskView({
  data,
  checks,
  standard = null,
  knownOn,
  invalidKnownOn = false,
  tryForm,
}: {
  data: PortfolioResponse;
  /** Journal TRADEs and tried trades. */
  checks: RiskChecks | null;
  /** The latest daily standard-position checks (TRADE-READY and L4). */
  standard?: RiskChecks | null;
  knownOn?: string;
  invalidKnownOn?: boolean;
  /** The try-a-trade form, shown only when viewing now. */
  tryForm?: ReactNode;
}) {
  const book = data.portfolio;
  const rules = data.rules;
  const largest = book.positions.reduce<string | null>(
    (top, p) =>
      p.weight_pct !== null &&
      (top === null || Number(p.weight_pct) > Number(top))
        ? p.weight_pct
        : top,
    null,
  );
  const limitedSectors = book.sectors.filter((s) => s.limited);
  const topSector = limitedSectors.reduce<string | null>(
    (top, s) => (top === null || Number(s.pct) > Number(top) ? s.pct : top),
    null,
  );
  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          <Metric termId="dashboard_portfolio_risk" zh>
            Portfolio Risk
          </Metric>
        </h1>
        <p className="text-sm text-neutral-400">
          The journal&apos;s open paper trades as one book: exposures, sectors,
          drawdown, and every limit a new paper trade must pass.
        </p>
        <p
          role="note"
          data-paper-only=""
          className="rounded border border-sky-700/60 bg-sky-950/30 px-3 py-2 text-sm text-sky-100"
        >
          <Metric termId="paper_portfolio" icon={false}>
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
          <Metric termId="risk_rule_set" icon={false}>
            risk rules {rules.rule_version}
          </Metric>
        </p>
      </header>

      <div
        className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4"
        data-block="summary"
      >
        <Tile
          termId="notional_capital"
          label="Capital"
          value={usd(rules.capital)}
        />
        <Tile
          termId="portfolio_equity"
          label="Equity"
          value={usd(book.equity)}
          sub={`realized ${usd(book.realized_pnl)} · open ${usd(book.unrealized_pnl)}`}
        />
        <Tile
          termId="gross_exposure"
          label="Gross exposure"
          value={pct(book.gross_pct)}
          sub={usd(book.gross)}
        />
        <Tile
          termId="net_exposure"
          label="Net exposure"
          value={pct(book.net_pct)}
          sub={`${usd(book.net)} · cash ${usd(book.cash)}`}
        />
        <Tile
          termId="beta_exposure"
          label="Beta-weighted exposure"
          value={book.beta_exposure !== null ? usd(book.beta_exposure) : "n/a"}
        />
        <Tile
          termId="portfolio_drawdown"
          label="Drawdown"
          value={pct(book.drawdown_pct)}
          sub={`peak ${usd(book.peak_equity)} · alert at ${pct(rules.drawdown_alert_pct)}`}
        />
        <Tile
          termId="paper_portfolio"
          label="Positions"
          value={String(book.positions.length)}
        />
        <Tile
          termId="risk_veto"
          label="Vetoes"
          value={String(data.vetoes)}
          sub="journal and tried trades"
        />
      </div>

      {book.curve.length >= 2 ? (
        <div className="space-y-1" data-block="curve">
          <h2 className="text-lg font-medium">
            <Metric termId="portfolio_equity">Equity curve</Metric>
          </h2>
          <Sparkline
            points={book.curve.map((p) => ({ day: p.day, value: p.equity }))}
            termId="portfolio_equity"
            label="Paper equity at each session's close"
            format={(v) => usd(v)}
          />
        </div>
      ) : null}

      <div className="space-y-2" data-block="limits">
        <h2 className="text-lg font-medium">
          <Metric termId="risk_check" zh>
            Limits
          </Metric>
        </h2>
        <div className="overflow-x-auto rounded border border-neutral-800">
          <table className="w-full min-w-[40rem] text-sm" aria-label="Limits">
            <thead>
              <tr className="border-b border-neutral-800 text-xs text-neutral-400">
                <th scope="col" className="px-3 py-1.5 text-left font-normal">
                  Limit
                </th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal">
                  Now
                </th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal">
                  Rule
                </th>
                <th scope="col" className="px-3 py-1.5 text-left font-normal">
                  Note
                </th>
              </tr>
            </thead>
            <tbody>
              <Usage
                termId="risk_limit_position"
                label="Largest position"
                used={largest}
                limit={rules.limits.position_pct}
              />
              <Usage
                termId="risk_limit_sector"
                label="Largest sector"
                used={topSector}
                limit={rules.limits.sector_pct}
                note="broad market, bonds and gold not limited"
              />
              <Usage
                termId="risk_limit_gross"
                label="Gross exposure"
                used={book.gross_pct}
                limit={rules.limits.gross_pct}
              />
              <Usage
                termId="portfolio_drawdown"
                label="Drawdown alert"
                used={book.drawdown_pct}
                limit={rules.drawdown_alert_pct}
              />
              <Usage
                termId="risk_limit_max_loss"
                label="Maximum loss per trade"
                used={null}
                limit={rules.limits.max_loss_pct}
                note="checked on each new trade; it must be stated"
              />
              <Usage
                termId="risk_limit_volume"
                label="Trade against average volume"
                used={null}
                limit={rules.limits.volume_pct}
                note={`checked on each new trade, against ${rules.limits.volume_sessions} sessions`}
              />
            </tbody>
          </table>
        </div>
        <p className="text-xs text-neutral-500">
          <Metric termId="risk_limit_price" icon={false}>
            A trade is checked at the last end-of-day close, at most{" "}
            {rules.limits.stale_after_days} days old; recorded or demo prices
            are vetoed.
          </Metric>
        </p>
      </div>

      <div className="space-y-2" data-block="positions">
        <h2 className="text-lg font-medium">
          <Metric termId="paper_portfolio" zh>
            Positions
          </Metric>
        </h2>
        {book.positions.length === 0 ? (
          <p className="text-sm text-neutral-400">
            <Metric termId="paper_portfolio" icon={false}>
              No open paper trade by this date. Record one from the Strategy
              Lab; it is checked first.
            </Metric>
          </p>
        ) : (
          <div className="overflow-x-auto rounded border border-neutral-800">
            <table
              className="w-full min-w-[56rem] text-sm"
              aria-label="Positions"
            >
              <thead>
                <tr className="border-b border-neutral-800 text-xs text-neutral-400">
                  {[
                    "Company",
                    "Side",
                    "Shares",
                    "Entry",
                    "Last close",
                    "Value",
                    "Weight",
                    "P&L",
                    "Beta",
                    "Sector",
                    "Days to exit",
                  ].map((h) => (
                    <th
                      key={h}
                      scope="col"
                      className="px-3 py-1.5 text-right font-normal first:text-left"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {book.positions.map((p) => (
                  <tr
                    key={p.decision_id}
                    data-position={p.ticker}
                    className="border-b border-neutral-900"
                  >
                    <th
                      scope="row"
                      className="px-3 py-1.5 text-left font-normal"
                    >
                      <Link
                        href={`/instruments/${p.ticker}#journal`}
                        data-identifier=""
                        className="underline-offset-2 hover:underline"
                      >
                        {p.ticker}
                      </Link>
                    </th>
                    <td className="px-3 py-1.5 text-right">
                      {p.side === "buy" ? "Long" : "Short"}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      <Metric termId="paper_portfolio" icon={false}>
                        {trim(p.shares)}
                      </Metric>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      <Metric termId="paper_portfolio" icon={false}>
                        {`${trim(p.entry_price)} (${p.entry_day})`}
                      </Metric>
                    </td>
                    <td
                      className={`px-3 py-1.5 text-right tabular-nums ${p.stale ? "text-amber-300" : ""}`}
                    >
                      <Metric termId="risk_limit_price" icon={false}>
                        {p.mark !== null
                          ? `${trim(p.mark)} (${p.mark_day})${p.stale ? " stale" : ""}`
                          : "n/a"}
                      </Metric>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      <Metric termId="position_weight" icon={false}>
                        {p.market_value !== null ? usd(p.market_value) : "n/a"}
                      </Metric>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      <Metric termId="position_weight" icon={false}>
                        {p.weight_pct !== null ? pct(p.weight_pct) : "n/a"}
                      </Metric>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      <Metric termId="paper_return" icon={false}>
                        {p.pnl !== null ? usd(p.pnl) : "n/a"}
                      </Metric>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      <Metric termId="beta_252d" icon={false}>
                        {p.beta ?? "n/a"}
                      </Metric>
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      <Metric termId="gics_sector" icon={false}>
                        {sectorLabel(p.sector)}
                      </Metric>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      <Metric termId="days_to_exit" icon={false}>
                        {p.days_to_exit ?? "n/a"}
                      </Metric>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {book.sectors.length > 0 ? (
          <ul
            className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-400"
            aria-label="Sectors"
          >
            {book.sectors.map((s) => (
              <li key={s.sector} data-sector={s.sector}>
                <Metric termId="gics_sector" icon={false}>
                  {`${sectorLabel(s.sector)}: ${pct(s.pct)}${s.limited ? "" : " (not limited)"}`}
                </Metric>
              </li>
            ))}
          </ul>
        ) : null}
        {book.notes.map((note) => (
          <p key={note} className="text-xs text-amber-300">
            <Metric termId="paper_portfolio" icon={false}>
              {note}
            </Metric>
          </p>
        ))}
      </div>

      {tryForm ? (
        <div className="space-y-2">
          <h2 className="text-lg font-medium">
            <Metric termId="risk_check" zh>
              Try a paper trade
            </Metric>
          </h2>
          {tryForm}
        </div>
      ) : null}

      <div className="space-y-2" data-block="checks">
        <h2 className="text-lg font-medium">
          <Metric termId="risk_check" zh>
            Risk checks
          </Metric>
        </h2>
        <CheckList
          checks={checks}
          label="Risk checks"
          empty="No journal or tried trade was checked by this date."
        />
        {standard && standard.checks.length > 0 ? (
          <>
            <h3 className="pt-2 text-sm font-medium text-neutral-300">
              <Metric termId="standard_position_check">
                Standard positions (TRADE-READY and L4)
              </Metric>
            </h3>
            <CheckList
              checks={standard}
              label="Standard position checks"
              empty=""
            />
          </>
        ) : null}
      </div>
    </section>
  );
}
