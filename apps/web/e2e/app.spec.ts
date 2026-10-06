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
  const errors = trackConsoleErrors(page);
  const pages = [
    "/",
    "/system/data-health",
    "/instruments",
    "/instruments/AAPL",
    "/macro",
    "/macro/PAYEMS",
    "/system/progress",
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
    // SEC EDGAR (M0.5) and FRED (M0.6) are enabled: judged, whatever their state.
    // GDELT is not enabled until M0.8.
    await expect(freshness(/SEC EDGAR/)).toHaveText(/^(Fresh|Stale|Failing)$/);
    await expect(freshness(/FRED/)).toHaveText(/^(Fresh|Stale|Failing)$/);
    await expect(freshness(/GDELT/)).toHaveText("Not enabled");
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
        if (!parent.closest("[data-metric],[data-identifier],code")) found.push(text.trim());
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
  "/system/progress",
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
    await page.goto("/dashboards/earnings");
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
