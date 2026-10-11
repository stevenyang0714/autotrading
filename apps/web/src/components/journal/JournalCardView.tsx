import Link from "next/link";
import type { ReactNode } from "react";

import { AsKnownOnForm } from "@/components/AsKnownOnForm";
import { Metric } from "@/components/Metric";
import { PaperOnlyNotice } from "@/components/journal/StrategyLabView";
import type { EvidenceItem, JournalCard, JournalClose, JournalDecision, Replay, ValuationSnapshot } from "@/lib/api";
import { formatChange, formatPrice } from "@/lib/format";
import {
  EVIDENCE_KINDS,
  decisionLabel,
  evidenceValue,
  formatPnl,
  performanceSummary,
  signedClass,
} from "@/lib/journal";
import { formatSgtEt } from "@/lib/time";

const QUOTED = new Set(["buyback_statement", "guidance_statement", "news"]);

function Evidence({ item }: { item: EvidenceItem }) {
  const kind = EVIDENCE_KINDS[item.kind];
  const quoted = QUOTED.has(item.kind);
  return (
    <li data-evidence={item.kind} className="space-y-0.5 rounded border border-neutral-800 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-xs uppercase tracking-wide text-neutral-500">{kind.label}</span>
        <Metric termId={kind.termId} icon={false}>
          <span className="text-neutral-200">{item.label}</span>
        </Metric>
      </div>
      {quoted ? (
        <q data-quoted="" className="block text-neutral-300">
          {item.summary}
        </q>
      ) : (
        <span className="block tabular-nums">
          <Metric termId="evidence_item" icon={false}>
            {evidenceValue(item)}
          </Metric>
        </span>
      )}
      <p className="text-xs text-neutral-500">
        <Metric termId="point_in_time" icon={false}>
          public {formatSgtEt(item.published_at)}
        </Metric>
        {item.source_url ? (
          <>
            {" · "}
            <a href={item.source_url} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
              source
            </a>
          </>
        ) : null}
      </p>
      {item.note ? (
        <p className="text-xs italic text-neutral-400">
          <Metric termId="evidence_item" icon={false}>
            Why: {item.note}
          </Metric>
        </p>
      ) : null}
    </li>
  );
}

function Valuation({ valuation }: { valuation: ValuationSnapshot }) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4" aria-label="Valuation at the time">
      <div>
        <dt className="text-xs text-neutral-500">
          <Metric termId="fair_value_dcf" icon={false}>
            Base DCF per share
          </Metric>
        </dt>
        <dd className="tabular-nums">
          <Metric termId="fair_value_dcf" icon={false}>
            {valuation.base_per_share ? formatPrice(valuation.base_per_share) : "unavailable"}
          </Metric>
        </dd>
      </div>
      <div>
        <dt className="text-xs text-neutral-500">
          <Metric termId="fair_value_dcf" icon={false}>
            Price
          </Metric>
        </dt>
        <dd className="tabular-nums">
          <Metric termId="fair_value_dcf" icon={false}>
            {valuation.price ? `${formatPrice(valuation.price)} (${valuation.price_day})` : "unavailable"}
          </Metric>
        </dd>
      </div>
      <div>
        <dt className="text-xs text-neutral-500">
          <Metric termId="margin_of_safety" icon={false}>
            Margin of safety
          </Metric>
        </dt>
        <dd className="tabular-nums">
          <Metric termId="margin_of_safety" icon={false}>
            {valuation.margin_of_safety ? formatChange(valuation.margin_of_safety) : "unavailable"}
          </Metric>
        </dd>
      </div>
      <div>
        <dt className="text-xs text-neutral-500">
          <Metric termId="valuation_assumptions" icon={false}>
            Assumptions
          </Metric>
        </dt>
        <dd>
          <Metric termId="valuation_assumptions" icon={false}>
            {valuation.assumption_version ? `version ${valuation.assumption_version}` : "built-in default"}
          </Metric>
        </dd>
      </div>
      {valuation.detail ? (
        <p className="col-span-full text-xs text-neutral-500">
          <Metric termId="fair_value_dcf" icon={false}>
            {valuation.detail}
          </Metric>
        </p>
      ) : null}
    </dl>
  );
}

function Close({ close, label }: { close: JournalClose | null | undefined; label: string }) {
  if (!close) return <span className="text-neutral-500">{label}: no close</span>;
  return (
    <Metric termId="paper_return" icon={false}>
      {label} {formatPrice(close.close)} ({close.day}){close.feed_status === "fixture" ? " recorded demo close" : ""}
      {close.stale ? " · stale" : ""}
    </Metric>
  );
}

function Decision({ decision, exit }: { decision: JournalDecision; exit?: ReactNode }) {
  const performance = decision.performance;
  return (
    <li data-decision-id={decision.id} className="space-y-1 rounded border border-neutral-800 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Metric termId={decision.decision === "no_trade" ? "no_trade" : "trade_decision"}>
          <span className="font-medium">{decisionLabel(decision)}</span>
        </Metric>
        <Metric termId="point_in_time" icon={false} className="text-xs text-neutral-500">
          {formatSgtEt(decision.known_at)} · card version {decision.card_version}
        </Metric>
      </div>
      {decision.max_loss ? (
        <p className="text-xs text-neutral-400">
          <Metric termId="trade_decision" icon={false}>
            Maximum loss {formatPrice(decision.max_loss)}
          </Metric>
        </p>
      ) : null}
      {decision.note ? (
        <p className="text-neutral-300">
          <Metric termId="trade_decision" icon={false}>
            {decision.note}
          </Metric>
        </p>
      ) : null}
      {decision.closes ? (
        <p className="text-xs text-neutral-400">
          <Close close={decision.closes.stock} label={decision.exits_decision_id ? "Exit at" : "Close then"} />
          {" · "}
          <Close close={decision.closes.benchmark} label="SPY" />
        </p>
      ) : null}
      {performance ? (
        <div className="text-sm" data-performance={performance.open ? "open" : "closed"}>
          <Metric termId="paper_return" icon={false}>
            <span className={signedClass(performance.return_pct)}>{performanceSummary(performance)}</span>
            {performance.pnl !== null ? ` · ${formatPnl(performance.pnl)}` : ""}
            {performance.mark ? ` · marked at ${formatPrice(performance.mark.close)} (${performance.mark.day})` : ""}
            {performance.split_factor !== "1" ? ` · split factor ${performance.split_factor}` : ""}
            {performance.open ? " · open" : decision.decision === "trade" ? " · closed" : ""}
          </Metric>
          {performance.max_loss_breached ? (
            <p className="text-xs text-amber-400">
              <Metric termId="trade_decision" icon={false}>
                The paper loss exceeds the maximum loss.
              </Metric>
            </p>
          ) : null}
        </div>
      ) : null}
      {exit}
    </li>
  );
}

function ReplayResult({ replay }: { replay: Replay }) {
  const items = [...replay.evidence, replay.valuation, ...replay.decisions];
  return (
    <div className="space-y-2" data-replay={replay.identical ? "identical" : "differs"}>
      <p className={`text-sm ${replay.identical ? "text-emerald-300" : "text-amber-400"}`}>
        <Metric termId="journal_replay" icon={false}>
          {replay.identical
            ? `All ${items.length} items identical when read again as known at ${formatSgtEt(replay.known_at)}.`
            : "Some items differ from what was stored: report this, the record should never change."}
        </Metric>
      </p>
      <ul className="space-y-0.5 text-xs text-neutral-400" aria-label="Replay items">
        {items.map((item, i) => (
          <li key={i} data-status={item.status}>
            <Metric termId="journal_replay" icon={false}>
              {item.status} · {item.label}
              {item.changed.length > 0 ? ` (changed: ${item.changed.join(", ")})` : ""}
            </Metric>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * One Thesis Card (M1.6, ADR-027): thesis, evidence as known when it was written, catalysts,
 * invalidation, valuation, decisions with their paper performance, versions and replay.
 */
export function JournalCardView({
  data,
  replay,
  knownOn,
  invalidKnownOn = false,
  exitForm,
}: {
  data: JournalCard;
  replay: Replay | null;
  knownOn?: string;
  invalidKnownOn?: boolean;
  /** The exit form for an open TRADE, shown only when viewing now. */
  exitForm?: (decision: JournalDecision) => ReactNode;
}) {
  const card = data.card;
  const href = `/journal/${card.card_id}`;
  const latest = data.versions[data.versions.length - 1];
  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <p className="text-sm text-neutral-400">
          <Link href="/dashboards/strategy-lab" className="underline-offset-2 hover:underline">
            Strategy Lab
          </Link>{" "}
          ·{" "}
          <Link
            href={`/instruments/${card.ticker}#journal`}
            data-identifier=""
            className="underline-offset-2 hover:underline"
          >
            {card.ticker}
          </Link>
        </p>
        <h1 className="text-2xl font-semibold">
          <Metric termId="thesis_card" zh>
            Thesis Card
          </Metric>{" "}
          <span data-identifier="" className="text-base text-neutral-400">
            {card.ticker} v{card.version}
          </span>
        </h1>
        <p className="text-sm text-neutral-400">
          <Metric termId="point_in_time" icon={false}>
            Written {formatSgtEt(card.known_at)}
          </Metric>
          , citing only what was known then.
        </p>
        <PaperOnlyNotice detail={data.detail} />
      </header>

      <div className="space-y-2">
        <h2 className="text-lg font-medium">
          <Metric termId="thesis_card">Thesis</Metric>
        </h2>
        <blockquote className="border-l-2 border-neutral-700 pl-3 text-neutral-100">
          <Metric termId="thesis_card" icon={false}>
            {card.thesis}
          </Metric>
        </blockquote>
      </div>

      <div className="space-y-2">
        <h2 className="text-lg font-medium">
          <Metric termId="evidence_item">Evidence</Metric>
        </h2>
        <ol className="space-y-2" aria-label="Evidence">
          {card.evidence.map((item, i) => (
            <Evidence key={i} item={item} />
          ))}
        </ol>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <h2 className="text-lg font-medium">
            <Metric termId="catalyst">Catalysts</Metric>
          </h2>
          {card.catalysts.length === 0 ? (
            <p className="text-sm text-neutral-400">None stated.</p>
          ) : (
            <ul className="space-y-1 text-sm" aria-label="Catalysts">
              {card.catalysts.map((c, i) => (
                <li key={i}>
                  <Metric termId="catalyst" icon={false}>
                    {c.description}
                    {c.expected ? ` (expected ${c.expected})` : ""}
                  </Metric>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="space-y-2">
          <h2 className="text-lg font-medium">
            <Metric termId="invalidation">Invalidation</Metric>
          </h2>
          <p className="text-sm">
            <Metric termId="invalidation" icon={false}>
              {card.invalidation}
            </Metric>
          </p>
        </div>
      </div>

      {card.notes ? (
        <div className="space-y-1">
          <h2 className="text-lg font-medium">Notes</h2>
          <p className="text-sm text-neutral-300">
            <Metric termId="thesis_card" icon={false}>
              {card.notes}
            </Metric>
          </p>
          <p className="text-xs text-neutral-500">Notes are not evidence.</p>
        </div>
      ) : null}

      <div className="space-y-2">
        <h2 className="text-lg font-medium">
          <Metric termId="fair_value_dcf">Valuation then</Metric>
        </h2>
        <Valuation valuation={card.valuation} />
      </div>

      <div className="space-y-2">
        <h2 className="text-lg font-medium">
          <Metric termId="trade_decision">Decisions</Metric>
        </h2>
        <AsKnownOnForm href={href} knownOn={knownOn} invalid={invalidKnownOn} />
        <p className="text-xs text-neutral-500">
          Paper performance as known at{" "}
          <Metric termId="point_in_time" icon={false}>
            {formatSgtEt(data.known_at)}
          </Metric>
          .
        </p>
        {data.decisions.length === 0 ? (
          <p className="text-sm text-neutral-400">No decision was recorded by this date.</p>
        ) : (
          <ul className="space-y-2" aria-label="Decisions">
            {data.decisions.map((decision) => (
              <Decision
                key={decision.id}
                decision={decision}
                exit={
                  decision.performance?.open && decision.decision === "trade" && exitForm
                    ? exitForm(decision)
                    : undefined
                }
              />
            ))}
          </ul>
        )}
      </div>

      <div className="space-y-2">
        <h2 className="text-lg font-medium">
          <Metric termId="thesis_card">Versions</Metric>
        </h2>
        <ul className="flex flex-wrap gap-2 text-sm" aria-label="Versions">
          {data.versions.map((v) => (
            <li key={v.id}>
              <Link
                href={`${href}?version=${v.version}`}
                aria-current={v.version === card.version ? "page" : undefined}
                className="underline-offset-2 hover:underline aria-[current=page]:font-medium"
              >
                <Metric termId="thesis_card" icon={false}>
                  v{v.version} {formatSgtEt(v.known_at)}
                </Metric>
              </Link>
            </li>
          ))}
        </ul>
        {card.version === latest?.version && !knownOn ? (
          <Link
            href={`/journal/new?card=${card.card_id}`}
            className="inline-block rounded border border-neutral-300 px-3 py-1 text-sm hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
          >
            Write a new version
          </Link>
        ) : null}
      </div>

      <div className="space-y-2">
        <h2 className="text-lg font-medium">
          <Metric termId="journal_replay">Replay</Metric>
        </h2>
        {replay ? (
          <ReplayResult replay={replay} />
        ) : (
          <p role="alert" className="text-sm text-neutral-400">
            Data unavailable: the replay could not be run.
          </p>
        )}
      </div>
    </section>
  );
}
