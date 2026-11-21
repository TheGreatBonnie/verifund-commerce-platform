import { beforeEach, describe, expect, it, vi } from "vitest";

const hoisted = vi.hoisted(() => ({
  protect: vi.fn(),
  adminAccess: vi.fn(),
  clerkClient: vi.fn(),
  getUserList: vi.fn(),
}));

vi.mock("@clerk/nextjs/server", () => ({
  auth: Object.assign(vi.fn(), { protect: hoisted.protect }),
  clerkClient: hoisted.clerkClient,
}));

vi.mock("@/lib/admin-access", () => ({ adminAccess: hoisted.adminAccess }));

import { GET } from "@/app/api/admin/users/route";

describe("GET /api/admin/users", () => {
  beforeEach(() => {
    hoisted.protect.mockReset().mockResolvedValue({ userId: "user_1" });
    hoisted.adminAccess.mockReset();
    hoisted.clerkClient.mockReset();
    hoisted.getUserList.mockReset();
    hoisted.clerkClient.mockResolvedValue({
      users: { getUserList: hoisted.getUserList },
    });
  });

  it("returns 403 for non-admins without touching Clerk", async () => {
    hoisted.adminAccess.mockResolvedValue(false);
    const response = await GET();
    expect(response.status).toBe(403);
    expect(hoisted.clerkClient).not.toHaveBeenCalled();
  });

  it("returns read-only user summaries for admins", async () => {
    hoisted.adminAccess.mockResolvedValue(true);
    hoisted.getUserList.mockResolvedValue({
      data: [
        {
          id: "user_1",
          primaryEmailAddressId: "e1",
          emailAddresses: [{ id: "e1", emailAddress: "a@example.com" }],
          publicMetadata: { role: "admin" },
        },
      ],
    });
    const response = await GET();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      users: [{ id: "user_1", email: "a@example.com", role: "admin" }],
    });
    expect(hoisted.getUserList).toHaveBeenCalledWith({ limit: 100 });
  });
});
