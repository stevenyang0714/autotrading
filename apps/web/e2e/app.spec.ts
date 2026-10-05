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
  for (const path of ["/", "/system/data-health", ...DASHBOARD_SLUGS.map((s) => `/dashboards/${s}`)]) {
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
    await expect(page.locator('tbody [data-term-id="data_freshness"]').first()).toHaveText(
      "Not enabled",
    );
  }
});

test("numbers on Data Health are all explained", async ({ page }) => {
  await page.goto("/system/data-health");
  const offenders = await page.evaluate(() => {
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
  expect(offenders).toEqual([]);
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
