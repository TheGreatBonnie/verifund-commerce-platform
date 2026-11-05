import { beforeEach, describe, expect, it, vi } from "vitest";

const { protect } = vi.hoisted(() => ({ protect: vi.fn() }));
vi.mock("@clerk/nextjs/server", () => ({
  auth: Object.assign(vi.fn(), { protect }),
}));

import { consoleSession } from "@/lib/console-session";

describe("consoleSession", () => {
  beforeEach(() => protect.mockClear());

  it("returns the verified identity", async () => {
    protect.mockResolvedValue({ userId: "user_1", orgId: "org_1", orgRole: "org:admin" });
    await expect(consoleSession()).resolves.toEqual({
      userId: "user_1",
      orgId: "org_1",
      orgRole: "org:admin",
    });
  });

  it("rejects when Clerk has no session", async () => {
    protect.mockRejectedValue(new Error("unauthenticated"));
    await expect(consoleSession()).rejects.toThrow("unauthenticated");
  });
});
