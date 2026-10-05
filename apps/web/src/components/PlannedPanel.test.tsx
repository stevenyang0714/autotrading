import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DASHBOARDS } from "@/lib/dashboards";

import { PlannedPanel } from "./PlannedPanel";

describe("PlannedPanel", () => {
  it.each(DASHBOARDS.map((dashboard) => [dashboard.label, dashboard] as const))(
    "%s shows its phase and no other numbers",
    (_label, dashboard) => {
      const { container } = render(<PlannedPanel dashboard={dashboard} />);

      const phase = screen.getByTestId("planned-phase");
      expect(phase.textContent).toBe(`Planned — Phase ${dashboard.plannedPhase}`);
      expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(dashboard.label);

      const rest = container.cloneNode(true) as HTMLElement;
      rest.querySelector('[data-testid="planned-phase"]')?.remove();
      expect(rest.textContent).not.toMatch(/\d/);
    },
  );
});
