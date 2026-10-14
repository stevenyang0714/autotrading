import { expect, test, type Page } from "@playwright/test";

const DASHBOARD_SLUGS = [
  "global-monitor",
  "market-regime",
  "opportunity-radar",
  "fundamental-research",
  "corporate-actions",
  "event-transmission",
  "earnings",
  "x-expert-watch",
  "policy-monitor",
  "congress-trades",
  "options-vol",
  "portfolio-risk",
  "alerts-center",
  "strategy-lab",
  "execution",
];

function trackConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

test("every page loads without console errors", async ({ page }) => {
  // About thirty pages in one test, several computing every company on load: allow for a
  // busy stack while the other workers run.
  test.setTimeout(60_000);
  const errors = trackConsoleErrors(page);
  const pages = [
    "/",
    "/system/data-health",
    "/instruments",
    "/instruments/AAPL",
    "/macro",
    "/macro/PAYEMS",
    "/news",
    "/news?kind=press_release",
    "/system/audit-log",
    "/system/audit-log?table=sources&action=insert",
    "/system/reconciliation",
    "/system/reconciliation?status=pass&form=10-K",
    "/system/reconciliation/0000320193-25-000079",
    "/instruments/META",
    "/instruments/SPY",
    "/system/progress",
    "/journal/new?ticker=AAPL",
    ...DASHBOARD_SLUGS.map((s) => `/dashboards/${s}`),
  ];
  for (const path of pages) {
    const response = await page.goto(path);
    expect(response?.status(), path).toBe(200);
    await expect(page.locator("h1")).toBeVisible();
  }
  expect(errors).toEqual([]);
});

test("unknown dashboard returns 404", async ({ page }) => {
  const response = await page.goto("/dashboards/does-not-exist");
  expect(response?.status()).toBe(404);
});

test("Data Health shows the registered sources from the live API", async ({ page, isMobile }) => {
  await page.goto("/system/data-health");
  // Next.js adds its own role="alert" route announcer, so check the text instead.
  await expect(page.getByText("Data unavailable")).toHaveCount(0);
  for (const name of [/SEC EDGAR/, /FRED/, /Alpaca/, /Massive/, /GDELT/]) {
    await expect(page.getByRole("link", { name }).first()).toBeVisible();
  }
  if (!isMobile) {
    await expect(page.getByRole("table")).toBeVisible();
    const freshness = (name: RegExp) =>
      page.getByRole("row", { name }).locator('[data-term-id="data_freshness"]');
    // SEC EDGAR (M0.5), FRED (M0.6) and GDELT (M0.8) are enabled: judged, whatever their
    // state. Massive stays off until its license check (ADR-004).
    await expect(freshness(/SEC EDGAR/)).toHaveText(/^(Fresh|Stale|Failing)$/);
    await expect(freshness(/FRED/)).toHaveText(/^(Fresh|Stale|Failing)$/);
    await expect(freshness(/GDELT/)).toHaveText(/^(Fresh|Stale|Failing)$/);
    await expect(freshness(/Massive/)).toHaveText("Not enabled");
  }
});

async function unexplainedNumbers(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const walker = document.createTreeWalker(document.querySelector("main")!, NodeFilter.SHOW_TEXT);
    const found: string[] = [];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const text = node.textContent ?? "";
      const parent = node.parentElement;
      if (/\d/.test(text) && parent && parent.offsetParent !== null) {
        // [data-quoted]: a publisher's own words shown verbatim (news headlines, summaries).
        if (!parent.closest("[data-metric],[data-identifier],[data-quoted],code")) found.push(text.trim());
      }
    }
    return found;
  });
}

for (const path of [
  "/system/data-health",
  "/instruments",
  "/instruments/AAPL",
  "/instruments/AAPL?known_on=2010-01-27",
  "/instruments/XOM",
  "/macro",
  "/macro/PAYEMS",
  "/macro/PAYEMS?known_on=2026-09-30",
  "/",
  "/?known_on=2026-09-30",
  "/news",
  "/news?ticker=NVDA",
  "/news?kind=article&tier=2",
  "/system/audit-log",
  "/system/audit-log?table=sources",
  "/system/reconciliation",
  "/system/reconciliation/0000320193-25-000079",
  "/instruments/META",
  "/system/progress",
  "/dashboards/fundamental-research",
  "/dashboards/fundamental-research?sort=roic&dir=desc",
  "/dashboards/corporate-actions",
  "/dashboards/corporate-actions?known_on=2026-04-15",
  "/dashboards/earnings",
  "/dashboards/earnings?known_on=2026-05-01",
  "/dashboards/strategy-lab",
  "/dashboards/alerts-center?status=all&backfilled=1",
  "/dashboards/market-regime",
  "/dashboards/market-regime?known_on=2026-09-15",
  "/dashboards/opportunity-radar",
  "/dashboards/opportunity-radar?known_on=2026-10-06&sort=momentum_6_1&dir=desc",
  "/instruments/AAPL?known_on=2026-10-06",
  "/instruments/TLT",
]) {
  test(`numbers on ${path} are all explained`, async ({ page }) => {
    await page.goto(path);
    expect(await unexplainedNumbers(page)).toEqual([]);
  });
}

// ---------- instrument page (M0.5b) ----------

function fy2008NetIncome(page: Page) {
  // Columns: newest fiscal year first; as known in January 2010 that is FY2009, then FY2008.
  return page
    .getByRole("table", { name: "Annual results" })
    .getByRole("row")
    .filter({ has: page.locator('th [data-term-id="net_income"]') })
    .locator("td")
    .nth(1);
}

test("AAPL: As known on before the 2010 10-K/A shows the original FY2008 net income", async ({
  page,
}) => {
  await page.goto("/instruments/AAPL?known_on=2010-01-25");
  await expect(fy2008NetIncome(page)).toContainText("$4.834B");
  await expect(fy2008NetIncome(page)).not.toContainText("Restated");

  await page.locator("#known_on").fill("2010-01-27");
  await page.getByRole("button", { name: "Show" }).click();
  await expect(page).toHaveURL(/known_on=2010-01-27/);
  await expect(fy2008NetIncome(page)).toContainText("$6.119B");
  await expect(fy2008NetIncome(page)).toContainText("Restated");
  await expect(fy2008NetIncome(page)).toContainText("was $4.834B");
});

test("AAPL values link to the SEC filing that reported them", async ({ page }) => {
  await page.goto("/instruments/AAPL");
  const link = page.getByRole("link", { name: "10-K 0000320193-25-000079" }).first();
  await expect(link).toHaveAttribute(
    "href",
    "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/0000320193-25-000079-index.htm",
  );
});

test("AAPL: per-share history is continuous across the 2020 split (M1.1)", async ({ page }) => {
  await page.goto("/instruments/AAPL");
  const history = page.getByRole("table", { name: "Per-share history" });
  const fy2017 = history.locator("th", { hasText: "2017-09-30" });
  await expect(fy2017).toBeVisible();
  const eps = history.getByRole("row").filter({ has: page.locator('th [data-term-id="eps_diluted"]') });
  await expect(eps).toContainText("$9.21");
  await expect(eps).toContainText("$2.3025 split-adjusted (÷4)");
  await expect(page.getByRole("list", { name: "Latest reported values" })).toContainText(
    "4-for-1 on 2020-08-31",
  );
});

test("AAPL: quarters and trailing twelve months, with inputs (M1.1)", async ({ page }) => {
  await page.goto("/instruments/AAPL");
  const quarterly = page.getByRole("table", { name: "Quarterly" });
  await expect(quarterly.locator("thead th")).toHaveCount(10);
  const fcf = page
    .getByRole("table", { name: "Annual results" })
    .getByRole("row")
    .filter({ has: page.locator('th [data-term-id="free_cash_flow"]') });
  await fcf.locator("summary").first().click();
  await expect(fcf).toContainText("Operating Cash Flow");
});

test("AAPL valuation uses only an end-of-day close (M1.2)", async ({ page }) => {
  await page.goto("/instruments/AAPL");
  const status = await page.locator("[data-price-status]").getAttribute("data-price-status");
  const cards = page.locator("[data-valuation]");
  await expect(cards).toHaveCount(8);
  if (status === "ok") {
    // Local stack: real end-of-day closes.
    await expect(page.locator('[data-valuation="market_cap"]')).toContainText(/\$\d\.\d{3}T/);
    await expect(page.locator('[data-valuation="pe_ratio_ttm"]')).toContainText(/\d+\.\d{2}x/);
  } else {
    // CI replays fixture closes (recorded up to 2026-10-05; later, none within reach): no
    // multiple may be computed from them (errata E4).
    expect(["fixture", "none", "stale"]).toContain(status);
    await expect(page.locator("[data-price-status]")).toContainText("Data unavailable");
    for (const card of await cards.all()) {
      await expect(card).toContainText("Data unavailable");
      await expect(card).not.toContainText(/\d+\.\d{2}x|\d+\.\d{2}%/);
    }
  }
});

test("AAPL fair value: model output with its assumptions, range and dates (M1.3a)", async ({ page }) => {
  await page.goto("/instruments/AAPL");
  const block = page.locator("#fair-value");
  await expect(block.locator("[data-model-output]")).toContainText("Model output, not fact");
  await expect(block.locator("[data-assumptions]")).toBeVisible();
  await expect(block.locator("[data-discount-rate]")).toContainText(/= 10-year Treasury \d+(\.\d+)?%/);
  // CI replays real filings and the 10-year yield, so the DCF stands either way.
  await expect(block.locator("[data-dcf-status]")).toHaveAttribute("data-dcf-status", "ok");
  for (const name of ["bear", "base", "bull"]) {
    await expect(block.locator(`[data-scenario="${name}"]`)).toContainText(/\$[\d,]+\.\d{2}/);
  }
  const comparison = block.getByRole("list", { name: "Price comparison" });
  if ((await comparison.getAttribute("data-comparison-price")) === "ok") {
    await expect(block.locator('[data-comparison="implied_upside"]')).toContainText(/-?\d+\.\d{2}%/);
    await expect(block.locator('[data-comparison="margin_of_safety"]')).toContainText(/-?\d+\.\d{2}%/);
  } else {
    // CI: fixture closes are never a valuation price (errata E4).
    for (const name of ["implied_upside", "margin_of_safety", "reverse_dcf_growth"]) {
      await expect(block.locator(`[data-comparison="${name}"]`)).toContainText("Data unavailable");
    }
  }
  await expect(block.getByRole("table", { name: "Relative valuation" }).locator("[data-relative]")).toHaveCount(6);
  await expect(block.locator("[data-model-dates]")).toContainText(/latest filing 10-[QK]/);
  await block.locator("[data-edit-assumptions] summary").click();
  await expect(block.getByRole("form", { name: "Edit assumptions" })).toBeVisible();
});

test("Saving assumptions adds a version; switching back reproduces the result (M1.3a)", async ({
  page,
  isMobile,
}) => {
  // Versions are append-only, so this writes only to CI's throwaway database, and once.
  test.skip(!process.env.CI, "saves a permanent assumption version; CI database only");
  test.skip(isMobile, "one writer, so version numbers do not race");
  await page.goto("/instruments/AAPL");
  const block = page.locator("#fair-value");
  const before = (await block.locator("[data-assumptions]").getAttribute("data-assumptions")) ?? "";
  const baseBefore = await block.locator('[data-scenario="base"] .text-xl').textContent();

  await block.locator("[data-edit-assumptions] summary").click();
  const growth = block.getByLabel(/Base growth/);
  const next = (await growth.inputValue()) === "6" ? "7" : "6";
  await growth.fill(next);
  await block.getByLabel(/Reason/).fill("e2e: base growth changed");
  await block.getByRole("button", { name: "Save as a new version" }).click();

  await expect(page).toHaveURL(/assumptions=\d+/);
  const saved = block.locator("[data-assumptions]");
  await expect(saved).not.toHaveAttribute("data-assumptions", before);
  await expect(saved).toContainText("e2e: base growth changed");
  await expect(block.locator('[data-scenario="base"]')).toContainText(`Base: ${next}% a year`);
  await expect(block.locator('[data-scenario="base"] .text-xl')).not.toHaveText(baseBefore ?? "");

  // The earlier version still gives exactly the earlier result.
  await block.getByLabel("Version", { exact: true }).selectOption(before === "default" ? "default" : before.slice(1));
  await block.getByRole("button", { name: "Use" }).click();
  await expect(block.locator("[data-assumptions]")).toHaveAttribute("data-assumptions", before);
  await expect(block.locator('[data-scenario="base"] .text-xl')).toHaveText(baseBefore ?? "");
});

test("Fundamental Research sorts companies and opens a Research Record (M1.3b)", async ({ page }) => {
  await page.goto("/dashboards/fundamental-research");
  const rows = page.locator("tbody tr[data-ticker]");
  expect(await rows.count()).toBeGreaterThanOrEqual(3);
  await expect(page.locator('[data-group="model"]')).toContainText("model output, not fact");

  // Both pages compute every company or the whole record on load: allow for a busy stack.
  await page.getByRole("link", { name: "Sort by ROIC" }).click();
  await expect(page).toHaveURL(/sort=roic&dir=desc/, { timeout: 15_000 });
  const roic = await page.locator('tbody td[data-column="roic"]').allTextContents();
  const values = roic.filter((text) => text.endsWith("%")).map((text) => Number(text.slice(0, -1)));
  expect(values.length).toBeGreaterThan(0);
  expect(values).toEqual([...values].sort((a, b) => b - a));
  expect(roic.slice(0, values.length).every((text) => text.endsWith("%"))).toBe(true); // n/m, n/a last

  await page.locator('tr[data-ticker="AAPL"]').getByRole("link", { name: "AAPL" }).click();
  await expect(page).toHaveURL(/\/instruments\/AAPL#research-record$/, { timeout: 15_000 });
  await expect(page.getByRole("table", { name: "Research Record" })).toBeVisible();
});

test("Research Record shows a value's inputs and the 10-K behind it (M1.3b)", async ({ page }) => {
  await page.goto("/instruments/AAPL");
  const record = page.getByRole("table", { name: "Research Record" });
  await expect(record.locator("thead th[data-period]")).toHaveCount(6);
  const fy2025 = record.locator('tr[data-row="roic"] td').nth(1);
  await expect(fy2025).toContainText(/\d+\.\d{2}%/);
  await fy2025.getByText("inputs").click();
  await expect(fy2025.getByRole("link", { name: "10-K 0000320193-25-000079" }).first()).toBeVisible();
});

test("AAPL buybacks keep authorization, repurchase and net share reduction apart (M1.4a)", async ({
  page,
}) => {
  await page.goto("/instruments/AAPL");
  const section = page.locator("#buybacks");
  for (const block of ["authorization", "repurchase", "net-share-reduction"]) {
    await expect(section.locator(`[data-block="${block}"]`)).toBeVisible();
  }
  const latest = section.getByRole("list", { name: "Announcements" }).locator("li[data-event-kind]").first();
  await expect(latest).toContainText(/Authorization increase \$\d+ billion/);
  await expect(latest.locator("q[data-quoted]").first()).toContainText(/authorized/);
  await expect(latest.getByRole("link").first()).toHaveAttribute("href", /^https:\/\/www\.sec\.gov\//);
  await expect(section.getByRole("table", { name: "Actual repurchase" }).locator('tr[data-row="share_repurchases"]')).toContainText(/\$\d+\.\d{3}B/);
  await expect(section.getByRole("table", { name: "Net share reduction" }).locator('tr[data-row="net_share_reduction"]')).toContainText(/shares/);
});

test("AAPL buybacks show the stored state with each condition against its threshold (M1.4b)", async ({
  page,
}) => {
  await page.goto("/instruments/AAPL");
  const card = page.locator('#buybacks [data-block="state"]');
  // The replay stores states now and at month ends since 2025 (fixture prices: no market cap).
  await expect(card.locator("[data-state]").first()).toHaveText(/^(No state|WATCH|ACTIVE|HIGH-CONVICTION candidate)$/);
  await expect(card).toContainText("rule v0.2.0");
  await expect(card.locator('[data-condition="watch.announcement"]')).toContainText("(within 365 days)");
  await expect(card.locator('[data-level="trade_ready"]')).toContainText("Unreachable in Phase 1.");
  await expect(card.locator('[data-block="score"]')).toContainText("default weights, unvalidated");
  expect(await card.getByRole("list", { name: "State history" }).locator("li").count()).toBeGreaterThan(1);
});

test("Corporate Actions reviews every company's state and opens its buybacks (M1.4b)", async ({ page }) => {
  await page.goto("/dashboards/corporate-actions");
  const table = page.getByRole("table", { name: "Threshold review" });
  expect(await table.locator("tbody tr[data-ticker]").count()).toBeGreaterThanOrEqual(3);
  await expect(table.locator('th[data-column="active.quarter_repurchase"]')).toContainText("≥ 0.5%");
  await expect(page.getByText("Thresholds are defaults, not validated.")).toBeVisible();
  await expect(page.getByRole("list", { name: "AAPL state history" })).toBeVisible();

  // An earlier date shows the state stored by then.
  await page.goto("/dashboards/corporate-actions?known_on=2026-04-15");
  await expect(page.getByText(/Showing the states stored by/)).toContainText("2026-04-15");

  await page.locator('tr[data-ticker="AAPL"]').getByRole("link", { name: "AAPL" }).click();
  await expect(page).toHaveURL(/\/instruments\/AAPL\?known_on=2026-04-15#buybacks$/, { timeout: 15_000 });
  await expect(page.locator('#buybacks [data-block="state"]')).toBeVisible();
});

test("AAPL earnings show each release at its acceptance time with actuals (M1.5)", async ({ page }) => {
  await page.goto("/instruments/AAPL");
  const section = page.locator("#earnings");
  const latest = section.locator("[data-event]").first();
  await expect(latest).toContainText(/\d{2}:\d{2} ET/);
  await expect(latest).toContainText(/after the close|before the open|during the session/);
  await expect(latest.getByRole("table", { name: "Quarter actuals" })).toBeVisible();
  await expect(latest.locator('tr[data-row="revenue"]')).toContainText(/\$\d+\.\d{3}B/);
  await expect(latest.locator("[data-consensus]")).toContainText("Consensus estimate: Data unavailable");
  await expect(latest.locator("[data-guidance]")).toBeVisible();
});

test("Earnings dashboard lists each company's latest release and opens it (M1.5)", async ({ page }) => {
  await page.goto("/dashboards/earnings");
  const latest = page.getByRole("table", { name: "Latest releases" });
  expect(await latest.locator("tbody tr[data-ticker]").count()).toBeGreaterThanOrEqual(3);
  await expect(latest.locator('tr[data-ticker="AAPL"]')).toContainText("Data unavailable");
  await latest.locator('tr[data-ticker="AAPL"]').getByRole("link", { name: "AAPL" }).click();
  await expect(page).toHaveURL(/\/instruments\/AAPL#earnings$/, { timeout: 15_000 });
  await expect(page.locator("#earnings [data-event]").first()).toBeVisible();
});

test("Strategy Lab shows the paper journal and the signals, and opens a new card (M1.6)", async ({ page }) => {
  await page.goto("/dashboards/strategy-lab");
  await expect(page.locator("[data-paper-only]")).toContainText("PAPER ONLY");
  await expect(page.locator("[data-paper-only]")).toContainText("no order can be sent");
  await expect(page.locator('[data-block="signals"]')).toBeVisible();
  await expect(page.locator('[data-block="journal"]')).toBeVisible();
  await page.locator("#new-ticker").fill("AAPL");
  await page.locator('[data-block="journal"]').getByRole("button", { name: "Write" }).click();
  await expect(page).toHaveURL(/\/journal\/new\?ticker=AAPL/, { timeout: 15_000 });
  const form = page.getByRole("form", { name: "New Thesis Card" });
  await expect(form).toBeVisible();
  expect(await form.locator('input[name="evidence"]').count()).toBeGreaterThanOrEqual(3);
});

test("the instrument page has the company's paper journal (M1.6)", async ({ page }) => {
  await page.goto("/instruments/AAPL");
  const section = page.locator("#journal");
  await expect(section).toContainText("Paper only: decisions are records, never orders.");
  await expect(section.getByRole("link", { name: "Write a Thesis Card" })).toHaveAttribute(
    "href",
    "/journal/new?ticker=AAPL",
  );
});

test("A NO TRADE and a paper TRADE are recorded alike, replay identical, and the TRADE exits (M1.6)", async ({
  page,
  isMobile,
}) => {
  // Journal entries are append-only, so this writes only to CI's throwaway database, and once.
  test.skip(!process.env.CI, "writes permanent journal entries; CI database only");
  test.skip(isMobile, "one writer");
  test.setTimeout(90_000);
  const write = async (trade: boolean) => {
    await page.goto("/journal/new?ticker=AAPL");
    const form = page.getByRole("form", { name: "New Thesis Card" });
    await form.locator('textarea[name="thesis"]').fill(`e2e: ${trade ? "buy" : "pass on"} the buyback compounder`);
    const boxes = form.locator('input[name="evidence"]');
    for (const i of [0, 1, 2]) await boxes.nth(i).check();
    await form.locator('textarea[name="invalidation"]').fill("Repurchases stop.");
    if (trade) {
      await form.getByRole("radio", { name: /Paper TRADE/ }).check();
      await form.locator('input[name="quantity"]').fill("5");
    }
    await form.getByRole("button", { name: "Save Thesis Card" }).click();
    await expect(page).toHaveURL(/\/journal\/[0-9a-f-]{36}$/, { timeout: 20_000 });
    await expect(page.locator("[data-replay]")).toHaveAttribute("data-replay", "identical");
    return page.url();
  };

  await write(false);
  await expect(page.getByRole("list", { name: "Decisions" })).toContainText("NO TRADE: Priced in");

  const tradeUrl = await write(true);
  const decisions = page.getByRole("list", { name: "Decisions" });
  await expect(decisions).toContainText("paper TRADE buy 5");
  await expect(decisions.locator('[data-performance="open"]')).toBeVisible();
  await decisions.getByRole("form", { name: "Exit" }).getByRole("button", { name: "Exit at the last close" }).click();
  await expect(page).toHaveURL(tradeUrl, { timeout: 20_000 });
  await expect(decisions).toContainText("paper exit sell 5");
  await expect(decisions.locator('[data-performance="closed"]')).toBeVisible();

  await page.goto("/dashboards/strategy-lab");
  const table = page.getByRole("table", { name: "Journal entries" });
  await expect(table.locator('tr[data-decision="no_trade"]').first()).toContainText("NO TRADE: Priced in");
  await expect(table.locator('tr[data-decision="trade"]').first()).toContainText("exited");
});

test("Opportunity Radar lists each instrument's trend and each company's value and quality (M2.2)", async ({
  page,
}) => {
  await page.goto("/dashboards/opportunity-radar");
  const trend = page.getByRole("table", { name: "Trend and risk" });
  expect(await trend.locator("tbody tr[data-ticker]").count()).toBeGreaterThanOrEqual(11); // 8 ETFs and the companies
  await expect(trend.locator('tr[data-ticker="SPY"] [data-column="beta_252d"]')).toContainText("n/m");
  const fundamentals = page.getByRole("table", { name: "Value and quality" });
  expect(await fundamentals.locator("tbody tr[data-ticker]").count()).toBeGreaterThanOrEqual(3);
  await expect(page.getByText(/never ranked against the other instruments/).first()).toBeVisible();
  // As known on a date the recorded closes cover (they end on 2026-10-05; later they are stale).
  await page.goto("/dashboards/opportunity-radar?known_on=2026-10-06");
  await expect(page.getByText(/Showing what was known by/)).toContainText("2026-10-06");
  await expect(trend.locator('tr[data-ticker="TLT"] [data-column="momentum_6_1"]')).toContainText("%");
  // An ETF opens its own page with its trend measures.
  await trend.locator('tr[data-ticker="TLT"] a').click();
  await expect(page).toHaveURL(/\/instruments\/TLT\?known_on=2026-10-06#factors$/, { timeout: 15_000 });
  await expect(page.locator("h1")).toContainText("Exchange-traded fund");
  const factors = page.locator('[data-block="factors"]');
  await expect(factors.locator('[data-measure="momentum_6_1"]')).toHaveAttribute("data-reason", "value");
  await expect(factors.locator('[data-group="value"]')).toHaveCount(0);
});

test("a company page shows its trend and factors against its own history (M2.2)", async ({ page }) => {
  await page.goto("/instruments/AAPL?known_on=2026-10-06#factors");
  const factors = page.locator('[data-block="factors"]');
  await expect(factors.getByRole("heading", { name: /Trend and factors/ })).toBeVisible();
  expect(await factors.locator("[data-measure]").count()).toBeGreaterThanOrEqual(9);
  await expect(factors.locator('[data-group="quality"] [data-measure="roic"]')).toBeVisible();
  await expect(factors.getByText(/factor definitions \d+\.\d+\.\d+/)).toBeVisible();
});

test("Market Regime shows the stress state, five dimensions, nine flags and the history (M2.1)", async ({
  page,
}) => {
  await page.goto("/dashboards/market-regime");
  await expect(page.locator("[data-stress]")).toBeVisible();
  await expect(page.getByRole("list", { name: "Dimensions" }).locator("[data-dimension]")).toHaveCount(5);
  await expect(page.getByRole("list", { name: "Stress flags" }).locator("[data-flag]")).toHaveCount(9);
  await expect(page.getByText(/regime rules \d+\.\d+\.\d+/).first()).toBeVisible();
  expect(await page.locator('tr[data-row="stress"] [data-state]').count()).toBeGreaterThanOrEqual(2);
  // As known on an earlier date: that date's assessment, never a later one.
  await page.goto("/dashboards/market-regime?known_on=2026-09-15");
  await expect(page.getByText(/Showing what was known by/)).toContainText("2026-09-15");
  const assessed = await page.locator("[data-stress]").textContent();
  expect(assessed ?? "").not.toMatch(/Assessed for 2026-(09-(1[6-9]|2\d|30)|1[0-2])/);
});

test("Alerts Center shows each company's level and alerts with their rules and evidence (M1.7)", async ({
  page,
}) => {
  await page.goto("/dashboards/alerts-center?status=all&backfilled=1");
  await expect(page.locator("[data-in-app]")).toContainText("IN-APP ONLY");
  const levels = page.getByRole("list", { name: "Convergence by company" });
  await expect(levels.locator("[data-company]").first()).toBeVisible();
  await expect(levels.locator('[data-check="4"]').first()).toHaveAttribute("data-status", "unavailable");
  const first = page.getByRole("list", { name: "Alerts" }).locator("[data-alert]").first();
  await expect(first).toContainText(/alert rules \d+\.\d+\.\d+/);
  await expect(first.getByRole("list", { name: "Evidence" }).locator("li").first()).toBeVisible();
  // The filter keeps its choices in the URL.
  await page.getByRole("form", { name: "Filter alerts" }).locator('select[name="status"]').selectOption("open");
  await page.getByRole("form", { name: "Filter alerts" }).getByRole("button", { name: "Filter" }).click();
  await expect(page).toHaveURL(/status=open/, { timeout: 15_000 });
});

test("Acknowledging an alert is recorded once and audited (M1.7)", async ({ page, isMobile }) => {
  // Acknowledgements are append-only, so this writes only to CI's throwaway database, and once.
  test.skip(!process.env.CI, "writes a permanent acknowledgement; CI database only");
  test.skip(isMobile, "one writer");
  await page.goto("/dashboards/alerts-center?backfilled=1");
  const open = page.locator('[data-alert][data-acknowledged="no"]').first();
  const id = await open.getAttribute("data-alert");
  await open.getByLabel("Note (optional)").fill("e2e: seen");
  await open.getByRole("button", { name: "Acknowledge" }).click();
  await expect(page.locator(`[data-alert="${id}"]`)).toHaveCount(0, { timeout: 20_000 });
  await page.goto("/dashboards/alerts-center?status=acknowledged&backfilled=1");
  await expect(page.locator(`[data-alert="${id}"]`)).toContainText("e2e: seen");
  await page.goto("/system/audit-log?table=alert_acknowledgements");
  await expect(page.getByText(/acknowledged: /).first()).toBeVisible();
});

test("Reconciliation lists Apple's 10-K as pass and opens its items (M1.1)", async ({ page }) => {
  await page.goto("/system/reconciliation");
  const apple = page.locator("[data-filing]:visible", { hasText: "0000320193-25-000079" });
  await expect(apple.locator("[data-status]")).toHaveText("pass");
  await apple.getByRole("link").click();
  await expect(page).toHaveURL(/\/system\/reconciliation\/0000320193-25-000079$/);
  await expect(page.getByRole("table", { name: "Reconciliation items" })).toContainText(
    "416,161,000,000",
  );
});

test("XOM shows its predecessor issuer", async ({ page }) => {
  await page.goto("/instruments/XOM");
  await expect(page.getByRole("list", { name: "Predecessor issuers" })).toContainText(
    "Exxon Mobil Corp",
  );
});

// ---------- overview, freshness, progress (M0.6, ADR-016) ----------
// Content checks use past "As known on" dates, so they hold as new data arrives.

test("Overview shows six blocks with charts and cited insights", async ({ page }) => {
  await page.goto("/?known_on=2026-10-05");
  for (const id of ["inflation", "labor", "growth", "policy", "curve", "risk"]) {
    const block = page.locator(`[data-block="${id}"]`);
    await expect(block.locator("svg[role=img]")).toBeVisible();
    await expect(block).toContainText("Based on");
  }
  await expect(page.locator('[data-block="labor"]')).toContainText(
    "Aug 2026 revised -60K from its first release",
  );
});

test("Overview as known before the payroll revision", async ({ page }) => {
  await page.goto("/?known_on=2026-09-30");
  await expect(page.locator('[data-block="labor"]')).toContainText("in Aug 2026");
  await expect(page.locator('[data-block="labor"]')).not.toContainText("revised -60K");
});

test("pages show how fresh their data is", async ({ page }) => {
  for (const path of ["/", "/macro", "/instruments/AAPL"]) {
    await page.goto(path);
    const freshness = page.getByRole("list", { name: "Data freshness" });
    await expect(freshness).toBeVisible();
    await expect(freshness.locator('[data-term-id="data_freshness"]').first()).toBeVisible();
  }
});

test("Build Progress reads the milestones", async ({ page }) => {
  await page.goto("/system/progress");
  await expect(page.locator('[data-milestone="M0.1"]')).toHaveAttribute("data-status", "done");
  await expect(page.getByRole("list", { name: "Open decisions" })).toContainText("OD-2");
});

test.describe("Chinese hints", () => {
  test.skip(({ isMobile }) => isMobile, "hover is a desktop interaction");

  test("key labels carry a Chinese name and tooltips explain in Chinese", async ({ page }) => {
    await page.goto("/?known_on=2026-10-05");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("總覽");
    await page.getByText("非農就業人數").first().hover();
    await expect(page.getByRole("tooltip")).toContainText("非農就業人數");
  });
});

// ---------- prices (M0.7, ADR-017) ----------

test("every price carries its feed status", async ({ page }) => {
  for (const path of ["/", "/instruments", "/instruments/AAPL"]) {
    await page.goto(path);
    const prices = page.locator('[data-term-id="last_price"]:not([role]) >> visible=true');
    const count = await prices.count();
    for (let i = 0; i < count; i++) {
      // The badge sits in the same tile, row or price block as the price.
      const holder = prices.nth(i).locator("xpath=ancestor::*[self::li or self::section][1]");
      await expect(holder.locator("[data-feed-status]").first(), `${path} price ${i}`).toBeVisible();
    }
  }
});

test("DEMO DATA banner appears exactly when recorded prices are shown", async ({ page }) => {
  for (const path of ["/", "/instruments", "/instruments/AAPL"]) {
    await page.goto(path);
    const recorded = await page.locator('[data-feed-status="fixture"], [data-feed-status="demo"]').count();
    // CI replays recorded Alpaca data (make replay-fixtures), labelled fixture.
    if (process.env.CI) expect(recorded, path).toBeGreaterThan(0);
    await expect(page.locator("[data-demo-banner]"), path).toHaveCount(recorded > 0 ? 1 : 0);
  }
});

test("a past date shows that day's last public close", async ({ page }) => {
  // As known on 2026-09-30 (end of day SGT, midday in New York): the 09-29 close.
  await page.goto("/instruments/AAPL?known_on=2026-09-30");
  const price = page.getByRole("region", { name: "Price" });
  await expect(price).toContainText("close of 2026-09-29");
  await expect(price.locator("[data-feed-status]").first()).toBeVisible();
  await expect(price).not.toContainText("US market");
});

// ---------- news (M0.8, ADR-018) ----------

test("news stories link to the original articles", async ({ page }) => {
  await page.goto("/news");
  const stories = page.getByRole("list", { name: "News stories" }).locator(":scope > li");
  await expect(stories.first()).toBeVisible();
  const href = await stories.first().getByRole("link").first().getAttribute("href");
  expect(href).toMatch(/^https?:\/\//);
  expect(href).not.toContain("127.0.0.1");
  await expect(page.getByRole("link", { name: "News discovery via the GDELT Project" })).toHaveAttribute(
    "href",
    "https://www.gdeltproject.org/",
  );
});

test("news filters by company and the instrument page shows its news", async ({ page }) => {
  // AAPL: its newsroom feed is replayed in CI (SEC fixtures cover AAPL and XOM only).
  await page.goto("/news?ticker=AAPL");
  const stories = page.getByRole("list", { name: "News stories" }).locator(":scope > li");
  await expect(stories.first()).toContainText("AAPL");
  await page.goto("/instruments/AAPL");
  await expect(page.getByRole("region", { name: "Recent news" })).toBeVisible();
});

test("DEMO DATA banner on news replayed from fixtures", async ({ page }) => {
  await page.goto("/news");
  const banner = page.locator("[data-demo-banner]");
  // CI replays recorded news labelled fixture (make replay-fixtures); live data has no banner.
  await expect(banner).toHaveCount(process.env.CI ? 1 : 0);
});

// ---------- M0.9: macro chart and audit log (ADR-019) ----------

test("the macro chart draws the series with its first release", async ({ page, isMobile }) => {
  await page.goto("/macro/PAYEMS");
  const chart = page.locator("[data-chart]");
  await expect(chart.locator("canvas").first()).toBeVisible();
  if (!isMobile) {
    const box = await chart.boundingBox();
    await page.mouse.move(box!.x + box!.width * 0.9, box!.y + box!.height * 0.4);
    await expect(page.locator(".series-chart-tooltip")).toContainText("Value");
  }
  const figure = page.locator("figure[data-last-revised]");
  // August 2026 payrolls were revised on 2026-10-02; as known on 2026-09-30, July was the
  // newest revised month.
  await expect(figure).toHaveAttribute("data-last-revised", "2026-08-01");
  await page.goto("/macro/PAYEMS?known_on=2026-09-30");
  await expect(page.locator("[data-chart] canvas").first()).toBeVisible();
  await expect(figure).toHaveAttribute("data-last-revised", "2026-07-01");
});

test("the audit log filters and pages", async ({ page }) => {
  await page.goto("/system/audit-log?table=sources");
  const entries = page.locator("[data-entry]:visible");
  await expect(entries.first()).toBeVisible();
  for (const text of await entries.allTextContents()) expect(text).toContain("sources");
  await page.goto("/system/audit-log");
  const older = page.getByRole("link", { name: "Older" });
  if (await older.count()) {
    await older.click();
    await expect(page).toHaveURL(/before_id=\d+/);
    await expect(page.getByRole("link", { name: "Newest" })).toBeVisible();
  }
});

test("Data Health links each source to its audit history", async ({ page }) => {
  await page.goto("/system/data-health");
  await page.getByRole("link", { name: /^History of SEC EDGAR/ }).first().click();
  await expect(page).toHaveURL(/table=sources&object_id=sec_edgar/);
  await expect(page.locator("[data-entry]:visible").first()).toContainText("SEC EDGAR");
});

// ---------- macro page (M0.6) ----------

test("PAYEMS: As known on before the revision shows the first release", async ({ page }) => {
  const august = () => page.locator('tr[data-date="2026-08-01"]');
  await page.goto("/macro/PAYEMS?known_on=2026-09-30");
  await expect(august()).toContainText("159,075");
  await expect(august()).not.toContainText("Revised");

  await page.getByRole("link", { name: "Today" }).click();
  await expect(page).not.toHaveURL(/known_on/);
  await expect(august()).toContainText("Revised");
  await expect(august()).toContainText("159,075 on 2026-09-04");
});

test("unknown macro series returns 404", async ({ page }) => {
  const response = await page.goto("/macro/NOPE");
  expect(response?.status()).toBe(404);
});

test("unknown instrument returns 404", async ({ page }) => {
  const response = await page.goto("/instruments/NOPE");
  expect(response?.status()).toBe(404);
});

test.describe("desktop tooltips", () => {
  test.skip(({ isMobile }) => isMobile, "hover is a desktop interaction");

  test("hovering a nav label shows its glossary tooltip", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Congress Trades" }).hover();
    await expect(page.getByRole("tooltip")).toContainText("Reported trades");
  });

  test("the ? button opens the full entry and Escape closes it", async ({ page }) => {
    await page.goto("/dashboards/policy-monitor");
    await page.getByRole("button", { name: "What is Planned Phase?" }).click();
    const dialog = page.getByRole("dialog", { name: "Planned Phase" });
    await expect(dialog).toContainText("Methodology");
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
  });
});

test.describe("mobile popover", () => {
  test.skip(({ isMobile }) => !isMobile, "tap is a mobile interaction");

  test("tapping ? opens the explanation and tapping elsewhere closes it", async ({ page }) => {
    await page.goto("/system/data-health");
    await page.getByRole("button", { name: "What is Data Health?" }).tap();
    const dialog = page.getByRole("dialog", { name: "Data Health" });
    await expect(dialog).toBeVisible();
    // Tap an empty spot of the page (main's padding), away from the open dialog.
    await page.locator("main").tap({ position: { x: 4, y: 4 } });
    await expect(dialog).toHaveCount(0);
  });

  test("the menu opens the navigation including System", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Menu" }).tap();
    await expect(page.getByRole("link", { name: "Data Health" })).toBeVisible();
  });
});
