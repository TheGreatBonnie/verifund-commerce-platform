import { describe, expect, it, vi, beforeEach } from "vitest";

const hoisted = vi.hoisted(() => {
  const protect = vi.fn();
  const authFn = vi.fn();
  const auth = Object.assign(authFn, { protect });
  const promoteUserRole = vi.fn();
  const currentUser = vi.fn();
  return { protect, authFn, auth, promoteUserRole, currentUser };
});

vi.mock("@clerk/nextjs/server", () => ({
  auth: hoisted.auth,
  currentUser: hoisted.currentUser,
}));

vi.mock("@/lib/user-role", () => ({
  promoteUserRole: hoisted.promoteUserRole,
}));

import { setRole } from "@/app/choose-role/actions";

describe("setRole action", () => {
  beforeEach(() => {
    hoisted.protect.mockReset();
    hoisted.authFn.mockReset();
    hoisted.promoteUserRole.mockClear();
    hoisted.currentUser.mockReset().mockResolvedValue({ publicMetadata: {} });
  });

  it("requires authentication and promotes the role", async () => {
    hoisted.protect.mockResolvedValue({ userId: "user_1" });
    hoisted.authFn.mockResolvedValue({ userId: "user_1" });
    await setRole("seller");
    expect(hoisted.protect).toHaveBeenCalled();
    expect(hoisted.promoteUserRole).toHaveBeenCalledWith("user_1", "seller");
  });

  it("refuses to demote an admin through the chooser", async () => {
    hoisted.protect.mockResolvedValue({ userId: "user_1" });
    hoisted.authFn.mockResolvedValue({ userId: "user_1" });
    hoisted.currentUser.mockResolvedValue({ publicMetadata: { role: "admin" } });
    await expect(setRole("buyer")).rejects.toThrow("admin role cannot be changed here");
    expect(hoisted.promoteUserRole).not.toHaveBeenCalled();
  });

  it("rejects when unauthenticated", async () => {
    hoisted.protect.mockRejectedValue(new Error("unauthenticated"));
    await expect(setRole("buyer")).rejects.toThrow("unauthenticated");
    expect(hoisted.promoteUserRole).not.toHaveBeenCalled();
  });
});
