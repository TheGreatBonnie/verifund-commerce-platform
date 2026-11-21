import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const { pushMock, useAuthMock, adminMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  useAuthMock: vi.fn(),
  adminMock: vi.fn(),
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
    if (opts.queryKey?.[0] === "admin-access" && opts.enabled === false) {
      return { data: undefined };
    }
    return { data: { admin: adminMock() } };
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

import { AdminLink } from "@/components/layout/admin-link";

describe("AdminLink (header)", () => {
  it("shows Admin for platform admins and navigates", () => {
    useAuthMock.mockReturnValue({ isSignedIn: true, orgId: null });
    adminMock.mockReturnValue(true);
    render(<AdminLink />);
    const btn = screen.getByText("Admin");
    expect(btn).toBeDefined();
    fireEvent.click(btn);
    expect(pushMock).toHaveBeenCalledWith("/admin");
  });

  it("renders nothing for non-admins", () => {
    useAuthMock.mockReturnValue({ isSignedIn: true, orgId: null });
    adminMock.mockReturnValue(false);
    const { container } = render(<AdminLink />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when signed out", () => {
    useAuthMock.mockReturnValue({ isSignedIn: false, orgId: null });
    adminMock.mockReturnValue(true);
    const { container } = render(<AdminLink />);
    expect(container).toBeEmptyDOMElement();
  });
});
