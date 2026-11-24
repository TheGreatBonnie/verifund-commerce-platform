import { expect, test } from "@playwright/test";

// The admin tests need a Clerk user whose publicMetadata.role === "admin".
// Role granting is out-of-band: set it in the Clerk Dashboard (or via the
// verified Clerk webhook), never through the console UI. Provide credentials
// for that user through CLERK_ADMIN_EMAIL / CLERK_ADMIN_PASSWORD; the tests
// skip when they are absent so the suite stays runnable without Clerk test
// users.
const ADMIN_EMAIL = process.env.CLERK_ADMIN_EMAIL;
const ADMIN_PASSWORD = process.env.CLERK_ADMIN_PASSWORD;

async function signInAsAdmin(page: import("@playwright/test").Page) {
  await page.goto("/sign-in");
  const email = page.getByLabel(/email/i).first();
  await email.fill(ADMIN_EMAIL!);
  await page.getByRole("button", { name: /continue/i }).first().click();
  await page.getByLabel(/password/i).first().fill(ADMIN_PASSWORD!);
  await page.getByRole("button", { name: /continue|sign in/i }).first().click();
  await expect(page).not.toHaveURL(/\/sign-in/, { timeout: 30_000 });
}

test("non-admin is silently redirected from /admin", async ({ page }) => {
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/$/);
});

test("admin can open the workspace and platform transactions", async ({ page }) => {
  test.skip(
    !ADMIN_EMAIL || !ADMIN_PASSWORD,
    "requires CLERK_ADMIN_EMAIL and CLERK_ADMIN_PASSWORD for an admin test user",
  );
  await signInAsAdmin(page);
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await page.goto("/admin/transactions");
  await expect(
    page.getByRole("heading", { name: "Platform transactions" }),
  ).toBeVisible();
});
