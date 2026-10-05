import Link from "next/link";

import { Metric } from "@/components/Metric";

/**
 * "As known on" date (M0.5b): a plain GET form, so it works without client JavaScript and the
 * chosen date stays in the URL (?known_on=YYYY-MM-DD). The date means the end of that day in
 * Singapore time; the page shows the exact timestamp it used.
 */
export function AsKnownOnForm({
  ticker,
  knownOn,
  invalid = false,
}: {
  ticker: string;
  knownOn?: string;
  invalid?: boolean;
}) {
  const href = `/instruments/${encodeURIComponent(ticker)}`;
  return (
    <form method="get" action={href} className="flex flex-wrap items-center gap-2 text-sm">
      <label htmlFor="known_on">
        <Metric termId="point_in_time">As known on</Metric>
      </label>
      <input
        id="known_on"
        name="known_on"
        type="date"
        defaultValue={invalid ? "" : (knownOn ?? "")}
        className="rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700"
      />
      <button
        type="submit"
        className="rounded border border-neutral-300 px-3 py-1 hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
      >
        Show
      </button>
      {knownOn ? (
        <Link href={href} className="text-neutral-400 underline-offset-2 hover:underline">
          Today
        </Link>
      ) : null}
      {invalid ? (
        <span role="status" className="text-amber-400">
          Not a calendar date; showing today.
        </span>
      ) : null}
    </form>
  );
}
