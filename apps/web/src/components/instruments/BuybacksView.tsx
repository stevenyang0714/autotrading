import { BuybackStateCard } from "@/components/buybacks/BuybackStateCard";
import { Metric } from "@/components/Metric";
import { PeriodTable } from "@/components/instruments/PeriodTable";
import { ValuationInputItem } from "@/components/instruments/ValuationView";
import type { AnnouncementEvent, Buybacks, BuybacksResult } from "@/lib/api";
import { formatSgtEt } from "@/lib/time";

const KIND_LABELS: Record<AnnouncementEvent["kind"], string> = {
  new: "New authorization",
  increase: "Authorization increase",
  plan: "Buyback plan",
  remaining: "Remaining authorization",
};
const SHOWN = 6;

/** "$110 billion", "$14.7 billion", "$500 million": an announced amount as issuers write it. */
export function formatAnnounced(value: string): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  const [scale, unit] = Math.abs(number) >= 1e9 ? [1e9, "billion"] : [1e6, "million"];
  return `$${Number((number / scale).toFixed(3)).toString()} ${unit}`;
}

/** The sentence without its own surrounding quotation marks (<q> adds them). */
function unquoted(sentence: string): string {
  return sentence.replace(/^[“"‘']+|[”"’']+$/g, "");
}

function Event({ event }: { event: AnnouncementEvent }) {
  return (
    <li className="space-y-1 border-b border-neutral-900 pb-2" data-event-kind={event.kind}>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <Metric termId="repurchase_announcement" icon={false}>
          <span className="font-medium">
            {KIND_LABELS[event.kind]} {formatAnnounced(event.amount)}
          </span>
        </Metric>
        {event.remaining_amount !== null ? (
          <Metric termId="repurchase_remaining" icon={false}>
            <span className="text-neutral-400">remaining {formatAnnounced(event.remaining_amount)}</span>
          </Metric>
        ) : null}
        <Metric termId="repurchase_announcement" icon={false}>
          <span className="text-xs text-neutral-500">{event.day}</span>
        </Metric>
      </div>
      <ul className="space-y-1">
        {event.sources.map((source) => (
          <li key={`${source.url}-${source.sentence}`} className="text-xs text-neutral-400">
            <q data-quoted="" className="text-neutral-300">
              {unquoted(source.sentence)}
            </q>{" "}
            <a
              href={source.url}
              target="_blank"
              rel="noreferrer"
              data-identifier=""
              className="whitespace-nowrap underline-offset-2 hover:underline"
            >
              {source.channel === "sec_8k" ? `${source.document_type ?? "8-K"} ${source.accession ?? ""}` : "Press release"}
            </a>
          </li>
        ))}
      </ul>
    </li>
  );
}

function Authorization({ data }: { data: Buybacks }) {
  const events = data.announcements;
  return (
    <div className="space-y-2" data-block="authorization">
      <h3 className="text-sm font-medium">
        <Metric termId="repurchase_announcement">Authorization</Metric>
      </h3>
      <ul className="space-y-1 text-xs text-neutral-400" aria-label="As tagged in filings">
        {(
          [
            ["repurchase_authorized", data.tagged_authorized],
            ["repurchase_remaining", data.tagged_remaining],
          ] as const
        ).map(([termId, tagged]) =>
          tagged ? (
            <ValuationInputItem key={termId} input={tagged} fallback={termId} />
          ) : (
            <li key={termId}>
              <Metric termId={termId} icon={false} />{" "}
              <Metric termId={termId} icon={false}>
                not tagged in the 10-Q or 10-K
              </Metric>
            </li>
          ),
        )}
      </ul>
      {events.length === 0 ? (
        <p className="text-sm text-neutral-400">
          <Metric termId="repurchase_announcement" icon={false}>
            No authorization, plan or remaining amount stated in 8-Ks since 2021 or in press
            releases.
          </Metric>
        </p>
      ) : (
        <>
          <ul className="space-y-2 text-sm" aria-label="Announcements">
            {events.slice(0, SHOWN).map((event) => (
              <Event key={`${event.kind}-${event.amount}-${event.day}`} event={event} />
            ))}
          </ul>
          {events.length > SHOWN ? (
            <details className="text-sm">
              <summary className="cursor-pointer select-none text-xs text-neutral-400">
                <Metric termId="repurchase_announcement" icon={false}>
                  {events.length - SHOWN} earlier
                </Metric>
              </summary>
              <ul className="mt-2 space-y-2">
                {events.slice(SHOWN).map((event) => (
                  <Event key={`${event.kind}-${event.amount}-${event.day}`} event={event} />
                ))}
              </ul>
            </details>
          ) : null}
        </>
      )}
    </div>
  );
}

/**
 * Buybacks section of the instrument page (M1.4a, ADR-025): the buyback state (M1.4b), then
 * authorization, actual repurchase and net share reduction shown apart (02 §5), as known at the
 * page's As known on time. An announcement is evidence of an authorization, never of a
 * repurchase.
 */
export function BuybacksView({ result }: { result: BuybacksResult }) {
  return (
    <section id="buybacks" aria-labelledby="buybacks-heading" className="space-y-4">
      <h2 id="buybacks-heading" className="text-lg font-medium">
        <Metric termId="buyback_record" zh>
          Buybacks
        </Metric>
      </h2>
      {result.status !== "ok" ? (
        <p role="alert" className="text-sm text-neutral-400">
          Data unavailable: the API could not be reached.
        </p>
      ) : (
        <>
          <p className="text-sm text-neutral-400">
            Authorization, actual repurchase and net share reduction, as known at{" "}
            <Metric termId="point_in_time" icon={false}>
              {formatSgtEt(result.data.known_at)}
            </Metric>
            . An announcement is not a repurchase, and a repurchase is not a smaller share count.
          </p>
          <BuybackStateCard
            state={result.data.state}
            history={result.data.state_history}
            ruleVersion={result.data.rule_version}
          />
          <Authorization data={result.data} />
          {result.data.periods.length === 0 ? (
            <p className="text-sm text-neutral-400">No fiscal years reported yet.</p>
          ) : (
            <>
              <div className="space-y-2" data-block="repurchase">
                <h3 className="text-sm font-medium">
                  <Metric termId="share_repurchases">Actual repurchase</Metric>
                </h3>
                <PeriodTable
                  label="Actual repurchase"
                  periods={result.data.periods}
                  rows={result.data.rows}
                  sections={[{ section: "repurchase", label: null }]}
                  fallback="buyback_record"
                />
              </div>
              <div className="space-y-2" data-block="net-share-reduction">
                <h3 className="text-sm font-medium">
                  <Metric termId="net_share_reduction">Net share reduction</Metric>
                </h3>
                <PeriodTable
                  label="Net share reduction"
                  periods={result.data.periods}
                  rows={result.data.rows}
                  sections={[{ section: "shares", label: null }]}
                  fallback="buyback_record"
                />
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
