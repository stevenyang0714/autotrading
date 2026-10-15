import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  recordedPortfolio,
  recordedPortfolioEmpty,
  recordedRiskChecks,
} from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { PortfolioRiskView } from "./PortfolioRiskView";

describe("PortfolioRiskView with recorded API responses", () => {
  it("shows the paper book with its exposures and every limit's use", () => {
    render(
      <PortfolioRiskView
        data={recordedPortfolio}
        checks={recordedRiskChecks}
      />,
    );
    expect(document.querySelector("[data-paper-only]")?.textContent).toContain(
      "PAPER ONLY",
    );
    expect(
      document.querySelector('[data-tile="notional_capital"]')?.textContent,
    ).toContain("100,000.00 USD");
    const position = document.querySelector('[data-position="AAPL"]');
    expect(position?.textContent).toContain("Long");
    expect(position?.textContent).toContain("3.31%");
    expect(position?.textContent).toContain("Information technology");
    const limits = screen.getByRole("table", { name: "Limits" });
    expect(
      limits.querySelector('[data-limit="risk_limit_position"]')?.textContent,
    ).toContain("at most 10.00%");
    expect(
      limits.querySelector('[data-limit="risk_limit_gross"]')?.textContent,
    ).toContain("3.31%");
    expect(screen.getByText(/risk rules 0\.1\.0/)).toBeTruthy();
  });

  it("lists the risk checks with each veto's failed limits, standard checks apart", () => {
    const own = {
      ...recordedRiskChecks,
      checks: recordedRiskChecks.checks.filter((c) => c.trigger !== "standard"),
    };
    const standard = {
      ...recordedRiskChecks,
      checks: recordedRiskChecks.checks.filter((c) => c.trigger === "standard"),
    };
    render(
      <PortfolioRiskView
        data={recordedPortfolio}
        checks={own}
        standard={standard}
      />,
    );
    const checks = screen.getByRole("list", { name: "Risk checks" });
    const vetoed = checks.querySelector(
      'li[data-trigger="trade"][data-verdict="veto"]',
    );
    expect(vetoed?.textContent).toContain("Journal TRADE: buy 1000 AAPL");
    expect(
      vetoed?.querySelector('[data-limit="position"]')?.textContent,
    ).toContain("Position size");
    expect(checks.querySelector('li[data-trigger="standard"]')).toBeNull();
    const standards = screen.getByRole("list", {
      name: "Standard position checks",
    });
    expect(
      standards.querySelector('li[data-trigger="standard"]')?.textContent,
    ).toContain("Standard position");
  });

  it("an empty book says so, and the try form only shows when given", () => {
    const { container } = render(
      <PortfolioRiskView
        data={recordedPortfolioEmpty}
        checks={null}
        knownOn="2026-09-14"
      />,
    );
    expect(
      container.querySelector('[data-block="positions"]')?.textContent,
    ).toContain("No open paper trade");
    expect(
      container.querySelector('[data-block="checks"]')?.textContent,
    ).toContain("Data unavailable");
    expect(container.querySelector('[data-block="try"]')).toBeNull();
  });

  it.each([
    ["with a position", recordedPortfolio],
    ["empty", recordedPortfolioEmpty],
  ] as const)("%s renders no unexplained number", (_name, data) => {
    const { container } = render(
      <PortfolioRiskView data={data} checks={recordedRiskChecks} />,
    );
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
