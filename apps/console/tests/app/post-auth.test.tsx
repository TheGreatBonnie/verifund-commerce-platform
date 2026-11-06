import { describe, expect, it, vi, beforeEach } from "vitest";

const hoisted = vi.hoisted(() => {
  const authProtect = vi.fn();
  const authFn = vi.fn();
  const auth = Object.assign(authFn, { protect: authProtect });
  const currentUser = vi.fn();
  const getOrganizationMembershipList = vi.fn();
  const createOrganization = vi.fn();
  const updateUserMetadata = vi.fn();
  const clerkClientFn = vi.fn(async () => ({
    users: { getOrganizationMembershipList, updateUserMetadata },
    organizations: { createOrganization },
  }));
  const redirect = vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  });
  return {
    auth,
    authFn,
    authProtect,
    currentUser,
    getOrganizationMembershipList,
    createOrganization,
    updateUserMetadata,
    clerkClientFn,
    redirect,
  };
});

vi.mock("@clerk/nextjs/server", () => ({
  auth: hoisted.auth,
  currentUser: hoisted.currentUser,
  clerkClient: hoisted.clerkClientFn,
}));

vi.mock("next/navigation", () => ({ redirect: hoisted.redirect }));

import PostAuthPage from "@/app/post-auth/page";

function makeUser(overrides: Record<string, unknown> = {}) {
  return {
    id: "user_1",
    firstName: "Ada",
    primaryEmailAddress: { emailAddress: "ada@example.com" },
    publicMetadata: {},
    unsafeMetadata: {},
    ...overrides,
  };
}

beforeEach(() => {
  hoisted.authProtect.mockReset().mockResolvedValue({ userId: "user_1" });
  hoisted.authFn.mockReset().mockResolvedValue({ userId: "user_1" });
  hoisted.currentUser.mockReset();
  hoisted.getOrganizationMembershipList.mockReset();
  hoisted.createOrganization.mockReset();
  hoisted.redirect.mockClear();
});

describe("PostAuthPage", () => {
  it("redirects buyers to /", async () => {
    hoisted.currentUser.mockResolvedValue(makeUser({ publicMetadata: { role: "buyer" } }));
    await expect(PostAuthPage()).rejects.toThrow("REDIRECT:/");
    expect(hoisted.redirect).toHaveBeenCalledWith("/");
  });

  it("promotes an unsafeMetadata hint to publicMetadata, then routes", async () => {
    hoisted.currentUser.mockResolvedValue(
      makeUser({ publicMetadata: {}, unsafeMetadata: { role: "buyer" } }),
    );
    await expect(PostAuthPage()).rejects.toThrow("REDIRECT:/");
    expect(hoisted.redirect).toHaveBeenCalledWith("/");
  });

  it("redirects role-less users to /choose-role", async () => {
    hoisted.currentUser.mockResolvedValue(makeUser({ publicMetadata: {}, unsafeMetadata: {} }));
    await expect(PostAuthPage()).rejects.toThrow("REDIRECT:/choose-role");
    expect(hoisted.redirect).toHaveBeenCalledWith("/choose-role");
  });

  it("routes sellers with an org to /seller/onboarding", async () => {
    hoisted.currentUser.mockResolvedValue(makeUser({ publicMetadata: { role: "seller" } }));
    hoisted.getOrganizationMembershipList.mockResolvedValue({ data: [{ id: "mem_1" }] });
    await expect(PostAuthPage()).rejects.toThrow("REDIRECT:/seller/onboarding");
    expect(hoisted.createOrganization).not.toHaveBeenCalled();
  });

  it("creates a business org for sellers without one, then routes to onboarding", async () => {
    hoisted.currentUser.mockResolvedValue(
      makeUser({ publicMetadata: { role: "seller" }, firstName: "Ada" }),
    );
    hoisted.getOrganizationMembershipList.mockResolvedValue({ data: [] });
    await expect(PostAuthPage()).rejects.toThrow("REDIRECT:/seller/onboarding");
    expect(hoisted.createOrganization).toHaveBeenCalledWith({
      name: "Ada's business",
      createdBy: "user_1",
    });
  });
});
