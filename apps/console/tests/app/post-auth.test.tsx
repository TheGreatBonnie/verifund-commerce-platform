import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const hoisted = vi.hoisted(() => {
  const authProtect = vi.fn();
  const authFn = vi.fn();
  const auth = Object.assign(authFn, { protect: authProtect });
  const currentUser = vi.fn();
  const updateUserMetadata = vi.fn();
  const clerkClientFn = vi.fn(async () => ({
    users: { updateUserMetadata },
  }));
  const redirect = vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  });
  return {
    auth,
    authFn,
    authProtect,
    currentUser,
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

vi.mock("@/app/post-auth/seller-activator", () => ({
  SellerActivator: () => <div data-testid="seller-activator" />,
}));

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
  hoisted.redirect.mockClear();
});

describe("PostAuthPage", () => {
  it("redirects buyers to /", async () => {
    hoisted.currentUser.mockResolvedValue(makeUser({ publicMetadata: { role: "buyer" } }));
    await expect(PostAuthPage()).rejects.toThrow("REDIRECT:/");
    expect(hoisted.redirect).toHaveBeenCalledWith("/");
  });

  it("promotes an unsafeMetadata hint to publicMetadata, then routes buyers home", async () => {
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

  it("renders the seller activator for sellers (no server-side org creation)", async () => {
    hoisted.currentUser.mockResolvedValue(makeUser({ publicMetadata: { role: "seller" } }));
    render(await PostAuthPage());
    expect(screen.getByTestId("seller-activator")).toBeInTheDocument();
    expect(hoisted.redirect).not.toHaveBeenCalled();
  });

  it("redirects to /sign-in when unauthenticated", async () => {
    hoisted.authProtect.mockRejectedValue(new Error("unauthenticated"));
    hoisted.authFn.mockResolvedValue({ userId: null });
    await expect(PostAuthPage()).rejects.toThrow("REDIRECT:/sign-in");
    expect(hoisted.redirect).toHaveBeenCalledWith("/sign-in");
  });
});
