import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedDataHealth } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { DataHealthView } from "./DataHealthView";

describe("DataHealthView with a recorded API response", () => {
  it("lists every source in the table and in the mobile cards", () => {
    render(<DataHealthView data={recordedDataHealth} />);
    const count = recordedDataHealth.report.sources.length;
    expect(screen.getAllByRole("row")).toHaveLength(count + 1); // header + one per source
    expect(within(screen.getByRole("list", { name: "Sources" })).getAllByRole("listitem")).toHaveLength(
      count,
    );
  });

  it("shows every freshness state, including sources that are not enabled", () => {
    const { container } = render(<DataHealthView data={recordedDataHealth} />);
    const freshness = Array.from(
      container.querySelectorAll('tbody [data-term-id="data_freshness"]'),
    ).map((el) => el.textContent);
    expect(new Set(freshness)).toEqual(new Set(["Fresh", "Stale", "Failing", "Not enabled"]));
  });

  it("shows runs and open dead letters", () => {
    render(<DataHealthView data={recordedDataHealth} />);
    const runs = within(screen.getByRole("list", { name: "Recent ingestion runs" }));
    expect(runs.getAllByRole("listitem")).toHaveLength(recordedDataHealth.runs.length);
    expect(runs.getAllByText("Dead-lettered").length).toBeGreaterThan(0);
    const letters = within(screen.getByRole("list", { name: "Open dead letters" }));
    expect(letters.getByText(/attempts/)).toBeTruthy();
    expect(letters.queryByText(/SECRET123/)).toBeNull(); // redacted by the API
  });

  it("renders no number outside a glossary-backed metric", () => {
    const { container } = render(<DataHealthView data={recordedDataHealth} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("shows Data unavailable and no numbers when the API is unreachable", () => {
    const { container } = render(<DataHealthView data={null} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
    expect(screen.queryByRole("table")).toBeNull();
    expect(container.textContent).not.toMatch(/\d/);
  });
});
