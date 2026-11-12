import { beforeEach, describe, expect, it, vi } from "vitest";

const { getToken } = vi.hoisted(() => ({ getToken: vi.fn() }));
vi.mock("@clerk/nextjs/server", () => ({
  auth: vi.fn(async () => ({ getToken, orgId: "org_1" })),
}));

import { controlPlaneForUser } from "@/lib/control-plane";

describe("controlPlaneForUser", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  });

  it("requests a token for the active organization", async () => {
    getToken.mockResolvedValue("tok_1");
    await controlPlaneForUser("/transactions");
    expect(getToken).toHaveBeenCalledWith({ organizationId: "org_1" });
    const [, init] = vi.mocked(fetch).mock.calls[0];
    const headers = init?.headers as Headers;
    expect(headers.get("authorization")).toBe("Bearer tok_1");
    expect(headers.get("x-actor-id")).toBeNull();
  });

  it("throws instead of falling back to the ops token", async () => {
    getToken.mockResolvedValue(null);
    await expect(controlPlaneForUser("/transactions")).rejects.toThrow("not signed in");
  });
});
