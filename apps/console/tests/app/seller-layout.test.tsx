import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hoisted = vi.hoisted(() => ({
  consoleSession: vi.fn(),
  sellerAccess: vi.fn(),
  redirect: vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  }),
  fetch: vi.fn(),
}));

vi.mock("@/lib/console-session", () => ({ consoleSession: hoisted.consoleSession }));
vi.mock("@/lib/seller-access", () => ({ sellerAccess: hoisted.sellerAccess }));
vi.mock("next/navigation", () => ({
  redirect: hoisted.redirect,
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("next/link", () => ({
  default: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
}));
vi.mock("@clerk/nextjs", () => ({
  UserButton: () => <div data-testid="user-button" />,
  OrganizationSwitcher: () => <div data-testid="org-switcher" />,
  useAuth: () => ({ isSignedIn: true, orgId: "org_1" }),
}));
vi.mock("@/components/seller/seller-nav", () => ({ SellerNav: () => <nav /> }));
vi.mock("@/components/layout/marketplace-link", () => ({ MarketplaceLink: () => <div /> }));
vi.mock("@/app/seller/actions", () => ({ signOutAction: vi.fn() }));

// Deliberately NOT mocking @tanstack/react-query, @/providers/query-provider,
// or @/components/layout/admin-link: the regression was a useQuery consumer
// rendered outside any QueryClientProvider.

import SellerLayout from "@/app/seller/layout";

describe("SellerLayout", () => {
  beforeEach(() => {
    hoisted.consoleSession.mockReset().mockResolvedValue({
      userId: "user_1",
      orgId: "org_1",
    });
    hoisted.sellerAccess.mockReset().mockResolvedValue("workspace");
    hoisted.redirect.mockClear();
    hoisted.fetch.mockReset().mockResolvedValue(
      new Response(JSON.stringify({ admin: false }), { status: 200 }),
    );
    vi.stubGlobal("fetch", hoisted.fetch);
  });

  it("renders with the real AdminLink without a QueryClient error", async () => {
    const tree = await SellerLayout({
      children: <div data-testid="seller-child">content</div>,
    });
    render(tree);
    expect(screen.getByTestId("seller-child")).toBeInTheDocument();
  });
});
