import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

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
  useQuery: (
    opts: {
      queryKey: unknown[];
      queryFn: () => Promise<unknown>;
      enabled?: boolean;
    },
  ) => {
    // Emulate the seller-access query only; catalog/runs queries are stubbed.
    // Respect enabled=false (signed-out / no org must not fetch seller access).
    if (opts.queryKey?.[0] === "seller-access") {
      if (opts.enabled === false) {
        return { data: undefined, isLoading: false };
      }
      return { data: { access: sellerAccessMock(), orgId: "org_1" }, isLoading: false };
    }
    return { data: [], isLoading: false };
  },
}));

vi.mock("@/lib/api", () => ({
  fetchMarketplaceProducts: vi.fn(async () => []),
}));

vi.mock("@/features/runs/use-runs", () => ({
  useRuns: () => ({ runs: [] }),
}));

// Components with heavy JSX/svg that Home imports — stub them to keep the test focused.
vi.mock("@/components/ui/button", () => ({
  Button: ({ children, onClick }: { children: unknown; onClick?: () => void }) => (
    <button type="button" onClick={onClick}>
      {children as string}
    </button>
  ),
}));
vi.mock("@/components/ui/panel", () => ({
  Panel: ({ children }: { children: unknown }) => <div>{children as never}</div>,
}));
vi.mock("@/features/runs/run-summary-card", () => ({
  RunSummaryCard: () => null,
}));

// Import after mocks
import Home from "@/app/(public)/page";

describe("Home seller dashboard link", () => {
  it("shows Open seller dashboard for verified sellers", () => {
    useAuthMock.mockReturnValue({ isSignedIn: true, orgId: "org_1" });
    sellerAccessMock.mockReturnValue("workspace");
    render(<Home />);
    expect(screen.getByText("Open seller dashboard")).toBeDefined();
  });

  it("shows Continue seller onboarding for onboarding state", () => {
    useAuthMock.mockReturnValue({ isSignedIn: true, orgId: "org_1" });
    sellerAccessMock.mockReturnValue("onboarding");
    render(<Home />);
    expect(screen.getByText("Continue seller onboarding")).toBeDefined();
  });

  it("hides seller links for buyers (none)", () => {
    useAuthMock.mockReturnValue({ isSignedIn: true, orgId: "org_1" });
    sellerAccessMock.mockReturnValue("none");
    render(<Home />);
    expect(screen.queryByText("Open seller dashboard")).toBeNull();
    expect(screen.queryByText("Continue seller onboarding")).toBeNull();
  });

  it("hides seller links when signed out", () => {
    useAuthMock.mockReturnValue({ isSignedIn: false, orgId: null });
    sellerAccessMock.mockReturnValue("workspace");
    render(<Home />);
    expect(screen.queryByText("Open seller dashboard")).toBeNull();
  });
});
