import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { chartRows } from "@/lib/macroChart";
import { recordedPayems } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { SeriesChart, chartValue } from "./SeriesChart";

// jsdom has no canvas: stand in for ECharts and keep what the chart was given.
const setOption = vi.fn();
vi.mock("echarts/core", () => ({
  use: vi.fn(),
  init: () => ({ setOption, resize: vi.fn(), dispose: vi.fn() }),
}));
vi.mock("echarts/charts", () => ({ LineChart: {} }));
vi.mock("echarts/components", () => ({
  GridComponent: {},
  TooltipComponent: {},
  DataZoomComponent: {},
  LegendComponent: {},
}));
vi.mock("echarts/renderers", () => ({ CanvasRenderer: {} }));
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    disconnect() {}
  },
);

describe("SeriesChart", () => {
  const rows = chartRows(recordedPayems.now.observations);

  it("draws the value and the first release, explained by the series term", async () => {
    const { container } = render(
      <SeriesChart rows={rows} termId="macro_nonfarm_payrolls" label="Nonfarm payrolls" units="Thous. of Persons" />,
    );
    const figure = container.querySelector("figure")!;
    expect(figure.getAttribute("data-term-id")).toBe("macro_nonfarm_payrolls");
    expect(figure.textContent).toContain("revised points");
    expect(unexplainedNumbers(container)).toEqual([]);
    await waitFor(() => expect(setOption).toHaveBeenCalled());
    const option = setOption.mock.calls[0][0];
    expect(option.series.map((s: { name: string }) => s.name)).toEqual(["Value", "First release"]);
    expect(option.series[0].data).toHaveLength(rows.length);
    const august = rows.findIndex((r) => r.day === "2026-08-01");
    expect(option.series[1].data[august]).toEqual(["2026-08-01", 159075]);
    const tooltip = option.tooltip.formatter([{ data: ["2026-08-01", rows[august].latest] }]);
    expect(tooltip).toContain("First release 159,075 (2026-09-04)");
  });

  it("formats values like the table", () => {
    expect(chartValue(159015)).toBe("159,015");
    expect(chartValue(4.33)).toBe("4.33");
  });
});
