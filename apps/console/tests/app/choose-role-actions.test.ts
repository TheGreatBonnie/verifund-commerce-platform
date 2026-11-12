import { describe, expect, it, vi, beforeEach } from "vitest";

const hoisted = vi.hoisted(() => {
  const protect = vi.fn();
  const authFn = vi.fn();
  const auth = Object.assign(authFn, { protect });
  const promoteUserRole = vi.fn();
  return { protect, authFn, auth, promoteUserRole };
});

vi.mock("@clerk/nextjs/server", () => ({
  auth: hoisted.auth,
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
  });

  it("requires authentication and promotes the role", async () => {
    hoisted.protect.mockResolvedValue({ userId: "user_1" });
    hoisted.authFn.mockResolvedValue({ userId: "user_1" });
    await setRole("seller");
    expect(hoisted.protect).toHaveBeenCalled();
    expect(hoisted.promoteUserRole).toHaveBeenCalledWith("user_1", "seller");
  });

  it("rejects when unauthenticated", async () => {
    hoisted.protect.mockRejectedValue(new Error("unauthenticated"));
    await expect(setRole("buyer")).rejects.toThrow("unauthenticated");
    expect(hoisted.promoteUserRole).not.toHaveBeenCalled();
  });
});
