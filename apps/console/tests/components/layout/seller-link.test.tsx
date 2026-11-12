import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const { pushMock, useAuthMock, sellerAccessMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  useAuthMock: vi.fn(),
  sellerAccessMock: vi.fn(),
}));

vi.mock("@clerk/nextjs", () => ({
  useAuth: useAuthMock,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: (opts: {
    queryKey: unknown[];
    enabled?: boolean;
  }) => {
    if (opts.queryKey?.[0] === "seller-access" && opts.enabled === false) {
      return { data: undefined };
    }
    return { data: { access: sellerAccessMock(), orgId: "org_1" } };
  },
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    onClick,
  }: {
    children: unknown;
    onClick?: () => void;
  }) => (
    <button type="button" onClick={onClick}>
      {children as string}
    </button>
  ),
}));

import { SellerLink } from "@/components/layout/seller-link";

describe("SellerLink (header)", () => {
  it("shows Seller dashboard for verified sellers and navigates", () => {
    useAuthMock.mockReturnValue({ isSignedIn: true, orgId: "org_1" });
    sellerAccessMock.mockReturnValue("workspace");
    render(<SellerLink />);
    const btn = screen.getByText("Seller dashboard");
    expect(btn).toBeDefined();
    fireEvent.click(btn);
    expect(pushMock).toHaveBeenCalledWith("/seller/dashboard");
  });

  it("shows Continue seller onboarding for onboarding state", () => {
    useAuthMock.mockReturnValue({ isSignedIn: true, orgId: "org_1" });
    sellerAccessMock.mockReturnValue("onboarding");
    render(<SellerLink />);
    expect(screen.getByText("Continue seller onboarding")).toBeDefined();
  });

  it("renders nothing for buyers (none)", () => {
    useAuthMock.mockReturnValue({ isSignedIn: true, orgId: "org_1" });
    sellerAccessMock.mockReturnValue("none");
    const { container } = render(<SellerLink />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when signed out", () => {
    useAuthMock.mockReturnValue({ isSignedIn: false, orgId: null });
    sellerAccessMock.mockReturnValue("workspace");
    const { container } = render(<SellerLink />);
    expect(container).toBeEmptyDOMElement();
  });
});
