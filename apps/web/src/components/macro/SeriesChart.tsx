"use client";

import { useEffect, useRef } from "react";

import { Metric } from "@/components/Metric";
import type { CompleteTermId } from "@/generated/glossary";
import { type ChartRow, chartSummary } from "@/lib/macroChart";

/** "159,015" or "4.33": a value as the chart labels it. */
export function chartValue(value: number): string {
  return Number.isInteger(value)
    ? value.toLocaleString("en-US")
    : value.toLocaleString("en-US", { maximumFractionDigits: 3 });
}

const LATEST = "#38bdf8"; // sky-400
const FIRST = "#fbbf24"; // amber-400
const AXIS = "#a3a3a3"; // neutral-400
const GRID = "#404040"; // neutral-700

/**
 * Large macro series chart (M0.9, ADR-019): Apache ECharts on a canvas, loaded on this page only.
 * Two lines: the value known at the chosen date and the value as first released (dashed); where
 * they differ the value was revised. Hover (or tap) shows both values with their vintages; drag
 * or pinch to zoom.
 * The figure carries data-metric for the series term, so the canvas and its tooltip count as
 * explained numbers; the caption repeats the range in text for readers without JavaScript.
 */
export function SeriesChart({
  rows,
  termId,
  label,
  units,
}: {
  rows: ChartRow[];
  termId: CompleteTermId;
  label: string;
  units: string | null | undefined;
}) {
  const host = useRef<HTMLDivElement>(null);
  const summary = chartSummary(rows);

  useEffect(() => {
    const element = host.current;
    if (!element || rows.length < 2 || typeof window === "undefined") return;
    let disposed = false;
    let dispose = () => {};
    void (async () => {
      const [core, charts, components, renderers] = await Promise.all([
        import("echarts/core"),
        import("echarts/charts"),
        import("echarts/components"),
        import("echarts/renderers"),
      ]);
      if (disposed) return;
      core.use([
        charts.LineChart,
        components.GridComponent,
        components.TooltipComponent,
        components.DataZoomComponent,
        components.LegendComponent,
        renderers.CanvasRenderer,
      ]);
      const chart = core.init(element, undefined, { renderer: "canvas" });
      const byDay = new Map(rows.map((row) => [row.day, row]));
      chart.setOption({
        animation: false,
        grid: { left: 64, right: 16, top: 32, bottom: 72 },
        legend: { top: 0, textStyle: { color: AXIS }, data: ["Value", "First release"] },
        xAxis: {
          type: "time",
          axisLabel: { color: AXIS },
          axisLine: { lineStyle: { color: GRID } },
        },
        yAxis: {
          type: "value",
          scale: true,
          axisLabel: { color: AXIS, formatter: (v: number) => chartValue(v) },
          splitLine: { lineStyle: { color: GRID } },
        },
        dataZoom: [
          { type: "inside" },
          { type: "slider", bottom: 16, height: 24, textStyle: { color: AXIS } },
        ],
        tooltip: {
          trigger: "axis",
          className: "series-chart-tooltip",
          formatter: (params: unknown) => {
            // The point's own [day, value]: the axis value is a timestamp in the browser's
            // time zone, which can fall on the previous UTC day.
            const items = params as { data: [string, number] }[];
            const day = items[0]?.data[0] ?? "";
            const row = byDay.get(day);
            if (!row) return day;
            const lines = [
              `<b>${row.day}</b>`,
              `Value ${chartValue(row.latest)} (released ${row.latestVintage})`,
            ];
            if (row.revised) {
              lines.push(`First release ${chartValue(row.first)} (${row.firstVintage})`);
            }
            return lines.join("<br/>");
          },
        },
        series: [
          {
            name: "Value",
            type: "line",
            showSymbol: false,
            lineStyle: { color: LATEST, width: 2 },
            itemStyle: { color: LATEST },
            data: rows.map((row) => [row.day, row.latest]),
          },
          {
            name: "First release",
            type: "line",
            // A dashed line only: most monthly releases are revised, so a mark per revised
            // point would bury the line; the gap shows the size, the tooltip the values.
            lineStyle: { color: FIRST, width: 1.5, type: "dashed" },
            itemStyle: { color: FIRST },
            showSymbol: false,
            data: rows.map((row) => [row.day, row.first]),
          },
        ],
      });
      const resize = new ResizeObserver(() => chart.resize());
      resize.observe(element);
      dispose = () => {
        resize.disconnect();
        chart.dispose();
      };
    })();
    return () => {
      disposed = true;
      dispose();
    };
  }, [rows]);

  if (!summary || rows.length < 2) return null;
  return (
    <figure
      data-metric=""
      data-term-id={termId}
      data-last-revised={summary.lastRevised ?? ""}
      className="space-y-2"
      aria-label={`${label} chart`}
    >
      <div
        ref={host}
        data-chart=""
        role="img"
        aria-label={`${label}: ${rows.length} observations from ${summary.from} to ${summary.to}`}
        className="h-80 w-full"
      />
      <figcaption className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-400">
        <span>
          {summary.from} – {summary.to}
          {units ? ` · ${units}` : ""}
        </span>
        <span>
          low {chartValue(summary.low)} · high {chartValue(summary.high)} · latest {chartValue(summary.last)}
        </span>
        <Metric termId="first_release_overlay" icon={false} zh>
          <span>
            <span aria-hidden="true" className="text-amber-300">
              ┄
            </span>{" "}
            first release: {summary.revisedCount} revised points
          </span>
        </Metric>
      </figcaption>
    </figure>
  );
}
