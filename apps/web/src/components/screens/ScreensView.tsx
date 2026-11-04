import { AsKnownOnForm } from "@/components/AsKnownOnForm";
import { Metric } from "@/components/Metric";
import { DemoBanner } from "@/components/prices/DemoBanner";
import { Sparkline } from "@/components/Sparkline";
import type {
  ScreenMetrics,
  ScreenMover,
  ScreenResult,
  TaiwanScreens,
  TaiwanScreensHistory,
  WatchLine,
} from "@/lib/api";
import { FLAGS, STATES, STATUS_MARKS, screenTerm, share, signedPct, times, twd, twdMillions, z } from "@/lib/screens";
import { formatTaipei } from "@/lib/time";

export const HREF = "/dashboards/opportunity-radar/taiwan-screens";

function Industry({ code, names }: { code: string; names: Record<string, string> }) {
  return (
    <Metric termId="twse_industry" icon={false}>
      {names[code] ?? code}
    </Metric>
  );
}

function Source({ source }: { source: WatchLine["source"] }) {
  if (!source) return <span className="text-neutral-500">–</span>;
  return (
    <span className="text-xs text-neutral-500">
      <Metric termId="feed_status" icon={false}>
        {source.feed}
      </Metric>{" "}
      <Metric termId="point_in_time" icon={false}>
        {formatTaipei(source.published_at)}
      </Metric>{" "}
      <span data-identifier="" title={source.bar_id}>
        row {source.bar_id.slice(0, 8)}
      </span>
    </span>
  );
}

function Flags({ flags }: { flags: string[] }) {
  if (flags.length === 0) return null;
  return (
    <span className="text-xs text-amber-300">
      <Metric termId="screen_adjusted_return" icon={false}>
        {flags.map((f) => FLAGS[f] ?? f).join("; ")}
      </Metric>
    </span>
  );
}

function Numbers({ m }: { m: ScreenMetrics }) {
  return (
    <>
      <td className="px-2 py-1 text-right">
        <Metric termId="twse_close" icon={false}>
          {twd(m.close)}
        </Metric>
      </td>
      <td className="px-2 py-1 text-right">
        <Metric termId="screen_adjusted_return" icon={false}>
          {signedPct(m.change_1d)}
        </Metric>
      </td>
      <td className="px-2 py-1 text-right">
        <Metric termId="screen_adjusted_return" icon={false}>
          {signedPct(m.change_5d)}
        </Metric>
      </td>
      <td className="px-2 py-1 text-right">
        <Metric termId="screen_volume_ratio" icon={false}>
          {times(m.volume_ratio)}
        </Metric>
      </td>
    </>
  );
}

function MoverRow({ mover, names }: { mover: ScreenMover; names: Record<string, string> }) {
  return (
    <tr data-code={mover.code} className="border-t border-neutral-800">
      <td className="px-2 py-1">
        <span data-identifier="">{mover.code}</span> {mover.name}
      </td>
      <td className="px-2 py-1">
        <Industry code={mover.industry} names={names} />
      </td>
      <Numbers m={mover.metrics} />
      <td className="px-2 py-1 text-right">
        <Metric termId="screen_z_score" icon={false}>
          {`${z(mover.metrics.z1)} / ${z(mover.metrics.z5)}`}
        </Metric>
      </td>
      <td className="px-2 py-1 text-right">
        <Metric termId="screen_liquidity" icon={false}>
          {twdMillions(mover.metrics.avg_trade_value)}
        </Metric>
      </td>
      <td className="px-2 py-1">
        <Flags flags={mover.flags} />
        <Source source={mover.source} />
      </td>
    </tr>
  );
}

function Movers({ data }: { data: TaiwanScreens }) {
  const run = data.run!;
  return (
    <section className="space-y-2" aria-label="Movers" data-block="movers">
      <h2 className="text-lg font-medium">
        <Metric termId="screen_mover" zh>
          Movers
        </Metric>
      </h2>
      <p className="text-sm text-neutral-400">
        <Metric termId="screen_mover" icon={false}>
          {`${run.movers_count} liquid stocks moved at least ${data.rules?.movers.z_threshold ?? "2.5"} times their own usual move, or traded at least ${data.rules?.movers.volume_ratio ?? "3"} times their usual volume; the largest change first.`}
        </Metric>
      </p>
      {run.movers.length === 0 ? (
        <p className="text-sm text-neutral-500">No mover this session.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" aria-label="Movers">
            <thead className="text-left text-xs text-neutral-400">
              <tr>
                <th className="px-2 py-1">Stock</th>
                <th className="px-2 py-1">
                  <Metric termId="twse_industry">Industry</Metric>
                </th>
                <th className="px-2 py-1 text-right">
                  <Metric termId="twse_close">Close</Metric>
                </th>
                <th className="px-2 py-1 text-right">
                  <Metric termId="screen_adjusted_return">1 day</Metric>
                </th>
                <th className="px-2 py-1 text-right">
                  <Metric termId="screen_adjusted_return">5 days</Metric>
                </th>
                <th className="px-2 py-1 text-right">
                  <Metric termId="screen_volume_ratio">Volume</Metric>
                </th>
                <th className="px-2 py-1 text-right">
                  <Metric termId="screen_z_score">z1 / z5</Metric>
                </th>
                <th className="px-2 py-1 text-right">
                  <Metric termId="screen_liquidity">Avg value</Metric>
                </th>
                <th className="px-2 py-1">Source</th>
              </tr>
            </thead>
            <tbody>
              {run.movers.map((m) => (
                <MoverRow key={m.code} mover={m} names={data.industries} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function WatchRow({
  line,
  names,
  term,
}: {
  line: WatchLine;
  names: Record<string, string>;
  term: ReturnType<typeof screenTerm>;
}) {
  return (
    <tr data-code={line.code} data-state={line.state} className="border-t border-neutral-800 align-top">
      <td className="px-2 py-1">
        <span data-identifier="">{line.code}</span> {line.name}
        <div>
          <Industry code={line.industry} names={names} />
        </div>
      </td>
      <td className="px-2 py-1">
        <Metric termId="screen_watch_list" icon={false}>
          {STATES[line.state] ?? line.state}
        </Metric>
        <div className="text-xs text-neutral-500">
          <Metric termId="screen_watch_list" icon={false}>
            {`since ${line.entered}, ${line.sessions} session${line.sessions === 1 ? "" : "s"}`}
          </Metric>
        </div>
        {line.reason ? (
          <div className="text-xs text-amber-300">
            <Metric termId="screen_watch_list" icon={false}>
              {line.reason}
            </Metric>
          </div>
        ) : null}
      </td>
      {line.metrics ? (
        <Numbers m={line.metrics} />
      ) : (
        <td className="px-2 py-1 text-neutral-500" colSpan={4}>
          No reading this session
        </td>
      )}
      <td className="px-2 py-1 text-xs">
        <ul className="space-y-0.5" aria-label={`${line.code} conditions`}>
          {line.conditions.map((c, i) => (
            <li key={`${c.kind}-${i}`} data-status={c.status}>
              <Metric termId={term} icon={false}>
                {`${STATUS_MARKS[c.status] ?? c.status} ${c.label}`}
              </Metric>
            </li>
          ))}
          {line.notes.map((n, i) => (
            <li key={`note-${i}`} data-note={n.status} className="text-neutral-400">
              <Metric termId="screen_flow_note" icon={false}>
                {`${STATUS_MARKS[n.status] ?? n.status} ${n.label}${n.days !== null && n.days !== undefined ? ` (${n.days}/${n.of})` : ""}`}
              </Metric>
            </li>
          ))}
        </ul>
      </td>
      <td className="px-2 py-1">
        <Flags flags={line.flags} />
        <Source source={line.source} />
      </td>
    </tr>
  );
}

function Screen({
  screen,
  data,
}: {
  screen: ScreenResult;
  data: TaiwanScreens;
}) {
  const definition = data.rules?.definitions.find((d) => d.screen_id === screen.screen_id);
  const term = screenTerm(screen.screen_id);
  const count = (state: string) => screen.lines.filter((l) => l.state === state).length;
  return (
    <section className="space-y-2" data-screen={screen.screen_id} aria-label={screen.name_zh}>
      <h2 className="text-lg font-medium">
        <Metric termId={term} zh>
          {screen.name_zh}
        </Metric>
      </h2>
      {definition ? (
        <div className="grid gap-2 text-xs text-neutral-400 md:grid-cols-3">
          <div>
            <p className="text-neutral-300">Conditions (all required)</p>
            <ul className="list-disc pl-4" aria-label={`${screen.name_zh} conditions`}>
              {definition.conditions.map((c) => (
                <li key={c}>
                  <Metric termId={term} icon={false}>
                    {c}
                  </Metric>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-neutral-300">Notes (shown, not required)</p>
            <ul className="list-disc pl-4">
              {definition.notes.map((c) => (
                <li key={c}>
                  <Metric termId="screen_flow_note" icon={false}>
                    {c}
                  </Metric>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-neutral-300">A watch ends when</p>
            <ul className="list-disc pl-4">
              {definition.invalidation.map((c) => (
                <li key={c}>
                  <Metric termId="screen_watch_list" icon={false}>
                    {c}
                  </Metric>
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
      <p className="text-sm text-neutral-400">
        <Metric termId="screen_watch_list" icon={false}>
          {`${screen.meeting} met it this session · ${count("entered")} entered · ${count("on_watch")} on watch · ${count("invalidated")} ended · ${count("expired")} expired · ${screen.unavailable} not judged (missing inputs)`}
        </Metric>
      </p>
      {screen.lines.length === 0 ? (
        <p className="text-sm text-neutral-500">Nothing on the watch list.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" aria-label={`${screen.name_zh} watch list`}>
            <thead className="text-left text-xs text-neutral-400">
              <tr>
                <th className="px-2 py-1">Stock</th>
                <th className="px-2 py-1">
                  <Metric termId="screen_watch_list">State</Metric>
                </th>
                <th className="px-2 py-1 text-right">
                  <Metric termId="twse_close">Close</Metric>
                </th>
                <th className="px-2 py-1 text-right">
                  <Metric termId="screen_adjusted_return">1 day</Metric>
                </th>
                <th className="px-2 py-1 text-right">
                  <Metric termId="screen_adjusted_return">5 days</Metric>
                </th>
                <th className="px-2 py-1 text-right">
                  <Metric termId="screen_volume_ratio">Volume</Metric>
                </th>
                <th className="px-2 py-1">
                  <Metric termId={term}>Conditions</Metric>
                </th>
                <th className="px-2 py-1">Source</th>
              </tr>
            </thead>
            <tbody>
              {screen.lines.map((line) => (
                <WatchRow key={`${line.code}-${line.state}`} line={line} names={data.industries} term={term} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function History({ history }: { history: TaiwanScreensHistory | null }) {
  if (history === null) {
    return <p className="text-sm text-neutral-500">Data unavailable: the history check could not be loaded.</p>;
  }
  return (
    <section className="space-y-2" aria-label="History check" data-block="history">
      <h2 className="text-lg font-medium">
        <Metric termId="screen_history_check" zh>
          History check
        </Metric>
      </h2>
      <p className="text-sm text-neutral-400">
        <Metric termId="screen_history_check" icon={false}>
          {`How many stocks met each screen on every judged session (${history.points.length} sessions); never their returns (OD-7).${history.industry_basis ? ` Backfilled sessions use the industry ${history.industry_basis.replace("first_known", "first known on")}.` : ""}`}
        </Metric>
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        {history.summary.map((s) => {
          const points = history.points.map((p) => ({ day: p.session, value: String(p.meeting[s.screen_id] ?? 0) }));
          return (
            <div key={s.screen_id} className="space-y-1 rounded border border-neutral-800 px-3 py-2" data-history={s.screen_id}>
              <p className="text-sm">
                <Metric termId={screenTerm(s.screen_id)} icon={false}>
                  {s.screen_id}
                </Metric>
              </p>
              <p className="text-xs text-neutral-400">
                <Metric termId="screen_history_check" icon={false}>
                  {`median ${s.median_meeting ?? "–"} a session · most ${s.max_meeting ?? "–"} · none on ${share(s.zero_share)} of sessions`}
                </Metric>
              </p>
              <Sparkline
                points={points}
                termId="screen_history_check"
                label={`${s.screen_id}: stocks meeting it per session`}
                format={(v) => v.toFixed(0)}
              />
            </div>
          );
        })}
      </div>
    </section>
  );
}

/**
 * The Taiwan screens (M3.11, ADR-042): every TWSE-listed company read each session. The movers,
 * each screen's watch list with its conditions and the bar behind each reading, the history
 * check and the sources. A research screen and a watch list, not advice.
 */
export function ScreensView({
  data,
  history,
  knownOn,
  invalidKnownOn,
}: {
  data: TaiwanScreens;
  history: TaiwanScreensHistory | null;
  knownOn?: string;
  invalidKnownOn: boolean;
}) {
  const run = data.run;
  return (
    <section className="space-y-6" data-page="taiwan-screens">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          <Metric termId="page_taiwan_screens" zh>
            Taiwan Screens
          </Metric>
        </h1>
        <p role="note" className="text-sm text-neutral-400">
          <Metric termId="page_taiwan_screens" icon={false}>
            {data.detail}
          </Metric>
        </p>
        <AsKnownOnForm href={HREF} knownOn={knownOn} invalid={invalidKnownOn} />
        <DemoBanner statuses={data.demo ? ["fixture"] : []} />
        {data.pending ? (
          <p role="status" className="text-sm text-amber-300" data-pending="">
            <Metric termId="screen_not_judged" icon={false}>
              {`${data.pending.session} not judged: ${data.pending.reason}`}
            </Metric>
          </p>
        ) : null}
        {run ? (
          <p className="text-sm text-neutral-400" data-run="">
            Session{" "}
            <Metric termId="point_in_time" icon={false}>
              {run.session}
            </Metric>{" "}
            ·{" "}
            <Metric termId="screen_coverage" icon={false}>
              {`coverage ${run.coverage.covered.toLocaleString("en-US")} of ${run.coverage.expected.toLocaleString("en-US")} (${share(run.coverage.ratio)}), ${run.coverage.liquid.toLocaleString("en-US")} liquid, ${run.coverage.read.toLocaleString("en-US")} read`}
            </Metric>{" "}
            ·{" "}
            <Metric termId="screen_rules" icon={false}>
              {`screen rules ${run.rule_version}`}
            </Metric>
            {data.rules ? (
              <>
                {" "}
                <span data-identifier="" title={data.rules.content_sha256}>
                  sha256 {data.rules.content_sha256.slice(0, 12)}
                </span>
              </>
            ) : null}{" "}
            ·{" "}
            <Metric termId="point_in_time" icon={false}>
              {`${data.backfilled ? "backfilled" : (data.trigger ?? "")} ${data.recorded_at ? formatTaipei(data.recorded_at) : ""}`}
            </Metric>
          </p>
        ) : null}
      </header>
      {run ? (
        <>
          <Movers data={data} />
          {run.screens.map((s) => (
            <Screen key={s.screen_id} screen={s} data={data} />
          ))}
        </>
      ) : (
        <p className="text-sm text-neutral-400">
          No judged session yet: the screens run at 08:05 and 10:00 Singapore time once the TWSE files of a session are
          stored.
        </p>
      )}
      <History history={history} />
      <footer className="space-y-1 text-xs text-neutral-500" data-block="attribution">
        <p>
          <span data-quoted="">{data.attribution.text}</span>
        </p>
        {data.attribution.supplementary.map((s) => (
          <p key={s.provider}>
            <span data-quoted="">{s.text}</span>
          </p>
        ))}
      </footer>
    </section>
  );
}
