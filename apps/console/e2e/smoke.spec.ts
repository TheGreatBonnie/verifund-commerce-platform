import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

for (const route of ["/", "/runs", "/sellers", "/settings", "/help"]) {
  test(`${route} loads`, async ({ page }) => {
    await page.goto(route);
    await expect(page.locator("body")).toBeVisible();
  });
}

test("home has no a11y violations", async ({ page }) => {
  await page.goto("/");
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});
