import { describe, expect, it, vi } from "vitest";

const hoisted = vi.hoisted(() => {
  const updateUserMetadata = vi.fn();
  const clerkClientFn = vi.fn(async () => ({
    users: { updateUserMetadata },
  }));
  return { updateUserMetadata, clerkClientFn };
});

vi.mock("@clerk/nextjs/server", () => ({
  clerkClient: hoisted.clerkClientFn,
}));

import { promoteUserRole } from "@/lib/user-role";

describe("promoteUserRole", () => {
  it("writes the role to publicMetadata", async () => {
    await promoteUserRole("user_1", "seller");
    expect(hoisted.clerkClientFn).toHaveBeenCalled();
    expect(hoisted.updateUserMetadata).toHaveBeenCalledWith("user_1", {
      publicMetadata: { role: "seller" },
    });
  });
});
