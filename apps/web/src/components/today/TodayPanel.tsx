import Link from "next/link";
import type { ReactNode } from "react";

import { Metric } from "@/components/Metric";
import type { CompleteTermId } from "@/generated/glossary";
import type {
  Alerts,
  Holdings,
  MarketState,
  OpportunityCandidates,
  SourceHealth,
  TaiwanList,
  TaiwanScreens,
} from "@/lib/api";
import { FLAG_LABELS, money, signedMoney, weight } from "@/lib/holdings";
import { formatSgtEt, formatTaipei } from "@/lib/time";

const WEEK_MS = 7 * 24 * 3600 * 1000;
const TOP = 5;

function Card({
  termId,
  title,
  href,
  link,
  block,
  children,
}: {
  termId: CompleteTermId;
  title: string;
  href: string;
  link: string;
  block: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-2 rounded border border-neutral-800 px-3 py-2" data-today={block} aria-label={title}>
      <h2 className="text-sm font-medium">
        <Metric termId={termId}>{title}</Metric>
      </h2>
      <div className="space-y-1 text-sm">{children}</div>
      <p className="text-xs">
        <Link href={href} className="text-neutral-400 underline-offset-2 hover:underline">
          {link}
        </Link>
      </p>
    </section>
  );
}

function Unavailable({ what }: { what: string }) {
  return <p className="text-neutral-400">{`Data unavailable: ${what} could not be loaded.`}</p>;
}

function HoldingsCard({ holdings }: { holdings: Holdings | null }) {
  return (
    <Card termId="page_holdings" title="Your holdings" href="/holdings" link="Holdings" block="holdings">
      {holdings === null ? (
        <Unavailable what="the holdings" />
      ) : holdings.entries === 0 ? (
        <p className="text-neutral-400">Nothing recorded yet: record your deposits and buys on the Holdings page.</p>
      ) : (
        <>
          <p className="text-lg tabular-nums">
            <Metric termId="holdings_equity" icon={false}>
              {money(holdings.equity_usd, "USD")}
            </Metric>{" "}
            <Metric termId="holdings_change" icon={false} className="text-sm text-neutral-400">
              {`${signedMoney(holdings.change_usd, "USD")} in 24 h`}
            </Metric>
          </p>
          <ol className="space-y-0.5" aria-label="Largest weights">
            {[...holdings.positions]
              .filter((p) => p.weight !== null)
              .sort((a, b) => Number(b.weight) - Number(a.weight))
              .slice(0, TOP)
              .map((p) => (
                <li key={`${p.account}:${p.instrument_id}`} className="flex justify-between gap-2">
                  <span data-identifier="">{p.symbol}</span>
                  <Metric termId="holding_weight" icon={false} className="tabular-nums">
                    {weight(p.weight)}
                  </Metric>
                </li>
              ))}
          </ol>
          {holdings.flags.length > 0 || holdings.positions.some((p) => p.flags.length > 0) ? (
            <p className="text-xs text-amber-300">
              <Metric termId="holding_flag" icon={false}>
                {holdings.flags.length > 0
                  ? (FLAG_LABELS[holdings.flags[0]] ?? holdings.flags[0])
                  : "a position needs a look (see Holdings)"}
              </Metric>
            </p>
          ) : null}
        </>
      )}
    </Card>
  );
}

function PushesCard({ alerts, now }: { alerts: Alerts | null; now: string }) {
  const since = new Date(now).getTime() - WEEK_MS;
  const pushed = (alerts?.entries ?? []).filter((a) => a.delivered_at && new Date(a.delivered_at).getTime() >= since);
  const open = alerts ? Object.values(alerts.open_by_level).reduce((sum, n) => sum + n, 0) : 0;
  return (
    <Card termId="alert_delivery" title="Pushed this week" href="/dashboards/alerts-center" link="Alerts Center" block="pushes">
      {alerts === null ? (
        <Unavailable what="the alerts" />
      ) : (
        <>
          {pushed.length === 0 ? (
            <p className="text-neutral-400">Nothing pushed to Telegram in the past week.</p>
          ) : (
            <ul className="space-y-1" aria-label="Pushed alerts">
              {pushed.slice(0, TOP).map((a) => (
                <li key={a.id} data-alert={a.id}>
                  <Metric termId="alert_delivery" icon={false}>
                    {a.title}
                  </Metric>
                  <span className="block text-xs text-neutral-500">
                    <Metric termId="alert_delivery" icon={false}>
                      {`pushed ${formatSgtEt(a.delivered_at as string)}`}
                    </Metric>
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-neutral-400">
            <Metric termId="alert_delivery" icon={false}>
              {`${open} open alerts in the app`}
            </Metric>
          </p>
        </>
      )}
    </Card>
  );
}

function session(open: boolean, lastClose: string, format: (iso: string) => string): string {
  return `${open ? "open now" : "closed"} · last close ${format(lastClose)}`;
}

function MarketsCard({ us, taiwan }: { us: MarketState | null; taiwan: TaiwanList | null }) {
  return (
    <Card termId="market_session" title="Markets" href="/instruments" link="Instruments" block="markets">
      <p>
        <span className="text-neutral-400">US </span>
        <Metric termId="market_session" icon={false}>
          {us ? session(us.open, us.last_close, formatSgtEt) : "unavailable"}
        </Metric>
      </p>
      <p>
        <span className="text-neutral-400">Taiwan </span>
        <Metric termId="taiwan_market_session" icon={false}>
          {taiwan ? session(taiwan.market_session.open, taiwan.market_session.last_close, formatTaipei) : "unavailable"}
        </Metric>
      </p>
    </Card>
  );
}

function RadarCard({ candidates }: { candidates: OpportunityCandidates | null }) {
  return (
    <Card
      termId="dashboard_opportunity_radar"
      title="Radar"
      href="/dashboards/opportunity-radar"
      link="Opportunity Radar"
      block="radar"
    >
      {candidates === null ? (
        <Unavailable what="the radar" />
      ) : (
        <p>
          <Metric termId="dashboard_opportunity_radar" icon={false}>
            {`${candidates.companies.length} companies, ${candidates.etfs.length} ETFs, ${candidates.momentum.length} momentum names flagged by the rules`}
          </Metric>
        </p>
      )}
    </Card>
  );
}

function ScreensCard({ screens }: { screens: TaiwanScreens | null }) {
  const run = screens?.run ?? null;
  return (
    <Card
      termId="page_taiwan_screens"
      title="Taiwan screens"
      href="/dashboards/opportunity-radar/taiwan-screens"
      link="Taiwan Screens"
      block="screens"
    >
      {screens === null ? (
        <Unavailable what="the Taiwan screens" />
      ) : run === null ? (
        <p className="text-neutral-400">No judged session yet.</p>
      ) : (
        <>
          <p>
            <Metric termId="screen_mover" icon={false}>
              {`${run.session}: ${run.movers_count} movers`}
            </Metric>
          </p>
          <ul className="space-y-0.5 text-neutral-300" aria-label="Screens">
            {run.screens.map((s) => (
              <li key={s.screen_id} data-screen={s.screen_id}>
                <Metric termId="screen_watch_list" icon={false}>
                  {`${s.name_zh}: ${s.lines.filter((l) => l.state === "entered").length} new, ${s.lines.filter((l) => l.state === "on_watch").length} on watch`}
                </Metric>
              </li>
            ))}
          </ul>
          {screens.pending ? (
            <p className="text-amber-300">
              <Metric termId="screen_not_judged" icon={false}>
                {`${screens.pending.session} not judged yet`}
              </Metric>
            </p>
          ) : null}
        </>
      )}
    </Card>
  );
}

function HealthCard({ sources }: { sources: SourceHealth[] | null }) {
  const trouble = (sources ?? []).filter((s) => s.enabled && (s.freshness === "stale" || s.freshness === "failing"));
  return (
    <Card termId="data_freshness" title="Data health" href="/system/data-health" link="Data Health" block="health">
      {sources === null ? (
        <Unavailable what="the source status" />
      ) : trouble.length === 0 ? (
        <p className="text-emerald-300">Every enabled source is fresh.</p>
      ) : (
        <ul className="space-y-0.5 text-amber-300" aria-label="Sources needing a look">
          {trouble.map((s) => (
            <li key={s.id}>
              <Metric termId="data_freshness" icon={false}>
                {`${s.name}: ${s.freshness}`}
              </Metric>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/**
 * Today (M3.10, ADR-041 H10): what to look at first, on the home page above the macro overview.
 * Your holdings (local only), what was pushed to Telegram this week, both markets' sessions, the
 * radar's count, the Taiwan screens' latest session (M3.11) and any source that needs a look. Shown when viewing now; As known on keeps the
 * overview alone.
 */
export function TodayPanel({
  holdings,
  alerts,
  candidates,
  screens = null,
  us,
  taiwan,
  sources,
  now,
}: {
  holdings: Holdings | null;
  alerts: Alerts | null;
  candidates: OpportunityCandidates | null;
  screens?: TaiwanScreens | null;
  us: MarketState | null;
  taiwan: TaiwanList | null;
  sources: SourceHealth[] | null;
  now: string;
}) {
  return (
    <section className="space-y-3" data-page="today">
      <h1 className="text-2xl font-semibold">
        <Metric termId="page_today" zh>
          Today
        </Metric>
      </h1>
      <p className="text-sm text-neutral-500">
        <Metric termId="page_today" icon={false}>
          {`As of ${formatSgtEt(now)}. Rule signals and records, not advice; nothing here places an order.`}
        </Metric>
      </p>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <HoldingsCard holdings={holdings} />
        <PushesCard alerts={alerts} now={now} />
        <MarketsCard us={us} taiwan={taiwan} />
        <RadarCard candidates={candidates} />
        <ScreensCard screens={screens} />
        <HealthCard sources={sources} />
      </div>
    </section>
  );
}
