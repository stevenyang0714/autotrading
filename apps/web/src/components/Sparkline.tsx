import type { CompleteTermId } from "@/generated/glossary";

export interface SparkPoint {
  day: string;
  value: string;
}

interface Props {
  points: SparkPoint[];
  /** Glossary term of the plotted values: the figure is the explained metric. */
  termId: CompleteTermId;
  label: string;
  format: (value: number) => string;
  zeroLine?: boolean;
  width?: number;
  height?: number;
}

const PAD = 4;

/**
 * Small server-rendered SVG line chart (M0.6 overview, ADR-016): no client JavaScript and no
 * chart library. The figure carries data-metric for its term, so its min, max and last labels
 * count as explained numbers; the exact series is on the Macro page.
 */
export function Sparkline({ points, termId, label, format, zeroLine = false, width = 240, height = 56 }: Props) {
  const values = points.map((p) => Number(p.value));
  if (values.length < 2) return null;
  let low = Math.min(...values);
  let high = Math.max(...values);
  if (zeroLine) {
    low = Math.min(low, 0);
    high = Math.max(high, 0);
  }
  const span = high - low || 1;
  const x = (i: number) => PAD + (i * (width - 2 * PAD)) / (values.length - 1);
  const y = (v: number) => PAD + ((high - v) * (height - 2 * PAD)) / span;
  const path = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const last = values[values.length - 1];
  const first = points[0].day;
  const end = points[points.length - 1].day;
  return (
    <figure data-metric="" data-term-id={termId} className="space-y-1">
      <svg
        role="img"
        aria-label={`${label}: ${values.length} points from ${first} to ${end}`}
        viewBox={`0 0 ${width} ${height}`}
        className="h-14 w-full text-sky-400"
        preserveAspectRatio="none"
      >
        {zeroLine && low < 0 && high > 0 ? (
          <line
            x1={PAD}
            x2={width - PAD}
            y1={y(0)}
            y2={y(0)}
            className="stroke-neutral-600"
            strokeDasharray="3 3"
            strokeWidth={1}
          />
        ) : null}
        <path d={path} fill="none" stroke="currentColor" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        <circle cx={x(values.length - 1)} cy={y(last)} r={2.5} className="fill-sky-300" />
      </svg>
      <figcaption className="flex justify-between text-[11px] text-neutral-500">
        <span>
          {first} – {end}
        </span>
        <span>
          low {format(Math.min(...values))} · high {format(Math.max(...values))}
        </span>
      </figcaption>
    </figure>
  );
}
