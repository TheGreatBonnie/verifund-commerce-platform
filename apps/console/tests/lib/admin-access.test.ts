import { beforeEach, describe, expect, it, vi } from "vitest";

const hoisted = vi.hoisted(() => ({
  protect: vi.fn(),
  forUser: vi.fn(),
}));
vi.mock("@/lib/console-session", () => ({ consoleSession: hoisted.protect }));
vi.mock("@/lib/control-plane", () => ({ controlPlaneForUser: hoisted.forUser }));

import { adminAccess } from "@/lib/admin-access";

describe("adminAccess", () => {
  beforeEach(() => {
    hoisted.protect.mockReset().mockResolvedValue({ userId: "user_1" });
    hoisted.forUser.mockReset();
  });

  it("returns true only for is_platform_admin", async () => {
    hoisted.forUser.mockResolvedValue(
      new Response(JSON.stringify({ is_platform_admin: true }), { status: 200 }),
    );
    expect(await adminAccess()).toBe(true);
  });

  it.each([
    ["non-admin 200", 200, { is_platform_admin: false }],
    ["403", 403, {}],
    ["malformed json", 200, null],
  ])("fails closed for %s", async (_name, status, body) => {
    hoisted.forUser.mockResolvedValue(
      new Response(body === null ? "not-json" : JSON.stringify(body), { status }),
    );
    expect(await adminAccess()).toBe(false);
  });

  it("fails closed on network error", async () => {
    hoisted.forUser.mockRejectedValue(new Error("offline"));
    expect(await adminAccess()).toBe(false);
  });
});
