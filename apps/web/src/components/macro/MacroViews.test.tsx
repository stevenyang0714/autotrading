import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedMacroSeries, recordedPayems } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { MacroList } from "./MacroList";
import { SeriesView } from "./SeriesView";

function augustRow(container: HTMLElement) {
  const row = container.querySelector('tr[data-date="2026-08-01"]');
  if (!row) throw new Error("August 2026 row missing");
  return row.textContent ?? "";
}

describe("MacroList", () => {
  it("lists the registry in order with explained numbers", () => {
    const { container } = render(<MacroList data={recordedMacroSeries} />);
    const items = within(screen.getByRole("list", { name: "Macro series" })).getAllByRole("listitem");
    expect(items).toHaveLength(11);
    expect(items[0].textContent).toContain("CPIAUCSL");
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("shows Data unavailable without numbers when the API is down", () => {
    const { container } = render(<MacroList data={null} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
    expect(container.textContent).not.toMatch(/\d/);
  });
});

describe("SeriesView (PAYEMS, recorded)", () => {
  it("shows the first release as known before the revision", () => {
    const { container } = render(
      <SeriesView data={recordedPayems.beforeRevision} knownOn="2026-09-30" />,
    );
    const august = augustRow(container);
    expect(august).toContain("159,075");
    expect(august).not.toContain("Revised");
    expect(container.querySelector("#known_on")).toHaveProperty("value", "2026-09-30");
  });

  it("shows today's revised value with its first release", () => {
    const { container } = render(<SeriesView data={recordedPayems.now} />);
    const august = augustRow(container);
    expect(august).toContain("159,015");
    expect(august).toContain("Revised");
    expect(august).toContain("159,075 on 2026-09-04");
  });

  it.each(Object.entries(recordedPayems))("%s renders no unexplained number", (_name, data) => {
    const { container } = render(<SeriesView data={data} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
