import { beforeEach, describe, expect, it, vi } from "vitest";

const { protect, currentUser } = vi.hoisted(() => ({
  protect: vi.fn(),
  currentUser: vi.fn(),
}));

vi.mock("@clerk/nextjs/server", () => ({
  auth: Object.assign(vi.fn(), { protect }),
  currentUser,
}));

import { identifyCopilotUser } from "@/lib/copilot-user";

describe("identifyCopilotUser", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    protect.mockResolvedValue({ userId: "user_123" });
  });

  it("uses the Clerk display name when available", async () => {
    currentUser.mockResolvedValue({
      fullName: "  Ada Lovelace  ",
      firstName: "Ada",
      lastName: "Lovelace",
      username: "ada",
      primaryEmailAddress: { emailAddress: "ada@example.test" },
    });

    await expect(identifyCopilotUser()).resolves.toEqual({
      id: "user_123",
      name: "Ada Lovelace",
    });
  });

  it("falls back to first and last name when fullName is blank", async () => {
    currentUser.mockResolvedValue({
      fullName: "",
      firstName: "Grace",
      lastName: "Hopper",
      username: "grace",
      primaryEmailAddress: { emailAddress: "grace@example.test" },
    });

    await expect(identifyCopilotUser()).resolves.toEqual({
      id: "user_123",
      name: "Grace Hopper",
    });
  });

  it("falls back to username, then email, then user id", async () => {
    currentUser.mockResolvedValueOnce({
      fullName: null,
      firstName: null,
      lastName: null,
      username: "katherine",
      primaryEmailAddress: { emailAddress: "katherine@example.test" },
    });
    await expect(identifyCopilotUser()).resolves.toEqual({
      id: "user_123",
      name: "katherine",
    });

    currentUser.mockResolvedValueOnce({
      fullName: "",
      firstName: " ",
      lastName: "",
      username: " ",
      primaryEmailAddress: { emailAddress: "  dorothy@example.test " },
    });
    await expect(identifyCopilotUser()).resolves.toEqual({
      id: "user_123",
      name: "dorothy@example.test",
    });

    currentUser.mockResolvedValueOnce({
      fullName: null,
      firstName: null,
      lastName: null,
      username: null,
      primaryEmailAddress: null,
    });
    await expect(identifyCopilotUser()).resolves.toEqual({
      id: "user_123",
      name: "user_123",
    });
  });

  it("falls back to the user id when Clerk cannot return a profile", async () => {
    currentUser.mockRejectedValue(new Error("Clerk backend unavailable"));

    await expect(identifyCopilotUser()).resolves.toEqual({
      id: "user_123",
      name: "user_123",
    });
  });
});
