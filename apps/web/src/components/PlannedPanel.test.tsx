import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DASHBOARDS } from "@/lib/dashboards";
import { unexplainedNumbers } from "@/test/numbers";

import { PlannedPanel } from "./PlannedPanel";

describe("PlannedPanel", () => {
  it.each(DASHBOARDS.map((dashboard) => [dashboard.label, dashboard] as const))(
    "%s shows its phase and explains every label",
    (_label, dashboard) => {
      const { container } = render(<PlannedPanel dashboard={dashboard} />);

      const phase = screen.getByTestId("planned-phase");
      expect(phase.textContent).toBe(`Planned — Phase ${dashboard.plannedPhase}`);
      expect(phase.closest("[data-metric]")?.getAttribute("data-term-id")).toBe("planned_phase");

      const heading = screen.getByRole("heading", { level: 1 });
      expect(heading.textContent).toContain(dashboard.label);
      expect(heading.querySelector("[data-metric]")?.getAttribute("data-term-id")).toBe(
        dashboard.termId,
      );
      expect(
        screen.getByRole("button", { name: `What is ${dashboard.label}?` }),
      ).toBeTruthy();

      expect(unexplainedNumbers(container)).toEqual([]);
    },
  );
});
