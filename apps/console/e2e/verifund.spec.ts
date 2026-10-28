import { expect, test } from "@playwright/test";

const MODE = process.env.VERIFUND_MODE ?? "off";

test.skip(MODE !== "fake", "Verifund fake mode only");

test("chat completes a Verifund transaction with funding and release approvals", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("MarketMesh", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Start Shopping" }).click();

  const approve = page.getByRole("button", { name: "Approve funding" });
  await expect(approve).toBeVisible({ timeout: 30_000 });
  await approve.first().click();

  const checkout = page.getByRole("link", { name: "Open the payment checkout" });
  await expect(checkout).toBeVisible({ timeout: 30_000 });
  const [checkoutPage] = await Promise.all([
    page.waitForEvent("popup"),
    checkout.click(),
  ]);

  await expect(checkoutPage.getByRole("heading", { name: "Verifund fake checkout" })).toBeVisible();
  await checkoutPage.getByRole("button", { name: "Approve payment" }).click();
  await expect(checkoutPage).toHaveURL(/funding=complete/, { timeout: 30_000 });

  await expect(page.getByText("Order confirmed").first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/2\/2 required evidence items received/i)).toBeVisible({ timeout: 60_000 });

  const release = page.getByRole("button", { name: "Release funds" });
  await expect(release).toBeVisible({ timeout: 60_000 });
  await release.click();

  await expect(page.getByText("Verified receipt", { exact: true })).toBeVisible({
    timeout: 30_000,
  });
  await page.getByRole("tab", { name: "Transaction Room" }).click();
  await expect(page.getByText("RELEASED", { exact: true })).toBeVisible();
});
