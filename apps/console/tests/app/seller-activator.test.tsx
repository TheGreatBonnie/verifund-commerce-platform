import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const createOrganizationProps = vi.hoisted(() => ({ value: null as any }));
const orgListState = vi.hoisted(() => ({
  current: {
    isLoaded: true as boolean,
    userMemberships: { isLoading: false as boolean, data: [] as unknown[] },
    createOrganization: vi.fn(),
    setActive: vi.fn(),
  },
}));

vi.mock("@clerk/nextjs", () => ({
  useOrganizationList: () => orgListState.current,
  useUser: () => ({ user: { firstName: "Ada" } }),
  CreateOrganization: (props: any) => {
    createOrganizationProps.value = props;
    return <div data-testid="create-organization" />;
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

import { SellerActivator } from "@/app/post-auth/seller-activator";

describe("SellerActivator", () => {
  it("shows a loading state while Clerk loads", () => {
    orgListState.current = {
      isLoaded: false,
      userMemberships: { isLoading: false, data: [] },
      createOrganization: vi.fn(),
      setActive: vi.fn(),
    } as any;
    render(<SellerActivator />);
    expect(screen.getByText(/loading your organizations/i)).toBeInTheDocument();
  });

  it("redirects Clerk-created organizations to onboarding", () => {
    orgListState.current = {
      isLoaded: true,
      userMemberships: { isLoading: false, data: [] },
      createOrganization: vi.fn(),
      setActive: vi.fn(),
    } as any;
    createOrganizationProps.value = null;
    render(<SellerActivator />);
    expect(createOrganizationProps.value?.afterCreateOrganizationUrl).toBe("/seller/onboarding");
  });
});
