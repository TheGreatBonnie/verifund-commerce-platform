import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@clerk/nextjs", () => ({
  useOrganizationList: () => ({
    isLoaded: false,
    userMemberships: { data: [] },
    createOrganization: vi.fn(),
    setActive: vi.fn(),
  }),
  useUser: () => ({ user: { firstName: "Ada" } }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

import { SellerActivator } from "@/app/post-auth/seller-activator";

describe("SellerActivator", () => {
  it("shows a loading state while Clerk loads", () => {
    render(<SellerActivator />);
    expect(screen.getByText(/loading your organizations/i)).toBeInTheDocument();
  });
});
