import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hoisted = vi.hoisted(() => ({
  adminAccess: vi.fn(),
  redirect: vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  }),
  signOutAction: vi.fn(),
}));

vi.mock("@/lib/admin-access", () => ({ adminAccess: hoisted.adminAccess }));
vi.mock("next/navigation", () => ({ redirect: hoisted.redirect }));
vi.mock("next/link", () => ({
  default: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
}));
vi.mock("@clerk/nextjs", () => ({
  UserButton: () => <div data-testid="user-button" />,
}));
vi.mock("@/components/admin/admin-nav", () => ({
  AdminNav: () => <nav data-testid="admin-nav" />,
}));
vi.mock("@/components/layout/marketplace-link", () => ({
  MarketplaceLink: () => <div data-testid="marketplace-link" />,
}));
vi.mock("@/app/admin/actions", () => ({ signOutAction: hoisted.signOutAction }));

import AdminLayout from "@/app/admin/layout";

describe("AdminLayout", () => {
  beforeEach(() => {
    hoisted.adminAccess.mockReset();
    hoisted.redirect.mockClear();
  });

  it("silently redirects non-admins to /", async () => {
    hoisted.adminAccess.mockResolvedValue(false);
    await expect(AdminLayout({ children: <div>secret</div> })).rejects.toThrow(
      "REDIRECT:/",
    );
    expect(hoisted.redirect).toHaveBeenCalledWith("/");
  });

  it("renders the admin shell for admins", async () => {
    hoisted.adminAccess.mockResolvedValue(true);
    render(await AdminLayout({ children: <div data-testid="admin-child">content</div> }));
    expect(screen.getByTestId("admin-child")).toBeInTheDocument();
    expect(screen.getByTestId("admin-nav")).toBeInTheDocument();
    expect(hoisted.redirect).not.toHaveBeenCalled();
  });
});
