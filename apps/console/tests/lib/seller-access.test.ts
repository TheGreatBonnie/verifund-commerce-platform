import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/control-plane", () => ({
  controlPlaneForUser: vi.fn(
    async () =>
      new Response(JSON.stringify({ profile: null }), { status: 200 }),
  ),
}));

import { sellerAccess } from "@/lib/seller-access";

describe("sellerAccess", () => {
  it("sends an organization with no seller profile to onboarding", async () => {
    await expect(sellerAccess("org_1")).resolves.toBe("onboarding");
  });
});
