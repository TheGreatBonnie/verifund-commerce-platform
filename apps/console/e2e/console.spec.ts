import { expect, test } from "@playwright/test";

const VERIFUND_MODE = process.env.VERIFUND_MODE ?? "sandbox";

test.skip(
  VERIFUND_MODE !== "off",
  "Legacy MarketMesh flow runs only with Verifund off",
);

test("buyer runs the demo and orders only after approval", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("MarketMesh", { exact: true })).toBeVisible();

  const runSample = page.getByRole("button", { name: "Run sample brief" });
  await expect(runSample).toBeEnabled({ timeout: 15_000 });
  await runSample.click();

  await expect(page.getByText("Northwind Audio").first()).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("CircuitForge").first()).toBeVisible();
  await expect(page.getByText("Aurora Supply").first()).toBeVisible();
  await expect(
    page.locator(".a2a-message-card-outgoing").filter({ hasText: "Aurora Supply" }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(
    page.locator(".a2a-message-card-incoming").filter({ hasText: "Aurora Supply" }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/R2/).first()).toBeVisible();
  await expect(page.getByText("Approve order").first()).toBeVisible({
    timeout: 30_000,
  });

  await page.getByRole("button", { name: "Approve order" }).first().click();
  await expect(page.getByText("Order confirmed").first()).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText(/MM-/).first()).toBeVisible();
  await expect(page.getByText("No order was placed")).toHaveCount(0);
});

test("reject path places no order", async ({ page }) => {
  await page.goto("/");
  const runSample = page.getByRole("button", { name: "Run sample brief" });
  await expect(runSample).toBeEnabled({ timeout: 15_000 });
  await runSample.click();
  await expect(page.getByText("Reject", { exact: true }).first()).toBeVisible({
    timeout: 30_000,
  });

  await page.getByRole("button", { name: "Reject", exact: true }).first().click();
  await expect(page.getByText("No order was placed").first()).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("Order confirmed")).toHaveCount(0);
});
