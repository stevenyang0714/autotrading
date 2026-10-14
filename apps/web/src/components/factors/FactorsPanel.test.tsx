import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  recordedFactorsAapl,
  recordedFactorsNvda,
  recordedFactorsNvdaEarlier,
  recordedFactorsTlt,
} from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { FactorsPanel } from "./FactorsPanel";

describe("FactorsPanel with recorded API responses", () => {
  it("shows each trend measure with its value, percentile in own history, window and inputs", () => {
    render(<FactorsPanel result={{ status: "ok", data: recordedFactorsNvda }} />);
    const momentum = document.querySelector('[data-measure="momentum_12_1"]');
    expect(momentum?.textContent).toContain("12-1 month momentum");
    expect(momentum?.textContent).toContain("+21.09%");
    expect(momentum?.textContent).toContain("17th percentile of 29 month ends since");
    expect(momentum?.textContent).toContain("2025-10-02 to 2026-09-03");
    expect(momentum?.textContent).toMatch(/close 2025-10-02: [\d.]+/);
    expect(document.querySelector('[data-measure="beta_252d"]')?.textContent).toContain("1.882");
    expect(document.querySelector('[data-measure="relative_momentum_12_1"]')?.textContent).toContain(
      "+4.60 pts",
    );
    expect(screen.getByText(/factor definitions 0\.1\.0/)).toBeTruthy();
  });

  it("shows value and quality for a company and none for an ETF", () => {
    render(<FactorsPanel result={{ status: "ok", data: recordedFactorsAapl }} />);
    const roic = document.querySelector('[data-measure="roic"]');
    expect(roic?.textContent).toContain("90.32%");
    expect(roic?.textContent).toContain("100th percentile of 33 month ends");
    const pe = document.querySelector('[data-measure="pe_ratio_ttm"]');
    expect(pe?.textContent).toContain("38.18x");
    // too few closes: unavailable with the reason, never a guess
    const unavailable = document.querySelector('[data-measure="momentum_12_1"]');
    expect(unavailable?.getAttribute("data-reason")).toBe("unavailable");
    expect(unavailable?.textContent).toContain("251 closes known; 253 needed");

    const { container } = render(<FactorsPanel result={{ status: "ok", data: recordedFactorsTlt }} />);
    expect(container.querySelector('[data-group="value"]')).toBeNull();
    expect(container.querySelector('[data-group="trend"]')).not.toBeNull();
  });

  it("as known on an earlier date shows the snapshot stored by then", () => {
    render(<FactorsPanel result={{ status: "ok", data: recordedFactorsNvdaEarlier }} />);
    expect(recordedFactorsNvdaEarlier.price?.known_at.startsWith("2024-06-08")).toBe(true);
    expect(document.querySelector('[data-block="factors"]')?.textContent).toContain("last close 2024-06-07");
  });

  it("says when the API is unavailable and hides itself for an unknown instrument", () => {
    render(<FactorsPanel result={{ status: "unavailable" }} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
    const { container } = render(<FactorsPanel result={{ status: "not_found" }} />);
    expect(container.innerHTML).toBe("");
  });

  it.each([
    ["NVDA", recordedFactorsNvda],
    ["AAPL", recordedFactorsAapl],
    ["TLT", recordedFactorsTlt],
    ["NVDA earlier", recordedFactorsNvdaEarlier],
  ] as const)("%s renders no unexplained number", (_name, data) => {
    const { container } = render(<FactorsPanel result={{ status: "ok", data }} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
