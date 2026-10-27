import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FactorsPanel } from "@/components/factors/FactorsPanel";
import { TaiwanList } from "@/components/taiwan/TaiwanList";
import { TaiwanView } from "@/components/taiwan/TaiwanView";
import { recordedFactors2330, recordedTaiwan, recordedTaiwan0050, recordedTaiwan2330 } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

describe("TaiwanView with recorded API responses (M3.7)", () => {
  it("shows the TWSE close, valuation, margin and FinMind flows with their files", () => {
    const { container } = render(
      <TaiwanView
        code="2330"
        result={{ status: "ok", data: recordedTaiwan2330 }}
        factors={<FactorsPanel result={{ status: "ok", data: recordedFactors2330 }} />}
        knownOn="2026-10-23"
      />,
    );
    expect(container.querySelector("h1")?.textContent).toContain("台積電（TSMC）");
    const prices = container.querySelector('[data-block="taiwan-prices"]');
    expect(prices?.textContent).toContain("NT$2,385.00");
    expect(prices?.textContent).toContain("-35.00");
    expect(prices?.textContent).toContain("NT$2,420.00"); // the reference price
    expect(prices?.textContent).toContain("上市個股日成交資訊");
    expect(prices?.textContent).toContain("public from 2026-10-22 23:59 Taipei");
    const valuation = container.querySelector('[data-measure="exchange_pe_ratio"]');
    expect(valuation?.textContent).toContain("27.65x");
    expect(valuation?.textContent).toContain("no percentile yet: 1 of 12 month ends");
    expect(valuation?.textContent).toContain("earnings and book value of 2026Q2");
    const margin = container.querySelector('[data-measure="margin_balance"]');
    expect(margin?.textContent).toContain("35,472 lots (+142)");
    // 2026-10-22's balances chain to the stored 2026-10-21 ones: verified, no caveat
    expect(container.querySelector('[data-block="taiwan-margin"]')?.textContent).not.toContain(
      "not yet checked",
    );
    // the flows come from FinMind (M3.7b): the groups' net buying, the holding, the attribution
    const flows = container.querySelector('[data-block="taiwan-flows"]');
    expect(flows?.querySelectorAll("tbody tr")).toHaveLength(4);
    expect(flows?.querySelector('[data-measure="inst_total_net"]')?.textContent).toContain("shares");
    expect(flows?.querySelector('[data-measure="foreign_ratio"]')?.textContent).toContain("68.58%");
    expect(flows?.textContent).toContain("資料來源：FinMind");
    expect(flows?.textContent).toContain("FinMind TaiwanStockInstitutionalInvestorsBuySell");
    const attribution = container.querySelector('[data-block="attribution"]');
    expect(attribution?.textContent).toContain("臺灣證券交易所 2026");
    expect(attribution?.textContent).toContain("政府資料開放授權條款");
    expect(attribution?.querySelector('[data-attribution="FinMind"]')?.textContent).toContain("資料來源：FinMind");
    // factors against 0050, never SPY
    expect(container.querySelector('[data-block="factors"]')?.textContent).toContain("Against 0050");
    expect(container.textContent).not.toContain("SPY");
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("names 0050 as an ETF and says when the API is down", () => {
    const { container } = render(<TaiwanView code="0050" result={{ status: "ok", data: recordedTaiwan0050 }} />);
    expect(container.querySelector("h1")?.textContent).toContain("元大台灣50");
    expect(container.textContent).toContain("ETF on the Taiwan Stock Exchange");
    expect(unexplainedNumbers(container)).toEqual([]);
    render(<TaiwanView code="2330" result={{ status: "unavailable" }} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
  });
});

describe("TaiwanList with recorded API responses (M3.7)", () => {
  it("lists the ten companies and 0050 with their latest close and the attribution", () => {
    const { container } = render(<TaiwanList data={recordedTaiwan} />);
    const items = container.querySelectorAll("li[data-code]");
    expect(items).toHaveLength(11);
    expect(items[0]?.textContent).toContain("台積電（TSMC）");
    expect(items[0]?.textContent).toContain("NT$2,385.00");
    expect(items[0]?.querySelector("a")?.getAttribute("href")).toBe("/instruments/2330");
    expect(items[10]?.getAttribute("data-code")).toBe("0050");
    expect(container.textContent).toContain("market cap on 2026-10-21");
    expect(container.querySelector('[data-block="attribution"]')).not.toBeNull();
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("says when the API is down", () => {
    render(<TaiwanList data={null} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
  });
});
